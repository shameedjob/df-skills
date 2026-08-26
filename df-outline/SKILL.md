---
name: df-outline
description: "A skill that parses dataflex files into an outline so that they can be read more efficiently"
---

When it is necessary to get context from a dataflex project file (typically .vw, .wo, .dd, .pkg files) we will run the following code instead of scanning the full file contents for context initially.

```
  python scripts/file_outliner.py -f file
```

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
  python scripts/file_outliner.py -f file --json
```

The default tree output is significantly cheaper in tokens for the same information and should be preferred. Only fall back to `--json` when you need clearer, machine-structured data (e.g. programmatically parsing the outline) — it costs substantially more tokens for large files, since it repeats keys (`block_name`, `block_type`, `start_line`, `end_line`, `children`) for every node instead of a single compact line. See the [README's benchmark](../README.md#benchmark) for measured numbers.

Afterwards, use an OS-specific command to read just the `start_line`-`end_line` range for the block you need instead of reading the whole file.

**macOS / Linux (bash, zsh):**
```bash
sed -n 'START,ENDp' file
```

**Windows (PowerShell):**
```powershell
Get-Content -Path file -TotalCount END | Select-Object -Skip (START - 1)
```

Replace `START`/`END` with the block's `start_line`/`end_line` from the JSON output.