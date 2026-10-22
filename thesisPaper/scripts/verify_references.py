"""Verify that every Table / Figure / Equation / Section / Appendix reference in the Part 2 analysis
actually exists in the extracted paper text. Unverified references are flagged inline with ⚠️ and
listed in a verification report appended to the analysis.

Usage (standalone):
  python verify_references.py "<workdir>" "<analysis.md>" [--in-place]

Used automatically by generate_thesis_analysis.py.
"""
import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
NUM = r"([A-Z]?\d+(?:\.\d+)*|[A-H](?:\.\d+)+|[A-H](?=\b))"

KIND_WORDS = {
    "table": r"Tables?|Tab\.|টেবিল|সারণি|সারণী",
    "figure": r"Figures?|Figs?\.?|চিত্র|ফিগার",
    "equation": r"Equations?|Eqs?\.?|Eqn\.?|সমীকরণ",
    "section": r"Sections?|Sec\.|§|সেকশন|ধারা|অনুচ্ছেদ",
    "appendix": r"Appendix|Appendices|App\.|পরিশিষ্ট|অ্যাপেন্ডিক্স",
}
REF_RE = re.compile(
    r"(?P<word>" + "|".join(f"(?P<{k}>{v})" for k, v in KIND_WORDS.items()) + r")\s*[-–]?\s*\(?" + NUM + r"\)?"
)


def load_source_text(workdir: pathlib.Path) -> str:
    parts = []
    for pattern in ("pages/page_*.md", "source/*.md"):
        for f in sorted(workdir.glob(pattern)):
            parts.append(f.read_text(encoding="utf-8", errors="replace"))
        if parts:
            break  # pages/ already contains everything; source/ is a fallback
    ad = workdir / "appendix_digest.md"
    if ad.exists():
        parts.append(ad.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def exists_in_source(kind: str, label: str, src: str) -> bool:
    L = re.escape(label)
    if kind == "table":
        return bool(re.search(rf"\b(?:Table|Tab\.)\s*{L}\b", src, re.I))
    if kind == "figure":
        return bool(re.search(rf"\b(?:Figure|Fig\.?)\s*{L}\b", src, re.I))
    if kind == "equation":
        return bool(re.search(rf"\(\s*{L}\s*\)|\b(?:Eq|Eqn|Equation)s?\.?\s*\(?{L}\b|\\tag\{{{L}\}}", src, re.I))
    if kind in ("section", "appendix"):
        if re.search(rf"\b(?:Section|Sec\.|§|Appendix)\s*{L}\b", src, re.I):
            return True
        # Heading-style: a line starting with "3.2 Title", "A.5 Title", "## 3.2 ..."
        return bool(re.search(rf"(?m)^[#\s>*]*{L}\.?\s+[A-Z]", src))
    return True


def verify(workdir: pathlib.Path, analysis_md: str) -> tuple[str, dict]:
    src = load_source_text(workdir).translate(BN_DIGITS)
    if not src.strip():
        return analysis_md, {"skipped": "no source text available"}

    checked, verified, unverified = {}, [], []
    out_parts, last = [], 0
    norm = analysis_md.translate(BN_DIGITS)  # same length as original (1:1 digit mapping)
    for m in REF_RE.finditer(norm):
        kind = next(k for k in KIND_WORDS if m.group(k))
        label = m.group(len(KIND_WORDS) + 2)  # the NUM group
        key = f"{kind}:{label}"
        if key not in checked:
            checked[key] = exists_in_source(kind, label, src)
            (verified if checked[key] else unverified).append(f"{m.group('word')} {label}")
        if not checked[key]:
            out_parts.append(analysis_md[last:m.end()] + " ⚠️")
            last = m.end()
    out_parts.append(analysis_md[last:])
    annotated = "".join(out_parts)

    report = {"total_unique_refs": len(checked), "verified": verified, "unverified": unverified}
    if checked:
        pct = 100 * len(verified) // len(checked)
        lines = [
            "\n\n---\n\n## 🔎 রেফারেন্স যাচাই (Automatic Reference Verification)\n",
            f"Part 2-এ উল্লেখিত **{len(checked)}টি** স্বতন্ত্র Table/Figure/Equation/Section রেফারেন্সের মধ্যে "
            f"**{len(verified)}টি ({pct}%)** মূল পেপারের টেক্সটে পাওয়া গেছে।",
        ]
        if unverified:
            lines.append("\n**⚠️ পেপারে পাওয়া যায়নি (নিজে যাচাই করুন; অন্য পেপারের রেফারেন্স হলে উপেক্ষা করুন):** "
                         + ", ".join(f"`{u}`" for u in unverified))
        annotated += "\n".join(lines) + "\n"
    return annotated, report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Flag Part 2 references that do not exist in the paper.")
    ap.add_argument("workdir")
    ap.add_argument("analysis_md")
    ap.add_argument("--in-place", action="store_true")
    a = ap.parse_args()
    wd = pathlib.Path(a.workdir).resolve()
    p = pathlib.Path(a.analysis_md).resolve()
    text, rep = verify(wd, p.read_text(encoding="utf-8"))
    print(json.dumps(rep, indent=2, ensure_ascii=False))
    if a.in_place:
        p.write_text(text, encoding="utf-8")
        print(f"[+] Annotated {p}")
