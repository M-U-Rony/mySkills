"""Plan and split extracted pages into Chapter-by-Chapter sources for full books.

Usage:
  python split_sections.py "<workdir>" [--max-pages-per-section 6] [--replan]

Reads <workdir>/toc.json and <workdir>/pages/, generates:
- <workdir>/chapters.json (hierarchical chapter manifest for full-book translation)
- <workdir>/sections.json (flat manifest of all sections with chapter_id)
- <workdir>/source/ch01_001_<slug>.md ...
- <workdir>/glossary.txt (consistent technical terminology dictionary)

Supports full multi-chapter books (100-800+ pages) as well as single papers/articles.
Sections titled References, Bibliography, Index, Acknowledgements, and Endnotes
are automatically excluded entirely from translation and the final output PDF.
"""
import argparse
import json
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

COMMON_GLOSSARY = """# Glossary (English = বাংলা). One line per term.
# Only terms that appear in a chunk are sent to the model, so adding terms is cheap.
# Add document-specific terms below before running translate_sections.py.

# --- Programming / software (code itself is NEVER translated; these are for prose) ---
API = এপিআই (API)
Argument = আর্গুমেন্ট (Argument)
Array = অ্যারে (Array)
Asynchronous = অ্যাসিঙ্ক্রোনাস (Asynchronous)
Bug = বাগ (Bug)
Callback = কলব্যাক (Callback)
Class = ক্লাস (Class)
Command line = কমান্ড লাইন (Command line)
Compiler = কম্পাইলার (Compiler)
Database = ডেটাবেস (Database)
Debugging = ডিবাগিং (Debugging)
Dependency = ডিপেন্ডেন্সি (Dependency)
Deployment = ডিপ্লয়মেন্ট (Deployment)
Exception = এক্সেপশন (Exception)
Framework = ফ্রেমওয়ার্ক (Framework)
Function = ফাংশন (Function)
Interface = ইন্টারফেস (Interface)
Library = লাইব্রেরি (Library)
Loop = লুপ (Loop)
Method = মেথড (Method)
Module = মডিউল (Module)
Object = অবজেক্ট (Object)
Package = প্যাকেজ (Package)
Parameter = প্যারামিটার (Parameter)
Query = কোয়েরি (Query)
Repository = রিপোজিটরি (Repository)
Request = রিকোয়েস্ট (Request)
Response = রেসপন্স (Response)
Runtime = রানটাইম (Runtime)
Server = সার্ভার (Server)
String = স্ট্রিং (String)
Thread = থ্রেড (Thread)
Type = টাইপ (Type)
Variable = ভেরিয়েবল (Variable)

# --- Machine learning / AI ---
Attention Mechanism = অ্যাটেনশন মেকানিজম (Attention Mechanism)
Backpropagation = ব্যাকপ্রোপাগেশন (Backpropagation)
Convolutional Neural Network = কনভোল্যুশনাল নিউরাল নেটওয়ার্ক (CNN)
Deep Learning = ডিপ লার্নিং (Deep Learning)
Downsampling = ডাউনস্যাম্পলিং (Downsampling)
Embedding = এম্বেডিং (Embedding)
Feed-forward Network = ফিড-ফরোয়ার্ড নেটওয়ার্ক (Feed-forward Network)
Fine-tuning = ফাইন-টিউনিং (Fine-tuning)
Gradient Descent = গ্রেডিয়েন্ট ডিসেন্ট (Gradient Descent)
Hyperparameter = হাইপারপ্যারামিটার (Hyperparameter)
Inference = ইনফারেন্স (Inference)
Large Language Model = লার্জ ল্যাঙ্গুয়েজ মডেল (LLM)
Latent Space = লেটেন্ট স্পেস (Latent Space)
Layer Normalization = লেয়ার নরমালাইজেশন (Layer Normalization)
Loss Function = লস ফাংশন (Loss Function)
Machine Learning = মেশিন লার্নিং (Machine Learning)
Multi-Head Attention = মাল্টি-হেড অ্যাটেনশন (Multi-Head Attention)
Natural Language Processing = ন্যাচারাল ল্যাঙ্গুয়েজ প্রসেসিং (NLP)
Neural Network = নিউরাল নেটওয়ার্ক (Neural Network)
Optimization = অপটিমাইজেশন (Optimization)
Overfitting = ওভারফিটিং (Overfitting)
Pre-training = প্রি-ট্রেনিং (Pre-training)
Recurrent Neural Network = রিকারেন্ট নিউরাল নেটওয়ার্ক (RNN)
Reinforcement Learning = রিইনফোর্সমেন্ট লার্নিং (Reinforcement Learning)
Residual Connection = রেসিডিউয়াল কানেকশন (Residual Connection)
Self-Attention = সেলফ-অ্যাটেনশন (Self-Attention)
Sequence-to-Sequence = সিকোয়েন্স-টু-সিকোয়েন্স (Seq2Seq)
Supervised Learning = সুপারভাইজড লার্নিং (Supervised Learning)
Tokenization = টোকেনাইজেশন (Tokenization)
Transformer = ট্রান্সফরমার (Transformer)
Underfitting = আন্ডারফিটিং (Underfitting)
Unsupervised Learning = আনসুপারভাইজড লার্নিং (Unsupervised Learning)
Weights and Biases = ওয়েটস ও বায়াসেস (Weights and Biases)
Zero-shot = জিরো-শট (Zero-shot)
"""

