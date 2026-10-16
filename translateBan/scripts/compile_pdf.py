"""Compile translated Bengali Markdown sections and figures into a publication-grade PDF.

Usage:
  python compile_pdf.py "<workdir>" [--section N] [--output "<custom_pdf_path>"]

--section N : compiles only section N -> <output_base>\\<title>_PartN_Bangla.pdf
(no flag)   : compiles all sections   -> <output_base>\\<title>_Bangla.pdf

<output_base> is $TRANSLATEBAN_OUT, else E:\\audiobook if it exists, else the workdir's parent.

Sections that are not translated yet appear as a visible notice (never silently dropped,
never replaced with English). Code blocks are rendered verbatim in a monospace font with
line wrapping so long lines are not cut off in print.

Requires Microsoft Edge (installed by default on Windows) for rendering.
"""
import argparse
import html
import json
import os
import pathlib
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")


def find_edge_path() -> str:
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")):
        if pathlib.Path(c).exists():
            return c
    raise FileNotFoundError("Microsoft Edge executable not found for PDF rendering.")


def output_base(workdir: pathlib.Path) -> pathlib.Path:
    """Output dir: $TRANSLATEBAN_OUT, else E:/audiobook if present, else the workdir's parent."""
    env = os.environ.get("TRANSLATEBAN_OUT")
    if env:
        return pathlib.Path(env).expanduser()
    audiobook = pathlib.Path("E:/audiobook")
    return audiobook if audiobook.exists() else workdir.parent


# ----------------------------------------------------------------------------------------
# Markdown -> HTML
# ----------------------------------------------------------------------------------------

def inline(text: str) -> str:
    """Inline Markdown -> HTML. Code and math are protected before anything else touches them."""
    tokens = []

    def protect(s: str) -> str:
        tokens.append(s)
        return f"\x00{len(tokens) - 1}\x00"

    text = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", lambda m: protect(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = re.sub(r"\$\$(.+?)\$\$", lambda m: protect(f"\\[{html.escape(m.group(1))}\\]"), text)
    # Pandoc rule for inline math: no space after opening $, none before closing $, no digit after it
    text = re.sub(r"(?<![\\$\w])\$(?=\S)([^$\n]*?\S)\$(?![\d$])", lambda m: protect(f"\\({html.escape(m.group(1))}\\)"), text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\*\w])\*(?![\s\*])(.+?)(?<![\s\*])\*(?![\*\w])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m.group(1))], text)


