"""Extract text, academic sections, equations/code, tables, figures, and references from a research paper PDF or URL.

Usage:
  python extract_paper.py "<pdf_path_or_arxiv_url>" ["<workdir>"]

Paper-Specific Features:
- Converts arXiv /abs/ or /html/ URLs automatically to /pdf/ and detects arXiv IDs (even from local PDF page margins).
- Column-aware reading order for two-column conference/journal papers (NeurIPS, ICML, ACL, CVPR, IEEE, ACM).
- Preserves fenced code/algorithm blocks and inline code/math verbatim.
- Extracts raster figures, renders vector plots/architecture diagrams as PNG clips, and converts PDF tables to Markdown.
- Detects academic paper structure (Abstract, numbered sections, Limitations, References, Appendices) even when PDF bookmarks are missing.
- Saves extracted References into <workdir>/references.md for citation tracking.
- Saves per-page Markdown in <workdir>/pages/page_NNNN.md and paper metadata in <workdir>/toc.json.
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

ACADEMIC_SECTION_RE = re.compile(
    r"^(?:"
    r"abstract|"
    r"(?:[0-9]{1,2}(?:\.[0-9]{1,2})?|[IVX]{1,4})\.?\s+[A-Z][A-Za-z0-9\s\-–:,/()]{2,75}|"
    r"(?:appendix|supplementary)\s*[A-Z0-9]?[:.\s\-–]*[A-Za-z0-9\s\-–:,/()]{0,75}|"
    r"references|bibliography|acknowledg(?:e)?ments?|limitations?(?:\s+and\s+future\s+work)?|broader\s+impact|ethical\s+considerations|conclusion(?:s|\s+and\s+future\s+work)?"
    r")$",
    re.I,
)

REFERENCES_HEADING_RE = re.compile(
    r"^#*\s*(?:[0-9IVX]+\.?\s+)?(?:references|bibliography|works\s+cited)\s*$",
    re.I,
)

APPENDIX_HEADING_RE = re.compile(
    r"^#*\s*(?:(?:appendix|appendices|supplementary\s+material)(?:\s+[A-Z0-9]+)?\b|[A-Z]\.?\s+(?:additional|implementation|hyperparameter|proof|ablation|experimental|further|more)\b)",
    re.I,
)

ARXIV_ID_RE = re.compile(r"arxiv[:\s/]+([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", re.I)


def normalize_url(url_or_path: str) -> str:
    """Normalize input URL, handling file:// and arXiv URLs."""
    if url_or_path.startswith("file://"):
        parsed = urllib.parse.urlparse(url_or_path)
        path = urllib.parse.unquote(parsed.path)
        if re.match(r"^/[a-zA-Z]:", path):
            path = path.lstrip("/")
        return path
    if url_or_path.startswith(("http://", "https://")):
        arxiv_m = re.search(r"arxiv\.org/(?:abs|html|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", url_or_path)
        if arxiv_m:
            # /abs/ and /pdf/ both map to PDF; /html/ is the HTML version
            # and must NOT get .pdf appended blindly — route via export arXiv.
            if "/html/" in url_or_path:
                return f"https://export.arxiv.org/pdf/{arxiv_m.group(1)}.pdf"
            return f"https://arxiv.org/pdf/{arxiv_m.group(1)}.pdf"
    return url_or_path


def validate_pdf_bytes(data: bytes, url: str) -> None:
    if len(data) < 1024:
        raise ValueError(f"Downloaded file too small ({len(data)} bytes) from {url}; not a valid PDF.")
    if not data[:5].startswith(b"%PDF"):
        raise ValueError(f"Downloaded content from {url} is not a PDF (missing %PDF header).")
    if len(data) > 200 * 1024 * 1024:
        raise ValueError(f"Downloaded PDF too large ({len(data) // (1024*1024)} MB); refusing to process.")


def fetch(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "_", text).strip("_")
    return slug[:55] or "paper"


def thesis_base() -> pathlib.Path:
    """Default output base: $THESIS_OUT, else E:/thesis if E:/ exists, else cwd/thesis."""
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


def span_is_mono(span: dict) -> bool:
    return bool(span.get("flags", 0) & 8) or bool(MONO_FONT_RE.search(span.get("font", "")))