EXCLUDE_RE = re.compile(
    r"^\s*(?:(?:part|chapter|section)\s+[0-9IVXLCDM\w]+[.:\s\-–]+)?"
    r"(?:"
    r"appendix(?:es)?(?:\s+[a-z0-9]+)?\b.*|appendices\b.*|"
    r"(?:subject\s+|author\s+|name\s+|general\s+|cumulative\s+)?index(?:es)?\s*(?:\(.*\))?$|indices\s*(?:\(.*\))?$|"
    r"references\b.*|bibliography\b.*|works\s+cited\b.*|"
    r"acknowledg(?:e)?ments?\b.*|endnotes?\b.*|further\s+reading\b.*|notes\s*(?:\(.*\))?$|"
    r"front\s*matter\b.*|preface\b.*|foreword\b.*|cover\b.*|contents?\s*(?:\(.*\))?$|table\s+of\s+contents\b.*"
    r")",
    re.I,
)

CHAPTER_RE = re.compile(
    r"\b(?:Chapter|CHAPTER|অধ্যায়|Part|PART|Unit|UNIT)\s+[0-9IVXLCDM]+",
    re.I,
)

FRONT_MATTER_RE = re.compile(
    r"^\s*(?:front\s*matter|preface|foreword|cover|title\s*page|copyright|contents?|table\s*of\s*contents)\b",
    re.I,
)


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return cleaned[:30] or "section"


def detect_chapters(raw_toc: list[dict], total_pages: int) -> list[dict]:
    """Identify top-level chapters from the TOC outline or text (excluding front matter, index, appendix)."""
    valid = [e for e in raw_toc if 1 <= e.get("page", 0) <= total_pages and e.get("title")]

    chapter_candidates = []

    # Case 1: Look for explicit 'Chapter' or 'Part' keywords in TOC entries
    explicit_chapters = [e for e in valid if CHAPTER_RE.search(e["title"]) and not EXCLUDE_RE.search(e["title"])]
    if len(explicit_chapters) >= 2:
        # Include any top-level exclusions (like Appendix, Index) so chapter end pages stop before them
        tail_exclusions = [e for e in valid if EXCLUDE_RE.search(e["title"]) and e.get("level", 1) <= 2]
        chapter_candidates = explicit_chapters + tail_exclusions
    elif valid:
        # Case 2: Level 1 entries (if reasonable in number), excluding front matter, index, appendix
        non_excluded = [e for e in valid if not EXCLUDE_RE.search(e["title"])]
        tail_exclusions = [e for e in valid if EXCLUDE_RE.search(e["title"]) and e.get("level", 1) <= 2]
        lvl1 = [e for e in non_excluded if e.get("level", 1) == 1]
        if 2 <= len(lvl1) <= 60:
            chapter_candidates = lvl1 + tail_exclusions
        else:
            lvl2 = [e for e in non_excluded if e.get("level", 1) <= 2]
            if 2 <= len(lvl2) <= 60:
                chapter_candidates = lvl2 + tail_exclusions
            else:
                chapter_candidates = non_excluded[:50] + tail_exclusions

    # Sort candidates strictly by page number
    chapter_candidates.sort(key=lambda x: (x.get("page", 0), x.get("level", 1)))

    # Deduplicate entries sharing the same page (keep earliest/highest level)
    deduped = []
    for e in chapter_candidates:
        if deduped and deduped[-1]["page"] == e["page"]:
            continue
        deduped.append(e)

    raw_chapters = []
    if deduped:
        for i, entry in enumerate(deduped):
            start_p = entry["page"]
            if i + 1 < len(deduped):
                next_p = deduped[i + 1]["page"]
                end_p = max(start_p, next_p - 1)
            else:
                end_p = max(start_p, total_pages)
            raw_chapters.append({
                "title": entry["title"],
                "start": start_p,
                "end": end_p,
            })
    else:
        # Fallback if no outline: split book into 20-page chapters
        curr = 1
        ch_idx = 1
        step = 20 if total_pages > 40 else total_pages
        while curr <= total_pages:
            end_p = min(curr + step - 1, total_pages)
            title = f"Chapter {ch_idx}" if total_pages > 30 else f"Section {ch_idx}"
            raw_chapters.append({
                "title": f"{title} (Pages {curr}-{end_p})",
                "start": curr,
                "end": end_p,
            })
            curr = end_p + 1
            ch_idx += 1

    # Filter out non-chapters (references, acknowledgements, bibliography, index, appendix, front matter)
    chapters = []
    body_ch_num = 1
    for entry in raw_chapters:
        if EXCLUDE_RE.search(entry["title"]):
            print(f"[-] Excluding non-chapter '{entry['title']}' (Pages {entry['start']}-{entry['end']}) from book plan.")
            continue
        entry["id"] = len(chapters) + 1
        entry["is_front_matter"] = False
        m = re.search(r"\b(?:Chapter|CHAPTER|অধ্যায়)\s+([0-9IVXLCDM]+)", entry["title"], re.I)
        if m:
            entry["chapter_num"] = m.group(1)
        else:
            entry["chapter_num"] = str(body_ch_num)
        body_ch_num += 1
        chapters.append(entry)

    return chapters


