import argparse
import copy
from functools import lru_cache
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys
import textwrap

# df-outline lives beside this skill in the df-skills repo; its folder name has a hyphen,
# so its scripts folder is put on the path rather than imported as a package
DF_OUTLINE_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'df-outline', 'scripts')
sys.path.insert(0, os.path.normpath(DF_OUTLINE_SCRIPTS))

import file_outliner

# letters, digits, and underscores (DataFlex names such as oOrder_DD use underscores)
OBJECT_NAME = re.compile(r'[A-Za-z0-9_]+')

# DataFlex enum values sent to the browser by the WebApp designer.
DEFAULT_CONSTANTS = {
    'c_webdefault': '-1',
    'prcenter': '0',
    'prleft': '1',
    'prright': '2',
    'prtop': '3',
    'prbottom': '4',
    'aligncenter': '1',
    'ltinherit': '0',
    'ltflow': '1',
    'ltgrid': '2',
    'lpleft': '0',
    'lptop': '1',
    'lpright': '2',
    'lpfloat': '3',
    'smfind': '0',
    'smvalidationtable': '1',
    'smcustom': '2',
    'fpfloatbycontrol': '1',
}

# These client classes exist in the framework, but Studio previews their
# standard parent control instead. Custom JavaScript classes are treated the
# same way because the standalone designer bundle does not load application JS.
DESIGNER_CLASS_FALLBACKS = {
    'df.WebMuliSelectList': 'df.WebList',
    'df.WebColumnSelectionIndicator': 'df.WebColumnCheckbox',
}

CLASS_SOURCE_EXTENSIONS = {'.pkg', '.inc'}
CLASS_DECLARATION = re.compile(r'^\s*Class\s+(\w+)\s+is\s+an?\s+(\w+)', re.IGNORECASE)

@lru_cache(maxsize=None)
def source_lines(file:str)->list[str]:
    return file_outliner.read_source(file).splitlines()

@lru_cache(maxsize=None)
def scan_class_props(file:str, line:int):
    return file_outliner.scan_props(file, line)

SET_VALUES_CACHE = {}

