"""Shared helpers for the thesisPaper skill (v2.0 Minimal Mode B).

- thesis_base(): resolves the output root ($THESIS_OUT > E:/thesis > ./thesis).
- Researcher profile: E:/thesis/RESEARCHER_PROFILE.md (template auto-created, injected into analysis).
- Global glossary: E:/thesis/glossary.txt (seeded into every workdir, merged back after each run).
- Corpus archive: E:/thesis/_corpus/<slug>/ keeps source text, digests, scout data and study guide
  so the workdir can be deleted without losing material for later cross-paper synthesis.
- Literature store: E:/thesis/literature.json is the source of truth; LITERATURE_MATRIX.md is rendered from it.
"""
import datetime
import json
import os
import pathlib
import re
import shutil

PROFILE_NAME = "RESEARCHER_PROFILE.md"
GLOBAL_GLOSSARY_NAME = "glossary.txt"
CORPUS_DIR_NAME = "_corpus"
LIT_JSON_NAME = "literature.json"
MATRIX_MD_NAME = "LITERATURE_MATRIX.md"

PROFILE_TEMPLATE = """# Researcher Profile (thesisPaper)

> Fill this in once and keep "Current Thesis Direction" updated. Every paper analysis is tailored to it.
> Lines still containing `<fill>` are ignored.

- **Degree level:** <fill: BSc / MSc / PhD>
- **University / Department:** <fill>
- **Thesis deadline:** <fill: YYYY-MM>
- **Research interests:** <fill: e.g. Bangla NLP, LLM reasoning, multimodal learning>
- **Areas to avoid:** <fill: e.g. pure hardware design, RL from scratch>
- **Supervisor's research area:** <fill>
- **Skills:** <fill: e.g. Python, PyTorch, HuggingFace Transformers, LaTeX>
- **Target venues:** <fill: e.g. ACL, EMNLP, IEEE, Conference/Workshop>
- **Language / data advantage:** <fill: e.g. native Bangla speaker, access to domain dataset>

## Current Thesis Direction
<fill: leave empty while exploring; once chosen, write the research question here so every new paper is analyzed against it>
"""


def thesis_base(*_args) -> pathlib.Path:
    env = os.environ.get("THESIS_OUT")
    if env:
        p = pathlib.Path(env).expanduser()
    elif pathlib.Path("E:/").exists():
        p = pathlib.Path("E:/thesis")
    else:
        p = pathlib.Path.cwd() / "thesis"
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    return name[:110] or "paper"


# ----------------------------------------------------------------- profile
def load_profile(base: pathlib.Path = None) -> str:
    """Return the filled-in part of the researcher profile ('' if unfilled). Creates template if missing."""
    base = base or thesis_base()
    f = base / PROFILE_NAME
    if not f.exists():
        f.write_text(PROFILE_TEMPLATE, encoding="utf-8")
        print(f"[!] Created researcher profile template: {f}  -> fill it in to get tailored thesis blueprints.")
        return ""
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines()
             if ln.strip() and "<fill" not in ln and not ln.lstrip().startswith(">")]
    meaningful = [ln for ln in lines if not ln.lstrip().startswith("#")]
    if not meaningful:
        print(f"[!] Researcher profile is still a template: {f}  (blueprints will be general)")
        return ""
    return "\n".join(lines)


# ---------------------------------------------------------------- glossary
def _gloss_key(line: str) -> str:
    return line.split("=", 1)[0].strip().lower() if "=" in line else ""


def seed_glossary(workdir: pathlib.Path, default_text: str):
    """Copy the global glossary into the workdir (creating the global one from defaults if needed)."""
    g = thesis_base() / GLOBAL_GLOSSARY_NAME
    if not g.exists():
        g.write_text(default_text, encoding="utf-8")
        print(f"[+] Created global glossary: {g}")
    wf = workdir / "glossary.txt"
    if not wf.exists():
        shutil.copyfile(g, wf)
        print(f"[+] Seeded workdir glossary from global glossary ({g})")


def merge_glossary_back(workdir: pathlib.Path) -> int:
    """Append terms added to the workdir glossary into the global one. Returns number of new terms."""
    wf = workdir / "glossary.txt"
    g = thesis_base() / GLOBAL_GLOSSARY_NAME
    if not wf.exists():
        return 0
    existing = g.read_text(encoding="utf-8") if g.exists() else ""
    keys = {_gloss_key(ln) for ln in existing.splitlines() if "=" in ln}
    new = [ln.strip() for ln in wf.read_text(encoding="utf-8").splitlines()
           if "=" in ln and not ln.strip().startswith("#") and _gloss_key(ln) not in keys]
    if new:
        with g.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if existing and not existing.endswith("\n") else "") + "\n".join(new) + "\n")
        print(f"[+] Merged {len(new)} new glossary term(s) into {g}")
    return len(new)


