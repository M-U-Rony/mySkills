"""Extract text, code, tables, outline, and figures from a PDF or a web article (local path or URL).

Usage:
  python extract_doc.py "<pdf_path_or_url>" ["<workdir>"]

Features:
- PDF: local path or URL (arXiv /abs/ links are converted to /pdf/).
- Web articles (HTML URLs or local .html files): main content converted to Markdown,
  <pre>/<code> preserved verbatim, images downloaded.
- CODE IS PRESERVED: monospace text in PDFs is detected and emitted as fenced ``` blocks
  (with reconstructed indentation) or `inline code`, so the translator never translates it.
- Column-aware reading order for two-column papers.
- Running headers/footers and page numbers are stripped (saves tokens).
- Raster figures extracted (decorative repeats like logos skipped); vector figures
  (plots/diagrams drawn as paths) rendered as PNG clips; tables converted to Markdown.
- Figures are placed at their position in the reading flow, not at the end of the page.
- Saves per-page Markdown in <workdir>/pages/page_NNNN.md and outline in <workdir>/toc.json.
"""
import argparse
import collections
import html as htmllib
import json
import os
import pathlib
import re
import statistics
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}

MONO_FONT_RE = re.compile(
    r"mono|courier|consol|menlo|inconsolata|code|typewriter|cmtt|sfmono|jetbrains|lucidaconsole|lucida console",
    re.I,
)
BULLET_CHARS = "•◦▪‣∙●○■–"


# ----------------------------------------------------------------------------------------
# Input handling
# ----------------------------------------------------------------------------------------

def normalize_url(url_or_path: str) -> str:
    """Normalize input URL, handling file:// and arXiv URLs."""
    if url_or_path.startswith("file://"):
        parsed = urllib.parse.urlparse(url_or_path)
        path = urllib.parse.unquote(parsed.path)
        if re.match(r"^/[a-zA-Z]:", path):
            path = path.lstrip("/")
        return path
    if url_or_path.startswith(("http://", "https://")):
        arxiv_abs = re.search(r"arxiv\.org/abs/([0-9]+\.[0-9]+(?:v[0-9]+)?)", url_or_path)
        if arxiv_abs:
            return f"https://arxiv.org/pdf/{arxiv_abs.group(1)}.pdf"
    return url_or_path


