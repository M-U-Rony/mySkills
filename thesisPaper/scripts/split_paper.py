"""Plan and split an extracted research paper into Main Paper sections + Background Appendix digest.

Usage:
  python split_paper.py "<workdir>" [--max-pages-per-section 4] [--max-appendix-pages 0] [--replan]

What it does:
- Identifies Main Paper sections (Abstract, Introduction, Related Work, Methodology, Experiments, Limitations, Conclusion).
- Excludes References/Bibliography pages from translation (saved in <workdir>/references.md).
- Background Appendix Mining:
  - Saves full Appendix text & tables into <workdir>/appendix_digest.md so the Thesis Gap Analysis can mine ablations and limitations without dumping 18+ pages of Appendix into the study PDF.
  - Defaults to --max-appendix-pages 0 so the study PDF stays minimal.
- Initializes a clean, bracket-free academic glossary in <workdir>/glossary.txt.
"""
import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

PAPER_GLOSSARY = """# Academic Paper Glossary (English = বাংলা). One line per term.
# Clean Bangla terms without repetitive parenthetical English clutter.

Ablation Study = অ্যাবলেশন স্টাডি
Activation Function = অ্যাক্টিভেশন ফাংশন
Adapter = অ্যাডাপ্টার
Adversarial Attack = অ্যাডভার্সারিয়াল অ্যাটাক
Alignment = অ্যালাইনমেন্ট
Attention Mechanism = অ্যাটেনশন মেকানিজম
Autoregressive = অটোরিগ্রেসিভ
Backbone = ব্যাকবোন
Backpropagation = ব্যাকপ্রোপাগেশন
Baseline = বেসলাইন
Batch Size = ব্যাচ সাইজ
Benchmark = বেঞ্চমার্ক
Bottleneck = বটলনেক
Chain-of-Thought = চেইন-অফ-থট (CoT)
Checkpoint = চেকপয়েন্ট
Classification = ক্লাসিফিকেশন
Context Length = কনটেক্সট লেন্থ
Context Window = কনটেক্সট উইন্ডো
Contrastive Learning = কন্ট্রাস্টিভ লার্নিং
Convergence = কনভার্জেন্স
Cross-Entropy = ক্রস-এনট্রপি
Cross-Lingual = ক্রস-লিঙ্গুয়াল
Data Augmentation = ডেটা অগমেন্টেশন
Dataset = ডেটাসেট
Decoder = ডিকোডার
Deep Learning = ডিপ লার্নিং
Diffusion Model = ডিফিউশন মডেল
Distillation = ডিস্টিলেশন
Domain Adaptation = ডোমেইন অ্যাডাপ্টেশন
Downstream Task = ডাউনস্ট্রিম টাস্ক
Dropout = ড্রপআউট
Embedding = এম্বেডিং
Empirical = এম্পিরিক্যাল
Encoder = এনকোডার
End-to-End = এন্ড-টু-এন্ড
Evaluation Metric = ইভ্যালুয়েশন মেট্রিক
Feature Extraction = ফিচার এক্সট্রাকশন
Few-shot = ফিউ-শট
Fine-tuning = ফাইন-টিউনিং
Foundation Model = ফাউন্ডেশন মডেল
Generalization = জেনারালাইজেশন
Generative Model = জেনারেটিভ মডেল
Gradient Descent = গ্রেডিয়েন্ট ডিসেন্ট
Ground Truth = গ্রাউন্ড ট্রুথ
Hallucination = হ্যালুসিনেশন
Heuristic = হিউরিস্টিক
Hidden State = হিডেন স্টেট
Hyperparameter = হাইপারপ্যারামিটার
In-Context Learning = ইন-কনটেক্সট লার্নিং
Inference = ইনফারেন্স
Instruction Tuning = ইনস্ট্রাকশন টিউনিং
Interpretability = ইন্টারপ্রেটেবিলিটি
Knowledge Graph = নলেজ গ্রাফ
Large Language Model = লার্জ ল্যাঙ্গুয়েজ মডেল (LLM)
Latency = ল্যাটেন্সি
Latent Space = লেটেন্ট স্পেস
Layer Normalization = লেয়ার নরমালাইজেশন
Learning Rate = লার্নিং রেট
Loss Function = লস ফাংশন
Low-Resource = লো-রিসোর্স
Machine Learning = মেশিন লার্নিং
Mixture of Experts = মিক্সচার অফ এক্সপার্টস (MoE)
Modality = মোডালিটি
Multi-Head Attention = মাল্টি-হেড অ্যাটেনশন
Multimodal = মাল্টিমোডাল
Neural Network = নিউরাল নেটওয়ার্ক
Objective Function = অবজেক্টিভ ফাংশন
Optimization = অপটিমাইজেশন
Out-of-Distribution = আউট-অফ-ডিস্ট্রিবিউশন (OOD)
Overfitting = ওভারফিটিং
Perplexity = পারপ্লেক্সিটি
Pre-training = প্রি-ট্রেনিং
Pruning = প্রুনিং
Quantization = কোয়ান্টাইজেশন
Regularization = রেগুলারাইজেশন
Reinforcement Learning = রিইনফোর্সমেন্ট লার্নিং
Representation = রিপ্রেজেন্টেশন
Residual Connection = রেসিডিউয়াল কানেকশন
Retrieval-Augmented Generation = রিট্রিভাল-অগমেন্টেড জেনারেশন (RAG)
Robustness = রোবাস্টনেস
Scalability = স্কেলেবিলিটি
Self-Attention = সেলফ-অ্যাটেনশন
Self-Supervised = সেলফ-সুপারভাইজড
Softmax = সফটম্যাক্স
Sparsity = স্পার্সিটি
State-of-the-Art = স্টেট-অফ-দ্য-আর্ট (SOTA)
Supervised Learning = সুপারভাইজড লার্নিং
Throughput = থ্রুপুট
Tokenization = টোকেনাইজেশন
Trade-off = ট্রেড-অফ
Transformer = ট্রান্সফরমার
Unsupervised Learning = আনসুপারভাইজড লার্নিং
Validation Set = ভ্যালিডেশন সেট
Zero-shot = জিরো-শট
"""