def rect_overlap_ratio(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    area_a = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return (x1 - x0) * (y1 - y0) / area_a


def center_inside(a, b) -> bool:
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


def cluster_rects(rects: list[tuple[float, float, float, float]], gap: float = 12.0):
    boxes = [list(r) for r in rects]
    changed = True
    while changed:
        changed = False
        out = []
        while boxes:
            cur = boxes.pop(0)
            i = 0
            while i < len(boxes):
                o = boxes[i]
                if not (cur[2] + gap < o[0] or o[2] + gap < cur[0] or cur[3] + gap < o[1] or o[3] + gap < cur[1]):
                    cur = [min(cur[0], o[0]), min(cur[1], o[1]), max(cur[2], o[2]), max(cur[3], o[3])]
                    boxes.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(cur)
        boxes = out
    return [tuple(b) for b in boxes]


def order_items(items: list[dict], page_width: float) -> list[dict]:
    """Column-aware reading order for two-column research papers."""
    mid = page_width / 2
    narrow = [it for it in items if (it["bbox"][2] - it["bbox"][0]) < page_width * 0.48]
    left_n = [it for it in narrow if it["bbox"][2] <= mid + page_width * 0.05]
    right_n = [it for it in narrow if it["bbox"][0] >= mid - page_width * 0.05]

    if len(left_n) >= 2 and len(right_n) >= 2:
        bands = []
        cur_l, cur_r = [], []
        for it in sorted(items, key=lambda x: x["bbox"][1]):
            b = it["bbox"]
            is_wide = (b[2] - b[0]) >= page_width * 0.55 or (b[0] < mid - 25 and b[2] > mid + 25)
            if is_wide:
                if cur_l or cur_r:
                    bands.extend(sorted(cur_l, key=lambda x: x["bbox"][1]))
                    bands.extend(sorted(cur_r, key=lambda x: x["bbox"][1]))
                    cur_l, cur_r = [], []
                bands.append(it)
            elif (b[0] + b[2]) / 2 < mid:
                cur_l.append(it)
            else:
                cur_r.append(it)
        bands.extend(sorted(cur_l, key=lambda x: x["bbox"][1]))
        bands.extend(sorted(cur_r, key=lambda x: x["bbox"][1]))
        return bands

    return sorted(items, key=lambda x: (round(x["bbox"][1] / 8), x["bbox"][0]))


def render_code(lines: list[tuple[float, list[dict]]]) -> str:
    raw = []
    for x0, spans in lines:
        txt = "".join(s["text"] for s in spans).rstrip()
        if txt.strip():
            raw.append((x0, txt))
    if not raw:
        return ""
    base_x = min(x for x, _ in raw)
    char_w = 5.0
    for _, spans in lines:
        for s in spans:
            if len(s["text"].strip()) >= 4:
                w = (s["bbox"][2] - s["bbox"][0]) / len(s["text"])
                if 2.5 <= w <= 12:
                    char_w = w
                    break
    out = []
    for x0, txt in raw:
        indent = max(0, round((x0 - base_x) / max(char_w, 1))) if x0 - base_x > char_w * 0.6 else 0
        out.append(" " * min(indent, 32) + txt)
    return "```\n" + "\n".join(out) + "\n```"


def render_prose(lines: list[tuple[float, list[dict]]]) -> str:
    out_lines = []
    for _, spans in lines:
        parts = []
        i = 0
        while i < len(spans):
            s = spans[i]
            t = s["text"]
            if not t:
                i += 1
                continue
            if span_is_mono(s) and t.strip():
                mono = [t]
                i += 1
                while i < len(spans) and (span_is_mono(spans[i]) or not spans[i]["text"].strip()):
                    mono.append(spans[i]["text"])
                    i += 1
                code_str = "".join(mono).strip()
                lead = " " if mono[0][:1].isspace() else ""
                trail = " " if mono[-1][-1:].isspace() else ""
                parts.append(f"{lead}`{code_str}`{trail}")
            else:
                parts.append(t)
                i += 1
        line = "".join(parts).strip()
        if line:
            out_lines.append(line)

    if not out_lines:
        return ""

    if len(out_lines) > 1 and sum(1 for l in out_lines if l[:1] in BULLET_CHARS or re.match(r"^\d+[.)]\s", l)) >= len(out_lines) * 0.5:
        normalized = []
        for l in out_lines:
            if l[:1] in BULLET_CHARS:
                normalized.append("- " + l[1:].strip())
            else:
                normalized.append(l)
        return "\n".join(normalized)

    merged = out_lines[0]
    for l in out_lines[1:]:
        if merged.endswith("-") and l[:1].islower() and not merged.endswith("--"):
            merged = merged[:-1] + l
        else:
            merged += " " + l
    if merged[:1] in BULLET_CHARS:
        merged = "- " + merged[1:].strip()
    return merged


def extract_pdf(local_pdf: pathlib.Path, workdir: pathlib.Path, doc_name: str, source_input: str = "") -> dict:
    try:
        import pymupdf
    except ImportError:
        print("[-] PyMuPDF not installed. Run: python -m pip install pymupdf", file=sys.stderr)
        sys.exit(1)

    figures_dir = workdir / "figures"
    pages_dir = workdir / "pages"
    doc = pymupdf.open(str(local_pdf))
    total_pages = len(doc)

    # Detect arXiv ID from source input or first page text
    arxiv_id = None
    m_in = re.search(r"([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", source_input)
    if m_in:
        arxiv_id = m_in.group(1)
    if not arxiv_id and total_pages >= 1:
        p1_raw = doc[0].get_text("text")
        m_p1 = ARXIV_ID_RE.search(p1_raw)
        if m_p1:
            arxiv_id = m_p1.group(1)

    title = (doc.metadata.get("title") or "").strip()
    if not title or len(title) < 4 or title.lower().startswith(("untitled", "microsoft word", "arxiv")):
        title = ""

    raw_toc = doc.get_toc()
    toc_entries = [{"level": lvl, "title": t.strip(), "page": p} for lvl, t, p in raw_toc if t.strip()]

    # First pass: body font size, repeated running headers/footers, decorative images, and paper title on page 1
    size_weights: collections.Counter = collections.Counter()
    margin_texts: collections.Counter = collections.Counter()
    img_xref_pages: collections.Counter = collections.Counter()
    p1_largest_candidates = []

    for p_idx, page in enumerate(doc):
        ph = page.rect.height
        for img in page.get_images(full=True):
            img_xref_pages[img[0]] += 1
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            bbox = b["bbox"]
            txt = " ".join("".join(s["text"] for s in ln["spans"]).strip() for ln in b["lines"]).strip()
            if not txt:
                continue
            if bbox[1] < ph * 0.08 or bbox[3] > ph * 0.92:
                norm = re.sub(r"\d+", "#", txt).strip()
                if norm:
                    margin_texts[norm] += 1
                continue
            for ln in b["lines"]:
                for s in ln["spans"]:
                    t = s["text"].strip()
                    if t and not span_is_mono(s):
                        size_weights[round(s["size"], 1)] += len(t)
                        if p_idx == 0 and bbox[1] < ph * 0.42 and len(t) >= 4:
                            p1_largest_candidates.append((round(s["size"], 1), bbox[1], txt))

    body_size = size_weights.most_common(1)[0][0] if size_weights else 10.0
    if not title and p1_largest_candidates:
        p1_largest_candidates.sort(key=lambda x: (-x[0], x[1]))
        top_title = p1_largest_candidates[0][2].strip()
        if 6 <= len(top_title) <= 220:
            title = re.sub(r"\s+", " ", top_title)
    if not title:
        title = doc_name

    repeat_min = max(3, int(total_pages * 0.25))
    repeated_margins = {t for t, c in margin_texts.items() if c >= repeat_min}
    decorative_xrefs = {x for x, c in img_xref_pages.items() if c >= repeat_min and total_pages > 5}

    print(f"[+] Opening Paper PDF: '{title}' ({total_pages} pages, body font ~{body_size}pt, arXiv={arxiv_id or 'N/A'})")

    stats = {"code_blocks": 0, "tables": 0, "raster_figures": 0, "vector_figures": 0, "margin_dropped": 0}
    detected_headings = []
    extracted_xrefs = set()
    empty_pages = 0
    references_start_page = None
    appendix_start_page = None
    extracted_references_lines = []
    in_references = False

    for page_idx, page in enumerate(doc):
        page_num = page_idx + 1
        pw, ph = page.rect.width, page.rect.height
        items = []

        # 1. Tables
        table_boxes = []
        try:
            for tab in page.find_tables().tables:
                rows = tab.extract()
                if not rows or len(rows) < 2:
                    continue
                non_empty = sum(1 for r in rows for c in r if c and str(c).strip())
                if non_empty < 4:
                    continue
                tb = tuple(tab.bbox)
                if tb[1] < ph * 0.06 or tb[3] > ph * 0.94:
                    continue
                cleaned = [[re.sub(r"\s+", " ", (c or "")).strip().replace("|", "\\|") for c in r] for r in rows]
                width = max(len(r) for r in cleaned)
                cleaned = [r + [""] * (width - len(r)) for r in cleaned]
                md = ["| " + " | ".join(cleaned[0]) + " |",
                      "| " + " | ".join(["---"] * width) + " |"]
                for r in cleaned[1:]:
                    if any(r):
                        md.append("| " + " | ".join(r) + " |")
                if len(md) >= 3:
                    table_boxes.append(tb)
                    items.append({"kind": "table", "bbox": tb, "md": "\n".join(md)})
                    stats["tables"] += 1
        except Exception:
            pass

        # 2. Text blocks
        code_boxes = []
        for b in page.get_text("dict")["blocks"]:
            if b.get("type") != 0:
                continue
            bbox = tuple(b["bbox"])
            if any(rect_overlap_ratio(bbox, tb) > 0.55 for tb in table_boxes):
                continue

            raw_txt = " ".join("".join(s["text"] for s in ln["spans"]).strip() for ln in b["lines"]).strip()
            if not raw_txt:
                continue

            in_margin = bbox[1] < ph * 0.07 or bbox[3] > ph * 0.93
            if in_margin:
                norm = re.sub(r"\d+", "#", raw_txt).strip()
                if norm in repeated_margins or re.fullmatch(r"[\d\s\-–—ivxlcdmIVXLCDM/]+", raw_txt) or len(raw_txt) < 60:
                    stats["margin_dropped"] += 1
                    continue

            lines = []
            total_chars, mono_chars, max_size, bold_chars = 0, 0, 0.0, 0
            for ln in b["lines"]:
                spans = [s for s in ln["spans"] if s["text"]]
                if not spans:
                    continue
                x0 = min(s["bbox"][0] for s in spans)
                lines.append((x0, spans))
                for s in spans:
                    n = len(s["text"].strip())
                    if n:
                        total_chars += n
                        if span_is_mono(s):
                            mono_chars += n
                        if s.get("flags", 0) & 16 or "bold" in (s.get("font", "") or "").lower():
                            bold_chars += n
                        max_size = max(max_size, s["size"])

            if not total_chars:
                continue

            if mono_chars / total_chars >= 0.72 and (len(lines) >= 2 or total_chars >= 25):
                code_boxes.append(bbox)
                items.append({"kind": "code", "bbox": bbox, "lines": lines})
                continue

            clean_single = re.sub(r"\s+", " ", raw_txt).strip()
            is_size_heading = len(lines) <= 3 and len(clean_single) <= 130 and max_size >= body_size * 1.15
            is_academic_heading = (
                len(lines) <= 2
                and len(clean_single) <= 100
                and (bold_chars / max(total_chars, 1) >= 0.6 or max_size >= body_size * 1.05)
                and bool(ACADEMIC_SECTION_RE.match(clean_single))
            )

            if is_size_heading or is_academic_heading:
                lvl = 1 if (max_size >= body_size * 1.32 or re.match(r"^(?:[0-9]{1,2}|[IVX]{1,4})\.?\s+[A-Z]|^(?:abstract|references|bibliography|appendix|conclusion)", clean_single, re.I)) else 2
                items.append({"kind": "heading", "bbox": bbox, "md": f"{'#' * lvl} {clean_single}", "level": lvl, "title": clean_single})
                continue

            items.append({"kind": "prose", "bbox": bbox, "lines": lines})

        # 3. Vector figures (plots, architecture diagrams)
        vector_boxes = []
        try:
            drawings = page.get_drawings()
            if 8 <= len(drawings) <= 4000:
                d_rects = []
                for d in drawings:
                    r = d.get("rect")
                    if not r or r.is_empty:
                        continue
                    if r.width > pw * 0.95 and r.height > ph * 0.95:
                        continue
                    if r.width < 2 and r.height < 2:
                        continue
                    if r.y0 < ph * 0.06 or r.y1 > ph * 0.94:
                        continue
                    d_rects.append((r.x0, r.y0, r.x1, r.y1))
                for rb in cluster_rects(d_rects, gap=10.0):
                    w, h = rb[2] - rb[0], rb[3] - rb[1]
                    if w < 90 or h < 65 or w * h < 9000:
                        continue
                    if any(rect_overlap_ratio(rb, cb) > 0.3 or rect_overlap_ratio(cb, rb) > 0.5 for cb in code_boxes + table_boxes):
                        continue
                    strokes = sum(
                        1 for dr in drawings if pymupdf.Rect(dr["rect"]).intersects(pymupdf.Rect(rb))
                        for it in dr["items"] if it[0] in ("l", "c", "qu")
                    )
                    if strokes < 8:
                        continue
                    inner_text = sum(
                        len(" ".join(s["text"] for _, sp in it["lines"] for s in sp))
                        for it in items if it["kind"] == "prose" and center_inside(it["bbox"], rb)
                    )
                    if inner_text > 450:
                        continue
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
            items = [it for it in items if it["kind"] == "figure" or it["kind"] == "heading"
                     or not any(center_inside(it["bbox"], vb) for vb in vector_boxes)]

        # 4. Raster figures
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

        # Order items and render page Markdown
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
                rendered = render_code(it["lines"])
                md_parts.append(rendered)
                stats["code_blocks"] += 1
            elif it["kind"] == "prose":
                rendered = render_prose(it["lines"])
                md_parts.append(rendered)
            else:
                rendered = it["md"]
                md_parts.append(rendered)

            if it["kind"] == "heading":
                h_title = it["title"]
                if REFERENCES_HEADING_RE.match(h_title):
                    if references_start_page is None:
                        references_start_page = page_num
                    in_references = True
                elif APPENDIX_HEADING_RE.match(h_title):
                    if appendix_start_page is None:
                        appendix_start_page = page_num
                    in_references = False
                if it["level"] <= 2:
                    detected_headings.append({"level": it["level"], "title": h_title, "page": page_num})

            if in_references and rendered.strip():
                extracted_references_lines.append(rendered.strip())

        page_md = "\n\n".join(p for p in md_parts if p.strip())
        if not page_md.strip():
            empty_pages += 1
        (pages_dir / f"page_{page_num:04d}.md").write_text(page_md, encoding="utf-8")

    if not toc_entries or len(toc_entries) < 2:
        toc_entries = detected_headings

    # Save extracted references to references.md for citation lookup and companion .md
    if extracted_references_lines:
        (workdir / "references.md").write_text("\n\n".join(extracted_references_lines), encoding="utf-8")

    # Extract abstract/first-page summary for literature scouting
    p1_md = (pages_dir / "page_0001.md").read_text(encoding="utf-8") if (pages_dir / "page_0001.md").exists() else ""
    abstract_preview = p1_md[:2500]

    print(f"[+] Extracted Paper: Code blocks={stats['code_blocks']} | Tables={stats['tables']} | "
          f"Figures={stats['raster_figures'] + stats['vector_figures']} | "
          f"References start p.{references_start_page or 'N/A'} | Appendix start p.{appendix_start_page or 'N/A'}")
    if empty_pages > total_pages * 0.5:
        print("[!] WARNING: Over 50% of pages are empty. PDF may be scanned requiring OCR.")

    return {
        "title": title,
        "arxiv_id": arxiv_id,
        "source_type": "pdf",
        "source_pdf": str(local_pdf),
        "total_pages": total_pages,
        "references_start_page": references_start_page,
        "appendix_start_page": appendix_start_page,
        "total_images": stats["raster_figures"] + stats["vector_figures"],
        "code_blocks": stats["code_blocks"],
        "tables": stats["tables"],
        "abstract_preview": abstract_preview,
        "toc": toc_entries,
    }


def extract_paper(doc_input: str, custom_workdir: str = None) -> pathlib.Path:
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
        workdir = thesis_base() / f"{safe_slug}_workdir"

    for d in ("pages", "figures", "source", "bangla"):
        (workdir / d).mkdir(parents=True, exist_ok=True)

    if is_url:
        print(f"[*] Downloading paper from: {input_str}")
        data, ctype = fetch(input_str)
        validate_pdf_bytes(data, input_str)
        local_pdf = workdir / (safe_slug + ".pdf")
        local_pdf.write_bytes(data)
        print(f"[+] Saved source PDF: {local_pdf} ({len(data) // 1024} KB)")
        meta = extract_pdf(local_pdf, workdir, doc_name, source_input=doc_input)
    else:
        p = pathlib.Path(doc_input).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Paper PDF not found: {doc_input}")
        meta = extract_pdf(p, workdir, doc_name, source_input=doc_input)

    (workdir / "toc.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[+] Paper extraction complete -> {workdir}")
    print(f"WORKDIR={workdir}")
    return workdir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract academic research paper PDF/URL into Markdown pages, figures, and metadata.")
    parser.add_argument("doc_input", help="Path or URL (e.g. arXiv link) to research paper PDF")
    parser.add_argument("workdir", nargs="?", default=None, help="Optional custom workdir")
    args = parser.parse_args()
    extract_paper(args.doc_input, args.workdir)
