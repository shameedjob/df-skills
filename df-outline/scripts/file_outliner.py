
import argparse
import csv
from dataclasses import asdict, dataclass, field
from functools import lru_cache
import json
import os
from pathlib import Path
import sys


@dataclass
class StructNode:
    block_name: str
    block_type: str
    start_line: int
    end_line: int
    children: list = field(default_factory=list)

    def closed(self)->bool:
        return self.end_line

    def __str__(self)->str:
        return f"{self.block_type} {self.block_name} @{self.start_line},{self.end_line}"

open_blocks = set(['object', 'function', 'procedure', 'class'])
close_blocks = set(['end_object', 'end_function', 'end_procedure', 'end_class', 'cd_end_object'])
use_command = 'use'


@lru_cache(maxsize=None)
def compress_file(file_path:str)->list[StructNode]:
    stack = []
    page = []
    with open(file_path, 'r') as file:
        for line_num, line in enumerate(file.readlines(), start=1):
            working_line = line.strip().split()
            if len(working_line) < 1: continue
            if working_line[0].lower() in open_blocks:
                new_struct = StructNode(working_line[1], working_line[0], line_num, 0)
                if len(stack):
                    stack[-1].children.append(new_struct)
                stack.append(new_struct)
            if working_line[0].lower() in close_blocks:
                old_block = stack.pop()
                old_block.end_line = line_num
                if not len(stack):
                    page.append(old_block)
    return page

def get_inheritance(file_path:str)->list[str]:
    inherited = []
    with open(file_path, 'r') as file:
        while (line:=file.readline()):
            args = line.strip().split()
            if len(args) >= 2:
                if args[0].lower() == use_command:
                    inherited.append(args[1])
    return inherited

def print_structure(page:list[StructNode]):
    for c in page:
        print_node(c, 0)

def print_node(node:StructNode, level:int):
    outp = ''
    if level:
        outp += '|'+'_'*level+' '
    outp += str(node)
    print(outp)
    for c in node.children:
        print_node(c, level+1)


def get_df_files(folder:str)->str:
    files = {}
    scan_folder_for_df_files(folder, files)
    return files

def scan_folder_for_df_files(folder:str, files:dict):
    for f in os.listdir(folder):
        path = Path(folder, f)
        if path.is_dir():
            scan_folder_for_df_files(str(path), files)
        if f not in files:
            if path.suffix.lower() in ['.pkg', '.wo', '.dd', '.vw', '.dg', '.sl', '.bp', '.inc']:
                files[f] = str(path)

@lru_cache(maxsize=None)
def build_file_index(search_dirs:tuple[str, ...])->dict[str, str]:
    index = {}
    for folder in search_dirs:
        for name, path in get_df_files(folder).items():
            index.setdefault(name.lower(), path)
    return index

def resolve_use(name:str, file_index:dict[str, str])->str|None:
    name = Path(name).name.lower()
    if not Path(name).suffix:
        name += '.pkg'
    return file_index.get(name)

def get_superclass(file:str, line:int)->str:
    with open(file, 'r') as f:
        for line_num, text in enumerate(f, start=1):
            if line_num == line:
                args = text.strip().lower().split()
                return args[-1] if args else ''
    return ''

def find_class_line(file:str, class_name:str)->int:
    with open(file, 'r') as f:
        for line_num, line in enumerate(f, start=1):
            args = line.strip().lower().split()
            if len(args) >= 2 and args[0] == 'class' and args[1] == class_name:
                return line_num
    return 0

def get_class_path(file:str, line:int, stop_class:str|None=None, search_dirs:list[str]|None=None)->list[tuple[str, str|None]]:
    """Depth first search through `use` dependencies following the superclass chain.

    Returns [(class, file), ...]; the last entry has file None if its definition was not found.
    """
    file_index = build_file_index(tuple(search_dirs or [os.path.dirname(os.path.abspath(file))]))
    with open(file, 'r') as f:
        args = f.readlines()[line-1].strip().split()
    path = [(args[1] if len(args) > 1 else '', file)]
    stop_class = stop_class.lower() if stop_class else None

    target = get_superclass(file, line)
    queue_stack = [file]
    memory_stack = []
    # files already searched for the current target; they stay in scope for the next one
    searched = []
    visited = set()
    while target:
        if not queue_stack:
            if not memory_stack:
                path.append((target, None))
                break
            queue_stack, memory_stack = memory_stack, []
        current = queue_stack.pop()
        key = (os.path.abspath(current), target)
        if key in visited:
            continue
        visited.add(key)
        searched.append(current)

        found_line = find_class_line(current, target)
        if found_line:
            path.append((target, current))
            if target == stop_class:
                break
            target = get_superclass(current, found_line)
            memory_stack.extend(searched[:-1] + queue_stack)
            searched = []
            # the superclass may be defined in the same file, so re-queue it under its dependencies
            queue_stack = [current]
        for dep in reversed(get_inheritance(current)):
            dep_file = resolve_use(dep, file_index)
            if dep_file:
                queue_stack.append(dep_file)
    return path

def strip_comment(line:str)->str:
    """Removes a trailing // comment, ignoring // inside quoted strings."""
    quote = None
    for i, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in '"\'':
            quote = char
        elif line.startswith('//', i):
            return line[:i]
    return line