def markdown_to_html(md_text: str, base_dir: pathlib.Path) -> str:
    lines = md_text.split("\n")
    out, para, list_items = [], [], []
    list_type = None
    i = 0

    def flush_para():
        nonlocal para
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para = []

    def flush_list():
        nonlocal list_items, list_type
        if list_items:
            start = ""
            if list_type == "ol" and list_items[0][0] != "1":
                start = f" start='{list_items[0][0]}'"
            out.append(f"<{list_type}{start}>" + "".join(f"<li>{inline(t)}</li>" for _, t in list_items) + f"</{list_type}>")
        list_items, list_type = [], None

    def flush_all():
        flush_para()
        flush_list()

    while i < len(lines):
        line = lines[i]
        s = line.strip()

        fence = re.match(r"^(`{3,}|~{3,})\s*([\w+#.-]*)", s)
        if fence:
            flush_all()
            marker, lang = fence.group(1), fence.group(2)
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                code_lines.append(lines[i])
                i += 1
            i += 1
            lang_attr = f" data-lang='{html.escape(lang)}'" if lang else ""
            label = f"<div class='code-lang'>{html.escape(lang)}</div>" if lang else ""
            out.append(f"<div class='code-block'{lang_attr}>{label}<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre></div>")
            continue

        if s.startswith("|") and s.endswith("|"):
            flush_all()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                rows.append(lines[i].strip())
                i += 1
            html_rows, header_done = [], False
            for r in rows:
                cols = [c.strip() for c in re.split(r"(?<!\\)\|", r)[1:-1]]
                if cols and all(re.fullmatch(r":?-{2,}:?", c) for c in cols if c):
                    continue
                tag = "td" if header_done else "th"
                header_done = True
                cells = "".join(f"<{tag}>{inline(c.replace(chr(92) + '|', '|').replace('<br>', ' '))}</{tag}>" for c in cols)
                html_rows.append(f"<tr>{cells}</tr>")
            out.append("<div class='table-container'><table>" + "".join(html_rows) + "</table></div>")
            continue

        i += 1
        if not s:
            flush_all()
            continue
        if s.startswith("<!--") and s.endswith("-->"):
            continue

        img = re.fullmatch(r"!\[(.*?)\]\((.*?)\)", s)
        if img:
            flush_all()
            caption, rel = img.groups()
            f = (base_dir / rel).resolve()
            src = f.as_uri() if f.exists() else rel
            cap = f"<figcaption>{inline(caption)}</figcaption>" if caption.strip() and caption.strip() != "চিত্র" else ""
            out.append(f"<figure class='doc-figure'><img src='{src}' alt='{html.escape(caption)}' />{cap}</figure>")
            continue

        h = re.match(r"^(#{1,6})\s+(.*)$", s)
        if h:
            flush_all()
            lvl = min(len(h.group(1)), 4)
            out.append(f"<h{lvl}>{inline(h.group(2).strip().rstrip('#').strip())}</h{lvl}>")
            continue

        if s.startswith(">"):
            flush_all()
            out.append(f"<blockquote>{inline(s.lstrip('>').strip())}</blockquote>")
            continue

        b = re.match(r"^[-*•]\s+(.*)$", s)
        n = re.match(r"^(\d+)[.)]\s+(.*)$", s)
        if b or n:
            flush_para()
            kind = "ul" if b else "ol"
            if list_type and list_type != kind:
                flush_list()
            list_type = kind
            list_items.append(("", b.group(1)) if b else (n.group(1), n.group(2)))
            continue

        if list_items and line.startswith((" ", "\t")):
            num, txt = list_items[-1]
            list_items[-1] = (num, f"{txt} {s}")
            continue

        flush_list()
        para.append(s)

    flush_all()
    return "\n".join(out)


# ----------------------------------------------------------------------------------------
# Compilation
# ----------------------------------------------------------------------------------------

