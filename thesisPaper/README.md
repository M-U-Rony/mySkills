# thesisPaper — research paper → printable Bangla study & thesis guide

Turn any research paper (local PDF or arXiv URL) into a **4–5 page, visual Bengali study
guide** that explains the method, the key equations, the headline results, the real gaps,
and the thesis ideas worth stealing — then print it, two pages per sheet, and read it on paper.

The guide is written in fluent Bangla, not machine-translated English: the paper's figures are
embedded, every core equation gets a plain-Bangla *intuition* card, and each claimed research
gap is checked against recent literature instead of being guessed.

The same instructions are available to any agent as a skill ([`SKILL.md`](SKILL.md)); this
README is the human-facing version. Style rules live in [`PAPER_GUIDE.md`](PAPER_GUIDE.md).

## What you get

Per paper, exactly one file:

```
<output_base>/<Title>_Thesis_Bangla.pdf
```

Four to five A4 pages, three sections:

| Section | Contents |
| --- | --- |
| **১. মূল গবেষণাপত্র সহজ ভাষায়** | Problem, central claim, step-by-step method, the paper's architecture/result figures, core equations with `[সহজ বাংলায় মূল কথা]` intuition cards, and a compact headline-results table. |
| **২. সীমাবদ্ধতা ও রিসার্চ গ্যাপ** | Explicit *and* hidden limitations, each tied to a verified `Section / Table / Equation` label, plus a short 2024–2026 **scoop check** of what is still open. |
| **৩. থিসিস আইডিয়া ও নভেলটি যাচাই** | One featured thesis blueprint (exact gap → concrete modification → validation plan → 3-line novelty/differentiation box) and a compact table of two alternatives. |

Nothing else is produced. Companion notes, `literature.json`, the literature matrix, the
terminology glossary, the researcher profile and the `_corpus` archive are all **deleted at the
end of the run** — they are working state, not deliverables. Pass `--keep-extras` if you want
the audit trail back.

## How it works

```
PDF / arXiv URL
   │  extract_paper.py            -> text, figures, tables, references, arXiv id
   │  scout_literature.py         -> Semantic Scholar / OpenAlex / arXiv / GitHub / BibTeX
   │  split_paper.py              -> section plan + background-appendix digest
   │  generate_thesis_analysis.py -> the Bangla guide (figures, equations, gap & idea audit)
   │  compile_thesis_pdf.py       -> <Title>_Thesis_Bangla.pdf  (+ purge intermediates)
   ▼
<output_base>/<Title>_Thesis_Bangla.pdf
```

Every stage is a standalone script, so you can stop after extraction, hand-edit, and resume:

```bash
python scripts/extract_paper.py "<pdf_or_arxiv_url>" "<workdir>"
python scripts/scout_literature.py "<workdir>"
python scripts/split_paper.py "<workdir>"
python scripts/generate_thesis_analysis.py "<workdir>" --model gemini-3.8-flash-high --effort high
python scripts/compile_thesis_pdf.py "<workdir>"
```

`scout_literature.py` and `generate_thesis_analysis.py` are the only stages that need network
and a model. Extraction, section planning and PDF compilation are pure local Python.

## Requirements

- **Python 3.10+** and PyMuPDF:

  ```bash
  python -m pip install -r requirements.txt
  ```

- **`agy` (Antigravity) CLI** — the model backend, already on `PATH`. Install and authenticate
  it separately; it is not a Python package. `agy models` shows what your account can use.
- **A Chromium-based browser** (Microsoft Edge is pre-installed on Windows) for headless PDF
  rendering. On macOS/Linux, point `find_edge_path()` in `scripts/compile_thesis_pdf.py` at a
  Chrome/Chromium binary.

Windows is the primary target; paths like `E:\thesis` are just the default output base.

## Quick start

One paper, one command, one PDF:

```bash
python scripts/run_thesis_pipeline.py "https://arxiv.org/abs/2405.12345"
python scripts/run_thesis_pipeline.py "D:\papers\my_paper.pdf" --pdf-dir "E:\thesis"
```

The pipeline prints a `STAGE n` line per stage and finishes with the path of the PDF.

### Two or more papers in one sitting

