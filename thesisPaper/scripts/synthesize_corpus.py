"""Cross-Paper Corpus Synthesizer (v2.0): clusters recurring gaps across all studied papers,
exports a unified E:\\thesis\\references.bib, and drafts a thematic Literature Review + Thesis Convergence report.

Usage:
  python synthesize_corpus.py [--model gemini-3.8-flash-high] [--effort high]
"""
import argparse
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).parent.resolve()))

from generate_thesis_analysis import call_model, get_agy_exe, normalize_model  # noqa: E402
from thesis_common import CORPUS_DIR_NAME, load_literature, load_profile, thesis_base  # noqa: E402

SYNTHESIS_PROMPT = """You are a senior AI/ML thesis advisor helping a researcher synthesize {n} papers studied so far into ONE cohesive thesis direction.

Given the researcher profile and the structured entries of all {n} papers in the corpus, produce `CROSS_PAPER_SYNTHESIS.md` with:
1. **Recurring Gap Clusters (বারবার উঠে আসা গবেষণা গ্যাপ):** Group the limitations that appear across multiple papers (cite [P1], [P2], ...). A gap that recurs across 3+ papers is prime thesis territory.
2. **Concept & Lineage Graph (Mermaid `flowchart LR`):** Show how the papers relate, extend, or trade off against one another.
3. **Top 2 Converged Thesis Proposals:** Combine insights/modules from at least 2 papers in the corpus into a unified, practical thesis topic tailored to the researcher's profile.
4. **Thematic Literature Review Chapter Draft (English + বাংলা):** Organized by *theme/paradigm* (never a laundry list of one paragraph per paper), citing the papers cleanly.
"""


def collect_bibtex(base: pathlib.Path) -> pathlib.Path:
    corpus = base / CORPUS_DIR_NAME
    bibs = []
    if corpus.is_dir():
        for sr in sorted(corpus.glob("*/scout_report.json")):
            try:
                data = json.loads(sr.read_text(encoding="utf-8"))
                b = (data.get("paper") or {}).get("bibtex", "").strip()
                if b:
                    bibs.append(b)
            except Exception:
                pass
    bib_file = base / "references.bib"
    bib_file.write_text("\n\n".join(bibs) + ("\n" if bibs else ""), encoding="utf-8")
    print(f"[+] Exported {len(bibs)} BibTeX entry/entries to {bib_file}")
    return bib_file


def synthesize_corpus(model: str = "gemini-3.8-flash-high", effort: str = "high", timeout: int = 900) -> pathlib.Path:
    base = thesis_base()
    entries = load_literature(base)
    collect_bibtex(base)
    if not entries:
        raise SystemExit(f"No papers found in {base / 'literature.json'} or {base / 'LITERATURE_MATRIX.md'} yet.")

    profile = load_profile(base) or "No researcher profile filled in yet."
    model = normalize_model(model, effort)
    prompt = (
        f"{SYNTHESIS_PROMPT.format(n=len(entries))}\n\n"
        f"=== RESEARCHER PROFILE ===\n{profile}\n\n"
        f"=== ALL STUDIED PAPERS ({len(entries)}) ===\n{json.dumps(entries, ensure_ascii=False, indent=2)}\n"
    )
    sandbox = base / ".agy_sandbox"
    sandbox.mkdir(exist_ok=True)
    print(f"[*] Synthesizing {len(entries)} paper(s) across corpus via {model} ...")
    out = call_model(get_agy_exe(), prompt, model, effort, timeout, sandbox)
    dest = base / "CROSS_PAPER_SYNTHESIS.md"
    dest.write_text(out.strip() + "\n", encoding="utf-8")
    print(f"[✓] Saved cross-paper synthesis: {dest}")
    return dest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Synthesize all studied papers into gap clusters, a thematic lit review, and references.bib.")
    ap.add_argument("--model", default="gemini-3.8-flash-high")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    synthesize_corpus(a.model, a.effort, a.timeout)