def plan_book_structure(workdir: pathlib.Path, max_pages: int = 6) -> tuple[list[dict], list[dict]]:
    toc_path = workdir / "toc.json"
    if not toc_path.exists():
        raise FileNotFoundError(f"Missing toc.json in {workdir}. Run extract_doc.py first.")
    meta = json.loads(toc_path.read_text(encoding="utf-8"))
    total_pages = meta.get("total_pages", 0)
    raw_toc = meta.get("toc", [])

    chapters = detect_chapters(raw_toc, total_pages)

    # Sub-chunk each chapter into sections of max_pages
    all_sections = []
    global_sec_id = 1

    for ch in chapters:
        ch_sections = []
        c_start, c_end = ch["start"], ch["end"]
        curr, part = c_start, 1

        while curr <= c_end:
            sub_end = min(curr + max_pages - 1, c_end)
            sec_title = ch["title"] if part == 1 else f"{ch['title']} (Part {part})"
            sec_obj = {
                "id": global_sec_id,
                "chapter_id": ch["id"],
                "chapter_num": ch.get("chapter_num"),
                "chapter_title": ch["title"],
                "is_front_matter": ch.get("is_front_matter", False),
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


def split_sections(workdir_path: str, max_pages: int = 6, replan: bool = False):
    workdir = pathlib.Path(workdir_path).resolve()
    pages_dir = workdir / "pages"
    source_dir = workdir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    chapters_file = workdir / "chapters.json"
    sections_file = workdir / "sections.json"

    if chapters_file.exists() and sections_file.exists() and not replan:
        print(f"[*] Reusing existing chapter plan: {chapters_file} (pass --replan to rebuild)")
        chapters = json.loads(chapters_file.read_text(encoding="utf-8"))
        sections = json.loads(sections_file.read_text(encoding="utf-8"))
    else:
        chapters, sections = plan_book_structure(workdir, max_pages=max_pages)
        chapters_file.write_text(json.dumps(chapters, indent=2, ensure_ascii=False), encoding="utf-8")
        sections_file.write_text(json.dumps(sections, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[+] Book Structure: Planned {len(chapters)} chapter(s) across {len(sections)} section(s).")

    glossary_file = workdir / "glossary.txt"
    if not glossary_file.exists():
        glossary_file.write_text(COMMON_GLOSSARY, encoding="utf-8")
        print(f"[+] Initialized glossary: {glossary_file}")

    for s in sections:
        parts = []
        for p in range(s["start"], s["end"] + 1):
            page_file = pages_dir / f"page_{p:04d}.md"
            if page_file.exists():
                text = page_file.read_text(encoding="utf-8").strip()
                if text:
                    parts.append(text)
        body = "\n\n".join(parts)
        head = re.sub(r"\W+", " ", body[:400]).lower()
        title_norm = re.sub(r"\W+", " ", s["title"]).lower().strip()
        # In multi-chapter book mode, compile_pdf renders an official chapter banner.
        # Only inject Markdown # Title if it's a single-article document or a sub-section with distinct heading.
        if len(chapters) <= 1 and not s.get("continuation") and title_norm and title_norm not in head:
            body = f"# {s['title']}\n\n{body}"
        (source_dir / s["filename"]).write_text(body, encoding="utf-8")

    print(f"\n[✓] Generated source files for {len(chapters)} chapters in: {source_dir}")
    for ch in chapters:
        print(f"    • Chapter {ch['id']}: {ch['title']} (Pages {ch['start']}-{ch['end']}, {len(ch['sections'])} sections)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split document into Chapter-by-Chapter sources for full books.")
    parser.add_argument("workdir", help="Path to document workdir")
    parser.add_argument("--max-pages-per-section", type=int, default=6, help="Maximum pages per section")
    parser.add_argument("--replan", action="store_true", help="Rebuild plan even if it exists")
    args = parser.parse_args()
    split_sections(args.workdir, args.max_pages_per_section, args.replan)