def fetch(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", text).strip("_")
    return slug[:50] or "document"


def audiobook_base() -> pathlib.Path:
    """Default output base: $TRANSLATEBAN_OUT, else E:/audiobook if present, else the cwd."""
    env = os.environ.get("TRANSLATEBAN_OUT")
    if env:
        return pathlib.Path(env).expanduser()
    base = pathlib.Path("E:/audiobook")
    return base if base.exists() else pathlib.Path.cwd()


# ----------------------------------------------------------------------------------------
# PDF extraction
# ----------------------------------------------------------------------------------------

def span_is_mono(span: dict) -> bool:
    return bool(span.get("flags", 0) & 8) or bool(MONO_FONT_RE.search(span.get("font", "")))


def rect_overlap_ratio(a, b) -> float:
    """Fraction of rect a's area covered by rect b."""
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    area_a = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return (x1 - x0) * (y1 - y0) / area_a


def center_inside(a, b) -> bool:
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


def block_lines(block: dict) -> list[tuple]:
    """Return [(bbox, spans)] for a text block, merging lines that share a baseline."""
    raw = []
    for ln in block.get("lines", []):
        spans = [s for s in ln.get("spans", []) if s.get("text")]
        if spans:
            raw.append([list(ln["bbox"]), spans])
    merged = []
    for bbox, spans in raw:
        if merged and abs(merged[-1][0][1] - bbox[1]) < 1.5 and abs(merged[-1][0][3] - bbox[3]) < 1.5:
            prev = merged[-1]
            prev[1] = prev[1] + spans
            prev[0] = [min(prev[0][0], bbox[0]), min(prev[0][1], bbox[1]), max(prev[0][2], bbox[2]), max(prev[0][3], bbox[3])]
        else:
            merged.append([bbox, spans])
    for m in merged:
        m[1].sort(key=lambda s: s["bbox"][0])
    return [tuple(m) for m in merged]


def char_width(spans: list[dict]) -> float:
    for s in spans:
        t = s["text"]
        if len(t) >= 4:
            w = (s["bbox"][2] - s["bbox"][0]) / len(t)
            if w > 0.5:
                return w
    sizes = [s.get("size", 10) for s in spans] or [10]
    return max(sum(sizes) / len(sizes) * 0.6, 1.0)


def spans_to_text(spans: list[dict], cw: float) -> str:
    """Join spans of one visual line, inserting spaces for horizontal gaps."""
    out = ""
    prev_x1 = None
    for s in spans:
        if prev_x1 is not None:
            gap = s["bbox"][0] - prev_x1
            if gap > cw * 0.8 and not out.endswith(" ") and not s["text"].startswith(" "):
                out += " " * max(1, round(gap / cw))
        out += s["text"]
        prev_x1 = s["bbox"][2]
    return out


def render_code(lines: list[tuple]) -> str:
    """Rebuild a code block, reconstructing indentation from x positions."""
    if not lines:
        return ""
    all_spans = [s for _, spans in lines for s in spans]
    cw = char_width(all_spans)
    x_min = min(b[0] for b, _ in lines)
    heights = [b[3] - b[1] for b, _ in lines]
    lh = statistics.median(heights) if heights else 10
    out = []
    prev_y1 = None
    for bbox, spans in lines:
        if prev_y1 is not None and bbox[1] - prev_y1 > lh * 0.9:
            out.append("")
        indent = max(0, round((bbox[0] - x_min) / cw))
        out.append(" " * indent + spans_to_text(spans, cw).rstrip())
        prev_y1 = bbox[3]
    return "```\n" + "\n".join(out) + "\n```"


def render_prose(lines: list[tuple]) -> str:
    """Join a prose block into a paragraph; wrap monospace runs in backticks; de-hyphenate."""
    rendered_lines = []
    for _, spans in lines:
        cw = char_width(spans)
        parts = []
        mono_run = []
        prev_x1 = None
        for s in spans:
            text = s["text"]
            if prev_x1 is not None and s["bbox"][0] - prev_x1 > cw * 0.8 and not text.startswith(" "):
                text = " " + text
            prev_x1 = s["bbox"][2]
            if span_is_mono(s) and text.strip():
                mono_run.append(text)
                continue
            if mono_run:
                code = "".join(mono_run)
                lead = code[: len(code) - len(code.lstrip())]
                parts.append(f"{lead}`{code.strip()}`")
                mono_run = []
            parts.append(text)
        if mono_run:
            code = "".join(mono_run)
            lead = code[: len(code) - len(code.lstrip())]
            parts.append(f"{lead}`{code.strip()}`")
        rendered_lines.append("".join(parts).strip())

    # Bullet lists
    if rendered_lines and rendered_lines[0][:1] in BULLET_CHARS:
        items, cur = [], ""
        for ln in rendered_lines:
            if ln[:1] in BULLET_CHARS:
                if cur:
                    items.append(cur)
                cur = ln[1:].strip()
            else:
                cur = join_lines(cur, ln)
        if cur:
            items.append(cur)
        return "\n".join(f"- {it}" for it in items)

    para = ""
    for ln in rendered_lines:
        para = join_lines(para, ln)
    return para


def join_lines(a: str, b: str) -> str:
    if not a:
        return b
    if re.search(r"[A-Za-z]-$", a) and b[:1].islower():
        return a[:-1] + b
    return a + " " + b


def order_items(items: list[dict], page_width: float) -> list[dict]:
    """Column-aware reading order (handles two-column papers)."""
    mid = page_width / 2
    text_items = [it for it in items if it["kind"] in ("prose", "code", "heading")]
    left = sum(1 for it in text_items if it["bbox"][2] < mid + 10)
    right = sum(1 for it in text_items if it["bbox"][0] > mid - 10)
    if left < 2 or right < 2:
        return sorted(items, key=lambda it: (round(it["bbox"][1], 1), it["bbox"][0]))

    def is_full(it):
        return it["bbox"][0] < mid - 20 and it["bbox"][2] > mid + 20

    fulls = sorted([it for it in items if is_full(it)], key=lambda it: it["bbox"][1])
    full_y = [f["bbox"][1] for f in fulls]

    def key(it):
        if is_full(it):
            return (fulls.index(it), 2, it["bbox"][1])
        band = sum(1 for y in full_y if y < it["bbox"][1])
        col = 0 if it["bbox"][2] <= mid + 20 else 1
        return (band, col, it["bbox"][1])

    return sorted(items, key=key)


def is_page_number(text: str) -> bool:
    return bool(re.fullmatch(r"(page\s*)?[0-9ivxlc]+(\s*(of|/)\s*\d+)?", text.strip(), re.I))


def margin_key(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())[:80]


def table_is_real(tab) -> bool:
    try:
        if tab.row_count < 2 or tab.col_count < 2:
            return False
        cells = [c for row in tab.extract() for c in row]
        empty = sum(1 for c in cells if not (c or "").strip())
        return empty <= len(cells) * 0.5
    except Exception:
        return False


def extract_pdf(local_pdf: pathlib.Path, workdir: pathlib.Path, doc_name: str) -> dict:
    import pymupdf

    pages_dir = workdir / "pages"
    figures_dir = workdir / "figures"
    doc = pymupdf.open(str(local_pdf))
    total_pages = len(doc)
    print(f"[*] Total Pages: {total_pages}")

    title = (doc.metadata or {}).get("title", "").strip() or doc_name

    # ---- Pass 1: statistics (body font size, repeating margins, repeating images) ----
    margin_counts = collections.Counter()
    xref_pages = collections.defaultdict(set)
    sizes = []
    for page in doc:
        h = page.rect.height
        d = page.get_text("dict")
        seen = set()
        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            text = " ".join(s["text"] for ln in b["lines"] for s in ln["spans"]).strip()
            for ln in b["lines"]:
                for s in ln["spans"]:
                    if s["text"].strip():
                        sizes.extend([round(s["size"], 1)] * len(s["text"]))
            if text and (b["bbox"][3] < h * 0.08 or b["bbox"][1] > h * 0.92):
                k = margin_key(text)
                if k not in seen:
                    margin_counts[k] += 1
                    seen.add(k)
        for img in page.get_images(full=True):
            xref_pages[img[0]].add(page.number)
    body_size = statistics.median(sizes) if sizes else 10.0
    repeat_threshold = max(3, int(total_pages * 0.25))
    repeating_margins = {k for k, c in margin_counts.items() if c >= repeat_threshold}
    decorative_xrefs = {x for x, p in xref_pages.items() if total_pages >= 4 and len(p) >= 3}

    toc_entries = [{"level": lvl, "title": t.strip(), "page": p} for lvl, t, p in doc.get_toc()]
    if toc_entries:
        print(f"[+] Found {len(toc_entries)} TOC outline items in PDF metadata.")
    detected_headings = []

    stats = collections.Counter()
    extracted_xrefs = set()
    empty_pages = 0

    # ---- Pass 2: per page ----
    for page in doc:
        page_num = page.number + 1
        pw, ph = page.rect.width, page.rect.height
        d = page.get_text("dict")
        items = []

        for b in d["blocks"]:
            if b.get("type") != 0:
                continue
            lines = block_lines(b)
            if not lines:
                continue
            plain = " ".join(spans_to_text(sp, char_width(sp)) for _, sp in lines).strip()
            if not plain:
                continue
            bbox = tuple(b["bbox"])
            in_margin = bbox[3] < ph * 0.08 or bbox[1] > ph * 0.92
            if in_margin and (is_page_number(plain) or margin_key(plain) in repeating_margins):
                stats["margin_dropped"] += 1
                continue

            total = mono = 0
            span_sizes = []
            bold = True
            for _, spans in lines:
                for s in spans:
                    n = len(s["text"].strip())
                    total += n
                    if span_is_mono(s):
                        mono += n
                    if n:
                        span_sizes.append(s["size"])
                        bold = bold and bool(s.get("flags", 0) & 16 or "bold" in s.get("font", "").lower())
            mono_ratio = mono / total if total else 0
            avg_size = sum(span_sizes) / len(span_sizes) if span_sizes else body_size

            if mono_ratio >= 0.7:
                items.append({"kind": "code", "bbox": bbox, "lines": lines})
                continue

            short = len(plain) <= 120 and len(lines) <= 3
            level = None
            if short and avg_size >= body_size * 1.6:
                level = 1
            elif short and avg_size >= body_size * 1.2:
                level = 2
            elif short and bold and avg_size >= body_size * 1.05 and not plain.endswith((".", ",", ":")):
                level = 3
            if level:
                items.append({"kind": "heading", "bbox": bbox, "md": "#" * level + " " + plain, "title": plain, "level": level})
                continue
            items.append({"kind": "prose", "bbox": bbox, "lines": lines})

        code_boxes = [it["bbox"] for it in items if it["kind"] == "code"]

        # Tables
        table_boxes = []
        try:
            for tab in page.find_tables().tables:
                tb = tuple(tab.bbox)
                if any(rect_overlap_ratio(cb, tb) > 0.3 for cb in code_boxes) or not table_is_real(tab):
                    continue
                md = tab.to_markdown().strip()
                if md:
                    table_boxes.append(tb)
                    items.append({"kind": "table", "bbox": tb, "md": md})
                    stats["tables"] += 1
        except Exception:
            pass
        if table_boxes:
            items = [it for it in items if it["kind"] == "table" or not any(center_inside(it["bbox"], tb) for tb in table_boxes)]

        # Vector figures (plots/diagrams drawn as paths)
        vector_boxes = []
        try:
            drawings = page.get_drawings()
            if len(drawings) >= 5:
                for r in page.cluster_drawings(drawings=drawings):
                    rb = (r.x0, r.y0, r.x1, r.y1)
                    if r.width < pw * 0.25 or r.height < 60 or (r.width > pw * 0.95 and r.height > ph * 0.9):
                        continue
                    if any(rect_overlap_ratio(rb, cb) > 0.3 or rect_overlap_ratio(cb, rb) > 0.5 for cb in code_boxes + table_boxes):
                        continue
                    strokes = sum(
                        1 for dr in drawings if pymupdf.Rect(dr["rect"]).intersects(r)
                        for it in dr["items"] if it[0] in ("l", "c", "qu")
                    )
                    if strokes < 8:
                        continue
                    inner_text = sum(
                        len(" ".join(s["text"] for _, sp in it["lines"] for s in sp))
                        for it in items if it["kind"] == "prose" and center_inside(it["bbox"], rb)
                    )
                    if inner_text > 400:
                        continue
                    # Grow the clip to include adjacent short labels (axis titles, legends)
                    for it in items:
                        if it["kind"] != "prose":
                            continue
                        ib = it["bbox"]
                        txt_len = len(" ".join(s["text"] for _, sp in it["lines"] for s in sp).strip())
                        near = (ib[0] >= rb[0] - 25 and ib[2] <= rb[2] + 25 and ib[1] >= rb[1] - 25 and ib[3] <= rb[3] + 25)
                        if txt_len <= 60 and near:
                            rb = (min(rb[0], ib[0]), min(rb[1], ib[1]), max(rb[2], ib[2]), max(rb[3], ib[3]))
                    clip = pymupdf.Rect(rb) + (-4, -4, 4, 4)
                    fname = f"fig_p{page_num:03d}_v{len(vector_boxes):02d}.png"
                    fpath = figures_dir / fname
                    if not fpath.exists():
                        page.get_pixmap(clip=clip, dpi=200).save(str(fpath))
                    vector_boxes.append(rb)
                    items.append({"kind": "figure", "bbox": rb, "md": f"![চিত্র]({'figures/' + fname})"})
                    stats["vector_figures"] += 1
        except Exception:
            pass
        if vector_boxes:
            # Drop axis labels / legends that belong to the rendered figure
            items = [it for it in items if it["kind"] == "figure" or it["kind"] == "heading"
                     or not any(center_inside(it["bbox"], vb) for vb in vector_boxes)]

        # Raster figures
        for img_idx, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            if xref in decorative_xrefs:
                continue
            try:
                rects = page.get_image_rects(xref)
                rb = tuple(rects[0]) if rects else (0, ph, pw, ph)
                if any(rect_overlap_ratio(rb, vb) > 0.6 for vb in vector_boxes):
                    continue
                base_img = doc.extract_image(xref)
                if base_img.get("width", 0) < 80 or base_img.get("height", 0) < 80:
                    continue
                fname = f"fig_p{page_num:03d}_{img_idx:02d}.{base_img['ext']}"
                fpath = figures_dir / fname
                if xref not in extracted_xrefs and not fpath.exists():
                    fpath.write_bytes(base_img["image"])
                extracted_xrefs.add(xref)
                items.append({"kind": "figure", "bbox": rb, "md": f"![চিত্র](figures/{fname})"})
                stats["raster_figures"] += 1
            except Exception:
                pass

        # Order, merge adjacent code blocks, render
        items = order_items(items, pw)
        merged = []
        for it in items:
            if it["kind"] == "code" and merged and merged[-1]["kind"] == "code":
                merged[-1]["lines"] = merged[-1]["lines"] + it["lines"]
            else:
                merged.append(dict(it))
        md_parts = []
        for it in merged:
            if it["kind"] == "code":
                md_parts.append(render_code(it["lines"]))
                stats["code_blocks"] += 1
            elif it["kind"] == "prose":
                md_parts.append(render_prose(it["lines"]))
            else:
                md_parts.append(it["md"])
            if it["kind"] == "heading" and it["level"] <= 2:
                detected_headings.append({"level": it["level"], "title": it["title"], "page": page_num})

        page_md = "\n\n".join(p for p in md_parts if p.strip())
        if not page_md.strip():
            empty_pages += 1
        (pages_dir / f"page_{page_num:04d}.md").write_text(page_md, encoding="utf-8")

    if not toc_entries:
        toc_entries = detected_headings

    print(f"[+] Code blocks: {stats['code_blocks']} | Tables: {stats['tables']} | "
          f"Raster figs: {stats['raster_figures']} | Vector figs: {stats['vector_figures']} | "
          f"Header/footer blocks dropped: {stats['margin_dropped']}")
    if empty_pages > total_pages * 0.5:
        print("[!] WARNING: Over 50% of pages are empty. Document may be a scanned image requiring OCR.")

    return {
        "title": title,
        "source_type": "pdf",
        "source_pdf": str(local_pdf),
        "total_pages": total_pages,
        "total_images": stats["raster_figures"] + stats["vector_figures"],
        "code_blocks": stats["code_blocks"],
        "toc": toc_entries,
    }


# ----------------------------------------------------------------------------------------
# HTML article extraction
# ----------------------------------------------------------------------------------------

class HTMLToMarkdown(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "aside", "form", "button",
            "iframe", "template", "select", "header"}
    BLOCK = {"p", "div", "section", "article", "figure", "ul", "ol", "li", "blockquote",
             "h1", "h2", "h3", "h4", "h5", "h6", "table", "hr", "main", "figcaption"}

    def __init__(self, image_cb):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.buf = ""
        self.skip = 0
        self.skip_tag = []
        self.in_pre = False
        self.pre_buf = ""
        self.pre_lang = ""
        self.in_inline_code = False
        self.heading = None
        self.list_stack = []
        self.quote = 0
        self.table = None
        self.cell = None
        self.image_cb = image_cb

    @staticmethod
    def _lang(attrs: dict) -> str:
        cls = attrs.get("class", "") or ""
        m = re.search(r"(?:language|lang)-([\w+#-]+)", cls)
        if m:
            return m.group(1)
        m = re.search(r"\bhighlight\s+([\w+#-]+)", cls)
        return m.group(1) if m else ""

    def flush(self):
        text = re.sub(r"[ \t\r\n]+", " ", self.buf).strip()
        self.buf = ""
        if not text or text in ("``", "****", "**", "*"):
            return
        if self.heading:
            text = "#" * self.heading + " " + text
        elif self.list_stack:
            kind, n = self.list_stack[-1]
            prefix = "- " if kind == "ul" else f"{n}. "
            text = "  " * (len(self.list_stack) - 1) + prefix + text
        if self.quote:
            text = "> " + text
        self.blocks.append(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.skip:
            if tag == self.skip_tag[-1]:
                self.skip += 1
            return
        if tag in self.SKIP:
            self.skip = 1
            self.skip_tag.append(tag)
            return
        if self.in_pre:
            if tag == "code" and not self.pre_lang:
                self.pre_lang = self._lang(attrs)
            elif tag == "br":
                self.pre_buf += "\n"
            return
        if self.table is not None:
            if tag == "tr":
                self.table.append([])
            elif tag in ("td", "th"):
                self.cell = ""
            elif tag == "br" and self.cell is not None:
                self.cell += " "
            return
        if tag == "pre":
            self.flush()
            self.in_pre = True
            self.pre_buf = ""
            self.pre_lang = self._lang(attrs)
            return
        if tag == "table":
            self.flush()
            self.table = []
            return
        if tag in self.BLOCK:
            self.flush()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = min(int(tag[1]), 4)
        elif tag in ("ul", "ol"):
            self.list_stack.append([tag, 0])
        elif tag == "li" and self.list_stack:
            self.list_stack[-1][1] += 1
        elif tag == "blockquote":
            self.quote += 1
        elif tag == "code":
            self.buf += "`"
            self.in_inline_code = True
        elif tag in ("strong", "b") and not self.in_inline_code:
            self.buf += "**"
        elif tag in ("em", "i") and not self.in_inline_code:
            self.buf += "*"
        elif tag == "br":
            self.buf += " "
        elif tag == "img":
            src = attrs.get("data-src") or attrs.get("src") or ""
            srcset = attrs.get("srcset") or attrs.get("data-srcset") or ""
            if srcset:
                src = srcset.split(",")[-1].strip().split(" ")[0] or src
            if src and not src.startswith("data:"):
                rel = self.image_cb(src)
                if rel:
                    self.flush()
                    alt = (attrs.get("alt") or "চিত্র").replace("[", "(").replace("]", ")")
                    self.blocks.append(f"![{alt}]({rel})")

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip_tag[-1]:
                self.skip -= 1
                if self.skip == 0:
                    self.skip_tag.pop()
            return
        if self.in_pre:
            if tag == "pre":
                code = self.pre_buf.strip("\n")
                if code.strip():
                    fence = "````" if "```" in code else "```"
                    self.blocks.append(f"{fence}{self.pre_lang}\n{code}\n{fence}")
                self.in_pre = False
            elif tag in ("div", "p", "tr") and self.pre_buf and not self.pre_buf.endswith("\n"):
                self.pre_buf += "\n"
            return
        if self.table is not None:
            if tag in ("td", "th") and self.cell is not None:
                if self.table:
                    self.table[-1].append(re.sub(r"\s+", " ", self.cell).strip().replace("|", "\\|"))
                self.cell = None
            elif tag == "table":
                rows = [r for r in self.table if r]
                if rows:
                    width = max(len(r) for r in rows)
                    rows = [r + [""] * (width - len(r)) for r in rows]
                    md = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
                    md += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                    self.blocks.append("\n".join(md))
                self.table = None
            return
        if tag == "code" and self.in_inline_code:
            self.buf += "`"
            self.in_inline_code = False
        elif tag in ("strong", "b") and not self.in_inline_code:
            self.buf += "**"
        elif tag in ("em", "i") and not self.in_inline_code:
            self.buf += "*"
        if tag in self.BLOCK:
            self.flush()
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.heading = None
        elif tag in ("ul", "ol") and self.list_stack:
            self.list_stack.pop()
        elif tag == "blockquote" and self.quote:
            self.quote -= 1

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_pre:
            self.pre_buf += data
        elif self.table is not None:
            if self.cell is not None:
                self.cell += data
        else:
            self.buf += data

    def close(self):
        super().close()
        self.flush()


def extract_html(html_text: str, base_url: str, workdir: pathlib.Path, doc_name: str, max_chars: int = 3500) -> dict:
    figures_dir = workdir / "figures"
    pages_dir = workdir / "pages"

    m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html_text, re.I)
    if not m:
        m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    title = htmllib.unescape(m.group(1)).strip() if m else doc_name

    region = html_text
    for tag in ("article", "main", "body"):
        s = re.search(rf"<{tag}\b", html_text, re.I)
        e = html_text.lower().rfind(f"</{tag}>")
        if s and e > s.start():
            region = html_text[s.start():e]
            break

    counter = {"n": 0}

    def save_image(src: str):
        url = urllib.parse.urljoin(base_url, src) if base_url else src
        try:
            if url.startswith(("http://", "https://")):
                data, ctype = fetch(url)
            else:
                # Local file, possibly as a file:// URL (local .html inputs).
                if url.startswith("file://"):
                    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
                    if re.match(r"^/[a-zA-Z]:", path):
                        path = path.lstrip("/")
                    p = pathlib.Path(path)
                else:
                    p = pathlib.Path(url)
                data, ctype = p.read_bytes(), ""
            if len(data) < 3000:  # tracking pixels / icons
                return None
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
                   "image/svg+xml": "svg"}.get(ctype.split(";")[0].strip(), "")
            if not ext:
                ext = pathlib.Path(urllib.parse.urlparse(url).path).suffix.lstrip(".").lower() or "png"
            counter["n"] += 1
            fname = f"img_{counter['n']:03d}.{ext[:4]}"
            (figures_dir / fname).write_bytes(data)
            return f"figures/{fname}"
        except Exception:
            return None

    parser = HTMLToMarkdown(save_image)
    parser.feed(region)
    parser.close()
    blocks = parser.blocks

    # Pack blocks into pseudo-pages (code blocks are never split)
    pages, cur, size = [], [], 0
    for b in blocks:
        if cur and size + len(b) > max_chars:
            pages.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += len(b)
    if cur:
        pages.append(cur)

    toc = []
    for i, pg in enumerate(pages, start=1):
        (pages_dir / f"page_{i:04d}.md").write_text("\n\n".join(pg), encoding="utf-8")
        for b in pg:
            hm = re.match(r"^(#{1,2})\s+(.*)", b)
            if hm:
                toc.append({"level": len(hm.group(1)), "title": hm.group(2).strip(), "page": i})

    n_code = sum(1 for b in blocks if b.startswith("```"))
    print(f"[+] Article: '{title}' | Blocks: {len(blocks)} | Code blocks: {n_code} | Images: {counter['n']}")
    if n_code == 0 and "<pre" not in region.lower() and re.search(r"gist\.github|<iframe", html_text, re.I):
        print("[!] WARNING: Code seems to be embedded via iframes/gists, which cannot be extracted from static HTML.")
    return {
        "title": title,
        "source_type": "html",
        "source_url": base_url,
        "total_pages": len(pages),
        "total_images": counter["n"],
        "code_blocks": n_code,
        "toc": toc,
    }


