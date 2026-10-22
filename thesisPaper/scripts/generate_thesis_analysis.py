"""Generate Ultra-Minimal Mode B Study & Thesis Guide PDF content, Companion .md Notes, and update LITERATURE_MATRIX.md.

Usage:
  python generate_thesis_analysis.py "<workdir>" [--model gemini-3.8-flash-high] [--effort high] [--append-to-translation]
  python generate_thesis_analysis.py "<workdir>" --from-markdown "<custom_analysis.md>"

What it produces:
1. By default (Mode B Ultra-Minimal): writes a 4–5 page visual Bangla Study & Thesis Guide into <workdir>/bangla/
   (covering: 1. Core Paper Explained with Figures, Equations & Main Table, 2. Flaw & Gap Matrix, 3. Top Verified Thesis Ideas)
   so compile_thesis_pdf.py renders a concise, high-signal 4–5 page PDF without translating 30+ pages of raw paper/appendix.
2. Saves the companion Markdown dossier: E:\\thesis\\<Title>_Thesis_Notes.md (which includes the study guide PLUS copy-paste
   assets kept out of the PDF: GitHub/dataset links, English & Bangla "Related Work" paragraphs, BibTeX, and prior-work links).
3. Updates E:\\thesis\\literature.json and E:\\thesis\\LITERATURE_MATRIX.md.
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

MINIMAL_STUDY_PROMPT = """You are a principal AI/ML research advisor and master educator writing an **Ultra-Minimal, Visual Bangla Study & Thesis Guide (target: 4–5 PDF pages total)** for a researcher.

You are given:
1. The paper content (full text or structured per-section digests).
2. A list of extracted figures (`![caption](figures/fig_...)`) available from the paper.
3. A Live Literature & Code Scout Report (real API data: code repositories, citation count, BibTeX, and 2024+ citing papers).
4. A compact view of the researcher's literature store (previous papers studied, labelled [P1], [P2], ...).
5. The RESEARCHER PROFILE (if filled in).

STRICT MINIMALIST & STYLE RULES:
- **NO HARDWARE / GPU / VRAM JARGON:** Do NOT mention "Single-GPU", "16GB–24GB VRAM", "RTX 3090", "Colab T4", or hardware memory estimates anywhere. Keep thesis ideas focused purely on clean algorithmic, architectural, mathematical, or data/evaluation innovations.
- **NO REPETITIVE ENGLISH BRACKETS:** Write in natural, fluent scholarly Bangla. Do NOT clutter sentences with repetitive parenthetical English words like `ইনফারেন্স (Inference)`, `বেঞ্চমার্ক (Benchmark)`, `অপটিমাইজেশন (Optimization)` on every line. Use English in parentheses ONLY once if introducing a rare technical concept.
- **EMBED KEY PAPER FIGURES:** In Section 1, embed **2 to 3 of the most informative figures** from the provided `AVAILABLE PAPER FIGURES` list (e.g., the main architecture diagram and key result plot) using their exact Markdown path `![বাংলা ক্যাপশন](figures/fig_pXXX_YY.png)`. Never invent figure filenames.
- **EQUATION INTUITION BOXES:** Include the paper's 1–3 core mathematical equations (`$$ ... $$`) in Section 1, and right below each `$$ ... $$` equation add a 2-sentence plain-Bangla intuition blockquote:
  > **[সহজ বাংলায় মূল কথা (Intuition)]:** <plain-Bangla explanation of what the equation computes and why>
- **EVIDENCE-BACKED FLAWS:** Every flaw in Section 2 MUST cite an exact `Section / Table / Figure / Equation` from the paper. Never write generic fluff like "test on more datasets".
- **CONCISE & READABLE:** The PDF study guide (Sections 1, 2, 3) MUST fit comfortably in **4–5 pages** (~1,500–2,000 words total). Put copy-paste reference material (GitHub links, Related Work paragraphs, BibTeX) strictly AFTER the `<!-- NOTES_ONLY_SPLIT -->` marker so it goes only into `_Thesis_Notes.md` and never bloats the PDF.

