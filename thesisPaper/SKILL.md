---
name: thesisPaper
description: Turn research papers into ultra-minimal, visual Bangla Study & Thesis Guide PDFs (~4–5 pages) in E:\thesis. The PDF is the ONLY output — no companion notes, literature matrix, glossary or corpus archive. Run with no arguments to pull the next two unread papers from the Notion "📚 Literature Library" (Reading Status = To Read), download them, process each in sequence, flip each row to Read as soon as its PDF lands, and merge the run's guides into one 2-pages-per-sheet A4 landscape PDF ready to print. Explains the core method, figures, equations (with plain-Bangla intuition boxes), results, verified research gaps, and top thesis ideas without overwhelming text dumps.
---

# Minimal Thesis Paper Study & Gap Analyzer (`thesisPaper`)

Transforms any research paper (local PDF path or arXiv URL) into a **4–5 page Visual Bangla Study & Thesis Guide PDF** stored in `E:\thesis\`.

**The PDF is the only output.** No companion Markdown, no `literature.json`, no `LITERATURE_MATRIX.md`, no `glossary.txt`, no `RESEARCHER_PROFILE.md`, no `_corpus` archive — those are all deleted automatically at the end of every run. Pass `--keep-extras` only when you explicitly want the audit trail back.

- **Scripts Directory (`SCRIPTS`)**: `C:\Users\Rony\.agents\skills\thesisPaper\scripts`
- **Style & Minimal Protocol Guide**: [PAPER_GUIDE.md](PAPER_GUIDE.md)
- **Prerequisites**: Python 3.10+, `pip install pymupdf`, `agy` CLI on PATH, Chromium browser (Edge/Chrome) for PDF render. Output base is `$THESIS_OUT`, else `E:\thesis`, else `cwd/thesis`.

---

## Deliverable — one printable PDF

Per paper: **`E:\thesis\<Title>_Thesis_Bangla.pdf`** (~4–5 pages). A two-paper run then merges those into **one 2-up print file** — two pages side by side on A4 landscape — so there is nothing to staple or configure by hand at the printer. See "Step 4 — Merge the run's PDFs".

Each guide contains:

1. **Section 1 — মূল গবেষণাপত্র সহজ ভাষায় (Core Paper Explained)**:
   - Core problem, central claim, and step-by-step architecture/method explanation in fluent, natural Bangla (no repetitive `(English)` bracket clutter).
   - Embeds the paper's **key architecture & result figures** extracted from the PDF.
   - Core mathematical equations (`$$...$$`) paired with **`[সহজ বাংলায় মূল কথা (Intuition)]`** emerald callout cards.
   - Compact summary of the headline experimental results (Main Table) and key takeaways.
2. **Section 2 — সীমাবদ্ধতা ও রিসার্চ গ্যাপ (Flaw & Gap Matrix)**:
   - Compact table of explicit and hidden limitations tied to verified `Section / Table / Equation` labels + concise **2024–2026 Scoop Check** of what remains open.
3. **Section 3 — থিসিস আইডিয়া ও নভেলটি যাচাই (Top Verified Thesis Blueprint)**:
   - **#1 Featured Thesis Blueprint** (Title, Exact Gap, Concrete Methodological Modification, Validation Plan, and a 3-line **Novelty & Differentiation Box** verified against 2024–2026 Semantic Scholar/arXiv papers).
   - **Compact Table of 2 Alternative Thesis Ideas** for quick comparison without decision fatigue.

### Suppressed by default (do not re-create these)

| Artefact | Why it is dropped |
|---|---|
| `<Title>_Thesis_Notes.md` | Companion dossier; superseded by the PDF for reading |
| `literature.json` + `LITERATURE_MATRIX.md` | Cross-paper store; only useful for corpus-wide synthesis |
| `glossary.txt` | Global Bangla terminology cache |
| `RESEARCHER_PROFILE.md` | Researcher personalization template |
| `_corpus\<Title>\` | Audit trail of source text, figures, scout data |
| Temporary workdir | Always cleaned up unless `--no-cleanup` |

If the user ever asks for "the notes", "the matrix", "the sources", or "why did it cite Table 5", re-run that paper with `--keep-extras` (or read the existing archive) — do not silently change the default. Never delete the user's existing PDFs.

**Note:** `synthesize_corpus.py` needs `literature.json`, so it only works on papers processed with `--keep-extras`.

---

## Default invocation — Notion Literature Library batch mode

**If the user invokes this skill with no paper argument** (e.g. `/thesisPaper`, "do my next two papers", "translate the next unread papers"), do **not** ask for a URL. Pull the work queue from Notion automatically.

### Source of truth

- Library database: **📚 Literature Library** — `https://app.notion.com/p/5e17bc44ddda4de499ffd484323d958e`
- Data source URL (use as the SQLite table name): `collection://77207033-7d0f-4d1e-817f-fff97ed726af`
- Status property: `Reading Status` — options `To Read`, `Reading`, `Read`, `Cited in Thesis`
- Paper URL property: `Link` (usually an arXiv abs URL); title property: `Paper`

