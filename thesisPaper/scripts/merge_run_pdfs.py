"""Merge the Bangla study-guide PDFs produced by one thesisPaper run into a single print file.

Defaults match the user's print workflow: A4 landscape, 2 pages per sheet, so a 10-page
run prints on 5 sheets with nothing to fold or staple by hand.

Usage:
  python merge_run_pdfs.py <pdf1> <pdf2> [<pdf3> ...] [--pages-per-sheet 2] [--sheet a4]
                           [--out <path>] [--keep-singles]

Defaults:
  --out            E:\\thesis\\ThesisGuides_<YYYY-MM-DD>.pdf   (auto _2, _3 ... on collision)
  --pages-per-sheet 2   (A4 landscape, two portrait guide pages side by side)
  singles          deleted after a verified merge; use --keep-singles to keep them

Each input PDF becomes one level-1 bookmark, remapped to the sheet it lands on, so the
printed copy keeps a navigable outline.
"""
import argparse
import datetime
import math
import pathlib
import sys

import pymupdf

SUFFIX = "_Thesis_Bangla"
A4_LANDSCAPE = (841.89, 595.28)
LETTER_LANDSCAPE = (792.0, 612.0)
SHEETS = {"a4": A4_LANDSCAPE, "letter": LETTER_LANDSCAPE}


def paper_title(pdf: pathlib.Path) -> str:
    stem = pdf.stem
    return stem[: -len(SUFFIX)] if stem.endswith(SUFFIX) else stem


def unique_out_path(base: pathlib.Path, stem: str) -> pathlib.Path:
    candidate = base / f"{stem}.pdf"
    n = 2
    while candidate.exists():
        candidate = base / f"{stem}_{n}.pdf"
        n += 1
    return candidate


def impose(doc, pages_per_sheet: int, sheet: str, margin: float = 18.0, gap: float = 14.0):
    """Place `pages_per_sheet` source pages on each landscape sheet, preserving vector quality."""
    if pages_per_sheet == 1:
        return doc, doc.page_count

    sheet_w, sheet_h = SHEETS.get(sheet.lower(), A4_LANDSCAPE)
    cols = pages_per_sheet
    cell_w = (sheet_w - 2 * margin - (cols - 1) * gap) / cols
    cell_h = sheet_h - 2 * margin

    out = pymupdf.open()
    total = doc.page_count
    sheets = math.ceil(total / cols)

    for s in range(sheets):
        page = out.new_page(width=sheet_w, height=sheet_h)
        for c in range(cols):
            idx = s * cols + c
            if idx >= total:
                break
            x0 = margin + c * (cell_w + gap)
            rect = pymupdf.Rect(x0, margin, x0 + cell_w, margin + cell_h)
            page.show_pdf_page(rect, doc, idx)
        if cols > 1:
            x = margin + cell_w + gap / 2
            page.draw_line(
                pymupdf.Point(x, margin), pymupdf.Point(x, sheet_h - margin),
                color=(0.82, 0.82, 0.82), width=0.5,
            )

    out.set_toc([[lvl, title, (pg - 1) // cols + 1] for lvl, title, pg in doc.get_toc()])
    return out, sheets


def merge(pdfs, out: pathlib.Path, keep_singles: bool,
          pages_per_sheet: int = 2, sheet: str = "a4") -> pathlib.Path:
    pdfs = [p.resolve() for p in pdfs]
    missing = [str(p) for p in pdfs if not p.is_file()]
    if missing:
        raise SystemExit(f"[!] Missing input PDF(s): {', '.join(missing)}")

    doc = pymupdf.open()
    expected_pages = 0
    for pdf in pdfs:
        src = pymupdf.open(pdf)
        start_page = doc.page_count + 1
        doc.insert_pdf(src)
        expected_pages += src.page_count
        doc.set_toc(doc.get_toc() + [[1, paper_title(pdf), start_page]])
        print(f"  + {paper_title(pdf)}  ({src.page_count} pages)")
        src.close()

    if doc.page_count != expected_pages:
        doc.close()
        raise SystemExit(f"[!] Page-count mismatch: expected {expected_pages}, got {doc.page_count}")

    result, sheets = impose(doc, pages_per_sheet, sheet)
    if result is not doc:
        doc.close()
        doc = result

    metadata = doc.metadata or {}
    metadata.update({"title": out.stem, "producer": "thesisPaper", "creator": "thesisPaper"})
    doc.set_metadata(metadata)
    doc.save(out, garbage=4, deflate=True)
    sheet_count = doc.page_count
    doc.close()

    size_kb = round(out.stat().st_size / 1024)
    if pages_per_sheet > 1:
        layout = f"{sheet_count} sheets = {expected_pages} pages, {pages_per_sheet}-up on {sheet.upper()} landscape"
    else:
        layout = f"{sheet_count} pages, 1-up"
    print(f"[+] Merged PDF: {out}  ({layout}, {size_kb} KB)")

    if not keep_singles:
        for pdf in pdfs:
            pdf.unlink(missing_ok=True)
        print(f"[*] Removed {len(pdfs)} single-paper PDF(s); pass --keep-singles to keep them")
    return out


def main():
    ap = argparse.ArgumentParser(description="Merge this run's thesisPaper guide PDFs into one print file.")
    ap.add_argument("pdfs", nargs="+", help="Study-guide PDFs produced by this run (2+ files)")
    ap.add_argument("--out", default=None, help="Output path (default: E:\\thesis\\ThesisGuides_<date>.pdf)")
    ap.add_argument("--keep-singles", action="store_true", help="Keep the individual PDFs after merging")
    ap.add_argument("--pages-per-sheet", type=int, choices=(1, 2), default=2,
                    help="Pages printed per sheet: 2 puts two portrait pages side by side on a landscape A4 (default 2)")
    ap.add_argument("--sheet", choices=("a4", "letter"), default="a4", help="Print sheet size (default a4)")
    args = ap.parse_args()

    try:
        from thesis_common import thesis_base
    except Exception:
        thesis_base = lambda: pathlib.Path("E:/thesis") if pathlib.Path("E:/").exists() else pathlib.Path.cwd() / "thesis"

    base = thesis_base()
    out = pathlib.Path(args.out) if args.out else unique_out_path(
        base, f"ThesisGuides_{datetime.date.today().isoformat()}"
    )

    if len(args.pdfs) < 2:
        print("[*] Only one PDF supplied — nothing to merge. Leaving it as-is.")
        return 0

    merge([pathlib.Path(p) for p in args.pdfs], out, args.keep_singles,
          pages_per_sheet=args.pages_per_sheet, sheet=args.sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
