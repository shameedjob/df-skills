# DF Skills

Utility skills to help agents operate on DataFlex source files.

## Skills

| Skill | Description |
| --- | --- |
| [df-outline](df-outline/SKILL.md) | Outlines a DataFlex file to enable more performant parsing over DataFlex files. |
| [df-designer-preview](df-designer-preview/SKILL.md) | Renders a DataFlex web view in the WebApp designer for design review. Uses df-outline's script, so install both. |

## Installation

Copy or clone the skill folder(s) you want into your agent's skills directory.

### Claude Code

```bash
# Project-level (available in this repo only)
git clone https://github.com/shameedjob/df-skills.git .claude/skills/df-skills

# User-level (available across all projects)
git clone https://github.com/shameedjob/df-skills.git ~/.claude/skills/df-skills
```

Claude Code will pick up any directory containing a `SKILL.md` file automatically.

### Codex CLI

```bash
# Project-level (available in this repo only)
git clone https://github.com/shameedjob/df-skills.git .agents/skills/df-skills

# User-level (available across all projects)
git clone https://github.com/shameedjob/df-skills.git ~/.agents/skills/df-skills
```

Codex CLI discovers any directory containing a `SKILL.md` file automatically. If a newly installed skill doesn't show up, restart Codex.

## Benchmark

Measured with `tiktoken` (cl100k_base) on `test_files/test_page.txt` (1,503 lines, 12,966 tokens), for the request:

> Add a condition to the onconstrains of oinvcdtl: if sScope='Admin' do not append an additional filter.

| Approach | Components | Tokens | Reduction |
| --- | --- | --- | --- |
| Without df-outline | request + full file read | 12,994 | — |
| With df-outline, tree output (default) | request + SKILL.md + tree outline + targeted object read | 3,271 | **74.8%** |
| With df-outline, `--json` fallback | request + SKILL.md + JSON outline + targeted object read | 8,871 | 31.7% |

The `--json` outline dumps every nested block across the whole file with full key/value structure, which is expensive for large files — it alone costs 7,831 tokens here, more than half the source file. The default tree output carries the same information (block type, name, line range, and nesting depth) in a fraction of the tokens, which is why it's the default; reach for `--json` only when a task needs machine-structured data.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