REFERENCES_RE = re.compile(
    r"^\s*(?:[0-9IVX]+\.?\s+)?(?:references|bibliography|works\s+cited)\b",
    re.I,
)

APPENDIX_RE = re.compile(
    r"^\s*(?:appendix|appendices|supplementary(?:\s+material)?)\b",
    re.I,
)

HIGH_VALUE_APPENDIX_RE = re.compile(
    r"ablation|hyperparameter|implementation|limitation|failure|error\s+analysis|complexity|compute|setup|architecture|proof",
    re.I,
)


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return cleaned[:32] or "section"


def plan_paper_structure(workdir: pathlib.Path, max_pages: int = 4, max_appendix_pages: int = 0) -> tuple[list[dict], list[dict]]:
    toc_path = workdir / "toc.json"
    if not toc_path.exists():
        raise FileNotFoundError(f"Missing toc.json in {workdir}. Run extract_paper.py first.")
    meta = json.loads(toc_path.read_text(encoding="utf-8"))
    total_pages = meta.get("total_pages", 1)
    ref_start = meta.get("references_start_page")
    app_start = meta.get("appendix_start_page")
    pages_dir = workdir / "pages"

    # Determine main body end page
    main_end = total_pages
    if ref_start and ref_start <= total_pages:
        main_end = min(main_end, ref_start - 1)
    if app_start and app_start <= total_pages:
        main_end = min(main_end, app_start - 1)
    main_end = max(1, main_end)

    # Save full Appendix digest for background gap analysis (never dumped into minimal PDF)
    appendix_pages = []
    if app_start and app_start <= total_pages:
        for p in range(app_start, total_pages + 1):
            pf = pages_dir / f"page_{p:04d}.md"
            if pf.exists():
                txt = pf.read_text(encoding="utf-8").strip()
                if txt:
                    appendix_pages.append((p, txt))
    elif ref_start and ref_start < total_pages:
        for p in range(ref_start + 1, total_pages + 1):
            pf = pages_dir / f"page_{p:04d}.md"
            if pf.exists():
                txt = pf.read_text(encoding="utf-8").strip()
                if app_start or APPENDIX_RE.search(txt[:400]) or HIGH_VALUE_APPENDIX_RE.search(txt[:400]):
                    if not app_start:
                        app_start = p
                    appendix_pages.append((p, txt))

    if appendix_pages:
        digest_lines = [f"# Appendix Digest (Pages {appendix_pages[0][0]}–{appendix_pages[-1][0]})"]
        for p_num, p_txt in appendix_pages:
            digest_lines.append(f"\n## [Appendix Page {p_num}]\n{p_txt}")
        (workdir / "appendix_digest.md").write_text("\n".join(digest_lines), encoding="utf-8")
        print(f"[+] Extracted Appendix Digest ({len(appendix_pages)} page(s)) -> {workdir / 'appendix_digest.md'}")

    # Build chapters for Main Paper
    raw_toc = [e for e in meta.get("toc", []) if 1 <= e.get("page", 0) <= main_end and e.get("title")]
    raw_toc = [
        e for e in raw_toc
        if not REFERENCES_RE.search(e["title"])
        and not APPENDIX_RE.search(e["title"])
        and not re.match(r"^arxiv:", e["title"], re.I)
        and not re.match(r"^acknowledg", e["title"], re.I)
    ]

    chapters = []
    if len(raw_toc) >= 2:
        dedup = []
        for e in sorted(raw_toc, key=lambda x: x["page"]):
            if dedup and dedup[-1]["page"] == e["page"]:
                continue
            dedup.append(e)

        if dedup[0]["page"] > 1:
            dedup.insert(0, {"level": 1, "title": "Abstract & Introduction", "page": 1})

        for i, entry in enumerate(dedup):
            start_p = entry["page"]
            end_p = (dedup[i + 1]["page"] - 1) if (i + 1 < len(dedup)) else main_end
            end_p = max(start_p, end_p)
            chapters.append({
                "id": len(chapters) + 1,
                "chapter_num": str(len(chapters) + 1),
                "title": entry["title"],
                "part_type": "main_paper",
                "start": start_p,
                "end": end_p,
            })
    else:
        curr = 1
        idx = 1
        while curr <= main_end:
            end_p = min(curr + max_pages - 1, main_end)
            title = "মূল গবেষণাপত্র (Main Paper - Abstract & Method)" if idx == 1 else f"মূল গবেষণাপত্র — অংশ {idx} (Pages {curr}-{end_p})"
            chapters.append({
                "id": idx,
                "chapter_num": str(idx),
                "title": title,
                "part_type": "main_paper",
                "start": curr,
                "end": end_p,
            })
            curr = end_p + 1
            idx += 1

    # Optional Appendix inclusion ONLY if --max-appendix-pages > 0 explicitly passed
    if appendix_pages and max_appendix_pages > 0:
        first_p = appendix_pages[0][0]
        last_p = min(first_p + max_appendix_pages - 1, appendix_pages[-1][0])
        chapters.append({
            "id": len(chapters) + 1,
            "chapter_num": str(len(chapters) + 1),
            "title": f"পরিশিষ্ট ও অতিরিক্ত পরীক্ষা (Selected Appendix, Pages {first_p}-{last_p})",
            "part_type": "appendix",
            "start": first_p,
            "end": last_p,
        })

    all_sections = []
    global_sec_id = 1
    for ch in chapters:
        ch_sections = []
        curr, part = ch["start"], 1
        while curr <= ch["end"]:
            sub_end = min(curr + max_pages - 1, ch["end"])
            sec_title = ch["title"] if part == 1 else f"{ch['title']} (Part {part})"
            sec_obj = {
                "id": global_sec_id,
                "chapter_id": ch["id"],
                "chapter_num": ch["chapter_num"],
                "chapter_title": ch["title"],
                "part_type": ch.get("part_type", "main_paper"),
                "is_front_matter": False,
                "title": sec_title,
                "start": curr,
                "end": sub_end,
                "continuation": part > 1,
                "translate": True,
                "filename": f"ch{ch['id']:02d}_{part:02d}_{slugify(sec_title)}.md",
            }
            ch_sections.append(sec_obj)
            all_sections.append(sec_obj)
            curr, part, global_sec_id = sub_end + 1, part + 1, global_sec_id + 1
        ch["sections"] = ch_sections

    return chapters, all_sections


