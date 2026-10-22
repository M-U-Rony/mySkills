"""Compile the Bangla Study & Thesis Guide PDF (Mode B Ultra-Minimal by default, or Full Translation + Part 2 if requested).

Usage:
  python compile_thesis_pdf.py "<workdir>" [--output "<custom_pdf_path>"] [--no-cleanup]

Features:
- Clean academic header showing Paper Title, Authors, Venue/Year, arXiv ID, and Citations.
- In default Mode B (single `minimal_study` section), omits the redundant Table of Contents and chapter banners so the 4–5 page Study & Thesis Guide starts immediately on Page 1.
- Renders `[সহজ বাংলায় মূল কথা (Intuition)]` blockquotes as styled academic intuition callout cards.
- Full KaTeX math rendering, code blocks, tables, figures, and Bengali page numbering.
- Outputs to E:\\thesis\\<Title>_Thesis_Bangla.pdf and cleans up temporary <workdir> upon success (unless --no-cleanup).
"""
import argparse
import html
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")


def find_browser_path() -> str:
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")):
        if pathlib.Path(c).exists():
            return c
    for name in ("msedge", "chrome", "chromium", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise FileNotFoundError("No Chromium-based browser found (Edge/Chrome/Chromium) for PDF rendering.")


def find_edge_path() -> str:
    return find_browser_path()


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


def escape_math(math_src: str) -> str:
    return math_src.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(text: str) -> str:
    tokens = []

    def protect(s: str) -> str:
        tokens.append(s)
        return f"\x00{len(tokens) - 1}\x00"

    text = re.sub(r"(?<!`)`([^`\n]+)`(?!`)", lambda m: protect(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = re.sub(r"\$\$(.+?)\$\$", lambda m: protect(f"\\[{escape_math(m.group(1))}\\]"), text, flags=re.S)
    text = re.sub(r"(?<![\\$\w])\$(?=\S)([^$\n]*?\S)\$(?![\d$])", lambda m: protect(f"\\({escape_math(m.group(1))}\\)"), text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\*\w])\*(?![\s\*])(.+?)(?<![\s\*])\*(?![\*\w])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m.group(1))], text)


def markdown_to_html(md_text: str, base_dir: pathlib.Path) -> str:
    lines = md_text.split("\n")
    out, para, list_items, quote_lines = [], [], [], []
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

    def flush_quote():
        nonlocal quote_lines
        if quote_lines:
            joined = " ".join(quote_lines)
            is_intuition = "সহজ বাংলায় মূল কথা" in joined or "Intuition" in joined[:60]
            cls = "intuition-box" if is_intuition else ""
            attr = f" class='{cls}'" if cls else ""
            out.append(f"<blockquote{attr}>{inline(joined)}</blockquote>")
            quote_lines = []

    def flush_all():
        flush_para()
        flush_list()
        flush_quote()

    while i < len(lines):
        line = lines[i]
        s = line.strip()

        if s.startswith("$$") and not (s.endswith("$$") and len(s) > 4):
            flush_all()
            math_lines = [s[2:]]
            i += 1
            while i < len(lines) and not lines[i].strip().endswith("$$"):
                math_lines.append(lines[i])
                i += 1
            if i < len(lines):
                math_lines.append(lines[i].strip()[:-2])
                i += 1
            out.append(f"<div class='math-block'>\\[{escape_math(chr(10).join(math_lines))}\\]</div>")
            continue

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
        if re.fullmatch(r"[-*_]{3,}", s):
            flush_all()
            out.append("<hr class='sec-hr' />")
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
            flush_para()
            flush_list()
            quote_lines.append(s.lstrip(">").strip())
            continue
        else:
            flush_quote()

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


