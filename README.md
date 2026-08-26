# DF Skills

Utility skills to help agents operate on DataFlex source files.

## Skills

| Skill | Description |
| --- | --- |
| [df-outline](df-outline/SKILL.md) | Outlines a DataFlex file to enable more performant parsing over DataFlex files. |

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
git clone https://github.com/<your-org>/df-skills.git .agents/skills/df-skills

# User-level (available across all projects)
git clone https://github.com/<your-org>/df-skills.git ~/.agents/skills/df-skills
```

Codex CLI discovers any directory containing a `SKILL.md` file automatically. If a newly installed skill doesn't show up, restart Codex.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
