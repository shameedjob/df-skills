
import argparse
import json
from dataclasses import asdict, dataclass, field


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
close_blocks = set(['end_object', 'end_function', 'end_procedure', 'end_class'])



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


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--file', required=True, help='path to the source file to outline')
    parser.add_argument('--json', action='store_true', help='output as JSON instead of a tree')
    args = parser.parse_args()

    page = compress_file(args.file)
    if args.json:
        print(json.dumps([asdict(node) for node in page], indent=2))
    else:
        print_structure(page)