# ------------------------------------------------------------------ corpus
def archive_paper(workdir: pathlib.Path, title: str) -> pathlib.Path:
    """Copy reusable artefacts of a paper run into E:/thesis/_corpus/<slug>/."""
    dest = thesis_base() / CORPUS_DIR_NAME / safe_filename(title)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("toc.json", "scout_report.json", "scout_summary.md", "references.md",
                 "appendix_digest.md", "novelty_evidence.json", "reference_check.json", "analysis_raw.md"):
        src = workdir / name
        if src.exists():
            shutil.copy2(src, dest / name)
    for sub in ("source", "digests", "figures"):
        sd = workdir / sub
        if sd.is_dir():
            shutil.copytree(sd, dest / sub, dirs_exist_ok=True)
    lab = workdir / "bangla" / "ch99_01_thesis_opportunity_lab.md"
    if lab.exists():
        shutil.copy2(lab, dest / "thesis_lab.md")
    merge_glossary_back(workdir)
    print(f"[+] Archived paper corpus: {dest}")
    return dest


# ------------------------------------------------------- literature store
MATRIX_HEADER = (
    "# Master Thesis Literature & Research Gap Matrix\n\n"
    "> Auto-maintained by the `thesisPaper` skill from `literature.json` (edit the JSON, not this table).\n\n"
    "| Date | Paper Title (Year / Venue) | Core Method & Architecture | Datasets & Metrics "
    "| Critical Limitation / Gap | #1 Thesis Idea | Novelty Audit | Deliverables |\n"
    "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
)


def _cell(v) -> str:
    return re.sub(r"\s+", " ", str(v or "—")).replace("|", "/").strip()


def _migrate_md(md_file: pathlib.Path) -> list[dict]:
    """One-time migration of a v1 LITERATURE_MATRIX.md table into entries."""
    entries = []
    for ln in md_file.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("| 20"):
            continue
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cols) < 7:
            continue
        m = re.match(r"\*\*(.+?)\*\*\s*\((.*?)\)", cols[1])
        title = m.group(1) if m else cols[1]
        yv = (m.group(2) if m else "").split(",", 1)
        entries.append({
            "date": cols[0], "title": title,
            "year": yv[0].strip() if yv else "", "venue": yv[1].strip() if len(yv) > 1 else "",
            "core_method": cols[2], "datasets_metrics": cols[3], "key_limitation": cols[4],
            "top_thesis_idea": cols[5], "novelty_verdict": "", "blueprints": [],
            "pdf": f"{safe_filename(title)}_Thesis_Bangla.pdf",
            "notes": f"{safe_filename(title)}_Thesis_Notes.md",
        })
    return entries


def load_literature(base: pathlib.Path = None) -> list[dict]:
    base = base or thesis_base()
    jf = base / LIT_JSON_NAME
    if jf.exists():
        try:
            return json.loads(jf.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[!] {jf} is not valid JSON; starting a fresh list (old file kept as .bak)")
            shutil.copy2(jf, jf.with_suffix(".json.bak"))
            return []
    md = base / MATRIX_MD_NAME
    return _migrate_md(md) if md.exists() else []


def upsert_literature(entry: dict, base: pathlib.Path = None) -> pathlib.Path:
    base = base or thesis_base()
    entries = [e for e in load_literature(base) if e.get("title", "").strip().lower() != entry["title"].strip().lower()]
    entry.setdefault("date", datetime.date.today().isoformat())
    entries.append(entry)
    (base / LIT_JSON_NAME).write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    rows = []
    for e in entries:
        rows.append(
            f"| {_cell(e.get('date'))} | **{_cell(e.get('title'))}** ({_cell(e.get('year'))}, {_cell(e.get('venue'))}) "
            f"| {_cell(e.get('core_method'))} | {_cell(e.get('datasets_metrics'))} | {_cell(e.get('key_limitation'))} "
            f"| {_cell(e.get('top_thesis_idea'))} | {_cell(e.get('novelty_verdict'))} "
            f"| [Bangla PDF]({e.get('pdf', '')}) · [Thesis Notes]({e.get('notes', '')}) |"
        )
    md = base / MATRIX_MD_NAME
    md.write_text(MATRIX_HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"[+] Updated {base / LIT_JSON_NAME} and {md} ({len(entries)} paper(s))")
    return md


def compact_literature_view(exclude_title: str = "", budget: int = 14000) -> str:
    """Compact per-paper lines for prompts; shrinks field widths so 40+ papers still fit."""
    entries = [e for e in load_literature() if e.get("title", "").strip().lower() != exclude_title.strip().lower()]
    if not entries:
        return "No previous papers in the literature store yet."
    for width in (260, 180, 120, 80, 50):
        lines = []
        for i, e in enumerate(entries, 1):
            lines.append(
                f"[P{i}] {e.get('title', '')[:110]} ({e.get('year', '')}) | method: {str(e.get('core_method', ''))[:width]} "
                f"| gap: {str(e.get('key_limitation', ''))[:width]} | idea: {str(e.get('top_thesis_idea', ''))[:width]}"
            )
        text = "\n".join(lines)
        if len(text) <= budget:
            return text
    return text[:budget]