### Step 1 — Query the next two unread papers

Use the Notion MCP tool `notion-query-data-sources` (SQL mode). Note the arguments go inside a **`data` wrapper**:

```jsonc
{
  "data": {
    "mode": "sql",
    "data_source_urls": ["collection://77207033-7d0f-4d1e-817f-fff97ed726af"],
    "query": "SELECT \"Paper\" AS paper, \"Link\" AS link, \"Reading Status\" AS status, \"date:Published:start\" AS pub FROM \"collection://77207033-7d0f-4d1e-817f-fff97ed726af\" WHERE \"Reading Status\" = ? ORDER BY \"date:Published:start\" ASC LIMIT 2",
    "params": ["To Read"]
  }
}
```

"Next two unread" = **earliest-published first** (`date:Published:start ASC`), matching the library's default view order. If only one row exists, process one. Never invent papers or fall back to already-read rows.

Skip any paper that already has `E:\thesis\<Title>_Thesis_Bangla.pdf` — re-running must not duplicate work.

### Step 2 — Fan out two subagents, one paper each

Never run the two papers one after the other — each takes minutes and they are independent. Spawn **two subagents in the same message** so they run concurrently, one per paper. Use the `general` subagent type (it can run shell commands and call Notion); two independent calls in one block start together, `background: true` works too.

The parent process does only four things: query Notion (Step 1), launch the two subagents, merge their PDFs (Step 4), report (Step 5). It never runs the paper pipeline itself.

Give each subagent this prompt, filled in for its row:

```
You are processing exactly ONE paper for the thesisPaper skill.
Paper: <title>
Notion page id: <page_id>
Source link: <Link>

1. Run this command and watch its output:
   python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\run_thesis_pipeline.py" "<Link>" --pdf-dir "E:\thesis"
2. The moment its output contains "[+] Saved source PDF", set THAT row's Reading Status to Read
   with notion-update-page (command: update_properties, properties: {"Reading Status": "Read"}).
   Do it immediately at download, not when the guide finishes.
3. Do NOT merge PDFs. Do NOT touch the other paper's Notion row. Do NOT delete anything in E:\thesis.
4. Reply with only the final PDF path and whether the status flip succeeded.
```

`--pdf-dir "E:\thesis"` is what makes true parallelism safe: the run builds its glossary, literature store, corpus archive and workdir inside a **private temp base**, purges them there, and moves only the finished PDF into `E:\thesis`. Without it the two runs would race over shared files.

Keep each run's log outside the output folder: `$env:TEMP\thesis_<arxivid>.log`. `Link` is an arXiv abs URL and is passed through unchanged — the pipeline resolves it to the PDF itself.

If only one unread paper exists, spawn one subagent and skip Step 4.

### Step 3 — Verify both status flips

The subagents flip their own rows at download time (Step 2, item 2). When both return, confirm both rows now say `Read`; if one subagent finished without flipping, flip it now. This is what advances the queue — without it every run returns the same papers. Status vocabulary is fixed: `To Read` → `Read`. Never invent a new option and never use `Reading` as an intermediate state.

**Only exception:** if a subagent's pipeline crashed *after* the download and produced no `_Thesis_Bangla.pdf`, revert that row to `To Read` and report the failure, so the paper comes back next run instead of being silently lost.

### Step 4 — Merge the run's PDFs into one print file (2 pages per sheet)

The user prints **two pages per sheet** and reads the printed copy, so a two-paper run must end as **one already-imposed PDF** — never hand them two files and never ask them to set "2 pages per sheet" in the print dialog. Once **both subagents from Step 2 have returned**, merge the two guide PDFs (and only those produced by this run):

```bash
python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\merge_run_pdfs.py" "<pdf_1>" "<pdf_2>"
```