Produce a Markdown document with this EXACT structure:

# ১. মূল গবেষণাপত্র সহজ ভাষায় (Core Paper Explained)

### মূল সমস্যা ও উদ্ভাবন (Problem & Core Idea)
- What exact bottleneck does this paper solve, why did prior approaches fall short, and what is the central claim (with headline numbers)? Keep to 2 crisp paragraphs.

### কীভাবে কাজ করে ও গাণিতিক মেকানিজম (Architecture, Pipeline & Core Math)
- Explain the step-by-step architecture and components clearly in Bangla.
- Embed **2–3 key figures** from `AVAILABLE PAPER FIGURES` (`![...](figures/...)`) at the relevant points.
- Show the core equations (`$$ ... $$`) and place a `> **[সহজ বাংলায় মূল কথা (Intuition)]:** ...` blockquote immediately below each display equation.

### প্রধান পরীক্ষামূলক ফলাফল (Headline Benchmark Results)
- One clean, compact Markdown table summarizing the main benchmark comparison (e.g., Main Paper Table 1 — top baselines vs. proposed method across key benchmarks).
- 3 concise bullet takeaways explaining what the numbers actually prove (and where gains are smallest).

# ২. সীমাবদ্ধতা ও রিসার্চ গ্যাপ (What This Paper Lacks)

### সীমাবদ্ধতা ম্যাট্রিক্স (Flaw & Gap Matrix)
Provide a compact 4-row Markdown table (`গ্যাপের ধরন | পেপারের সুনির্দিষ্ট রেফারেন্স | মূল টেকনিক্যাল দুর্বলতা ও কেন এটি ঘটে`) covering:
1. **Methodological / Mathematical Bottleneck** (cite exact Section/Equation).
2. **Missing Ablation / Evaluation Bias** (cite exact Table/Section).
3. **Scalability / Efficiency / Failure Mode** (cite exact Table/Section where method degrades).
4. **Domain / Multilingual / Low-Resource Gap** (cite exact dataset table/section).

### সাম্প্রতিক গবেষণা ও খোলা সুযোগ (2024–2026 Scoop Check)
- 3–4 short bullet points based ONLY on the Scout Report's recent citing papers: what follow-up papers already explored, and the **2–3 clearest wide-open gaps** left untouched.

# ৩. থিসিস আইডিয়া ও গবেষণা পরিকল্পনা (Actionable Thesis Ideas)

### সেরা থিসিস ব্লুপ্রিন্ট (Featured Thesis Blueprint #1)
Present the **#1 strongest, most original thesis direction** in clear, focused points:
- **প্রস্তাবিত শিরোনাম (Proposed Title):** English and Bangla.
- **কোন গ্যাপটি পূরণ করে (Exact Gap Addressed):** Tied to a specific flaw from Section 2.
- **সুনির্দিষ্ট মেথডোলজিক্যাল পরিবর্তন (Exact Methodological Change):** What module, objective function, or pipeline step to modify (include the proposed mathematical formulation `$$ ... $$` + a 1-line intuition).
- **প্রমাণের কৌশল ও বেসলাইন (Validation & Defense Plan):** Which dataset, metric, and baseline table from the paper to compare against, and what ablation proves the claim.

### বিকল্প আরও ২টি থিসিস আইডিয়া (Alternative Thesis Ideas — At a Glance)
Provide a compact 2-row Markdown comparison table for **Blueprint #2** and **Blueprint #3** with columns:
`| আইডিয়া ও প্রস্তাবিত শিরোনাম | কোন গ্যাপ পূরণ করে | মূল মেথডোলজিক্যাল পরিবর্তন | প্রমাণের মাপকাঠি (Dataset & Metric) |`

<!-- NOTES_ONLY_SPLIT -->

