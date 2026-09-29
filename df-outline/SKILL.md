---
name: df-outline
description: "A skill that parses dataflex files into an outline so that they can be read more efficiently"
---

When it is necessary to get context from a dataflex project file (typically .vw, .wo, .dd, .pkg files) we will run the following code instead of scanning the full file contents for context initially.

```
  python scripts/file_outliner.py structure -f file
```

The script has four subcommands:

| Subcommand | Purpose |
| --- | --- |
| `structure` | Outline the Objects, Functions, Procedures, and Classes of a file (see below) |
| `dependency` | List the files a file includes with `Use` |
| `classpath` | Follow the inheritance chain of a Class/Object declaration through its `Use` dependencies |
| `props` | List the properties declared within a line range as CSV, optionally only `{ WebProperty=... }` ones |

Using that output you can find the line positions for specific functional blocks within a dataflex file: the Objects, Functions, Procedures, and Classes necessary for a project to run.

As a reminder:
  - Objects  
  - Procedures: functions with no return, called with Send typically
  - Functions: functions with a defined return in their header line '.* Returns TYPE'

## Parsing the default (tree) output

Each line has the form:

```
type name @start_line,end_line
```

Nesting/parentage is denoted by a `|` followed by one underscore per level of depth, before the line's own content — a top-level block has no prefix, a child has `|_`, a grandchild has `|__`, and so on. For example:

```
Object oInvt_DD @142,159
|_ Procedure OnRegisterFilters @145,147
|_ Procedure OnBuildSqlFilter @149,157
Object oSalesP_DD @173,180
|_ Procedure OnRegisterFilters @177,179
```

`oInvt_DD` is a top-level Object spanning lines 142-159, and `OnRegisterFilters`/`OnBuildSqlFilter` are Procedures nested one level inside it (children of `oInvt_DD`), at lines 145-147 and 149-157 respectively. Count the underscores to determine which ancestor a block belongs to — a block belongs to the nearest preceding line with one fewer underscore (or no prefix, for depth 1).

## Falling back to `--json`

```
  python scripts/file_outliner.py structure -f file --json
```

The default tree output is significantly cheaper in tokens for the same information and should be preferred. Only fall back to `--json` when you need clearer, machine-structured data (e.g. programmatically parsing the outline) — it costs substantially more tokens for large files, since it repeats keys (`block_name`, `block_type`, `start_line`, `end_line`, `children`) for every node instead of a single compact line. See the [README's benchmark](https://github.com/shameedjob/df-skills#benchmark) for measured numbers.

Afterwards, use an OS-specific command to read just the `start_line`-`end_line` range for the block you need instead of reading the whole file.

**macOS / Linux (bash, zsh):**
```bash
sed -n 'START,ENDp' file
```

**Windows (PowerShell):**
```powershell
Get-Content -Path file -TotalCount END | Select-Object -Skip (START - 1)
```

Replace `START`/`END` with the block's `start_line`/`end_line` from the outline.

## Dependencies

```
  python scripts/file_outliner.py dependency -f file
```

Prints one used file per line (e.g. `cWebPanel.pkg`), in the order of the file's `Use` statements.

## Class path

```
  python scripts/file_outliner.py classpath -f file -l LINE [-s STOP_CLASS] [-I FOLDER ...]
```

`LINE` is the line of a `Class X is a Y` or `Object X is a Y` declaration (take it from the `structure` output). The script finds where the superclass `Y` is defined by searching the file and its `Use` dependencies depth first, then repeats for that class's superclass until the chain ends or `STOP_CLASS` is reached. Output:

```
(oView, view.vw) -> (cmid, pkg/cMid.pkg) -> (cbase, pkg/cBase.pkg) -> (cwebobject, not found)
```

Class names after the first are lowercased. `not found` means no searched folder defines that class, usually because it lives in the DataFlex install's `Pkg` folder. Pass `-I` once per folder to search (subfolders are included); it defaults to the file's own folder. Use `-s` to stop at the class you care about instead of walking the whole chain.

## Properties

```
  python scripts/file_outliner.py props -f file [-l START] [-e END] [--web] [--super [-I FOLDER ...]]
```

Prints a headerless CSV table (`class,name,value`) of every `Property` declared in the line range:

```
String,psLabel,""""""
Integer,piOrderId,0
String,psUrl,"""http://example.com"""
```

`class` is the property's type, `name` its name, and `value` its default value with any trailing `//` comment removed; it is empty when the declaration has none. Values are CSV-quoted, so a DataFlex string `"x"` appears as `"""x"""`.

- `-l START`: when `START` is the declaration line of a Class/Object (its `start_line` from the `structure` output), only that block is scanned, and properties declared inside its nested Objects are skipped. Otherwise lines `START`-`END` are scanned as-is. The default is the whole file.
- `--web` (`-w`): only list properties declared right after a `{ WebProperty=... }` annotation.
- `--super` (`-s`): also list the properties inherited through the class path of the Class/Object at `START`, subclass first. A property redeclared lower in the path overrides the one above it, including whether it is a web property. `-I` works as it does for `classpath`, and `-e` is ignored.
