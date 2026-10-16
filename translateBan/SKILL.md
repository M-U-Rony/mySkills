---
name: translateBan
description: Translate a full English book, PDF, research paper, or programming/web article (local path or URL) into idiomatic, natural Bangla. Translates chapter by chapter with full progress visibility and resumes instantly, keeping code untranslated, preserving figures/tables/formulas, and merging into a single publication-quality Bengali book PDF in E:\audiobook with a Table of Contents (সূচিপত্র).
---

Produces a polished **Bangla PDF** from a full English book, paper, or article. Handles **entire books (100–800+ pages)** by detecting and organizing chapters, translating **chapter by chapter** with instant resume support, and finally merging everything into a unified book PDF.

Scripts: `<skill_dir>/scripts` (abbreviated `SCRIPTS`), where `<skill_dir>` is this skill's own directory (the folder containing this `SKILL.md`).
Translation style rules: [TRANSLATION_GUIDE.md](TRANSLATION_GUIDE.md) (the translator prompt enforces the same rules).

> [!IMPORTANT]
> **Code is never translated.** Fenced code blocks are swapped for `⟦CODE_n⟧` placeholders before the model sees the text and restored byte-for-byte afterwards; inline `code`, identifiers, commands, paths, and URLs survive unchanged. Code comments stay in English.

### Dependencies
```bash
python -m pip install pymupdf
```
PDF rendering uses headless Microsoft Edge (pre-installed on Windows; see "Known limits" for other platforms). Translation uses the `agy` (Antigravity) CLI, which must be installed and authenticated separately — it is not a Python package.

`--model` accepts any model `agy models` lists, so the translation step works with non-Gemini models too (e.g. `claude-sonnet-5-5-high`, `gpt-oss-120b-medium`) with no code changes.

### Workdir & Delivery Convention
Work lives temporarily in `<workdir>`, defaulting to `<output_base>\<doc_name>_bangla` (or `<pdf_parent>/<doc_name>_bangla`). `<output_base>` is `$TRANSLATEBAN_OUT` if set, otherwise `E:\audiobook` if that folder exists, otherwise the current directory.
Output:
- **Final Merged Book PDF**: `<output_base>\<title>_Bangla.pdf` (includes Bengali সূচিপত্র and Chapter divider banners)

Upon successful translation and compilation, the script automatically **deletes the temporary `<workdir>` folder** leaving only the clean final PDF. (Pass `--no-cleanup` if you need to retain source files for debugging).

```
<workdir>/ (Temporary during execution, auto-deleted upon finish)
  pages/page_0001.md        extracted Markdown per page (code fenced, tables, figure tags)
  figures/                  raster figures + rendered vector figures
  toc.json                  title, source type, outline, counts
  chapters.json             hierarchical chapter breakdown (Ch 1, Ch 2, etc.)
  sections.json             sub-sections plan ("translate": false = copied verbatim)
  glossary.txt              English = বাংলা (only terms present in a chunk are sent)
  source/chNN_*.md          English chapter section text
  chunks/                   validated translated chunks (resume cache)
  bangla/chNN_*.md          final Bengali sections
  translation_report.json   per-section status, failures, token usage
```

---

## 1. Extract
```bash
python SCRIPTS/extract_doc.py "<pdf_or_article_path_or_url>" ["<workdir>"]
```
- Ingests the full book PDF or article.
- Preserves code indentation, strips running headers/footers, extracts tables and vector/raster figures.

## 2. Plan Chapters & Sections
```bash
python SCRIPTS/split_sections.py "<workdir>" [--max-pages-per-section 6] [--replan]
```
- Automatically identifies top-level **Chapters** (`chapters.json`) and sub-chunks each chapter into manageable sections of max 6 pages (`sections.json`).
- **Translates chapters only**: Front matter (Cover, Contents, Preface, Foreword), Appendices (`Appendix`, `Appendices`), Indexes (`Index`, `Indices`), and References/Bibliography sections are automatically detected and **completely excluded** from planning, translation, and the final output PDF.

## 3. Curate Glossary
Skim `source/ch01_*.md`. Append 10–40 book-specific terms to `<workdir>/glossary.txt` as `English = বাংলা (English)`. Only terms appearing in a chunk are sent to the model.

## 4. Translate Chapter by Chapter (Background Execution)
```bash
python SCRIPTS/translate_sections.py "<workdir>" --model gemini-3.8-flash --workers 8
```
- Any model shown by `agy models` works here (e.g. `gemini-3.8-flash`, `claude-sonnet-5-5-high`, `gpt-oss-120b-medium`); the model only affects step 4.
- Continuous high-throughput pipeline: all 8 workers stay saturated from start to finish across chapters without barrier idling.
- Instant resume: if interrupted, re-running skips completed chunks and sections immediately.
- Once all chapters are translated, it **merges the full book** into a single cohesive PDF with a Bengali Table of Contents (সূচিপত্র), chapter banners, and Bengali page numbering, then automatically deletes the temporary folder (unless `--no-cleanup` is passed).
- Code blocks are masked with placeholders and restored 100% verbatim.
- Each chunk is validated for: code placeholders, inline code, figure-tag count, length ratio (catches truncation), and Bengali share (catches untranslated text). A failing chunk is retried with feedback, then split in half and retried.
- Safety: the prompt is sent via stdin, there is no tool auto-approval, the call runs sandboxed with timeouts, and source text is treated as untrusted data.
- Upon 100% successful validation and compilation, it automatically cleans up leftover previews and deletes the `<workdir>` folder (unless `--no-cleanup` is passed).
- Useful flags: `--workers 8`, `--effort ""` (fastest technical translation), `--effort low` (extra nuance), `--chunk-chars 12000`, `--timeout 900`, `--no-cleanup`.

Exit code `0` means all sections succeeded and the directory was cleaned up. Exit code `2` means some sections failed (the directory is kept for resuming).

## 5. Verify and deliver
1. Verify the final `<output_base>\<title>_Bangla.pdf` file exists and has healthy file size.
2. Report the PDF path, token usage, and confirmation that temporary working files were cleaned up.

## Manual re-compile (optional)
> [!NOTE]
> If you plan to inspect source files or recompile manually, run `translate_sections.py` with `--no-cleanup` so `<workdir>` is preserved.
```bash
python SCRIPTS/compile_pdf.py "<workdir>"               # complete document
python SCRIPTS/compile_pdf.py "<workdir>" --section 1   # one section
python SCRIPTS/compile_pdf.py "<workdir>" --output "D:\out.pdf"
```

## Known limits
- Equations in PDFs are extracted as plain Unicode text, not LaTeX. They are kept, but complex formulas may look degraded.
- Code embedded in web pages through GitHub gists or iframes cannot be extracted from static HTML.
- Scanned PDFs need OCR, which is not built in.
- PDF rendering looks for Microsoft Edge on Windows only. On macOS/Linux, point `find_edge_path()` in `compile_pdf.py` at a Chromium/Chrome binary (`--headless --print-to-pdf` compatible).
- Bengali output quality depends on the chosen model; the validation thresholds (Bengali share, length ratio) were tuned on Gemini and may need loosening for other models.
