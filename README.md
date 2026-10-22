# mySkills

Agent skills I use daily, written for [OpenCode](https://opencode.ai) but readable as plain
instructions by any tool that can run Python.

Each skill is a self-contained folder: `SKILL.md` (the agent-facing instructions and
frontmatter), a `README.md` (the human-facing explanation), and the `scripts/` that do the work.

| Skill | What it does |
| --- | --- |
| [`thesisPaper`](thesisPaper/) | Research paper (PDF or arXiv) → 4–5 page visual **Bangla study & thesis guide**: method, figures, equations with intuitive explanations, verified research gaps, and a ranked thesis blueprint. Papers can be pulled in batch from a Notion reading library and merged into one 2-pages-per-sheet print file. |
| [`translateBan`](translateBan/) | Full English book / paper / article → publication-quality **Bengali PDF**, translated chapter by chapter with resume support; code stays untouched, figures, tables and formulas are preserved, and the book gets a Bengali সূচিপত্র. |
| [`bangla-audiobook`](bangla-audiobook/) | PDF → narrated **Bangla audiobook MP3**, with chapter planning, a phonetic glossary and concurrent TTS narration. |

## Common requirements

All three skills are Windows-first (paths like `E:\thesis` and `E:\audiobook` are defaults, not
hard requirements) and share the same shape:

- **Python 3.10+** with the skill's `requirements.txt` installed.
- **`agy` (Antigravity) CLI** on `PATH` for model calls — install and authenticate separately.
- **Microsoft Edge / Chrome** for headless PDF rendering where a PDF is produced.

```bash
cd thesisPaper && python -m pip install -r requirements.txt
```

## Usage

OpenCode loads a skill when your request matches its description, or you can invoke one
explicitly:

```
/thesisPaper
/thesisPaper "https://arxiv.org/abs/2405.12345"
```

Outside OpenCode, read the skill's `SKILL.md` and run the scripts directly — every stage is a
normal CLI command, and each README documents the flags.

## Notes

- Skills not listed above are private experiments and are excluded via [`.gitignore`](.gitignore).
- Generated outputs (PDFs, MP3s, workdirs, `__pycache__`) are never committed.