def find_node(nodes:list[StructNode], line:int)->StructNode|None:
    for node in nodes:
        if node.start_line == line:
            return node
        if node.start_line < line <= node.end_line:
            return find_node(node.children, line)
    return None

def child_object_ranges(node:StructNode)->list[tuple[int, int]]:
    """Line ranges of the Objects nested (at any depth) inside node."""
    ranges = []
    for child in node.children:
        if child.block_type.lower() == 'object':
            ranges.append((child.start_line, child.end_line))
        else:
            ranges.extend(child_object_ranges(child))
    return ranges

def scan_props(file:str, line_start:int=1, line_end:int|None=None)->list[tuple[str, str, str, bool]]:
    """Returns (class, name, value, is_web) for each Property declared in the line range.

    If line_start is the first line of a block, the scan covers that block (up to line_end if given)
    and skips the Objects nested inside it, so their properties are not attributed to the block.
    """
    skipped = []
    node = find_node(compress_file(file), line_start)
    if node:
        line_end = line_end or node.end_line
        skipped = child_object_ranges(node)

    props = []
    flag = False
    with open(file, 'r') as f:
        for line_num, line in enumerate(f, start=1):
            if line_num < line_start: continue
            if line_end and line_num > line_end: break
            if any(start <= line_num <= end for start, end in skipped):
                flag = False
                continue
            working_line = line.strip().lower()
            if '{ webproperty=' in working_line:
                flag = True
            elif working_line.startswith('property'):
                args = strip_comment(line).strip().split()
                if len(args) >= 3:
                    props.append((args[1], args[2], ' '.join(args[3:]), flag))
                flag = False
    return props

def get_props(file:str, line_start:int=1, line_end:int|None=None, web_only:bool=False)->list[tuple[str, str, str]]:
    """Returns (class, name, value) for each Property declared in the line range.

    With web_only, only properties right after a { WebProperty=... } annotation are returned.
    """
    return [(c, name, value) for c, name, value, is_web in scan_props(file, line_start, line_end)
            if is_web or not web_only]

def get_super_props(file:str, line:int, web_only:bool=False, search_dirs:list[str]|None=None)->list[tuple[str, str, str]]:
    """Returns the properties of the Class/Object declared at line plus those inherited through its class path.

    A property declared in a subclass overrides one of the same name further up the path.
    """
    props = []
    seen = set()
    for i, (class_name, class_file) in enumerate(get_class_path(file, line, None, search_dirs)):
        if class_file is None:
            break
        start = line if i == 0 else find_class_line(class_file, class_name)
        for c, name, value, is_web in scan_props(class_file, start):
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            if is_web or not web_only:
                props.append((c, name, value))
    return props

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)

    structure_parser = subparsers.add_parser('structure', help='outline the blocks of a file')
    structure_parser.add_argument('-f', '--file', required=True, help='path to the source file to outline')
    structure_parser.add_argument('--json', action='store_true', help='output as JSON instead of a tree')

    dependency_parser = subparsers.add_parser('dependency', help='output included (use) file dependencies')
    dependency_parser.add_argument('-f', '--file', required=True, help='path to the source file')

    classpath_parser = subparsers.add_parser('classpath', help='output the inheritance path of a class/object')
    classpath_parser.add_argument('-f', '--file', required=True, help='path to the source file')
    classpath_parser.add_argument('-l', '--line', required=True, type=int, help='line of the Class/Object declaration')
    classpath_parser.add_argument('-s', '--stop', dest='stop_class', help='stop once this class is found')
    classpath_parser.add_argument('-I', '--include', action='append', dest='search_dirs',
                                  help="folder to search for used files (repeatable, default: the file's folder)")

    props_parser = subparsers.add_parser('props', help='output the properties declared in a line range as CSV')
    props_parser.add_argument('-f', '--file', required=True, help='path to the source file')
    props_parser.add_argument('-l', '--start', type=int, default=1,
                              help='first line to scan (default: 1); a block declaration line scans that block')
    props_parser.add_argument('-e', '--end', type=int, help='last line to scan (default: end of the block or file)')
    props_parser.add_argument('-w', '--web', action='store_true', help='only output properties marked { WebProperty=... }')
    props_parser.add_argument('-s', '--super', action='store_true',
                              help='include properties inherited through the class path of the Class/Object at --start')
    props_parser.add_argument('-I', '--include', action='append', dest='search_dirs',
                              help="with --super: folder to search for used files (repeatable, default: the file's folder)")

    args = parser.parse_args()

    if args.command == 'dependency':
        for f in get_inheritance(args.file):
            print(f)
    elif args.command == 'classpath':
        path = get_class_path(args.file, args.line, args.stop_class, args.search_dirs)
        print(' -> '.join(f"({c}, {f if f else 'not found'})" for c, f in path))
    elif args.command == 'props':
        if args.super:
            props = get_super_props(args.file, args.start, args.web, args.search_dirs)
        else:
            props = get_props(args.file, args.start, args.end, args.web)
        csv.writer(sys.stdout).writerows(props)
    else:
        page = compress_file(args.file)
        if args.json:
            print(json.dumps([asdict(node) for node in page], indent=2))
        else:
            print_structure(page)