# ৪. রেফারেন্স, কোড ও থিসিস ড্রাফট কিট (Notes-Only Reference Kit)
- **অফিসিয়াল কোড ও ডেটাসেট লিংক (Code & Resources):** Direct GitHub / model / dataset links from the Scout Report.
- **Draft English "Related Work" Paragraph:** 1 polished academic paragraph summarizing this paper's method, headline numbers (with Table refs), and limitation leading into your thesis.
- **বাংলা সাহিত্য পর্যালোচনা অনুচ্ছেদ (Bangla Literature Review Snippet):** 1 scholarly Bangla paragraph for a Bangla thesis report.
- **BibTeX Citation:** Exact BibTeX from the Scout Report.

Finally, at the very end of your response, include a single JSON block fenced with ```json ... ``` with these exact keys:
```json
{
  "matrix_row": {
    "year": "YYYY",
    "venue": "Venue/arXiv",
    "core_method": "1-sentence English summary of core method",
    "datasets_metrics": "Main datasets & metrics",
    "key_limitation": "Most critical flaw/gap with section/table ref",
    "top_thesis_idea": "#1 recommended thesis idea in 1 sentence"
  },
  "blueprints": [
    {"id": 1, "title": "English title of Blueprint 1",
     "search_queries": ["2 short keyword queries (4-7 words each) to check prior work on Semantic Scholar"]}
  ]
}
```
(Include all 3 blueprints in the "blueprints" list.)
"""


def thesis_base(workdir: pathlib.Path = None) -> pathlib.Path:
    env = os.environ.get("THESIS_OUT")
    if env:
        p = pathlib.Path(env).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    e_drive = pathlib.Path("E:/")
    if e_drive.exists():
        p = e_drive / "thesis"
        p.mkdir(parents=True, exist_ok=True)
        return p
    p = pathlib.Path.cwd() / "thesis"
    p.mkdir(parents=True, exist_ok=True)
    return p


def normalize_model(model: str, effort: str = "") -> str:
    m = (model or "").strip()
    eff = (effort or "").strip().lower()
    if m.startswith("gemini-3.8-flash"):
        if eff in ("low", "medium", "high"):
            target = f"gemini-3.8-flash-{eff}"
            if m != target:
                print(f"[*] Normalizing model '{m}' with effort '{eff}' -> '{target}'.")
            return target
        if m == "gemini-3.8-flash":
            return "gemini-3.8-flash-low"
    return m or "gemini-3.8-flash-low"


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    return name[:110] or "paper"


def get_agy_exe() -> str:
    exe = shutil.which("agy")
    if exe:
        return exe
    for p in (pathlib.Path.home() / "AppData/Local/agy/bin/agy.exe",
              pathlib.Path.home() / "AppData/Local/Programs/agy/agy.exe",
              pathlib.Path.home() / ".local/bin/agy"):
        if p.exists():
            return str(p)
    raise SystemExit("agy CLI not found on PATH or in AppData/Local/agy/bin")


def call_model(agy: str, prompt: str, model: str, effort: str, timeout: int, cwd: pathlib.Path) -> str:
    msg = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
    cmd = [agy, "--disable-slash-commands", "--sandbox", "--model", model,
           "--input-format", "stream-json", "--output-format", "stream-json",
           f"--print-timeout={timeout}s"]
    if effort and not model.endswith(("-low", "-medium", "-high")):
        cmd += ["--effort", effort]
    cmd.append("-p=")
    last_err = ""
    for wait in (0, 10, 30):
        if wait:
            time.sleep(wait)
        try:
            res = subprocess.run(cmd, input=msg, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=timeout + 60, cwd=str(cwd))
        except subprocess.TimeoutExpired:
            last_err = f"timeout after {timeout}s"
            continue
        result = None
        for line in res.stdout.splitlines():
            if line.startswith("{") and '"event":"result"' in line.replace(" ", ""):
                try:
                    result = json.loads(line)["result"]
                except json.JSONDecodeError:
                    pass
        if result and result.get("status") == "SUCCESS" and result.get("response", "").strip():
            out = result["response"].strip()
            m = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```$", out, re.S)
            return m.group(1).strip() if m else out
        last_err = (result.get("error") if result else None) or (res.stderr or res.stdout)[-500:]
    raise RuntimeError(f"Thesis analysis model call failed: {last_err}")


def discover_main_figures(workdir: pathlib.Path) -> str:
    """List extracted figures from the main paper with their nearby Figure caption text."""
    lines = []
    seen = set()
    sources = sorted((workdir / "source").glob("*.md")) or sorted((workdir / "pages").glob("page_*.md"))
    for sf in sources:
        if "appendix" in sf.name.lower():
            continue
        txt = sf.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"!\[[^\]]*\]\((figures/[^)]+)\)", txt):
            rel = m.group(1)
            if rel in seen or not (workdir / rel).exists():
                continue
            seen.add(rel)
            # Grab 280 chars around the image tag to find Figure N caption
            window = txt[max(0, m.start() - 120): min(len(txt), m.end() + 320)]
            cap_m = re.search(r"(?:Figure|Fig\.?)\s*\d+[:.][^\n]+", window, re.I)
            cap = cap_m.group(0).strip() if cap_m else "Paper figure / diagram"
            lines.append(f"- `{rel}` — {cap[:200]}")
    return "\n".join(lines[:10]) if lines else "No extracted figure files found."


def register_thesis_lab_chapter(workdir: pathlib.Path, pdf_md: str, append_to_translation: bool = False):
    """Register the generated Markdown for PDF compilation.
    In default Mode B (append_to_translation=False), the PDF contains ONLY the ultra-minimal study guide (4-5 pages).
    If append_to_translation=True, it appends Part 2 after the translated main paper."""
    bangla_dir = workdir / "bangla"
    bangla_dir.mkdir(parents=True, exist_ok=True)
    lab_filename = "ch99_01_thesis_opportunity_lab.md"
    (bangla_dir / lab_filename).write_text(pdf_md, encoding="utf-8")

    chapters_file = workdir / "chapters.json"
    sections_file = workdir / "sections.json"

    if not append_to_translation:
        ch_title = "মূল গবেষণাপত্র ও থিসিস গাইড (Minimal Study & Thesis Guide)"
        sec_obj = {
            "id": 1,
            "chapter_id": 1,
            "chapter_num": "1",
            "chapter_title": ch_title,
            "part_type": "minimal_study",
            "is_front_matter": False,
            "title": ch_title,
            "start": 0,
            "end": 0,
            "continuation": False,
            "translate": True,
            "filename": lab_filename,
        }
        ch_obj = {
            "id": 1,
            "chapter_num": "1",
            "title": ch_title,
            "part_type": "minimal_study",
            "is_front_matter": False,
            "start": 0,
            "end": 0,
            "sections": [sec_obj],
        }
        chapters_file.write_text(json.dumps([ch_obj], indent=2, ensure_ascii=False), encoding="utf-8")
        sections_file.write_text(json.dumps([sec_obj], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[+] Configured Ultra-Minimal Mode B PDF (single compact study guide) in {chapters_file.name}")
        return

    chapters = json.loads(chapters_file.read_text(encoding="utf-8")) if chapters_file.exists() else []
    sections = json.loads(sections_file.read_text(encoding="utf-8")) if sections_file.exists() else []
    chapters = [c for c in chapters if c.get("part_type") not in ("thesis_lab", "minimal_study")]
    sections = [s for s in sections if s.get("part_type") not in ("thesis_lab", "minimal_study")]

    next_ch_id = max((c["id"] for c in chapters), default=0) + 1
    next_sec_id = max((s["id"] for s in sections), default=0) + 1
    ch_title = "গবেষণা ফরেনসিক, সীমাবদ্ধতা ও থিসিস ব্লুপ্রিন্ট (Thesis Opportunity & Gap Analysis)"

    sec_obj = {
        "id": next_sec_id,
        "chapter_id": next_ch_id,
        "chapter_num": str(next_ch_id),
        "chapter_title": ch_title,
        "part_type": "thesis_lab",
        "is_front_matter": False,
        "title": ch_title,
        "start": 0,
        "end": 0,
        "continuation": False,
        "translate": True,
        "filename": lab_filename,
    }
    ch_obj = {
        "id": next_ch_id,
        "chapter_num": str(next_ch_id),
        "title": ch_title,
        "part_type": "thesis_lab",
        "is_front_matter": False,
        "start": 0,
        "end": 0,
        "sections": [sec_obj],
    }
    chapters.append(ch_obj)
    sections.append(sec_obj)
    chapters_file.write_text(json.dumps(chapters, indent=2, ensure_ascii=False), encoding="utf-8")
    sections_file.write_text(json.dumps(sections, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] Registered Part 2 Thesis Opportunity Chapter in {chapters_file.name} & {sections_file.name}")


def build_paper_context(workdir: pathlib.Path, model: str, effort: str, timeout: int, raw_budget: int = 58000) -> str:
    """Assemble paper context without dropping middle sections or blowing up prompt size."""
    source_files = sorted((workdir / "source").glob("*.md"))
    source_parts = [f"--- SECTION ({sf.name}) ---\n" + sf.read_text(encoding="utf-8") for sf in source_files]
    paper_text = "\n\n".join(source_parts)
    if not paper_text.strip():
        for pf in sorted((workdir / "pages").glob("page_*.md")):
            paper_text += f"\n\n--- PAGE ({pf.name}) ---\n" + pf.read_text(encoding="utf-8")

    if len(paper_text) <= raw_budget:
        return paper_text

    from digest_paper import digest_paper, load_digests
    digests = load_digests(workdir)
    if not digests and source_files:
        try:
            digest_paper(str(workdir), model=model, effort="low", workers=6, timeout=min(timeout, 600))
            digests = load_digests(workdir)
        except Exception as e:
            print(f"[!] Section digest step had an error ({e}); falling back to sampled sections.", flush=True)

    if digests:
        main_parts, app_parts = [], []
        for k, v in digests.items():
            if "appendix" in k.lower() or k.startswith("ch07"):
                app_parts.append(v[:3500])
            else:
                main_parts.append(v)
        combined = "\n\n".join(main_parts + app_parts)
        return (
            "=== STRUCTURED FACT DIGESTS OF ALL PAPER SECTIONS (MAIN PAPER + APPENDIX) ===\n"
            + combined[:raw_budget]
        )

    per_sec = max(3000, raw_budget // max(1, len(source_parts)))
    return "\n\n".join(p[:per_sec] for p in source_parts)


def run_blueprint_novelty_audit(workdir: pathlib.Path, paper_title: str, blueprints: list[dict],
                                agy: str, model: str, effort: str, timeout: int) -> tuple[str, str, str]:
    """Run live topic searches on Semantic Scholar / arXiv (2024+) for each proposed blueprint.
    Returns (compact_pdf_summary_md, detailed_notes_md, short_verdict_for_matrix)."""
    from scout_literature import search_related, _norm_title

    if not blueprints:
        return "", "", "Unchecked"

    own_norm = _norm_title(paper_title)
    evidence = []
    notes_parts = [
        "\n\n---\n\n## স্বয়ংক্রিয় নভেলটি অডিট ও পূর্ববর্তী গবেষণা লিংক (Prior Work Search Log)\n",
    ]

    for bp in blueprints[:3]:
        bp_id = bp.get("id") or "?"
        bp_title = bp.get("title") or f"Blueprint {bp_id}"
        queries = [q for q in (bp.get("search_queries") or []) if isinstance(q, str) and q.strip()][:2]
        if not queries and bp_title:
            queries = [bp_title[:80]]

        hits, seen = [], {own_norm}
        for q in queries:
            for item in search_related(q, min_year=2024, limit=2):
                k = _norm_title(item.get("title"))
                if k and k not in seen:
                    seen.add(k)
                    item["matched_query"] = q
                    hits.append(item)
        hits.sort(key=lambda x: (x.get("cited_by_count") or 0), reverse=True)
        top_hits = hits[:2]
        evidence.append({"id": bp_id, "title": bp_title, "queries": queries, "closest_papers": top_hits})

        notes_parts.append(f"\n### Blueprint {bp_id}: {bp_title}")
        if top_hits:
            for h in top_hits:
                notes_parts.append(f"- **{h.get('title')}** ({h.get('year')}, {h.get('venue')}) — {h.get('url') or ''}")
        else:
            notes_parts.append("- সরাসরি মিলে যাওয়া কোনো ২০২৪+ পেপার পাওয়া যায়নি।")

    (workdir / "novelty_evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")

    verdict = f"Checked ({sum(len(e['closest_papers']) for e in evidence)} related papers)"
    compact_pdf_md = ""
    try:
        critic_prompt = (
            "You are Reviewer #2 for ACL/NeurIPS — concise and practical.\n"
            "Given the proposed thesis blueprints and retrieved 2024-2026 papers:\n"
            "1. Output ONLY a single compact Markdown table in Bangla (no headings, no intro text, no hardware/GPU talk) with columns:\n"
            "   `| ব্লুপ্রিন্ট | ওভারল্যাপ ঝুঁকি ও নিকটতম পেপার | মৌলিকত্ব (১-৫) | স্বাতন্ত্র্য বজায় রাখার উপায় (১ বাক্যে) |`\n"
            "2. After the table, output a single line `VERDICT: <short 4-8 word English recommendation>`.\n\n"
            f"RETRIEVED PRIOR WORK PER BLUEPRINT:\n{json.dumps(evidence, ensure_ascii=False, indent=2)}"
        )
        sandbox = workdir / ".agy_sandbox"
        sandbox.mkdir(exist_ok=True)
        fast_model = normalize_model(model, "low")
        critique = call_model(agy, critic_prompt, fast_model, "low", min(timeout, 240), sandbox)
        m_v = re.search(r"VERDICT:\s*(.+)", critique)
        if m_v:
            verdict = m_v.group(1).strip()[:90]
            critique = re.sub(r"\n*VERDICT:\s*.+", "", critique).strip()
        compact_pdf_md = "\n\n### নভেলটি যাচাই ও স্বাতন্ত্র্য নোট (Novelty & Reviewer Check)\n\n" + critique + "\n"
        notes_parts.append("\n### নভেলটি যাচাই ও স্বাতন্ত্র্য নোট\n\n" + critique)
    except Exception as e:
        print(f"[!] Reviewer-2 critique pass skipped ({e}).", flush=True)

    return compact_pdf_md, "\n".join(notes_parts) + "\n", verdict


def generate_thesis_analysis(workdir_path: str, model: str = "gemini-3.8-flash-high", effort: str = "high",
                             timeout: int = 600, from_markdown: str = None,
                             append_to_translation: bool = False) -> pathlib.Path:
    from thesis_common import compact_literature_view, load_profile, safe_filename, thesis_base, upsert_literature
    from verify_references import verify as verify_refs

    workdir = pathlib.Path(workdir_path).resolve()
    model = normalize_model(model, effort)
    toc = json.loads((workdir / "toc.json").read_text(encoding="utf-8")) if (workdir / "toc.json").exists() else {}
    scout = json.loads((workdir / "scout_report.json").read_text(encoding="utf-8")) if (workdir / "scout_report.json").exists() else {}
    scout_meta = scout.get("paper") or {}
    title = scout_meta.get("title") or toc.get("title") or "Research_Paper"
    out_dir = thesis_base(workdir)
    agy = get_agy_exe()

    if from_markdown:
        raw_out = pathlib.Path(from_markdown).resolve().read_text(encoding="utf-8")
    else:
        paper_context = build_paper_context(workdir, model=model, effort=effort, timeout=timeout)
        has_digests = (workdir / "digests").is_dir() and any((workdir / "digests").glob("*.md"))
        appendix_text = "" if has_digests else (
            (workdir / "appendix_digest.md").read_text(encoding="utf-8")[:6000] if (workdir / "appendix_digest.md").exists() else ""
        )
        scout_md = (workdir / "scout_summary.md").read_text(encoding="utf-8") if (workdir / "scout_summary.md").exists() else ""
        figures_list = discover_main_figures(workdir)
        matrix_compact = compact_literature_view(exclude_title=title, budget=8000)
        profile_md = load_profile(out_dir) or "No researcher profile filled in yet."

        prompt = (
            f"{MINIMAL_STUDY_PROMPT}\n\n"
            f"=== AVAILABLE PAPER FIGURES (EMBED 2-3 IN SECTION 1) ===\n{figures_list}\n\n"
            f"=== RESEARCHER PROFILE ===\n{profile_md}\n\n"
            f"=== LIVE LITERATURE & CODE SCOUT REPORT ===\n{scout_md}\n\n"
            f"=== COMPACT LITERATURE STORE (PREVIOUS PAPERS STUDIED) ===\n{matrix_compact}\n\n"
            + (f"=== APPENDIX DIGEST (FOR GAP MINING ONLY) ===\n{appendix_text}\n\n" if appendix_text else "")
            + f"=== PAPER CONTENT ===\n{paper_context}\n\n"
            f"Now write the complete Ultra-Minimal Bangla Study & Thesis Guide:"
        )
        print(f"[*] Generating Ultra-Minimal Study & Thesis Guide (prompt={len(prompt)} chars) via {model} ...", flush=True)
        sandbox = workdir / ".agy_sandbox"
        sandbox.mkdir(exist_ok=True)
        raw_out = call_model(agy, prompt, model, effort, timeout, sandbox)
        (workdir / "analysis_raw.md").write_text(raw_out, encoding="utf-8")

    # Extract trailing JSON block
    matrix_row, blueprints = {}, []
    json_blocks = list(re.finditer(r"```json\s*(\{.*?\})\s*```", raw_out, re.S))
    clean_md = raw_out
    for jm in reversed(json_blocks):
        try:
            parsed = json.loads(jm.group(1))
            if isinstance(parsed, dict) and ("matrix_row" in parsed or "core_method" in parsed or "top_thesis_idea" in parsed):
                matrix_row = parsed.get("matrix_row") or parsed
                blueprints = parsed.get("blueprints") or []
                clean_md = (raw_out[:jm.start()] + raw_out[jm.end():]).strip()
                break
        except Exception:
            continue

    # Split PDF study content vs Notes-only reference kit
    if "<!-- NOTES_ONLY_SPLIT -->" in clean_md:
        pdf_md, notes_only_md = [p.strip() for p in clean_md.split("<!-- NOTES_ONLY_SPLIT -->", 1)]
    else:
        # Fallback split at Section 4 if marker was omitted
        m_sec4 = re.search(r"(?m)^#\s*[4৪]\.", clean_md)
        if m_sec4:
            pdf_md, notes_only_md = clean_md[:m_sec4.start()].strip(), clean_md[m_sec4.start():].strip()
        else:
            pdf_md, notes_only_md = clean_md.strip(), ""

    # Run novelty audit if not already present in pre-written markdown
    if "নভেলটি যাচাই" not in pdf_md and blueprints:
        print("[*] Running live novelty check (Semantic Scholar / arXiv) ...", flush=True)
        compact_nov_md, detailed_nov_md, novelty_verdict = run_blueprint_novelty_audit(
            workdir, title, blueprints, agy=agy, model=model, effort=effort, timeout=timeout
        )
        if compact_nov_md:
            pdf_md = pdf_md.rstrip() + compact_nov_md
        if detailed_nov_md:
            notes_only_md = (notes_only_md + "\n" + detailed_nov_md).strip()
    else:
        novelty_verdict = matrix_row.get("novelty_verdict") or "Verified"

    # Verify cited Table / Figure / Section / Equation labels quietly (flag unverified inline, no noisy footer in PDF)
    print("[*] Verifying cited Table / Figure / Section / Equation labels against paper source ...", flush=True)
    _, ref_report = verify_refs(workdir, pdf_md)
    (workdir / "reference_check.json").write_text(json.dumps(ref_report, indent=2, ensure_ascii=False), encoding="utf-8")

    # 1. Register study guide for the Minimal Bangla PDF
    register_thesis_lab_chapter(workdir, pdf_md, append_to_translation=append_to_translation)

    # 2. Write the Companion Markdown Dossier in E:\thesis\<Safe_Title>_Thesis_Notes.md
    safe_t = safe_filename(title)
    pdf_filename = f"{safe_t}_Thesis_Bangla.pdf"
    notes_filename = f"{safe_t}_Thesis_Notes.md"
    notes_path = out_dir / notes_filename

    scout_header = [
        f"# Thesis Study & Research Dossier: {title}",
        "",
        f"- **Minimal Bangla Study PDF:** `{pdf_filename}`",
        f"- **Authors:** {', '.join(scout_meta.get('authors', [])[:8]) or 'See Paper'}",
        f"- **Year / Venue:** {scout_meta.get('year') or 'N/A'} | {scout_meta.get('venue') or 'N/A'}",
        f"- **arXiv / DOI:** {scout_meta.get('arxiv_id') or 'N/A'} | {scout_meta.get('doi') or 'N/A'}",
        f"- **Citations:** {scout_meta.get('cited_by_count', 0)}",
        f"- **Novelty Audit Verdict:** {novelty_verdict}",
        "",
        "---",
        "",
    ]
    full_notes = "\n".join(scout_header) + "\n" + pdf_md.strip()
    if notes_only_md:
        full_notes += "\n\n---\n\n" + notes_only_md.strip()
    notes_path.write_text(full_notes + "\n", encoding="utf-8")
    print(f"[+] Saved Companion Thesis Notes: {notes_path}", flush=True)

    # 3. Update JSON-backed literature store + regenerate LITERATURE_MATRIX.md
    upsert_literature({
        "title": title,
        "year": str(matrix_row.get("year") or scout_meta.get("year") or "N/A"),
        "venue": str(matrix_row.get("venue") or scout_meta.get("venue") or "Paper"),
        "arxiv_id": scout_meta.get("arxiv_id"),
        "doi": scout_meta.get("doi"),
        "cited_by_count": scout_meta.get("cited_by_count", 0),
        "core_method": matrix_row.get("core_method") or "See Notes",
        "datasets_metrics": matrix_row.get("datasets_metrics") or "See Notes",
        "key_limitation": matrix_row.get("key_limitation") or "See Notes",
        "top_thesis_idea": matrix_row.get("top_thesis_idea") or "See Notes",
        "novelty_verdict": novelty_verdict,
        "blueprints": blueprints,
        "pdf": pdf_filename,
        "notes": notes_filename,
    }, base=out_dir)
    return notes_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate Ultra-Minimal Study & Thesis Guide, Companion .md, and update LITERATURE_MATRIX.md.")
    ap.add_argument("workdir", help="Path to paper workdir")
    ap.add_argument("--model", default="gemini-3.8-flash-high", help="Model to use via agy CLI")
    ap.add_argument("--effort", default="high", help="Reasoning effort (default: high)")
    ap.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    ap.add_argument("--from-markdown", default=None, help="Optional path to pre-written Markdown analysis")
    ap.add_argument("--append-to-translation", action="store_true", help="Append Part 2 after full paper translation instead of standalone minimal Mode B")
    a = ap.parse_args()
    generate_thesis_analysis(
        a.workdir, model=a.model, effort=a.effort, timeout=a.timeout,
        from_markdown=a.from_markdown, append_to_translation=a.append_to_translation
    )
