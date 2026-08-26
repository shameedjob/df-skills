---
name: df-outline
description: "A skill that parses dataflex files into an outline so that they can be read more efficiently"
---

When it is necessary to get context from a dataflex project file (typically .vw, .wo, .dd, .pkg files) we will run the following code instead of scanning the full file contents for context initially.

```
  python scripts/file_outliner.py -f file --json
```

Using that output you can find the line positions for specific functional blocks within a dataflex file: the Objects, Functions, Procedures, and Classes necessary for a project to run.

As a reminder:
  - Objects  
  - Procedures: functions with no return, called with Send typically
  - Functions: functions with a defined return in their header line '.* Returns TYPE'

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