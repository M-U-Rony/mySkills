"""End-to-end orchestrator for the thesisPaper skill (Default: Mode B Ultra-Minimal 4–5 Page Study & Thesis Guide).

Usage:
  python run_thesis_pipeline.py "<pdf_path_or_arxiv_url>" [--model gemini-3.8-flash-high] [--full-translate] [--no-cleanup]

Default Ultra-Minimal Pipeline (Mode B):
  1. extract_paper.py            -> Extracts pages, figures, tables, references, and arXiv ID.
  2. scout_literature.py         -> Queries OpenAlex, arXiv & GitHub for BibTeX, code repos, and 2024-2026 citing papers.
  3. split_paper.py              -> Plans Main Paper sections & Background Appendix digest.
  4. generate_thesis_analysis.py -> Generates 4–5 page visual Bangla Study & Thesis Guide, Companion .md, & updates LITERATURE_MATRIX.md.
  5. compile_thesis_pdf.py       -> Compiles `E:\\thesis\\<Title>_Thesis_Bangla.pdf` and cleans up temporary workdir.

Optional Flag:
  --full-translate               -> Also runs translate_paper.py to include full section-by-section paper translation before the thesis guide.
"""
import argparse
import os
import pathlib
import shutil
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")

SCRIPTS_DIR = pathlib.Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPTS_DIR))

from extract_paper import extract_paper
from scout_literature import scout_paper
from split_paper import split_paper
from translate_paper import translate_paper
from generate_thesis_analysis import generate_thesis_analysis
from compile_thesis_pdf import compile_thesis_pdf
from thesis_common import (
    CORPUS_DIR_NAME,
    GLOBAL_GLOSSARY_NAME,
    LIT_JSON_NAME,
    MATRIX_MD_NAME,
    PROFILE_NAME,
    thesis_base,
)


def purge_supporting_artefacts(base, corpus_root, corpus_before, notes_path):
    """Delete everything except the final PDF (default PDF-only output mode)."""
    dropped = []
    targets = [
        pathlib.Path(notes_path) if notes_path else None,
        base / LIT_JSON_NAME,
        base / MATRIX_MD_NAME,
        base / GLOBAL_GLOSSARY_NAME,
        base / PROFILE_NAME,
    ]
    for target in targets:
        try:
            if target and target.exists():
                target.unlink() if target.is_file() else shutil.rmtree(target, ignore_errors=True)
                dropped.append(target.name)
        except OSError:
            pass
    if corpus_root.is_dir():
        for child in corpus_root.iterdir():
            if child.is_dir() and child.name not in corpus_before:
                shutil.rmtree(child, ignore_errors=True)
                dropped.append(f"{CORPUS_DIR_NAME}/{child.name}")
        try:
            if not any(corpus_root.iterdir()):
                corpus_root.rmdir()
                dropped.append(CORPUS_DIR_NAME)
        except OSError:
            pass
    return dropped


def deliver_pdf(pdf_path, deliver_dir, isolated_base, keep_extras=False):
    """Move the finished PDF out of the isolated base, then drop the isolated base."""
    if not deliver_dir:
        return pdf_path
    deliver_dir.mkdir(parents=True, exist_ok=True)
    final_pdf = deliver_dir / pathlib.Path(pdf_path).name
    shutil.move(str(pdf_path), str(final_pdf))
    if isolated_base:
        if keep_extras:
            print(f"[*] Extras kept in isolated base: {isolated_base}")
        else:
            shutil.rmtree(isolated_base, ignore_errors=True)
    return final_pdf