- Default layout: **2-up on A4 landscape** — two portrait guide pages side by side per sheet, with a faint divider line down the middle. A 10-page run becomes 5 printable sheets.
- Default output: `E:\thesis\ThesisGuides_<YYYY-MM-DD>.pdf` (auto-suffixed `_2`, `_3` if that name is taken, so a second run the same day never overwrites the first).
- Each paper becomes a level-1 bookmark, remapped to the sheet it lands on, so the printed copy is navigable.
- Pages are placed with `show_pdf_page`, so text stays selectable/extractable and figures stay vector — the file is not rasterized.
- On success it **deletes the two single-paper PDFs**, leaving exactly one printable file. Page count is verified against the sources first; a mismatch aborts without deleting anything.
- Escape hatches: `--pages-per-sheet 1` for a normal one-page-per-sheet file, `--sheet letter` if the paper tray is Letter, `--keep-singles` to keep the individual PDFs.

Skip the merge if the run produced only one paper (e.g. only one unread row remained) — print a one-line note instead of forcing a merge. If the merge fails, keep both singles and report both paths.

### Step 5 — Report

One compact table: paper, arXiv id, status, and the **final printable path** (the merged file, or the single PDF when no merge happened). Keep it short; no recap of the paper contents.

### Fallbacks

- Notion MCP unreachable or no OAuth access → say so in one line and ask for a PDF path or arXiv URL instead of silently doing nothing.
- If the user names a specific paper, a status other than `To Read`, or a count other than two ("my next five", "the ones I'm reading"), honour that instead: only the *default* is "next two To Read by published date". For three or more, still fan out one subagent per paper.
- One subagent fails or times out → do not kill the other, do not fall back to sequential re-runs. Merge what landed, report the missing paper, and leave its row `To Read`.
- Both fail → report the failing stage of each (the last `STAGE n` line) and change nothing in Notion beyond any row already flipped at download.

---

## Fast One-Command Execution (Default Ultra-Minimal Mode B, PDF-only)

```bash
python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\run_thesis_pipeline.py" "<pdf_path_or_arxiv_url>"
```

Produces exactly one file: `E:\thesis\<Title>_Thesis_Bangla.pdf`. Everything else the pipeline generates internally (notes, literature store, glossary cache, corpus archive, workdir) is deleted before the command exits.

*(Optional: `--full-translate` for the section-by-section paper translation; `--keep-extras` to retain the notes/matrix/corpus audit trail; `--pdf-dir "E:\thesis"` to isolate all intermediates in a temp base — use this whenever several papers run at once.)*

Single-paper runs stop here — one PDF, no merge. When a batch of two or more papers is processed, follow with `merge_run_pdfs.py` (Step 4 above) so the user gets one file already laid out 2 pages per sheet.

---

## Step-by-Step Pipeline & Companion Utilities

### 1. Extract Paper, Figures, Tables & References
```bash
python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\extract_paper.py" "<pdf_path_or_arxiv_url>" ["<workdir>"]
```

### 2. Scout Live Literature (Semantic Scholar + OpenAlex + arXiv + GitHub + BibTeX)
```bash
python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\scout_literature.py" "<workdir>"
```

### 3. Plan Main Paper Sections & Background Appendix Digest
```bash
python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\split_paper.py" "<workdir>"
```

### 4. Generate Ultra-Minimal Study Guide & Thesis Blueprint
```bash
python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\generate_thesis_analysis.py" "<workdir>" --model gemini-3.8-flash-high --effort high
```

### 5. Compile Minimal Bangla PDF, Archive Corpus & Cleanup
```bash
python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\compile_thesis_pdf.py" "<workdir>"
```

### Companion Utilities
- **Merge a run's guide PDFs into one 2-up print file** (auto-names `E:\thesis\ThesisGuides_<date>.pdf`, imposes 2 pages per A4 landscape sheet, adds a bookmark per paper, deletes the singles on success):
  ```bash
  python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\merge_run_pdfs.py" "<pdf1>" "<pdf2>" [--pages-per-sheet 1] [--sheet letter] [--keep-singles] [--out <path>]
  ```
- **Cross-Paper Corpus Synthesizer** (needs papers processed with `--keep-extras`):
  ```bash
  python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\synthesize_corpus.py"
  ```
- **Standalone Reference Verifier**:
  ```bash
  python "C:\Users\Rony\.agents\skills\thesisPaper\scripts\verify_references.py" "<workdir>" "<analysis.md>" [--in-place]
  ```