CSS = """
  @page { size: A4; margin: 11mm 12mm 13mm 12mm; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; box-sizing: border-box; }
  body { font-family: 'Noto Serif Bengali', 'Kalpurush', 'SolaimanLipi', 'Vrinda', 'Nirmala UI', serif;
         font-size: 10pt; line-height: 1.5; color: #1e293b; margin: 0; }
  h1, h2, h3, h4 { font-family: 'Hind Siliguri', 'Nirmala UI', sans-serif; color: #0f172a; line-height: 1.25; break-after: avoid; }
  h1 { font-size: 13.5pt; border-bottom: 1.5px solid #2563eb; padding-bottom: 3px; margin: 11px 0 6px; color: #0f172a; }
  h2 { font-size: 11.5pt; color: #1e3a8a; margin: 9px 0 4px; }
  h3, h4 { font-size: 10.4pt; color: #1e40af; margin: 7px 0 3px; }
  p { margin: 0 0 6px; text-align: justify; }
  a { color: #1d4ed8; text-decoration: none; }
  ul, ol { margin: 0 0 6px; padding-left: 18px; }
  li { margin-bottom: 3px; }
  .sec-hr { border: none; border-top: 1px solid #cbd5e1; margin: 8px 0; }
  blockquote { border-left: 3px solid #3b82f6; margin: 6px 0; padding: 6px 10px; background: #f8fafc; color: #334155; border-radius: 0 4px 4px 0; }
  blockquote.intuition-box { border-left: 4px solid #059669; background: #ecfdf5; color: #064e3b; padding: 6px 10px; margin: 6px 0; border-radius: 0 5px 5px 0; }
  .math-block { margin: 5px 0; padding: 5px 8px; background: #f8fafc; border-radius: 4px; overflow-x: auto; text-align: center; font-size: 9.5pt; }
  code { font-family: 'Fira Code', 'Cascadia Code', 'Consolas', monospace; font-size: 0.85em;
         background: #f1f5f9; color: #9f1239; padding: 0 3px; border-radius: 3px; direction: ltr; unicode-bidi: embed; }
  .code-block { margin: 5px 0 7px; border: 1px solid #d0d7de; border-radius: 4px; background: #f6f8fa; break-inside: auto; }
  .code-lang { font-family: 'Fira Code', 'Consolas', monospace; font-size: 7.5pt; color: #57606a;
               padding: 2px 8px; border-bottom: 1px solid #d0d7de; background: #eef1f4; border-radius: 4px 4px 0 0; }
  .code-block pre { margin: 0; padding: 5px 8px; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word;
                    line-height: 1.32; text-align: left; }
  .code-block pre code { background: transparent; color: #1f2328; padding: 0; font-size: 8pt; }
  .doc-figure { margin: 7px auto; text-align: center; break-inside: avoid; }
  .doc-figure img { max-width: 86%; max-height: 92mm; height: auto; border: 1px solid #e2e8f0; border-radius: 4px; }
  .doc-figure figcaption { margin-top: 3px; font-size: 8.5pt; font-family: 'Hind Siliguri', sans-serif; color: #475569; }
  .table-container { margin: 6px 0; break-inside: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 8.6pt; line-height: 1.35; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; }
  th, td { border: 1px solid #cbd5e1; padding: 4px 6px; text-align: left; vertical-align: top; }
  th { background: #f1f5f9; font-family: 'Hind Siliguri', sans-serif; color: #0f172a; }
  .missing { border: 1.5px dashed #dc2626; background: #fef2f2; color: #991b1b; padding: 6px 10px; margin: 6px 0; border-radius: 4px; }
  .paper-cover { text-align: center; padding: 6px 10px 8px; border-bottom: 2px solid #2563eb; margin-bottom: 8px; }
  .paper-badge { display: inline-block; font-family: 'Hind Siliguri', sans-serif; font-size: 8.5pt; color: #1d4ed8; background: #eff6ff; border: 1px solid #bfdbfe; padding: 1px 10px; border-radius: 12px; font-weight: 700; margin-bottom: 4px; }
  .paper-main-title { font-size: 14.5pt; line-height: 1.22; color: #0f172a; border-bottom: none; margin: 0 0 4px; padding: 0; }
  .paper-meta { font-family: 'Hind Siliguri', sans-serif; font-size: 8.6pt; color: #475569; margin: 2px 0; }
  .book-toc { padding: 4px 6px 8px; margin-bottom: 8px; border-bottom: 1.5px solid #cbd5e1; }
  .toc-header { font-size: 11.5pt; color: #0f172a; border-bottom: 1px solid #2563eb; padding-bottom: 2px; margin: 0 0 5px; }
  .toc-list { list-style: none; padding: 0; margin: 0; columns: 2; column-gap: 14px; }
  .toc-item { font-family: 'Hind Siliguri', sans-serif; font-size: 8.8pt; margin-bottom: 3px; border-bottom: 1px dotted #cbd5e1; padding-bottom: 2px; display: flex; justify-content: space-between; break-inside: avoid; }
  .toc-item.thesis-lab-toc { background: #f5f3ff; padding: 2px 6px; border-radius: 4px; border: 1px solid #ddd6fe; font-weight: 600; }
  .toc-ch-num { font-weight: 700; color: #2563eb; margin-right: 6px; min-width: 78px; }
  .toc-item.thesis-lab-toc .toc-ch-num { color: #6d28d9; }
  .toc-ch-title { color: #1e293b; flex-grow: 1; }
  .chapter-divider { margin: 10px 0 6px; padding: 5px 10px; background: #f8fafc; border-left: 4px solid #2563eb; border-radius: 0 5px 5px 0; break-after: avoid; break-inside: avoid; }
  .chapter-divider.thesis-lab-banner { background: #f5f3ff; border-left: 5px solid #7c3aed; padding: 7px 12px; margin: 12px 0 7px; }
  .chapter-kicker { font-family: 'Hind Siliguri', sans-serif; font-size: 8.5pt; font-weight: 700; color: #2563eb; text-transform: uppercase; letter-spacing: 0.5px; }
  .chapter-divider.thesis-lab-banner .chapter-kicker { color: #6d28d9; font-size: 9pt; }
  .chapter-title-text { font-size: 12.5pt; color: #0f172a; margin: 1px 0 0; border-bottom: none; padding-bottom: 0; line-height: 1.22; }
  .doc-section { margin: 0; padding: 0; }
"""


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" ._")
    return name[:110] or "paper"


