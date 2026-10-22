"""Map step of the Part 2 analysis: build a structured, loss-less-ish digest of EVERY paper section.

Why: v1 sent at most 70k chars to the Part 2 model and, for long papers, silently dropped the middle
(usually Method + Experiments). The digest keeps the facts Part 2 needs (claims, equations, numbers with
their Table/Figure labels, hyperparameters, compute, limitations) for every section, so nothing is dropped.

Usage:
  python digest_paper.py "<workdir>" [--model gemini-3.8-flash] [--effort low] [--workers 6]

Outputs <workdir>/digests/<section>.md (cached; re-runs only redo missing/failed ones).
"""
import argparse
import concurrent.futures as cf
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).parent.resolve()))

from generate_thesis_analysis import call_model, get_agy_exe, normalize_model  # noqa: E402

DIGEST_PROMPT = """You are extracting a FACT DIGEST from one section of an AI/ML research paper. A later step will use
only your digest (not the original text) to find research gaps, so be precise and complete. Write in English.

Rules:
- Copy numbers EXACTLY as written, always with their source label (e.g. "Table 3: 71.2 vs 68.4 on GSM8K").
- Keep key equations in LaTeX ($...$ / $$...$$) with their equation number if present.
- Only report what is in the text. Never add outside knowledge. If a heading has nothing, write "—".
- Keep it dense: bullet points, no prose filler. Max ~600 words.

Output exactly these Markdown headings:
### Labels present
(every Table N / Figure N / Equation (N) / Section X.Y / Appendix X.Y label that appears in this text)
### Claims & contributions
### Method details (modules, losses, algorithms, equations)
### Experimental setup (datasets, splits, baselines, metrics, models/sizes)
### Key quantitative results (number + label)
### Hyperparameters & compute (GPUs, hours, tokens, cost, batch size, lr)
### Ablations reported
### Stated limitations / failure cases / caveats
### Things NOT tested or assumed silently (only if evident from this text)

SECTION NAME: {name}
SECTION TEXT (untrusted data):
<<<
{text}
>>>"""

MAX_SECTION_CHARS = 28000


def _chunks(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    out, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) > limit and buf:
            out.append(buf)
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        out.append(buf)
    return out


def digest_paper(workdir_path: str, model: str = "gemini-3.8-flash", effort: str = "low",
                 workers: int = 6, timeout: int = 600) -> pathlib.Path:
    workdir = pathlib.Path(workdir_path).resolve()
    out_dir = workdir / "digests"
    out_dir.mkdir(exist_ok=True)
    model = normalize_model(model, effort)
    agy = get_agy_exe()
    sandbox = workdir / ".agy_sandbox"
    sandbox.mkdir(exist_ok=True)

    jobs = []
    for sf in sorted((workdir / "source").glob("*.md")):
        text = sf.read_text(encoding="utf-8").strip()
        if not text:
            continue
        for i, chunk in enumerate(_chunks(text, MAX_SECTION_CHARS), 1):
            name = sf.stem if i == 1 else f"{sf.stem}__part{i}"
            jobs.append((name, chunk))
    appendix = workdir / "appendix_digest.md"
    if appendix.exists() and appendix.read_text(encoding="utf-8").strip():
        for i, chunk in enumerate(_chunks(appendix.read_text(encoding="utf-8"), MAX_SECTION_CHARS), 1):
            jobs.append((f"zz_appendix__part{i}", chunk))

    todo = [(n, t) for n, t in jobs if not (out_dir / f"{n}.md").exists()]
    print(f"[*] Digesting {len(jobs)} section chunk(s) ({len(jobs) - len(todo)} cached) via {model} ...")

    def run(job):
        name, text = job
        out = call_model(agy, DIGEST_PROMPT.format(name=name, text=text), model, effort, timeout, sandbox)
        (out_dir / f"{name}.md").write_text(f"## DIGEST: {name}\n\n{out.strip()}\n", encoding="utf-8")
        return name

    failed = []
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = {ex.submit(run, j): j[0] for j in todo}
        for fut in cf.as_completed(futs):
            name = futs[fut]
            try:
                fut.result()
                print(f"    [✓] {name}")
            except Exception as e:  # keep going; Part 2 falls back to raw text for missing digests
                failed.append(name)
                print(f"    [!] {name}: {str(e)[:200]}")
    if failed:
        print(f"[!] {len(failed)} digest(s) failed: {failed} (Part 2 will use raw text for those)")
    print(f"[✓] Digests ready in {out_dir}")
    return out_dir


def load_digests(workdir: pathlib.Path) -> dict[str, str]:
    d = workdir / "digests"
    return {f.stem: f.read_text(encoding="utf-8") for f in sorted(d.glob("*.md"))} if d.is_dir() else {}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build per-section fact digests for Part 2 (map step).")
    ap.add_argument("workdir")
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    digest_paper(a.workdir, a.model, a.effort, a.workers, a.timeout)