def split_paper(workdir_path: str, max_pages: int = 4, max_appendix_pages: int = 0, replan: bool = False):
    workdir = pathlib.Path(workdir_path).resolve()
    pages_dir = workdir / "pages"
    source_dir = workdir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    chapters_file = workdir / "chapters.json"
    sections_file = workdir / "sections.json"

    if chapters_file.exists() and sections_file.exists() and not replan:
        print(f"[*] Reusing existing paper plan: {chapters_file} (pass --replan to rebuild)")
        chapters = json.loads(chapters_file.read_text(encoding="utf-8"))
        sections = json.loads(sections_file.read_text(encoding="utf-8"))
    else:
        chapters, sections = plan_paper_structure(workdir, max_pages=max_pages, max_appendix_pages=max_appendix_pages)
        chapters_file.write_text(json.dumps(chapters, indent=2, ensure_ascii=False), encoding="utf-8")
        sections_file.write_text(json.dumps(sections, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[+] Paper Structure Planned: {len(chapters)} part(s) across {len(sections)} section(s).")

    from thesis_common import seed_glossary
    seed_glossary(workdir, PAPER_GLOSSARY)

    expected = {s["filename"] for s in sections if s.get("part_type") != "thesis_lab"}
    for stale in source_dir.glob("*.md"):
        if stale.name not in expected:
            stale.unlink()
            print(f"[*] Removed stale source section: {stale.name}")

    for s in sections:
        if s.get("part_type") == "thesis_lab":
            continue
        parts = []
        for p in range(s["start"], s["end"] + 1):
            pf = pages_dir / f"page_{p:04d}.md"
            if pf.exists():
                t = pf.read_text(encoding="utf-8").strip()
                if t:
                    parts.append(t)
        body = "\n\n".join(parts)
        (source_dir / s["filename"]).write_text(body, encoding="utf-8")

    print(f"[✓] Source sections ready in {source_dir}:")
    for ch in chapters:
        print(f"    • Part {ch['id']} [{ch.get('part_type', 'main_paper')}]: {ch['title']} (Pages {ch['start']}-{ch['end']})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Split extracted research paper into main paper sections + Appendix digest.")
    ap.add_argument("workdir", help="Path to paper workdir")
    ap.add_argument("--max-pages-per-section", type=int, default=4, help="Max pages per section (default: 4)")
    ap.add_argument("--max-appendix-pages", type=int, default=0, help="Max appendix pages to translate (default: 0 for minimal PDF)")
    ap.add_argument("--replan", action="store_true", help="Rebuild plan even if it exists")
    args = ap.parse_args()
    split_paper(args.workdir, args.max_pages_per_section, args.max_appendix_pages, args.replan)