# ----------------------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------------------

def extract_document(doc_input: str, custom_workdir: str = None) -> pathlib.Path:
    input_str = normalize_url(doc_input)
    is_url = input_str.startswith(("http://", "https://"))
    if is_url:
        parsed = urllib.parse.urlparse(input_str)
        doc_name = pathlib.Path(parsed.path.rstrip("/")).stem or parsed.netloc
    else:
        doc_name = pathlib.Path(doc_input).stem
    safe_slug = slugify(doc_name)

    if custom_workdir:
        workdir = pathlib.Path(custom_workdir).resolve()
    else:
        workdir = audiobook_base() / f"{safe_slug}_bangla"

    for d in ("pages", "figures", "source", "bangla"):
        (workdir / d).mkdir(parents=True, exist_ok=True)

    if is_url:
        print(f"[*] Fetching: {input_str}")
        data, ctype = fetch(input_str)
        if data[:5] == b"%PDF-" or "pdf" in ctype.lower():
            local_pdf = workdir / (safe_slug + ".pdf")
            local_pdf.write_bytes(data)
            print(f"[+] Downloaded PDF to: {local_pdf} ({len(data) // 1024} KB)")
            meta = extract_pdf(local_pdf, workdir, doc_name)
        else:
            charset = re.search(r"charset=([\w-]+)", ctype)
            html_text = data.decode(charset.group(1) if charset else "utf-8", errors="replace")
            (workdir / "source.html").write_text(html_text, encoding="utf-8")
            meta = extract_html(html_text, input_str, workdir, doc_name)
    else:
        p = pathlib.Path(doc_input).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Input not found: {doc_input}")
        if p.suffix.lower() in (".html", ".htm"):
            meta = extract_html(p.read_text(encoding="utf-8", errors="replace"), p.parent.as_uri() + "/", workdir, doc_name)
        else:
            meta = extract_pdf(p, workdir, doc_name)

    (workdir / "toc.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] Saved pages, figures and toc.json into: {workdir}")
    print(f"WORKDIR={workdir}")
    return workdir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract PDF/HTML content, code, TOC, and figures.")
    parser.add_argument("doc_input", help="Path or URL to a PDF or web article")
    parser.add_argument("workdir", nargs="?", default=None, help="Optional output workdir")
    args = parser.parse_args()
    extract_document(args.doc_input, args.workdir)
