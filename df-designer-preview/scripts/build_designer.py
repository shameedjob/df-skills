import argparse
import json
import os
from pathlib import Path
import random
import shutil
import sys

# df-outline lives beside this skill in the df-skills repo; its folder name has a hyphen,
# so its scripts folder is put on the path rather than imported as a package
DF_OUTLINE_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'df-outline', 'scripts')
sys.path.insert(0, os.path.normpath(DF_OUTLINE_SCRIPTS))

import file_outliner

def get_web_objects(file:str, search_dirs:list[str]|None=None, super_class:str='cWebObject')->dict:
    """Returns the hierarchy of Objects in file whose class path reaches super_class.

    Objects that are not web objects are left out along with everything nested in them.
    Other blocks (Procedures, Functions, Classes) are looked through for Objects.
    """
    super_class = super_class.lower()
    is_web_class = {}

    def is_web(node:file_outliner.StructNode)->tuple[bool, str]:
        superclass = file_outliner.get_superclass(file, node.start_line)
        if superclass not in is_web_class:
            path = file_outliner.get_class_path(file, node.start_line, super_class, search_dirs)
            is_web_class[superclass] = any(c.lower() == super_class for c, _ in path[1:])
        return is_web_class[superclass], superclass

    def collect(nodes:list[file_outliner.StructNode])->list[dict]:
        objects = []
        for node in nodes:
            if node.block_type.lower() != 'object':
                objects.extend(collect(node.children))
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
    if node.block_type.lower() == 'class':
        node = next((c for c in node.children
                     if c.block_type.lower() == 'procedure' and c.block_name.lower() == 'construct_object'), None)
        if node is None:
            return {}
    skipped = [(c.start_line, c.end_line) for c in node.children]

    values = {}
    with open(file, 'r') as f:
        for line_num, line in enumerate(f, start=1):
            if line_num <= node.start_line: continue
            if line_num >= node.end_line: break
            if any(start <= line_num <= end for start, end in skipped): continue
            args = file_outliner.strip_comment(line).strip().split()
            if len(args) >= 4 and args[0].lower() == 'set' and args[2].lower() == 'to':
                values[args[1].lower()] = ' '.join(args[3:])
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
    return value

def get_class_levels(file:str, line:int, search_dirs:list[str]|None=None)->list[tuple[str, str, file_outliner.StructNode]]:
    """Returns (class name, file, block) for the Object at line and each class above it, up to and including cWebObject."""
    levels = []
    for i, (class_name, class_file) in enumerate(file_outliner.get_class_path(file, line, 'cWebObject', search_dirs)):
        if class_file is None:
            break
        start = line if i == 0 else file_outliner.find_class_line(class_file, class_name)
        levels.append((class_name, class_file, file_outliner.find_node(file_outliner.compress_file(class_file), start)))
    return levels

def get_designer_class(file:str, line:int, search_dirs:list[str]|None=None,
                       constants:dict[str, str]|None=None)->tuple[str, dict[str, str]]|None:
    """Returns (sType, props) for the Object at line, or None if no class in its path sets psJSClass.

    props are the web properties from the class that sets psJSClass up to cWebObject, each with the
    value from the first of those levels that Sets or declares it, sorted by name ignoring case.
    """
    levels = get_class_levels(file, line, search_dirs)
    for js_level, (_, level_file, node) in enumerate(levels[1:], start=1):
        js_class = get_set_values(level_file, node).get('psjsclass')
        if js_class:
            break
    else:
        return None

    names = {}
    is_web = {}
    values = {}
    for _, level_file, node in levels[js_level:]:
        for key, value in get_set_values(level_file, node).items():
            values.setdefault(key, value)
        for _, name, value, web in file_outliner.scan_props(level_file, node.start_line):
            key = name.lower()
            if key not in names:
                names[key] = name
                is_web[key] = web
            values.setdefault(key, value)

    props = {names[key]: to_designer_value(values[key], constants) for key in names if is_web[key]}
    return to_designer_value(js_class), dict(sorted(props.items(), key=lambda item: item[0].lower()))

