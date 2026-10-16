# translateBan — English → বাংলা book translator

Turn a full English **book, research paper, or programming/web article** (local path or URL)
into a polished Bengali PDF. It detects and organizes chapters, translates **chapter by
chapter** with instant resume support, keeps all code untouched, preserves figures, tables,
and formulas, and merges everything into a single publication-quality Bengali book PDF with a
Bengali সূচিপত্র (Table of Contents) and chapter divider banners.

The same instructions are available to any agent as a skill
([`SKILL.md`](SKILL.md)); this README is the human-facing version.

## How it works

```
PDF / HTML article
   │  extract_doc.py        -> pages/*.md, figures/, toc.json
   │  split_sections.py     -> chapters.json, sections.json, source/*.md, glossary.txt
   │  (edit glossary.txt)
   │  translate_sections.py -> bangla/*.md  (chapter-by-chapter, parallel, resumable)
   ▼
<output_base>/<title>_Bangla.pdf
```

**Code is never translated.** Fenced code blocks are swapped for `⟦CODE_n⟧` placeholders
before the model sees the text and restored byte-for-byte afterwards; inline `code`,
identifiers, commands, paths, and URLs survive unchanged. Code comments stay in English.

Every translated chunk is validated (code placeholders, inline code, figure-tag count, length
ratio, Bengali share). A failing chunk is retried with feedback, then split in half and
retried. A section file is written only if all of its chunks pass.

## Requirements

- **Python 3.9+** and **PyMuPDF**:

  ```bash
  python -m pip install -r requirements.txt
  ```

- **`agy` (Antigravity) CLI** — the translation backend. Install and authenticate it
  separately; it is not a Python package. Run `agy models` to see the models your account can
  use.
- **Microsoft Edge** (pre-installed on Windows) for headless PDF rendering. On macOS/Linux,
  point `find_edge_path()` in `scripts/compile_pdf.py` at a Chromium/Chrome binary.

## Usage

```bash
# 1. Extract text, code, tables, outline, and figures
python scripts/extract_doc.py "<pdf_or_article_path_or_url>" ["<workdir>"]

# 2. Plan chapters and sections (auto-excludes front matter, appendices, index, references)
python scripts/split_sections.py "<workdir>" [--max-pages-per-section 6] [--replan]

# 3. (optional) Add 10-40 book-specific terms to <workdir>/glossary.txt as "English = বাংলা (English)"

# 4. Translate every chapter, then merge + compile the final PDF (resumable)
python scripts/translate_sections.py "<workdir>" --model gemini-3.8-flash --workers 8
```

Step 4 exits `0` when every section succeeded (and the temporary workdir is removed) or `2`
when some sections failed (the workdir is kept so you can just re-run to resume).

## Models

`--model` is passed straight to the `agy` CLI, so the translation step is **not** tied to
Gemini. Anything `agy models` lists works, e.g.:

```bash
python scripts/translate_sections.py "<workdir>" --model claude-sonnet-5-5-high
python scripts/translate_sections.py "<workdir>" --model gpt-oss-120b-medium
```

Only step 4 is model-dependent — extraction, planning, and PDF compilation are pure local
Python. The validation thresholds (Bengali share, length ratio) were tuned on Gemini and may
need loosening for other models.

## Configuration

| Variable | Effect |
| --- | --- |
| `TRANSLATEBAN_OUT` | Output base directory for workdirs and the final PDF. Default: `E:\audiobook` if it exists, otherwise the current directory (or the workdir's parent for the PDF). |

## Workdir & output layout

```
<workdir>/                       (temporary; auto-deleted on success unless --no-cleanup)
  pages/page_0001.md             extracted Markdown per page
  figures/                       raster + rendered vector figures
  toc.json                       title, source type, outline, counts
  chapters.json                  hierarchical chapter breakdown
  sections.json                  sub-section plan ("translate": false = copied verbatim)
  glossary.txt                   English = বাংলা (only terms present in a chunk are sent)
  source/chNN_*.md               English section text
  chunks/                        validated translated chunks (resume cache)
  bangla/chNN_*.md               final Bengali sections
  translation_report.json        per-section status, failures, token usage
```

Final output: `<output_base>/<title>_Bangla.pdf`.

## Manual re-compile

Run step 4 with `--no-cleanup` if you want to inspect or recompile:

```bash
python scripts/compile_pdf.py "<workdir>"               # complete document
python scripts/compile_pdf.py "<workdir>" --section 1   # single-section preview
python scripts/compile_pdf.py "<workdir>" --output "D:\out.pdf"
```

## Useful flags (step 4)

`--workers 8` · `--chunk-chars 12000` · `--timeout 900` · `--effort low` · `--no-cleanup`

## Known limits

- Equations in PDFs are extracted as plain Unicode text, not LaTeX; they are kept, but complex
  formulas may look degraded.
- Code embedded in web pages via GitHub gists or iframes cannot be extracted from static HTML.
- Scanned PDFs need OCR, which is not built in.
- PDF rendering looks for Microsoft Edge on Windows only (see Requirements).

## Translation style

See [`TRANSLATION_GUIDE.md`](TRANSLATION_GUIDE.md). The translator prompt in
`scripts/translate_sections.py` enforces the same rules (idiomatic Bengali, glossary
consistency, transliteration-with-English-in-parentheses for technical terms, code/math
preserved).