def to_bangla_digits(num) -> str:
    b_map = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
    return str(num).translate(b_map)


def add_page_numbers(pdf_path: pathlib.Path, has_cover: bool = False):
    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
        fontfile = None
        for candidate in (r"C:\Windows\Fonts\kalpurush.ttf", r"C:\Windows\Fonts\vrinda.ttf", r"C:\Windows\Fonts\Nirmala.ttc"):
            if pathlib.Path(candidate).exists():
                fontfile = candidate
                break

        start_page = 1 if (has_cover and len(doc) > 1) else 0
        for p_idx in range(start_page, len(doc)):
            page = doc[p_idx]
            pw, ph = page.rect.width, page.rect.height
            page_num_str = to_bangla_digits(p_idx + 1)
            rect = pymupdf.Rect(0, ph - 28, pw, ph - 8)
            if fontfile:
                page.insert_textbox(rect, page_num_str, fontsize=8.5, fontname="bangla", fontfile=fontfile,
                                    align=pymupdf.TEXT_ALIGN_CENTER, color=(0.4, 0.45, 0.55))
            else:
                page.insert_textbox(rect, str(p_idx + 1), fontsize=8.5,
                                    align=pymupdf.TEXT_ALIGN_CENTER, color=(0.4, 0.45, 0.55))
        doc.save(doc.name, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
        doc.close()
    except Exception as e:
        print(f"[!] Note: Could not stamp page numbers ({e})")


def remove_readonly(func, path, excinfo):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def cleanup_workdir(workdir: pathlib.Path):
    for _ in range(5):
        try:
            if workdir.exists():
                shutil.rmtree(workdir, onerror=remove_readonly)
            if not workdir.exists():
                print(f"[✓] Cleaned up temporary workdir: {workdir}")
                return True
        except Exception:
            time.sleep(1)
    return not workdir.exists()


def compile_thesis_pdf(workdir_path: str, custom_output: str = None, no_cleanup: bool = False) -> pathlib.Path:
    workdir = pathlib.Path(workdir_path).resolve()
    bangla_dir = workdir / "bangla"
    meta = json.loads((workdir / "toc.json").read_text(encoding="utf-8")) if (workdir / "toc.json").exists() else {}
    scout = json.loads((workdir / "scout_report.json").read_text(encoding="utf-8")) if (workdir / "scout_report.json").exists() else {}
    scout_paper = scout.get("paper") or {}

    title = scout_paper.get("title") or meta.get("title") or "Research_Paper"
    authors = ", ".join((scout_paper.get("authors") or [])[:6])
    year_venue = f"{scout_paper.get('year') or ''} | {scout_paper.get('venue') or ''}".strip(" |")
    arxiv_id = scout_paper.get("arxiv_id") or meta.get("arxiv_id") or ""
    citations = scout_paper.get("cited_by_count")

    sections = json.loads((workdir / "sections.json").read_text(encoding="utf-8")) if (workdir / "sections.json").exists() else []
    chapters = json.loads((workdir / "chapters.json").read_text(encoding="utf-8")) if (workdir / "chapters.json").exists() else []

    out_name = f"{safe_filename(title)}_Thesis_Bangla.pdf"
    dest_pdf = pathlib.Path(custom_output).resolve() if custom_output else (thesis_base(workdir) / out_name)
    dest_pdf.parent.mkdir(parents=True, exist_ok=True)

    is_minimal_mode = len(chapters) == 1 and chapters[0].get("part_type") == "minimal_study"

    meta_lines = []
    if authors:
        meta_lines.append(f"<div class='paper-meta'><strong>লেখকবৃন্দ (Authors):</strong> {html.escape(authors)}</div>")
    if year_venue or arxiv_id or citations is not None:
        bits = [b for b in [year_venue, f"arXiv: {arxiv_id}" if arxiv_id else "", f"Citations: {citations}" if citations is not None else ""] if b]
        meta_lines.append(f"<div class='paper-meta'>{' · '.join(html.escape(b) for b in bits)}</div>")

    badge_text = "গবেষণাপত্র সারসংক্ষেপ, রিসার্চ গ্যাপ ও থিসিস গাইড" if is_minimal_mode else "বাংলা অনুবাদ ও থিসিস ব্লুপ্রিন্ট"
    parts = [f"""<div class='paper-cover'>
  <div class='paper-badge'>{badge_text}</div>
  <h1 class='paper-main-title'>{html.escape(title)}</h1>
  {''.join(meta_lines)}
</div>"""]

    if not is_minimal_mode and len(chapters) > 1:
        toc_items_html = []
        for ch in chapters:
            ch_id = ch.get("id")
            ptype = ch.get("part_type", "main_paper")
            if ptype == "thesis_lab":
                kicker = "অংশ ২ (THESIS LAB)"
                cls = "toc-item thesis-lab-toc"
            elif ptype == "appendix":
                kicker = f"পরিশিষ্ট ({to_bangla_digits(ch_id)})"
                cls = "toc-item"
            else:
                kicker = f"অংশ ১.{to_bangla_digits(ch_id)}"
                cls = "toc-item"
            toc_items_html.append(
                f"<li class='{cls}'><span class='toc-ch-num'>{html.escape(kicker)}</span>"
                f"<span class='toc-ch-title'>{html.escape(ch.get('title', ''))}</span></li>"
            )
        parts.append(f"""<div class='book-toc'>
  <h2 class='toc-header'>সূচিপত্র (Table of Contents)</h2>
  <ul class='toc-list'>
    {''.join(toc_items_html)}
  </ul>
</div>""")

    missing = []
    current_ch_id = None
    ch_map = {c["id"]: c for c in chapters}

    for s in sections:
        ch_id = s.get("chapter_id")
        f = bangla_dir / s["filename"]
        ch_obj = ch_map.get(ch_id, {})
        ptype = s.get("part_type") or ch_obj.get("part_type", "main_paper")

        is_first_sec_of_ch = (ch_id is not None and ch_id != current_ch_id)
        if is_first_sec_of_ch and not is_minimal_mode:
            current_ch_id = ch_id
            if ptype == "thesis_lab":
                kicker = "অংশ ২ • THESIS OPPORTUNITY & GAP ANALYSIS"
                banner_cls = "chapter-divider thesis-lab-banner"
            elif ptype == "appendix":
                kicker = "অংশ ১ (পরিশিষ্ট) • SELECTED APPENDIX"
                banner_cls = "chapter-divider"
            else:
                kicker = f"অংশ ১ • মূল গবেষণাপত্র (বিভাগ {to_bangla_digits(ch_id)})"
                banner_cls = "chapter-divider"
            c_title = ch_obj.get("title") or s.get("title", "")
            parts.append(f"""<div class='{banner_cls}'>
  <div class='chapter-kicker'>{html.escape(kicker)}</div>
  <h1 class='chapter-title-text'>{html.escape(c_title)}</h1>
</div>""")

        if f.exists():
            raw_md = f.read_text(encoding="utf-8")
            body = markdown_to_html(raw_md, base_dir=workdir)
        else:
            missing.append(s["id"])
            body = (f"<div class='missing'><strong>অনুবাদ অসম্পূর্ণ:</strong> অংশ {s['id']} — "
                    f"“{html.escape(s['title'])}” — এখনও প্রস্তুত হয়নি।</div>")
        parts.append(f"<section class='doc-section'>\n{body}\n</section>")

    doc_html = f"""<!DOCTYPE html>
<html lang="bn">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} - স্টাডি ও থিসিস গাইড</title>
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
    temp_html = workdir / "_render_thesis_full.html"
    temp_html.write_text(doc_html, encoding="utf-8")

    dest_resolved = dest_pdf.resolve()
    workdir_resolved = workdir.resolve()
    dest_inside_workdir = dest_resolved.is_relative_to(workdir_resolved) if hasattr(dest_resolved, "is_relative_to") else str(dest_resolved).startswith(str(workdir_resolved))
    if dest_inside_workdir and not no_cleanup:
        no_cleanup = True

    browser = find_browser_path()
    print(f"[*] Compiling Bangla Study & Thesis PDF via {pathlib.Path(browser).name} ...")
    if dest_pdf.exists():
        dest_pdf.unlink()
    cmd = [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer",
           "--run-all-compositor-stages-before-draw", "--virtual-time-budget=20000",
           f"--user-data-dir={workdir / '.edge_profile'}",
           f"--print-to-pdf={dest_pdf}", temp_html.as_uri()]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if not dest_pdf.exists() or dest_pdf.stat().st_size == 0:
        raise RuntimeError(f"PDF generation failed (browser={browser}): {res.stderr[-800:]}")

    add_page_numbers(dest_pdf, has_cover=False)
    print(f"[+] Generated Thesis PDF: {dest_pdf} ({dest_pdf.stat().st_size // 1024} KB)")

    try:
        from thesis_common import archive_paper
        archive_paper(workdir, title)
    except Exception as e:
        print(f"[!] Note: Could not archive paper corpus ({e})")

    if not missing and not no_cleanup:
        cleanup_workdir(workdir)
    elif missing:
        print(f"[!] {len(missing)} section(s) missing ({missing}); workdir retained at {workdir}")
    else:
        print(f"[*] Workdir retained at {workdir} (--no-cleanup).")

    return dest_pdf


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compile Bangla Study & Thesis Guide PDF.")
    ap.add_argument("workdir", help="Path to paper workdir")
    ap.add_argument("--output", default=None, help="Custom output PDF path")
    ap.add_argument("--no-cleanup", action="store_true", help="Keep temporary workdir after compilation")
    a = ap.parse_args()
    compile_thesis_pdf(a.workdir, custom_output=a.output, no_cleanup=a.no_cleanup)