class ClassIndex:
    """Persistent class -> [parent class, file] lookup with per-file invalidation."""
    def __init__(self, search_dirs:list[str], view_file:str|None=None):
        self.search_dirs = list(dict.fromkeys(os.path.abspath(folder) for folder in search_dirs))
        self.cache_path = Path(get_cache_dir()) / 'class-inheritance.json'
        try:
            previous = json.loads(self.cache_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = {}
        old_files = (previous.get('files', {}) if previous.get('version') == 2
                     and previous.get('search_dirs') == self.search_dirs else {})
        files = {}
        chosen_names = set()
        changed = previous.get('version') != 2 or previous.get('search_dirs') != self.search_dirs

        def add_file(path:str):
            nonlocal changed
            stat = os.stat(path)
            old = old_files.get(path)
            if old and old['mtime_ns'] == stat.st_mtime_ns and old['size'] == stat.st_size:
                files[path] = old
            else:
                classes = []
                for line_number, line in enumerate(source_lines(path), 1):
                    if match := CLASS_DECLARATION.match(line):
                        classes.append([match.group(1).lower(), match.group(2).lower(), line_number])
                files[path] = {'mtime_ns': stat.st_mtime_ns, 'size': stat.st_size, 'classes': classes}
                changed = True

        for folder in self.search_dirs:
            for root, dirs, names in os.walk(folder):
                dirs.sort()
                for name in sorted(names):
                    if Path(name).suffix.lower() not in CLASS_SOURCE_EXTENSIONS or name.lower() in chosen_names:
                        continue
                    chosen_names.add(name.lower())
                    add_file(os.path.join(root, name))
        if view_file:
            add_file(os.path.abspath(view_file))

        self.entries = {}
        for path, info in files.items():
            for name, parent, line in info['classes']:
                self.entries.setdefault(name, (parent, path, line))
        if changed or len(files) != len(old_files):
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            data = {'version': 2, 'search_dirs': self.search_dirs, 'files': files,
                    'classes': {name: [parent, path] for name, (parent, path, _) in self.entries.items()}}
            temp_path = self.cache_path.with_suffix('.tmp')
            temp_path.write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
            temp_path.replace(self.cache_path)

    def reaches(self, name:str, ancestor:str)->bool:
        current = name.lower()
        ancestor = ancestor.lower()
        seen = set()
        while current and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            current = self.entries.get(current, ('', None, 0))[0]
        return False

    def path(self, name:str, stop_class:str='cWebObject')->list[tuple[str, str, int]]:
        path = []
        current = name.lower()
        seen = set()
        while current and current not in seen:
            seen.add(current)
            entry = self.entries.get(current)
            if entry is None:
                break
            parent, file, line = entry
            path.append((current, file, line))
            if current == stop_class.lower():
                break
            current = parent
        return path

def get_web_objects(file:str, search_dirs:list[str]|None=None, super_class:str='cWebObject',
                    class_index:ClassIndex|None=None)->dict:
    """Returns the hierarchy of Objects in file whose class path reaches super_class.

    Objects that are not web objects, or whose names are not plain identifiers (such as the
    `Object !1 is a !2` placeholders in #COMMAND macros), are left out along with everything nested in them.
    Other blocks (Procedures, Functions, Classes) are looked through for Objects.
    """
    super_class = super_class.lower()
    is_web_class = {}
    lines = source_lines(file)

    def is_web(node:file_outliner.StructNode)->tuple[bool, str]:
        superclass = lines[node.start_line - 1].strip().split()[-1].lower()
        if superclass not in is_web_class:
            if class_index:
                is_web_class[superclass] = class_index.reaches(superclass, super_class)
            else:
                path = file_outliner.get_class_path(file, node.start_line, super_class, search_dirs)
                is_web_class[superclass] = any(c.lower() == super_class for c, _ in path[1:])
        return is_web_class[superclass], superclass

    def collect(nodes:list[file_outliner.StructNode])->list[dict]:
        objects = []
        for node in nodes:
            if node.block_type.lower() != 'object':
                objects.extend(collect(node.children))
                continue
            if not OBJECT_NAME.fullmatch(node.block_name):
                continue
            web, superclass = is_web(node)
            if web:
                objects.append({
                    'name': node.block_name,
                    'class': superclass,
                    'start_line': node.start_line,
                    'end_line': node.end_line,
                    'children': collect(node.children),
                })
        return objects

    return {'file': file, 'objects': collect(file_outliner.compress_file(file))}


def get_set_values(file:str, node:file_outliner.StructNode)->dict[str, str]:
    """Returns {property name (lowercased): value} for the `Set name to value` lines that initialize node.

    For an Object these are the lines directly in its block; for a Class, the lines directly in
    its Construct_Object procedure. Lines inside nested blocks are ignored, as are Sets aimed at
    another object (`Set name of oOther to value`).
    """
    cache_key = (file, node.start_line)
    if cache_key in SET_VALUES_CACHE:
        return SET_VALUES_CACHE[cache_key]
    if node.block_type.lower() == 'class':
        node = next((c for c in node.children
                     if c.block_type.lower() == 'procedure' and c.block_name.lower() == 'construct_object'), None)
        if node is None:
            return {}
    skipped = [(c.start_line, c.end_line) for c in node.children]

    values = {}
    multiline_name = None
    multiline_lines = []
    with file_outliner.open_source(file) as f:
        for line_num, line in enumerate(f, start=1):
            if line_num <= node.start_line: continue
            if line_num >= node.end_line: break
            if multiline_name:
                if '"""' in line:
                    multiline_lines.append(line.split('"""', 1)[0].rstrip('\r\n'))
                    values[multiline_name] = textwrap.dedent('\n'.join(multiline_lines)).strip('\n')
                    multiline_name, multiline_lines = None, []
                else:
                    multiline_lines.append(line.rstrip('\r\n'))
                continue
            if any(start <= line_num <= end for start, end in skipped): continue
            args = file_outliner.strip_comment(line).strip().split()
            if len(args) >= 4 and args[0].lower() == 'set' and args[2].lower() == 'to':
                name = args[1].lower()
                value = ' '.join(args[3:])
                if value.startswith('"""') and value.count('"""') == 1:
                    multiline_name = name
                    multiline_lines = [value[3:]]
                else:
                    values[name] = value
    SET_VALUES_CACHE[cache_key] = values
    return values

def get_web_property_values(file:str, line:int, search_dirs:list[str]|None=None)->list[tuple[str, str, str]]:
    """Returns (class, name, value) for each web property of the Class/Object declared at line,
    with value being what the property is initialized as.

    Walking the class path from the Class/Object up, the first level that Sets or declares a
    property decides its value; a Set wins over a declaration at the same level.
    """
    props = [list(p) for p in file_outliner.get_super_props(file, line, True, search_dirs)]
    unresolved = {name.lower(): i for i, (_, name, _) in enumerate(props)}

    for i, (class_name, class_file) in enumerate(file_outliner.get_class_path(file, line, None, search_dirs)):
        if not unresolved or class_file is None:
            break
        start = line if i == 0 else file_outliner.find_class_line(class_file, class_name)
        node = file_outliner.find_node(file_outliner.compress_file(class_file), start)
        sets = get_set_values(class_file, node)
        declared = {name.lower() for _, name, _, _ in file_outliner.scan_props(class_file, start)}
        for name in list(unresolved):
            if name in sets:
                props[unresolved.pop(name)][2] = sets[name]
            elif name in declared:
                # the declared default is already the value from get_super_props
                unresolved.pop(name)
    return [tuple(p) for p in props]


def get_property_value(file:str, line:int, name:str, search_dirs:list[str]|None=None)->str|None:
    """Returns what property `name` is initialized as for the Class/Object declared at line.

    Unlike get_web_property_values the property does not need to be declared in the class path
    (it may come from a mixin), and it does not need to be a web property. Walking the class path
    from the Class/Object up, the first level that Sets or declares it decides the value; a Set wins
    over a declaration at the same level. Returns None if no level does.
    """
    name = name.lower()
    for i, (class_name, class_file) in enumerate(file_outliner.get_class_path(file, line, None, search_dirs)):
        if class_file is None:
            break
        start = line if i == 0 else file_outliner.find_class_line(class_file, class_name)
        node = file_outliner.find_node(file_outliner.compress_file(class_file), start)
        sets = get_set_values(class_file, node)
        if name in sets:
            return sets[name]
        for _, prop_name, value, _ in file_outliner.scan_props(class_file, start):
            if prop_name.lower() == name:
                return value
    return None

def get_js_class(file:str, line:int, search_dirs:list[str]|None=None)->str|None:
    """Returns the psJSClass the Class/Object declared at line is initialized with."""
    return get_property_value(file, line, 'psJSClass', search_dirs)


def to_designer_value(value:str, constants:dict[str, str]|None=None)->str:
    """Converts a DataFlex value to the string form the designer expects."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
        return value[1:-1]
    lowered = value.lower()
    if lowered in ('true', '(true)'):
        return '1'
    if lowered in ('false', '(false)'):
        return '0'
    if constants and lowered in constants:
        return str(constants[lowered])
    if lowered in DEFAULT_CONSTANTS:
        return DEFAULT_CONSTANTS[lowered]
    return value

def to_object_property_value(name:str, value:str, constants:dict[str, str]|None=None)->str:
    # A server function cannot be evaluated by this static preview. A literal
    # expression in psHtml would otherwise appear as visible text in the view.
    if name.lower() == 'pshtml' and value.strip().startswith('('):
        return ''
    return to_designer_value(value, constants)

def get_workspace_constants(search_dirs:list[str])->dict[str, str]:
    """Resolve numeric Define and Enum_List values from framework constant packages."""
    result = {}
    for filename in ('WebUIConstants.pkg', 'WebAppConstants.pkg', 'tSuggestion.pkg'):
        path = next((Path(folder) / filename for folder in search_dirs
                     if (Path(folder) / filename).is_file()), None)
        if path is None:
            continue
        in_enum = False
        enum_value = 0
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            line = file_outliner.strip_comment(line).strip()
            if re.fullmatch(r'Enum_List', line, re.IGNORECASE):
                in_enum, enum_value = True, 0
            elif re.fullmatch(r'End_Enum_List', line, re.IGNORECASE):
                in_enum = False
            elif match := re.match(r'Define\s+(\w+)(?:\s+for\s+(-?\d+))?\b', line, re.IGNORECASE):
                if match.group(2) is not None:
                    value = int(match.group(2))
                elif in_enum:
                    value = enum_value
                else:
                    continue
                result.setdefault(match.group(1).lower(), str(value))
                if in_enum:
                    enum_value = value + 1
    return result

def get_class_levels(file:str, line:int, search_dirs:list[str]|None=None,
                     class_index:ClassIndex|None=None)->list[tuple[str, str, file_outliner.StructNode]]:
    """Returns (class name, file, block) for the Object at line and each class above it, up to and including cWebObject."""
    if class_index:
        page = file_outliner.compress_file(file)
        object_node = file_outliner.find_node(page, line)
        source_line = source_lines(file)[line - 1]
        superclass = source_line.strip().split()[-1]
        levels = [(object_node.block_name, file, object_node)]
        for class_name, class_file, class_line in class_index.path(superclass):
            node = file_outliner.find_node(file_outliner.compress_file(class_file), class_line)
            if node:
                levels.append((class_name, class_file, node))
        return levels
    levels = []
    for i, (class_name, class_file) in enumerate(file_outliner.get_class_path(file, line, 'cWebObject', search_dirs)):
        if class_file is None:
            break
        start = line if i == 0 else file_outliner.find_class_line(class_file, class_name)
        levels.append((class_name, class_file, file_outliner.find_node(file_outliner.compress_file(class_file), start)))
    return levels

def get_designer_class(file:str, line:int, search_dirs:list[str]|None=None,
                       constants:dict[str, str]|None=None,
                       class_defaults:dict[str, dict[str, str]]|None=None,
                       class_index:ClassIndex|None=None)->tuple[str, dict[str, str]]|None:
    """Returns (sType, props) for the Object at line, or None if no class in its path sets psJSClass.

    props include defaults and overrides from the full DataFlex subclass chain,
    not only from the ancestor that sets psJSClass.
    """
    levels = get_class_levels(file, line, search_dirs, class_index)
    js_class = None
    for _, level_file, node in levels[1:]:
        js_class = get_set_values(level_file, node).get('psjsclass')
        if js_class:
            js_class = to_designer_value(js_class)
            if js_class.startswith('df.'):
                js_class = DESIGNER_CLASS_FALLBACKS.get(js_class, js_class)
                break
    if not js_class or not js_class.startswith('df.'):
        return None

    names = {}
    is_web = {}
    values = {}
    for _, level_file, node in levels[1:]:
        for key, value in get_set_values(level_file, node).items():
            values.setdefault(key, value)
        for _, name, value, web in scan_class_props(level_file, node.start_line):
            key = name.lower()
            if key not in names:
                names[key] = name
                is_web[key] = web
            values.setdefault(key, value)

    # Some framework properties are declared by imported mixins, which the
    # class outline does not expand. The Studio class catalog supplies their
    # canonical names so both class defaults and object Sets retain them.
    known_names = {}
    for name in (class_defaults or {}).get(js_class, {}):
        known_names.setdefault(name.lower(), name)
    for key in values:
        if key in known_names:
            names[key] = known_names[key]
            is_web[key] = True

    props = {names[key]: to_designer_value(values[key], constants) for key in names if is_web[key]}
    return js_class, dict(sorted(props.items(), key=lambda item: item[0].lower()))

WEB_APP_DEFAULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'res', 'webapp.json')
DESIGNER_CLASS_DEFAULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'res',
                                       'designer-classes-1.0.52.json')

def load_web_app_defaults()->dict:
    """The df.WebApp class and oWebApp object used when no base output provides them."""
    with open(WEB_APP_DEFAULTS, 'r', encoding='utf-8') as f:
        return json.load(f)

def find_web_app_class(output:dict|None)->dict|None:
    return next((c for c in (output or {}).get('aClasses', []) if c.get('sType') == 'df.WebApp'), None)

def load_designer_class_defaults(base:dict|None=None)->dict[str, dict[str, str]]:
    """Load browser-side class defaults, overriding them from a supplied designer export."""
    def normalize_props(props:dict)->dict:
        normalized = {}
        seen = set()
        for name, value in props.items():
            if name.lower() not in seen:
                normalized[name] = value
                seen.add(name.lower())
        return normalized

    with open(DESIGNER_CLASS_DEFAULTS, 'r', encoding='utf-8') as f:
        entries = json.load(f)['aClasses']
    defaults = {entry['sType']: normalize_props(entry['props']) for entry in entries}
    for entry in (base or {}).get('aClasses', []):
        defaults[entry['sType']] = normalize_props(entry['props'])
    return defaults

def get_web_app_sets(file:str)->dict[str, str]:
    """Read the application's oWebApp settings next to its view source, when available."""
    app_file = os.path.join(os.path.dirname(os.path.abspath(file)), 'WebApp.src')
    if not os.path.isfile(app_file):
        return {}
    app_node = next((node for node in file_outliner.compress_file(app_file)
                     if node.block_type.lower() == 'object' and node.block_name.lower() == 'owebapp'), None)
    return get_set_values(app_file, app_node) if app_node else {}

def build_designer_output(file:str, search_dirs:list[str]|None=None, base:dict|None=None,
                          constants:dict[str, str]|None=None)->dict:
    """Builds the designer output for the web objects in file.

    The df.WebApp class and oWebApp root object are copied with their props unchanged from base
    (an existing output), falling back to res/webapp.json for whichever base does not have; the
    file's top level web objects become the children of oWebApp. constants maps DataFlex constant
    names (lowercased) to the values written out for them.
    """
    web_app_class = find_web_app_class(base) or find_web_app_class(load_web_app_defaults())
    web_app = (base or {}).get('obj') or load_web_app_defaults()['obj']
    class_defaults = load_designer_class_defaults(base)
    class_index = ClassIndex(search_dirs or [os.path.dirname(os.path.abspath(file))], file)
    classes = [{'sType': 'df.WebApp', 'hClassId': 0, 'props': copy.deepcopy(web_app_class['props'])}]

    base_handles = {}
    def collect_handles(obj:dict, parent_path:str=''):
        path = parent_path + '/' + obj['sName']
        if obj.get('iCdsNodeHandle'):
            base_handles[path] = obj['iCdsNodeHandle']
        for child in obj.get('aObjs', []):
            collect_handles(child, path)
    if base and base.get('obj'):
        collect_handles(base['obj'])

    reserved_handles = set(base_handles.values())
    used_handles = set()
    def new_handle(path:str)->str:
        if (handle := base_handles.get(path)) and handle not in used_handles:
            used_handles.add(handle)
            return handle
        while (handle := str(random.randint(100000, 999999))) in used_handles or handle in reserved_handles:
            pass
        used_handles.add(handle)
        return handle

    page = file_outliner.compress_file(file)
    designer_classes = {}  # superclass -> (sType, props); objects of the same class share them
    class_ids = {}  # keep distinct DataFlex classes even when they use the same JavaScript type

    def build(obj:dict, parent_path:str)->dict|None:
        superclass = obj['class']
        path = parent_path + '/' + obj['name']
        if superclass not in designer_classes:
            designer_classes[superclass] = get_designer_class(file, obj['start_line'], search_dirs,
                                                              constants, class_defaults, class_index)
        if designer_classes[superclass] is None:
            return None
        s_type, class_props = designer_classes[superclass]
        if superclass not in class_ids:
            class_ids[superclass] = len(classes)
            if s_type in class_defaults:
                props = copy.deepcopy(class_defaults[s_type])
                canonical = {name.lower(): name for name in props}
                props.update({canonical[name.lower()]: value for name, value in class_props.items()
                              if name.lower() in canonical and not value.strip().startswith('(')})
            else:
                props = copy.deepcopy(class_props)
            classes.append({'sType': s_type, 'hClassId': len(classes), 'props': props})

        prop_names = {name.lower(): name for name in classes[class_ids[superclass]]['props']}
        sets = get_set_values(file, file_outliner.find_node(page, obj['start_line']))
        return {
            'sName': obj['name'],
            'hClassId': class_ids[superclass],
            'iCdsNodeHandle': new_handle(path),
            'props': {prop_names[key]: to_object_property_value(key, value, constants)
                      for key, value in sets.items() if key in prop_names},
            'aObjs': [child for child in (build(c, path) for c in obj['children']) if child],
        }

    root_props = copy.deepcopy(web_app.get('props', {}))
    if base is None:
        root_names = {name.lower(): name for name in classes[0]['props']}
        root_props.update({root_names[key]: to_designer_value(value, constants)
                           for key, value in get_web_app_sets(file).items() if key in root_names})
    root_path = '/' + web_app.get('sName', 'oWebApp')
    root = {
        'sName': web_app.get('sName', 'oWebApp'),
        'hClassId': 0,
        'iCdsNodeHandle': new_handle(root_path),
        'props': root_props,
        'aObjs': [child for child in (build(c, root_path)
                  for c in get_web_objects(file, search_dirs, class_index=class_index)['objects']) if child],
    }
    return {'aClasses': classes, 'obj': root}


TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'res', 'base.html')