CSS = """
  @page { size: A4; margin: 20mm 17mm 22mm 17mm; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: 'Noto Serif Bengali', 'Kalpurush', 'SolaimanLipi', 'Vrinda', 'Nirmala UI', serif;
         font-size: 11.5pt; line-height: 1.85; color: #1e293b; margin: 0; }
  h1, h2, h3, h4 { font-family: 'Hind Siliguri', 'Nirmala UI', sans-serif; color: #0f172a; line-height: 1.35; break-after: avoid; }
  h1 { font-size: 21pt; border-bottom: 2px solid #2563eb; padding-bottom: 6px; margin: 14px 0 18px; }
  h2 { font-size: 15.5pt; color: #1e3a8a; margin: 22px 0 12px; }
  h3, h4 { font-size: 13pt; color: #334155; margin: 18px 0 8px; }
  p { margin: 0 0 12px; text-align: justify; }
  a { color: #1d4ed8; text-decoration: none; }
  ul, ol { margin: 0 0 12px; padding-left: 24px; }
  li { margin-bottom: 4px; }
  blockquote { border-left: 4px solid #3b82f6; margin: 16px 0; padding: 8px 16px; background: #f8fafc; color: #475569; }
  code { font-family: 'Fira Code', 'Cascadia Code', 'Consolas', monospace; font-size: 0.86em;
         background: #f1f5f9; color: #9f1239; padding: 1px 4px; border-radius: 4px; direction: ltr; unicode-bidi: embed; }
  .code-block { margin: 14px 0 18px; border: 1px solid #d0d7de; border-radius: 6px; background: #f6f8fa; break-inside: auto; }
  .code-lang { font-family: 'Fira Code', 'Consolas', monospace; font-size: 8pt; color: #57606a;
               padding: 3px 10px; border-bottom: 1px solid #d0d7de; background: #eef1f4; border-radius: 6px 6px 0 0; }
  .code-block pre { margin: 0; padding: 10px 12px; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
                    line-height: 1.45; text-align: left; }
  .code-block pre code { background: transparent; color: #1f2328; padding: 0; font-size: 8.8pt; }
  .doc-figure { margin: 20px auto; text-align: center; break-inside: avoid; }
  .doc-figure img { max-width: 92%; max-height: 210mm; height: auto; border: 1px solid #e2e8f0; border-radius: 4px; }
  .doc-figure figcaption { margin-top: 8px; font-size: 9.5pt; font-family: 'Hind Siliguri', sans-serif; color: #64748b; }
  .table-container { margin: 16px 0; break-inside: avoid; }
  table { width: 100%; border-collapse: collapse; font-size: 9.5pt; }
  th, td { border: 1px solid #cbd5e1; padding: 6px 10px; text-align: left; vertical-align: top; }
  th { background: #f1f5f9; font-family: 'Hind Siliguri', sans-serif; }
  .missing { border: 2px dashed #dc2626; background: #fef2f2; color: #991b1b; padding: 14px 18px; margin: 18px 0; border-radius: 6px; }
  .page-break { break-after: page; }
  .book-cover { text-align: center; padding: 80px 20px 40px; break-after: page; }
  .book-badge { display: inline-block; font-family: 'Hind Siliguri', sans-serif; font-size: 11pt; color: #2563eb; background: #eff6ff; padding: 4px 14px; border-radius: 20px; font-weight: 600; margin-bottom: 20px; }
  .book-main-title { font-size: 28pt; line-height: 1.3; color: #0f172a; border-bottom: none; margin: 0 0 15px; }
  .book-toc { padding: 30px 10px 10px; break-after: page; }
  .toc-header { font-size: 22pt; color: #0f172a; border-bottom: 2px solid #2563eb; padding-bottom: 6px; margin-bottom: 24px; }
  .toc-list { list-style: none; padding: 0; margin: 0; }
  .toc-item { font-family: 'Hind Siliguri', sans-serif; font-size: 12.5pt; margin-bottom: 12px; border-bottom: 1px dotted #cbd5e1; padding-bottom: 4px; display: flex; justify-content: space-between; }
  .toc-ch-num { font-weight: 700; color: #2563eb; margin-right: 12px; min-width: 80px; }
  .toc-ch-title { color: #1e293b; flex-grow: 1; }
  .chapter-divider { margin: 10px 0 24px; padding-bottom: 12px; border-bottom: 2px solid #cbd5e1; break-after: avoid; }
  .chapter-kicker { font-family: 'Hind Siliguri', sans-serif; font-size: 11pt; font-weight: 700; color: #2563eb; text-transform: uppercase; letter-spacing: 1px; }
  .chapter-title-text { font-size: 22pt; color: #0f172a; margin: 6px 0 0; line-height: 1.3; }
"""


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    return name[:120] or "document"


def to_bangla_digits(num) -> str:
    b_map = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
    return str(num).translate(b_map)


