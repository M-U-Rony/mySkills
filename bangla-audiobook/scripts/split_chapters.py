"""Assemble per-page text into one source file per chapter.

Usage: python split_chapters.py <workdir> [--chapter N]
Reads <workdir>/chapters.json:
  [{"title": "Chapter 1: The Beginning", "start": 7, "end": 21}, ...]   (1-based, inclusive PDF page numbers)
Writes <workdir>/source/001.txt, 002.txt, ... (first line = chapter title).
--chapter N writes only chapter N (1-based position in chapters.json), so a chapter subagent extracts just its own.
"""
import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")


ROMAN_NUMERAL = re.compile(
    r"m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})",
    re.IGNORECASE,
)


def looks_like_header_label(label: str) -> bool:
    """A running-head label is short and title-cased/all-caps, never a sentence."""
    words = label.split()
    if not words or len(words) > 5:
        return False
    return all(re.fullmatch(r"[A-Z][A-Za-z0-9'’\-\.:]*", w) for w in words)


def is_header_or_page_num(line: str) -> bool:
    line = line.strip()
    if not line:
        return False
    # Bare page number: arabic digits, or a valid roman numeral (length-capped).
    if re.fullmatch(r"\d{1,4}", line) or (len(line) <= 7 and ROMAN_NUMERAL.fullmatch(line)):
        return True
    # Running headers where the page number is separated by wide spacing/tabs.
    if re.match(r"^\d{1,4}\s{2,}[A-Za-z]", line) or re.search(r"[A-Za-z]\s{2,}\d{1,4}$", line):
        return True
    # Running headers like "12 CHAPTER ONE" / "CHAPTER ONE 12". The label must look
    # like a title (title-case or all-caps) so ordinary body sentences are never dropped.
    m = re.fullmatch(r"\d{1,3}\s+(.+)", line)
    if m and looks_like_header_label(m.group(1)):
        return True
    m = re.fullmatch(r"(.+?)\s+\d{1,3}", line)
    if m and looks_like_header_label(m.group(1)):
        return True
    return False


def clean_page_lines(text: str) -> list[str]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    # Strip running headers from top of page (first 1-2 lines)
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and is_header_or_page_num(lines[0]):
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    # Strip running footers/page numbers from bottom of page
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and is_header_or_page_num(lines[-1]):
        lines.pop()
    return lines


def clean(lines: list[str]) -> str:
    paragraphs, current = [], []
    for ln in lines:
        stripped = ln.strip()
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if is_header_or_page_num(stripped):
            continue
        if current and current[-1].endswith("-") and stripped[:1].islower():
            current[-1] = current[-1][:-1] + stripped  # re-join hyphenated word
        else:
            current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir")
    ap.add_argument("--chapter", type=int, help="only extract this chapter number")
    args = ap.parse_args()

    work = pathlib.Path(args.workdir).resolve()
    chapters = json.loads((work / "chapters.json").read_text(encoding="utf-8-sig"))
    out_dir = work / "source"
    out_dir.mkdir(exist_ok=True)
    for n, ch in enumerate(chapters, 1):
        if args.chapter and n != args.chapter:
            continue
        all_lines = []
        stop_chapter = False
        for p in range(ch["start"], ch["end"] + 1):
            if stop_chapter:
                break
            page_file = work / "pages" / f"page_{p:04d}.txt"
            if page_file.exists():
                page_lines = clean_page_lines(page_file.read_text(encoding="utf-8"))
                filtered_lines = []
                for ln in page_lines:
                    s = ln.strip()
                    if re.match(r"^Notes for this section begin on page \d+\.?$", s, re.IGNORECASE):
                        continue
                    if s == "Notes":
                        stop_chapter = True
                        break
                    filtered_lines.append(ln)
                all_lines.extend(filtered_lines)
                all_lines.append("")  # paragraph separator between pages if needed
        body = clean(all_lines)
        (out_dir / f"{n:03d}.txt").write_text(f"{ch['title']}\n\n{body}\n", encoding="utf-8")
        print(f"{n:03d}.txt  p{ch['start']}-{ch['end']}  {len(body):>7} chars  {ch['title']}")


if __name__ == "__main__":
    main()