def get_view_name(file:str)->str|None:
    """Returns the name of the first top level Object in file (the view)."""
    return next((node.block_name for node in file_outliner.compress_file(file)
                 if node.block_type.lower() == 'object'), None)

def to_script_literal(value)->str:
    # "</" would end the <script> block the literal is written into
    return json.dumps(value).replace('</', '<\\/')

def build_preview_html(file:str, search_dirs:list[str]|None=None, base:dict|None=None,
                       constants:dict[str, str]|None=None, template:str=TEMPLATE,
                       output_path:str|None=None, json_output_path:str|None=None)->str:
    """Writes the preview template filled with the view name and designer output for file.

    The page is written to output_path, or by default to <view name>_preview.html beside the
    template so its relative asset links resolve. Returns the absolute path of the written page.
    """
    with open(template, 'r', encoding='utf-8') as f:
        html = f.read()
    view_name = get_view_name(file) or Path(file).stem
    output = build_designer_output(file, search_dirs, base, constants)
    if not output['obj']['aObjs']:
        raise ValueError(f'no web objects found in {file}; the classes it uses could not be traced to '
                         f'cWebObject in the search folders: {search_dirs}')
    if json_output_path:
        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=4)
    html = (html.replace('%%VIEW_OBJECT%%', to_script_literal(view_name))
                .replace('%%JSON_OBJECT%%', to_script_literal(output)))

    output_path = os.path.abspath(output_path or os.path.join(os.path.dirname(template), f'{view_name}_preview.html'))
    if os.path.isfile(output_path):
        os.chmod(output_path, 0o666)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    return output_path


