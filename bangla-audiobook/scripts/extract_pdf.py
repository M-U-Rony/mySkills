"""Extract a PDF into one text file per page, plus its outline and chapter-heading candidates.

Usage: python extract_pdf.py <book.pdf> [workdir]
Default workdir: E:/audiobook/<pdf stem>_audiobook
"""
import json
import pathlib
import re
import sys

import pymupdf as fitz

sys.stdout.reconfigure(encoding="utf-8")

import os

def get_default_workdir(pdf: pathlib.Path) -> pathlib.Path:
    env_root = os.environ.get("AUDIOBOOK_ROOT")
    if env_root:
        return pathlib.Path(env_root).resolve() / f"{pdf.stem}_audiobook"
    e_drive = pathlib.Path(r"E:\audiobook")
    if e_drive.exists():
        return e_drive / f"{pdf.stem}_audiobook"
    return pdf.parent / f"{pdf.stem}_audiobook"

HEADING = re.compile(
    r"^\s*(chapter|part|book|prologue|epilogue|preface|introduction|foreword|afterword)\b"
    r"|^\s*[IVXLC]{1,7}\.?\s*$",
    re.IGNORECASE,
)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python extract_pdf.py <book.pdf> [workdir]")
    pdf = pathlib.Path(sys.argv[1]).resolve()
    work = pathlib.Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else get_default_workdir(pdf)
    pages_dir = work / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf)
    empty_pages, candidates = [], []
    for i, page in enumerate(doc, 1):
        text = page.get_text("text", sort=True)
        if len(text.strip()) < 20:
            empty_pages.append(i)
        for line in text.splitlines()[:12]:  # headings sit near the top of a page
            if HEADING.match(line):
                candidates.append({"page": i, "line": line.strip()})
        (pages_dir / f"page_{i:04d}.txt").write_text(text, encoding="utf-8")

    toc = [{"level": lvl, "title": title, "page": page} for lvl, title, page in doc.get_toc()]
    (work / "toc.json").write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"workdir: {work}")
    print(f"pages: {doc.page_count}  (near-empty: {len(empty_pages)})")
    if doc.page_count and len(empty_pages) > doc.page_count * 0.5:
        print("WARNING: most pages have no text layer -- this looks like a scanned PDF and needs OCR first.")
    print(f"outline entries: {len(toc)}  -> toc.json")
    for entry in toc:
        print(f"  {'  ' * (entry['level'] - 1)}p{entry['page']}: {entry['title']}")
    print(f"heading candidates: {len(candidates)}")
    for c in candidates[:150]:
        print(f"  p{c['page']}: {c['line']}")


if __name__ == "__main__":
    main()