Run each paper with its own `--pdf-dir`, which isolates every intermediate file in a private
temp base so parallel runs cannot race over shared state. Then impose the guides for printing:

```bash
python scripts/merge_run_pdfs.py "<guide_1.pdf>" "<guide_2.pdf>"
```

That produces one **2-up A4 landscape** file (`<output_base>/ThesisGuides_<YYYY-MM-DD>.pdf`):
two portrait guide pages side by side per sheet, with a faint centre divider, a bookmark per
paper, and selectable text. It deletes the individual guides on success — pass
`--keep-singles` to keep them. Other options: `--pages-per-sheet 1`, `--sheet letter`,
`--out <path>`.

## Batch mode over a Notion library

When the agent runs the skill with no paper argument, it reads the work queue from a Notion
**📚 Literature Library** database instead of asking for a URL: the two earliest-published rows
with *Reading Status* = `To Read`, one subagent per paper (concurrently), each row flipped to
`Read` the moment its source PDF is downloaded. The two guides are then merged into the single
2-up print file from the previous section. A tutorial database URL is hard-coded in
[`SKILL.md`](SKILL.md) — swap it for your own before using this mode.

## Configuration

| Variable | Effect |
| --- | --- |
| `THESIS_OUT` | Output base for the PDF, the merged print file and any `--keep-extras` artefacts. Default: `E:\thesis` if drive `E:` exists, otherwise `<cwd>\thesis`. |
| `--pdf-dir` | (flag, not env) Deliver the finished PDF to this folder while all intermediates stay in an isolated temp base. Use it whenever runs may overlap. |

## Flags

`run_thesis_pipeline.py`

| Flag | Effect |
| --- | --- |
| `--model` | Model for the guide (default `gemini-3.8-flash-high`). |
| `--effort` / `--analysis-effort` | Reasoning effort for the guide (default `high`). |
| `--pdf-dir` | Isolated intermediates + PDF delivered here (parallel-safe). |
| `--keep-extras` | Keep notes, `literature.json`, matrix, glossary, profile, corpus archive. |
| `--full-translate` | Also translate the whole paper section-by-section and prepend it (Mode A). |
| `--workers`, `--chunk-chars`, `--timeout` | Translation concurrency, chunk size, per-call timeout. |
| `--from-markdown` | Compile a guide you wrote yourself instead of calling the model. |
| `--no-cleanup` | Keep the temporary workdir (and `--strict-translation` to fail on hard translation errors). |

## Scripts

| Script | Role |
| --- | --- |
| `run_thesis_pipeline.py` | End-to-end orchestrator (the usual entry point). |
| `extract_paper.py` | Resolves arXiv URLs, extracts text/figures/tables/references, renders vector figures. |
| `scout_literature.py` | Live literature scout: citing papers, code repos, BibTeX, novelty evidence. |
| `split_paper.py` | Plans sections, builds the background-appendix digest. |
| `generate_thesis_analysis.py` | Writes the Bangla guide; calls `agy`. |
| `compile_thesis_pdf.py` | HTML → print-quality PDF via headless Chromium, then archives and cleans up. |
| `merge_run_pdfs.py` | Imposes several guides into one 2-up print file. |
| `translate_paper.py` | Optional full paper translation (`--full-translate`). |
| `verify_references.py` | Standalone check of citations against the extracted paper. |
| `synthesize_corpus.py` | Cross-paper synthesis; needs papers processed with `--keep-extras`. |
| `thesis_common.py` | Shared paths, glossary, corpus archive, literature store. |

## Known limits

- The guide is ~4–5 pages by design. Dense theory papers lose detail — use `--full-translate`
  or read the paper for proofs.
- Figures are the ones the PDF lets us extract or render; figures baked into raster scans keep
  their original resolution.
- Gap/novelty claims depend on the live scout and the model. They are evidence-linked, not
  peer-reviewed — verify before you build a thesis on one.
- `synthesize_corpus.py` only sees papers processed with `--keep-extras`, since the default run
  removes `literature.json`.
- The Bangla copy assumes a Bengali-reading researcher; there is no English output mode.

## License

Personal research tooling — no license file yet. Add one before publishing or redistributing.