def get_cache_dir()->str:
    """Folder the preview bundle and its config are kept in (override with DF_SKILLS_CACHE)."""
    if os.environ.get('DF_SKILLS_CACHE'):
        root = os.environ['DF_SKILLS_CACHE']
    elif os.name == 'nt':
        root = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'df-skills')
    else:
        root = os.path.join(os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache')), 'df-skills')
    return os.path.join(root, 'designer-preview')

def get_config_path()->str:
    return os.path.join(get_cache_dir(), 'config.json')

def get_bundle_dir()->str:
    return os.path.join(get_cache_dir(), 'bundle')

def get_workspace_dependency_dirs(file:str)->list[str]:
    """Find AppSrc folders of file-based .sws dependencies of the view's workspace."""
    view_dir = Path(file).resolve().parent
    workspace = next((sorted(folder.glob('*.sws'))[0]
                      for folder in (view_dir, *view_dir.parents) if any(folder.glob('*.sws'))), None)
    if workspace is None:
        return []
    found = []
    seen = set()

    def visit(sws:Path):
        if sws in seen or not sws.is_file():
            return
        seen.add(sws)
        try:
            data = json.loads(sws.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            return
        for name in data.get('dependencies', []):
            if not name.lower().endswith('.sws'):
                continue
            dependency = (sws.parent / name).resolve()
            app_src = dependency.parent / 'AppSrc'
            if dependency.is_file() and app_src.is_dir() and str(app_src) not in found:
                found.append(str(app_src))
            visit(dependency)

    visit(workspace)
    return found

def load_config()->dict:
    try:
        with open(get_config_path(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_config(config:dict):
    os.makedirs(get_cache_dir(), exist_ok=True)
    with open(get_config_path(), 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4)

def require_file(path:str, description:str)->str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f'{description} not found: {path}')
    return path

def copy_stylesheets(config:dict, bundle_dir:str):
    """Refresh the three root-level stylesheets in HTML load order."""
    sources = (
        ('system.css', os.path.join(config['apphtml_dir'], 'WebUI', 'system.css')),
        ('application.css', config['application_css']),
        ('theme.css', config['theme_css']),
    )
    for name, source in sources:
        require_file(source, name)
    for name, source in sources:
        target = os.path.join(bundle_dir, name)
        if os.path.isfile(target):
            os.chmod(target, 0o666)
        shutil.copyfile(source, target)

CONFIG_KEYS = ('theme_css', 'application_css', 'apphtml_dir', 'search_dirs')

def make_preview_bundle(theme_css:str|None=None, application_css:str|None=None, apphtml_dir:str|None=None,
                        search_dirs:list[str]|None=None)->str:
    """(Re)builds the preview bundle in the cache and returns its folder.

    The bundle is a copy of <AppHtml>/WebUI_Designer with the application's theme.css and
    application.css and <AppHtml>/WebUI/system.css added. search_dirs are the folders searched for
    used files when previewing (the workspace source and the DataFlex Pkg folder). Paths not given
    are taken from the saved config; the paths used are saved for later runs.
    """
    config = load_config()
    for key, value in (('theme_css', theme_css), ('application_css', application_css), ('apphtml_dir', apphtml_dir)):
        if value:
            config[key] = os.path.abspath(value)
    if search_dirs:
        config['search_dirs'] = [os.path.abspath(folder) for folder in search_dirs]
    missing = [key for key in CONFIG_KEYS if not config.get(key)]
    if missing:
        raise ValueError(f'missing paths (not given and not in {get_config_path()}): {", ".join(missing)}')
    for folder in config['search_dirs']:
        if not os.path.isdir(folder):
            raise FileNotFoundError(f'search folder not found: {folder}')

    designer_dir = os.path.join(config['apphtml_dir'], 'WebUI_Designer')
    if not os.path.isdir(designer_dir):
        raise FileNotFoundError(f'WebUI_Designer folder not found: {designer_dir}')
    require_file(os.path.join(config['apphtml_dir'], 'WebUI', 'system.css'), 'system.css')

    bundle_dir = get_bundle_dir()
    if os.path.isdir(bundle_dir):
        def remove_readonly(func, path, _exc_info):
            os.chmod(path, 0o700)
            func(path)
        shutil.rmtree(bundle_dir, onerror=remove_readonly)
    shutil.copytree(designer_dir, bundle_dir, copy_function=shutil.copyfile)
    copy_stylesheets(config, bundle_dir)
    save_config(config)
    return bundle_dir

def make_preview(file:str, extra_search_dirs:list[str]|None=None, base:dict|None=None,
                 constants:dict[str, str]|None=None, json_output_path:str|None=None)->str:
    """Refreshes the bundle's three CSS files and writes the view's preview as its WebAppDesigner.html.

    Used files are searched for in the view's folder, the saved search folders, and extra_search_dirs.
    Returns the path of the preview page.
    """
    bundle_dir = get_bundle_dir()
    config = load_config()
    if not os.path.isdir(bundle_dir) or any(not config.get(key) for key in CONFIG_KEYS):
        raise FileNotFoundError(f'no preview bundle in {get_cache_dir()}, or its config is incomplete; '
                                'run the bundle command first')
    copy_stylesheets(config, bundle_dir)
    search_dirs = ([os.path.dirname(os.path.abspath(file))] + config['search_dirs']
                   + get_workspace_dependency_dirs(file) + (extra_search_dirs or []))
    resolved_constants = get_workspace_constants(search_dirs)
    resolved_constants.update(constants or {})
    return build_preview_html(file, search_dirs, base, resolved_constants,
                              output_path=os.path.join(bundle_dir, 'WebAppDesigner.html'),
                              json_output_path=json_output_path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='build a designer preview of a DataFlex web view')
    subparsers = parser.add_subparsers(dest='command', required=True)

    bundle_parser = subparsers.add_parser('bundle', help='(re)build the cached preview bundle')
    bundle_parser.add_argument('--theme', dest='theme_css', help="path to the application's theme.css")
    bundle_parser.add_argument('--application-css', dest='application_css', help="path to the application's application.css")
    bundle_parser.add_argument('--apphtml', dest='apphtml_dir', help='path to the DataFlex AppHtml folder')
    bundle_parser.add_argument('-I', '--include', action='append', dest='search_dirs',
                               help='folder to search for used files when previewing, e.g. the workspace source '
                                    'and the DataFlex Pkg folder (repeatable; replaces the saved list)')

    preview_parser = subparsers.add_parser('preview', help='generate the preview page for a view in the bundle')
    preview_parser.add_argument('-I', '--include', action='append', dest='extra_search_dirs',
                                help='extra folder to search for used files in this run only (repeatable)')
    for sub in (bundle_parser, preview_parser):
        sub.add_argument('-f', '--file', required=sub is preview_parser,
                         help='path to the .wo/.vw file' + ('' if sub is preview_parser else ' to preview right away'))
        sub.add_argument('-b', '--base', help='existing designer output JSON for oWebApp and class defaults')
        sub.add_argument('-c', '--constants', help='JSON file mapping DataFlex constant names to values')
        sub.add_argument('-j', '--json-output', help='also write the generated designer definition to this JSON file')

    status_parser = subparsers.add_parser('status', help='print the cache folder, saved paths, and whether the bundle exists')
    args = parser.parse_args()

    if args.command == 'status':
        print(json.dumps({'cache_dir': get_cache_dir(), 'bundle_built': os.path.isdir(get_bundle_dir()),
                          'config': load_config()}, indent=4))
        sys.exit(0)

    try:
        if args.command == 'bundle':
            print(make_preview_bundle(args.theme_css, args.application_css, args.apphtml_dir, args.search_dirs))
        if args.file:
            base = None
            if args.base:
                with open(args.base, 'r', encoding='utf-8') as f:
                    base = json.load(f)
            constants = None
            if args.constants:
                with open(args.constants, 'r', encoding='utf-8') as f:
                    constants = {name.lower(): value for name, value in json.load(f).items()}
            print(Path(make_preview(args.file, getattr(args, 'extra_search_dirs', None), base, constants,
                                    args.json_output)).as_uri())
    except (FileNotFoundError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(2)