def build_designer_output(file:str, search_dirs:list[str]|None=None, base:dict|None=None,
                          constants:dict[str, str]|None=None)->dict:
    """Builds the designer output for the web objects in file.

    base is an existing output whose df.WebApp class and oWebApp root object are kept as they are;
    the file's top level web objects become the children of oWebApp. constants maps DataFlex
    constant names (lowercased) to the values written out for them.
    """
    web_app_class = next((c for c in (base or {}).get('aClasses', []) if c['sType'] == 'df.WebApp'),
                         {'sType': 'df.WebApp', 'props': {}})
    web_app = (base or {}).get('obj') or {'sName': 'oWebApp', 'props': {}}
    classes = {'df.WebApp': {**web_app_class, 'hClassId': 0}}

    used_handles = {web_app['iCdsNodeHandle']} if 'iCdsNodeHandle' in web_app else set()
    def new_handle()->str:
        while (handle := str(random.randint(100000, 999999))) in used_handles:
            pass
        used_handles.add(handle)
        return handle

    page = file_outliner.compress_file(file)
    designer_classes = {}  # superclass -> (sType, props); objects of the same class share them

    def build(obj:dict)->dict|None:
        superclass = obj['class']
        if superclass not in designer_classes:
            designer_classes[superclass] = get_designer_class(file, obj['start_line'], search_dirs, constants)
        if designer_classes[superclass] is None:
            return None
        s_type, class_props = designer_classes[superclass]
        if s_type not in classes:
            classes[s_type] = {'sType': s_type, 'hClassId': len(classes), 'props': class_props}

        prop_names = {name.lower(): name for name in classes[s_type]['props']}
        sets = get_set_values(file, file_outliner.find_node(page, obj['start_line']))
        return {
            'sName': obj['name'],
            'hClassId': classes[s_type]['hClassId'],
            'iCdsNodeHandle': new_handle(),
            'props': {prop_names[key]: to_designer_value(value, constants)
                      for key, value in sets.items() if key in prop_names},
            'aObjs': [child for child in map(build, obj['children']) if child],
        }

    root = {
        **web_app,
        'hClassId': 0,
        'iCdsNodeHandle': web_app.get('iCdsNodeHandle') or new_handle(),
        'aObjs': [child for child in map(build, get_web_objects(file, search_dirs)['objects']) if child],
    }
    return {'aClasses': list(classes.values()), 'obj': root}


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
                       output_path:str|None=None)->str:
    """Writes the preview template filled with the view name and designer output for file.

    The page is written to output_path, or by default to <view name>_preview.html beside the
    template so its relative asset links resolve. Returns the absolute path of the written page.
    """
    with open(template, 'r') as f:
        html = f.read()
    view_name = get_view_name(file) or Path(file).stem
    output = build_designer_output(file, search_dirs, base, constants)
    html = (html.replace('%%VIEW_OBJECT%%', to_script_literal(view_name))
                .replace('%%JSON_OBJECT%%', to_script_literal(output)))

    output_path = os.path.abspath(output_path or os.path.join(os.path.dirname(template), f'{view_name}_preview.html'))
    with open(output_path, 'w') as f:
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

def load_config()->dict:
    try:
        with open(get_config_path(), 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_config(config:dict):
    os.makedirs(get_cache_dir(), exist_ok=True)
    with open(get_config_path(), 'w') as f:
        json.dump(config, f, indent=4)

def require_file(path:str, description:str)->str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f'{description} not found: {path}')
    return path

def copy_app_css(config:dict, bundle_dir:str):
    """Copies the application's theme.css and application.css into the bundle."""
    shutil.copyfile(require_file(config['theme_css'], 'theme.css'), os.path.join(bundle_dir, 'theme.css'))
    shutil.copyfile(require_file(config['application_css'], 'application.css'), os.path.join(bundle_dir, 'application.css'))

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
    system_css = require_file(os.path.join(config['apphtml_dir'], 'WebUI', 'system.css'), 'system.css')

    bundle_dir = get_bundle_dir()
    if os.path.isdir(bundle_dir):
        shutil.rmtree(bundle_dir)
    shutil.copytree(designer_dir, bundle_dir)
    shutil.copyfile(system_css, os.path.join(bundle_dir, 'system.css'))
    copy_app_css(config, bundle_dir)
    save_config(config)
    return bundle_dir

def make_preview(file:str, extra_search_dirs:list[str]|None=None, base:dict|None=None,
                 constants:dict[str, str]|None=None)->str:
    """Refreshes the bundle's application CSS and writes the view's preview as its WebAppDesigner.html.

    Used files are searched for in the view's folder, the saved search folders, and extra_search_dirs.
    Returns the path of the preview page.
    """
    bundle_dir = get_bundle_dir()
    config = load_config()
    if not os.path.isdir(bundle_dir) or any(not config.get(key) for key in CONFIG_KEYS):
        raise FileNotFoundError(f'no preview bundle in {get_cache_dir()}, or its config is incomplete; '
                                'run the bundle command first')
    copy_app_css(config, bundle_dir)
    search_dirs = [os.path.dirname(os.path.abspath(file))] + config['search_dirs'] + (extra_search_dirs or [])
    return build_preview_html(file, search_dirs, base, constants,
                              output_path=os.path.join(bundle_dir, 'WebAppDesigner.html'))


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
        sub.add_argument('-b', '--base', help='existing designer output JSON to take the oWebApp object from')
        sub.add_argument('-c', '--constants', help='JSON file mapping DataFlex constant names to values')

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
                with open(args.base, 'r') as f:
                    base = json.load(f)
            constants = None
            if args.constants:
                with open(args.constants, 'r') as f:
                    constants = {name.lower(): value for name, value in json.load(f).items()}
            print(make_preview(args.file, getattr(args, 'extra_search_dirs', None), base, constants))
    except (FileNotFoundError, ValueError) as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(2)