def compile_pdf(workdir_path: str, section_num: int = None, custom_output: str = None) -> pathlib.Path:
    workdir = pathlib.Path(workdir_path).resolve()
    bangla_dir = workdir / "bangla"
    meta = {}
    if (workdir / "toc.json").exists():
        meta = json.loads((workdir / "toc.json").read_text(encoding="utf-8"))
    title = meta.get("title") or "document"

    if (workdir / "sections.json").exists():
        sections = json.loads((workdir / "sections.json").read_text(encoding="utf-8"))
    else:
        sections = [{"id": int(p.name[:3]), "title": p.stem, "filename": p.name, "continuation": False}
                    for p in sorted(bangla_dir.glob("*.md")) if p.name[:3].isdigit()]

    chapters_file = workdir / "chapters.json"
    chapters = []
    if chapters_file.exists():
        try:
            chapters = json.loads(chapters_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    if section_num is not None:
        sections = [s for s in sections if s["id"] == section_num]
        if not sections or not (bangla_dir / sections[0]["filename"]).exists():
            raise FileNotFoundError(f"Section {section_num} has not been translated yet (no file in {bangla_dir}).")
        out_name = f"{safe_filename(title)}_Part{section_num}_Bangla.pdf"
    else:
        out_name = f"{safe_filename(title)}_Bangla.pdf"

    if custom_output:
        dest_pdf = pathlib.Path(custom_output).resolve()
    else:
        dest_pdf = output_base(workdir) / out_name
    dest_pdf.parent.mkdir(parents=True, exist_ok=True)

    parts, missing = [], []

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
    FRONT_MATTER_RE = re.compile(
        r"^\s*(?:front\s*matter|preface|foreword|cover|title\s*page|copyright|contents?|table\s*of\s*contents)\b",
        re.I,
    )
    LABEL_RE = re.compile(
        r"^(?:অধ্যায়\s*[\d০-৯IVXLCDM]+|[\d০-৯IVXLCDM]+\s*(?:ম|য়|র্থ|ষ্ঠ|তম)?\s*অধ্যায়|chapter\s*[\dIVXLCDM]+)\s*$",
        re.I,
    )
    chapters = [c for c in chapters if not EXCLUDE_RE.search(c.get("title", ""))]

    def analyze_chapter(ch_obj, body_ch_index):
        raw_title = ch_obj.get("title", "")
        is_fm = bool(FRONT_MATTER_RE.search(raw_title))

        if is_fm:
            ch_num = None
            bn_num = None
        else:
            m = re.search(r"\b(?:Chapter|CHAPTER|অধ্যায়)\s+([0-9IVXLCDM]+)", raw_title, re.I)
            if m:
                ch_num = m.group(1)
            else:
                ch_num = str(body_ch_index)
            bn_num = to_bangla_digits(ch_num)

        display_kicker = f"অধ্যায় {bn_num}" if bn_num else None

        display_title = None
        raw_label_in_md = None
        first_sec = next((s for s in sections if s.get("chapter_id") == ch_obj["id"]), None)
        if first_sec:
            f = bangla_dir / first_sec["filename"]
            if f.exists():
                lines = [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
                h_lines = [re.sub(r"^#+\s*", "", ln).strip() for ln in lines[:8] if ln.startswith("# ")]
                for h in h_lines:
                    if LABEL_RE.match(h):
                        raw_label_in_md = h
                    elif not display_title:
                        display_title = h

        if not display_title:
            clean_title = re.sub(r"^(?:Chapter\s+[0-9IVXLCDM]+[:.\s\-–]*|অধ্যায়\s+[০-৯0-9]+[:.\s\-–]*)", "", raw_title, flags=re.I).strip()
            display_title = clean_title or raw_title or (f"অধ্যায় {bn_num}" if bn_num else "বিভাগ")

        if is_fm and (display_title.lower() == "front matter" or not display_title):
            display_title = "প্রারম্ভিক (Front Matter)"

        return {
            "is_front_matter": is_fm,
            "ch_num": ch_num,
            "bn_num": bn_num,
            "display_kicker": display_kicker,
            "display_title": display_title,
            "raw_label_in_md": raw_label_in_md,
        }

    def strip_leading_chapter_headings(md_text: str, label: str = None, title: str = None) -> str:
        lines = md_text.splitlines()
        i = 0
        stripped = 0
        while i < len(lines) and stripped < 2:
            ln = lines[i].strip()
            if not ln:
                i += 1
                continue
            if ln.startswith("# "):
                h = ln[2:].strip()
                if LABEL_RE.match(h) or (label and h.lower() == label.lower()):
                    stripped += 1
                    i += 1
                    continue
                if title and (h.lower() == title.lower() or h.startswith(title) or title.startswith(h)):
                    stripped += 1
                    i += 1
                    continue
                if re.match(r"^(?:অধ্যায়\s*[\d০-৯IVXLCDM]+|[\d০-৯IVXLCDM]+\s*(?:ম|য়|র্থ|ষ্ঠ|তম)?\s*অধ্যায়|chapter\s*[\dIVXLCDM]+)", h, re.I):
                    stripped += 1
                    i += 1
                    continue
            break
        return "\n".join(lines[i:])

    ch_info_map = {}
    body_ch_counter = 1
    for ch in chapters:
        is_fm = bool(FRONT_MATTER_RE.search(ch.get("title", "")))
        curr_idx = body_ch_counter if not is_fm else 0
        info = analyze_chapter(ch, curr_idx)
        ch_info_map[ch["id"]] = info
        if not is_fm:
            body_ch_counter += 1

    # If compiling full document and multiple chapters exist, generate Table of Contents page
    if section_num is None and len(chapters) > 1:
        toc_items_html = []
        for ch in chapters:
            info = ch_info_map[ch["id"]]
            kicker_span = f"<span class='toc-ch-num'>{html.escape(info['display_kicker'])}</span>" if info["display_kicker"] else "<span class='toc-ch-num'></span>"
            toc_items_html.append(
                f"<li class='toc-item'>{kicker_span}"
                f"<span class='toc-ch-title'>{html.escape(info['display_title'])}</span></li>"
            )

        book_toc_html = f"""<div class='book-cover'>
  <div class='book-badge'>বাংলা পূর্ণাঙ্গ সংস্করণ</div>
  <h1 class='book-main-title'>{html.escape(title)}</h1>
</div>
<div class='book-toc'>
  <h2 class='toc-header'>সূচিপত্র (Table of Contents)</h2>
  <ul class='toc-list'>
    {''.join(toc_items_html)}
  </ul>
</div>"""
        parts.append(book_toc_html)

    # Filter out excluded sections (references, acknowledgements, etc.)
    sections = [s for s in sections if s.get("translate", True) and not EXCLUDE_RE.search(s.get("title", "")) and not EXCLUDE_RE.search(s.get("chapter_title", ""))]

    current_ch_id = None
    for idx, s in enumerate(sections):
        ch_id = s.get("chapter_id")
        f = bangla_dir / s["filename"]

        # Insert chapter banner before first section of each chapter in full-book mode
        is_first_sec_of_ch = (section_num is None and len(chapters) > 1 and ch_id is not None and ch_id != current_ch_id)
        if is_first_sec_of_ch:
            current_ch_id = ch_id
            info = ch_info_map.get(ch_id, {})
            # Only numbered chapters get a chapter divider banner; Front matter flows directly
            if not info.get("is_front_matter", False):
                kicker = info.get("display_kicker") or f"অধ্যায় {to_bangla_digits(ch_id)}"
                c_title = info.get("display_title") or s.get("chapter_title", "")
                break_div = "<div class='page-break'></div>\n" if idx > 0 else ""
                chapter_banner = f"""{break_div}<div class='chapter-divider'>
  <div class='chapter-kicker'>{html.escape(kicker)}</div>
  <h1 class='chapter-title-text'>{html.escape(c_title)}</h1>
</div>"""
                parts.append(chapter_banner)
            elif idx > 0 and not s.get("continuation"):
                parts.append("<div class='page-break'></div>")
        elif idx > 0 and not s.get("continuation"):
            parts.append("<div class='page-break'></div>")

        if f.exists():
            raw_md = f.read_text(encoding="utf-8")
            if is_first_sec_of_ch and not ch_info_map.get(ch_id, {}).get("is_front_matter", False):
                raw_md = strip_leading_chapter_headings(
                    raw_md,
                    label=ch_info_map.get(ch_id, {}).get("raw_label_in_md"),
                    title=ch_info_map.get(ch_id, {}).get("display_title"),
                )
            body = markdown_to_html(raw_md, base_dir=workdir)
        else:
            missing.append(s["id"])
            body = (f"<div class='missing'><strong>অনুবাদ অসম্পূর্ণ:</strong> অংশ {s['id']} — "
                    f"“{html.escape(s['title'])}” — এখনও অনুবাদ করা হয়নি বা যাচাইয়ে ব্যর্থ হয়েছে।</div>")
        parts.append(f"<section class='doc-section'>\n{body}\n</section>")

    doc_html = f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} - বাংলা অনুবাদ</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;600&family=Hind+Siliguri:wght@500;600;700&family=Noto+Serif+Bengali:wght@400;600;700&display=block" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.8/dist/contrib/auto-render.min.js"
    onload="renderMathInElement(document.body, {{delimiters: [
        {{left: '\\\\[', right: '\\\\]', display: true}},
        {{left: '\\\\(', right: '\\\\)', display: false}}], throwOnError: false}});"></script>