def main():
    ap = argparse.ArgumentParser(description="Run Minimal Thesis Paper Study & Gap Analysis pipeline.")
    ap.add_argument("doc_input", help="Path or URL (e.g. arXiv link) to research paper PDF")
    ap.add_argument("--workdir", default=None, help="Optional custom workdir")
    ap.add_argument("--model", default="gemini-3.8-flash-high", help="Model for Study & Thesis Guide (default: gemini-3.8-flash-high)")
    ap.add_argument("--analysis-model", default=None, help="Optional override model for analysis")
    ap.add_argument("--analysis-effort", default="high", help="Reasoning effort for Study & Thesis Guide (default: high)")
    ap.add_argument("--effort", default="", help="Reasoning effort for full translation if --full-translate is used")
    ap.add_argument("--chunk-chars", type=int, default=10000, help="Max source chars per translation chunk")
    ap.add_argument("--timeout", type=int, default=900, help="Per-call timeout in seconds")
    ap.add_argument("--from-markdown", default=None, help="Optional pre-written Study Guide Markdown (skips model call)")
    ap.add_argument("--workers", type=int, default=8, help="Concurrent workers if --full-translate is used")
    ap.add_argument("--max-pages-per-section", type=int, default=4, help="Max pages per section")
    ap.add_argument("--max-appendix-pages", type=int, default=0, help="Max appendix pages to translate (default: 0)")
    ap.add_argument("--full-translate", action="store_true", help="Translate full paper section-by-section (Mode A) instead of default Ultra-Minimal Mode B")
    ap.add_argument("--no-cleanup", action="store_true", help="Keep temporary workdir after PDF compilation")
    ap.add_argument("--strict-translation", action="store_true", help="Abort on hard-failed translation sections")
    ap.add_argument("--keep-extras", action="store_true", help="Also keep the companion .md notes, literature.json, LITERATURE_MATRIX.md, glossary.txt, RESEARCHER_PROFILE.md and the _corpus archive. Default output is the final PDF only.")
    ap.add_argument("--pdf-dir", default=None, help="Deliver the final PDF to this folder while keeping every intermediate file in an isolated temp base. Required for running two papers in parallel without shared-state races (default: the thesis base).")
    args = ap.parse_args()

    # Parallel-safe mode: give this run its own private base so two concurrent
    # pipelines never touch the same glossary/literature/corpus files.
    deliver_dir = pathlib.Path(args.pdf_dir).expanduser().resolve() if args.pdf_dir else None
    isolated_base = None
    if deliver_dir:
        isolated_base = pathlib.Path(tempfile.mkdtemp(prefix="thesis_iso_"))
        os.environ["THESIS_OUT"] = str(isolated_base)
        print(f"[*] Isolated base for this run: {isolated_base}")
        print(f"[*] Final PDF will be delivered to: {deliver_dir}")

    analysis_model = args.analysis_model or args.model

    print("=" * 75)
    print("STAGE 1: EXTRACTING RESEARCH PAPER PDF, FIGURES, TABLES & REFERENCES")
    print("=" * 75)
    workdir = extract_paper(args.doc_input, args.workdir)

    print("\n" + "=" * 75)
    print("STAGE 2: LIVE LITERATURE, GITHUB CODE & 2024-2026 SCOOP CHECK")
    print("=" * 75)
    scout_paper(str(workdir))

    print("\n" + "=" * 75)
    print("STAGE 3: PLANNING PAPER SECTIONS & BACKGROUND APPENDIX DIGEST")
    print("=" * 75)
    split_paper(str(workdir), max_pages=args.max_pages_per_section, max_appendix_pages=args.max_appendix_pages)

    if args.full_translate:
        print("\n" + "=" * 75)
        print("STAGE 4A: TRANSLATING FULL PAPER (--full-translate enabled)")
        print("=" * 75)
        rc = translate_paper(str(workdir), workers=args.workers, model="gemini-3.8-flash-low", chunk_chars=args.chunk_chars, effort=args.effort, timeout=args.timeout)
        if rc != 0 and args.strict_translation:
            sys.exit(rc)

    print("\n" + "=" * 75)
    print("STAGE 4: GENERATING ULTRA-MINIMAL STUDY & THESIS GUIDE")
    print("=" * 75)
    notes_path = generate_thesis_analysis(
        str(workdir), model=analysis_model, effort=args.analysis_effort,
        timeout=args.timeout, from_markdown=args.from_markdown,
        append_to_translation=args.full_translate
    )

    print("\n" + "=" * 75)
    print("STAGE 5: COMPILING MINIMAL BANGLA STUDY PDF")
    print("=" * 75)
    base = thesis_base()
    corpus_root = base / CORPUS_DIR_NAME
    corpus_before = {p.name for p in corpus_root.iterdir()} if corpus_root.is_dir() else set()
    pdf_path = compile_thesis_pdf(str(workdir), no_cleanup=args.no_cleanup)

    if not args.keep_extras:
        dropped = purge_supporting_artefacts(base, corpus_root, corpus_before, notes_path)
        if dropped:
            print(f"[*] PDF-only mode: removed {len(dropped)} supporting artefact(s) -> {', '.join(dropped)}")

    if deliver_dir:
        pdf_path = deliver_pdf(pdf_path, deliver_dir, isolated_base, args.keep_extras)

    print("\n" + "=" * 75)
    print("THESIS PAPER PIPELINE COMPLETE!")
    print(f"   • Minimal Bangla PDF : {pdf_path}")
    if args.keep_extras:
        print(f"   • Thesis Notes (.md) : {notes_path}")
        print(f"   • Literature Matrix  : {pdf_path.parent / 'LITERATURE_MATRIX.md'}")
    else:
        print("   • Extras             : none (PDF-only mode; pass --keep-extras to keep them)")
    print("=" * 75)


if __name__ == "__main__":
    main()