<style>{CSS}</style>
</head>
<body>
{chr(10).join(parts)}
</body>
</html>
"""
    temp_html = workdir / f"_render_{'part_' + str(section_num) if section_num else 'full'}.html"
    temp_html.write_text(doc_html, encoding="utf-8")

    edge = find_edge_path()
    print(f"[*] Rendering {len(sections)} section(s) via Microsoft Edge ...")
    if dest_pdf.exists():
        dest_pdf.unlink()
    cmd = [edge, "--headless", "--disable-gpu", "--no-pdf-header-footer",
           "--run-all-compositor-stages-before-draw", "--virtual-time-budget=20000",
           f"--user-data-dir={workdir / '.edge_profile'}",
           f"--print-to-pdf={dest_pdf}", temp_html.as_uri()]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if not dest_pdf.exists() or dest_pdf.stat().st_size == 0:
        raise RuntimeError(f"PDF generation failed: {res.stderr[-800:]}")

    # Add page numbers using PyMuPDF (since Chromium @page bottom margin boxes are unsupported)
    add_page_numbers(dest_pdf, has_cover=(section_num is None and len(chapters) > 1))

    print(f"[✓] Generated PDF: {dest_pdf} ({dest_pdf.stat().st_size // 1024} KB)")
    if missing:
        print(f"[!] {len(missing)} section(s) not translated yet, shown as notices in the PDF: {missing}")
    return dest_pdf


def add_page_numbers(pdf_path: pathlib.Path, has_cover: bool = False):
    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
        fontfile = None
        for candidate in (r"C:\Windows\Fonts\kalpurush.ttf", r"C:\Windows\Fonts\vrinda.ttf", r"C:\Windows\Fonts\Nirmala.ttc"):
            if pathlib.Path(candidate).exists():
                fontfile = candidate
                break

        # If has_cover is True, cover and TOC pages (pages 0 and 1) skip numbering
        start_page = 2 if (has_cover and len(doc) > 2) else 0
        for p_idx in range(start_page, len(doc)):
            page = doc[p_idx]
            pw, ph = page.rect.width, page.rect.height
            page_num_str = to_bangla_digits(p_idx + 1)
            rect = pymupdf.Rect(0, ph - 42, pw, ph - 15)
            if fontfile:
                page.insert_textbox(rect, page_num_str, fontsize=9, fontname="bangla", fontfile=fontfile,
                                    align=pymupdf.TEXT_ALIGN_CENTER, color=(0.4, 0.45, 0.55))
            else:
                page.insert_textbox(rect, str(p_idx + 1), fontsize=9,
                                    align=pymupdf.TEXT_ALIGN_CENTER, color=(0.4, 0.45, 0.55))
        doc.save(doc.name, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        doc.close()
    except Exception as e:
        print(f"[!] Note: Could not stamp page numbers ({e})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compile translated markdown into PDF.")
    ap.add_argument("workdir", help="Work directory containing translated markdown and figures")
    ap.add_argument("--section", type=int, default=None, help="Section number to compile as preview")
    ap.add_argument("--output", default=None, help="Custom output PDF path")
    a = ap.parse_args()
    compile_pdf(a.workdir, section_num=a.section, custom_output=a.output)
