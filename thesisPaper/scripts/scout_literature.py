"""Live Literature, Code & "Scoop Check" Scout for a research paper (v1.1).

Usage:
  python scout_literature.py "<workdir>"

Queries public academic & code APIs with graceful fallbacks:
1. Metadata from Semantic Scholar (merges arXiv + venue versions; reliable author names, citation counts,
   influential citations, TLDR) + arXiv + OpenAlex.
2. Real BibTeX: DBLP (prefers the published venue over CoRR) -> doi.org content negotiation -> generated fallback.
3. Code: repo links in the paper, HuggingFace Papers API (linked repo, models, datasets), GitHub search.
4. "Scoop Check": recent (2024+) citing papers from Semantic Scholar AND OpenAlex, merged and de-duplicated.
5. Writes <workdir>/scout_report.json and <workdir>/scout_summary.md.

Optional env vars: GITHUB_TOKEN (raises GitHub rate limit), S2_API_KEY (Semantic Scholar key),
OPENALEX_EMAIL (polite pool).
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding="utf-8")

UA = {"User-Agent": f"ThesisPaperSkill/1.1 (mailto:{os.environ.get('OPENALEX_EMAIL', 'research@example.com')})"}
S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,authors,year,venue,publicationVenue,citationCount,influentialCitationCount,externalIds,tldr,url,abstract"


def _headers(url: str, extra: dict = None) -> dict:
    h = dict(UA)
    if "api.github.com" in url and os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    if "semanticscholar.org" in url and os.environ.get("S2_API_KEY"):
        h["x-api-key"] = os.environ["S2_API_KEY"]
    if extra:
        h.update(extra)
    return h


def _fetch(url: str, timeout: int = 20, extra_headers: dict = None, retries: int = 3) -> str:
    """GET with backoff on 429/5xx (Semantic Scholar's shared pool rate-limits aggressively)."""
    for attempt in range(retries):
        req = urllib.request.Request(url, headers=_headers(url, extra_headers))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 + attempt * 4)
                continue
            return ""
        except Exception:
            if attempt < retries - 1:
                time.sleep(1.5)
                continue
            return ""
    return ""


def get_json(url: str, timeout: int = 20, extra_headers: dict = None):
    txt = _fetch(url, timeout, extra_headers)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def get_text(url: str, timeout: int = 20, extra_headers: dict = None) -> str:
    return _fetch(url, timeout, extra_headers)


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def _strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id or "")


# ------------------------------------------------------- Semantic Scholar
def query_semantic_scholar(arxiv_id: str, doi: str, title: str) -> dict:
    paper = None
    clean_id = _strip_version(arxiv_id)
    if clean_id:
        paper = get_json(f"{S2_BASE}/paper/arXiv:{clean_id}?fields={S2_FIELDS}")
    if not paper and doi:
        d = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
        paper = get_json(f"{S2_BASE}/paper/DOI:{urllib.parse.quote(d)}?fields={S2_FIELDS}")
    if not paper and title:
        m = get_json(f"{S2_BASE}/paper/search/match?query={urllib.parse.quote(title)}&fields={S2_FIELDS}")
        if m and m.get("data"):
            paper = m["data"][0]
    if not paper or not paper.get("paperId"):
        return {}
    pv = paper.get("publicationVenue") or {}
    return {
        "s2_id": paper["paperId"],
        "title": paper.get("title"),
        "authors": [a.get("name") for a in (paper.get("authors") or []) if a.get("name")],
        "year": paper.get("year"),
        "venue": pv.get("name") or paper.get("venue") or "",
        "cited_by_count": paper.get("citationCount") or 0,
        "influential_citations": paper.get("influentialCitationCount") or 0,
        "external_ids": paper.get("externalIds") or {},
        "tldr": (paper.get("tldr") or {}).get("text", ""),
        "url": paper.get("url"),
        "abstract": paper.get("abstract") or "",
    }


def s2_recent_citations(s2_id: str, min_year: int = 2024, top: int = 10) -> list[dict]:
    out, offset = [], 0
    fields = "title,year,venue,citationCount,externalIds,abstract,url,authors"
    while offset < 1000:
        data = get_json(f"{S2_BASE}/paper/{s2_id}/citations?fields={fields}&limit=100&offset={offset}")
        if not data or not data.get("data"):
            break
        for row in data["data"]:
            cp = row.get("citingPaper") or {}
            if not cp.get("title") or (cp.get("year") or 0) < min_year:
                continue
            ext = cp.get("externalIds") or {}
            url = (f"https://arxiv.org/abs/{ext['ArXiv']}" if ext.get("ArXiv")
                   else (f"https://doi.org/{ext['DOI']}" if ext.get("DOI") else cp.get("url")))
            out.append({
                "title": cp["title"], "year": cp.get("year"), "venue": cp.get("venue") or "Preprint",
                "cited_by_count": cp.get("citationCount") or 0,
                "authors": [a.get("name") for a in (cp.get("authors") or [])[:3] if a.get("name")],
                "url": url, "abstract_snippet": (cp.get("abstract") or "")[:420], "source": "SemanticScholar",
            })
        if data.get("next") is None:
            break
        offset = data["next"]
    out.sort(key=lambda x: x["cited_by_count"], reverse=True)
    return out[:top]


def search_related(query: str, min_year: int = 2024, limit: int = 6) -> list[dict]:
    """Topic search (not citation-based) used by the per-blueprint novelty check.
    Semantic Scholar first, arXiv API as fallback."""
    results = []
    data = get_json(f"{S2_BASE}/paper/search?query={urllib.parse.quote(query)}&year={min_year}-"
                    f"&limit={limit}&fields=title,year,venue,citationCount,externalIds,abstract,url")
    for p in (data or {}).get("data") or []:
        ext = p.get("externalIds") or {}
        results.append({
            "title": p.get("title"), "year": p.get("year"), "venue": p.get("venue") or "Preprint",
            "cited_by_count": p.get("citationCount") or 0,
            "url": f"https://arxiv.org/abs/{ext['ArXiv']}" if ext.get("ArXiv") else p.get("url"),
            "abstract_snippet": (p.get("abstract") or "")[:500], "source": "SemanticScholar",
        })
    if results:
        return results
    words = re.findall(r"[A-Za-z0-9\-]{3,}", query)[:6]
    if not words:
        return []
    terms = "+AND+".join(f"all:{urllib.parse.quote(w)}" for w in words)
    xml_txt = get_text(f"http://export.arxiv.org/api/query?search_query={terms}&sortBy=submittedDate"
                       f"&sortOrder=descending&max_results={limit}")
    if not xml_txt:
        return []
    try:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for e in ET.fromstring(xml_txt).findall("a:entry", ns):
            year = int((e.findtext("a:published", "", ns) or "0")[:4] or 0)
            if year < min_year:
                continue
            results.append({
                "title": re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip(), "year": year,
                "venue": "arXiv", "cited_by_count": None,
                "url": (e.findtext("a:id", "", ns) or "").strip(),
                "abstract_snippet": re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip()[:500],
                "source": "arXiv",
            })
    except ET.ParseError:
        pass
    return results


# ------------------------------------------------------------------ BibTeX
def fetch_bibtex(title: str, doi: str = None, arxiv_id: str = None) -> tuple[str, str]:
    """Return (bibtex, source). Prefers DBLP's published-venue record, then DOI negotiation."""
    if title:
        data = get_json(f"https://dblp.org/search/publ/api?q={urllib.parse.quote(title)}&format=json&h=5")
        hits = (((data or {}).get("result") or {}).get("hits") or {}).get("hit") or []
        want = _norm_title(title)
        matches = [h["info"] for h in hits if _norm_title(h.get("info", {}).get("title", "")) == want]
        # Prefer the formally published record over the CoRR (arXiv) mirror.
        matches.sort(key=lambda i: (i.get("venue") == "CoRR", "Informal" in i.get("type", "")))
        for info in matches:
            bib = get_text(f"https://dblp.org/rec/{info['key']}.bib")
            if bib.strip().startswith("@"):
                return bib.strip(), f"DBLP ({info.get('venue', '')})"
    dois = []
    if doi:
        dois.append(re.sub(r"^https?://(dx\.)?doi\.org/", "", doi))
    if arxiv_id:
        dois.append(f"10.48550/arXiv.{_strip_version(arxiv_id)}")
    for d in dois:
        bib = get_text(f"https://doi.org/{d}", extra_headers={"Accept": "application/x-bibtex"})
        if bib.strip().startswith("@"):
            return bib.strip(), f"doi.org ({d})"
    return "", ""


def query_huggingface(arxiv_id: str) -> dict:
    if not arxiv_id:
        return {}
    clean_id = _strip_version(arxiv_id)
    out = {"paper_page": None, "github_repo": None, "models": [], "datasets": []}
    p = get_json(f"https://huggingface.co/api/papers/{clean_id}")
    if p and p.get("id"):
        out["paper_page"] = f"https://huggingface.co/papers/{clean_id}"
        out["github_repo"] = p.get("githubRepo")
        out["upvotes"] = p.get("upvotes")
    for kind in ("models", "datasets"):
        items = get_json(f"https://huggingface.co/api/{kind}?filter=arxiv:{clean_id}&sort=downloads&limit=8") or []
        out[kind] = [{"id": i.get("id"), "downloads": i.get("downloads"),
                      "url": f"https://huggingface.co/{'datasets/' if kind == 'datasets' else ''}{i.get('id')}"}
                     for i in items if isinstance(i, dict) and i.get("id")]
    return out


def reconstruct_openalex_abstract(inv_idx: dict) -> str:
    if not inv_idx or not isinstance(inv_idx, dict):
        return ""
    pos_map = {}
    for word, positions in inv_idx.items():
        for p in positions:
            pos_map[p] = word
    return " ".join(pos_map[k] for k in sorted(pos_map.keys()))


def query_arxiv(arxiv_id: str, title: str) -> dict:
    clean_id = re.sub(r"v\d+$", "", arxiv_id or "")
    if clean_id:
        q_url = f"http://export.arxiv.org/api/query?id_list={urllib.parse.quote(clean_id)}"
    else:
        clean_t = re.sub(r"[^a-zA-Z0-9\s]", " ", title).strip()
        q_url = f"http://export.arxiv.org/api/query?search_query=ti:{urllib.parse.quote(clean_t)}&max_results=1"
    xml_txt = get_text(q_url)
    if not xml_txt:
        return {}
    try:
        root = ET.fromstring(xml_txt)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entry = root.find("a:entry", ns)
        if entry is None:
            return {}
        e_title = re.sub(r"\s+", " ", (entry.findtext("a:title", "", ns) or "").strip())
        e_summary = re.sub(r"\s+", " ", (entry.findtext("a:summary", "", ns) or "").strip())
        e_pub = (entry.findtext("a:published", "", ns) or "")[:4]
        e_id_url = (entry.findtext("a:id", "", ns) or "").strip()
        m_id = re.search(r"([0-9]{4}\.[0-9]{4,5})", e_id_url)
        authors = [a.findtext("a:name", "", ns).strip() for a in entry.findall("a:author", ns) if a.findtext("a:name", "", ns)]
        return {
            "title": e_title,
            "authors": authors,
            "year": int(e_pub) if e_pub.isdigit() else None,
            "arxiv_id": m_id.group(1) if m_id else clean_id,
            "abstract": e_summary,
            "url": f"https://arxiv.org/abs/{m_id.group(1)}" if m_id else e_id_url,
        }
    except Exception:
        return {}


def query_openalex(title: str, arxiv_id: str = None) -> tuple[dict, list[dict]]:
    work = None
    if arxiv_id:
        clean_id = re.sub(r"v\d+$", "", arxiv_id)
        data = get_json(f"https://api.openalex.org/works?filter=ids.arxiv:https://arxiv.org/abs/{clean_id}&per-page=1")
        if data and data.get("results"):
            work = data["results"][0]

    if not work and title:
        clean_t = re.sub(r"[^\w\s]", " ", title).strip()
        data = get_json(f"https://api.openalex.org/works?search={urllib.parse.quote(clean_t)}&per-page=3")
        if data and data.get("results"):
            work = data["results"][0]

    if not work:
        return {}, []

    oa_id = work.get("id", "")
    authors = [
        a.get("author", {}).get("display_name", "")
        for a in (work.get("authorships") or [])
        if a.get("author", {}).get("display_name")
    ]
    loc = work.get("primary_location") or {}
    source = loc.get("source") or {}
    venue = source.get("display_name") or "arXiv / Preprint"
    paper_info = {
        "openalex_id": oa_id,
        "title": work.get("title") or title,
        "authors": authors,
        "year": work.get("publication_year"),
        "venue": venue,
        "cited_by_count": work.get("cited_by_count", 0),
        "doi": work.get("doi"),
        "abstract": reconstruct_openalex_abstract(work.get("abstract_inverted_index")),
    }

    # Fetch recent citing works (2024-2026) for the "Scoop Check"
    citing_papers = []
    short_oa_id = oa_id.rstrip("/").split("/")[-1]
    if short_oa_id:
        cite_url = (
            f"https://api.openalex.org/works?filter=cites:{short_oa_id},publication_year:>2023"
            f"&sort=cited_by_count:desc&per-page=8"
        )
        c_data = get_json(cite_url)
        if c_data and c_data.get("results"):
            for cw in c_data["results"]:
                c_authors = [
                    a.get("author", {}).get("display_name", "")
                    for a in (cw.get("authorships") or [])[:3]
                    if a.get("author", {}).get("display_name")
                ]
                c_loc = cw.get("primary_location") or {}
                c_src = c_loc.get("source") or {}
                citing_papers.append({
                    "title": cw.get("title", ""),
                    "year": cw.get("publication_year"),
                    "venue": c_src.get("display_name") or "Preprint",
                    "cited_by_count": cw.get("cited_by_count", 0),
                    "authors": c_authors,
                    "url": cw.get("doi") or c_loc.get("landing_page_url") or cw.get("id"),
                    "abstract_snippet": reconstruct_openalex_abstract(cw.get("abstract_inverted_index"))[:420],
                })

    return paper_info, citing_papers


def query_github_repos(title: str, arxiv_id: str = None, page1_text: str = "") -> list[dict]:
    repos = []
    seen = set()

    # 1. Check explicit github.com links in the paper text itself
    for m in re.finditer(r"https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", page1_text):
        slug = m.group(1).rstrip(".,;)")
        if slug.lower() not in seen:
            seen.add(slug.lower())
            repos.append({
                "full_name": slug,
                "url": f"https://github.com/{slug}",
                "stars": "Official (in paper)",
                "description": "Repository link extracted directly from the paper.",
                "official": True,
            })

    # 2. Search GitHub API by arXiv ID or paper title
    queries = []
    if arxiv_id:
        queries.append(re.sub(r"v\d+$", "", arxiv_id))
    if title and len(title) >= 8:
        short_title = " ".join(re.sub(r"[^\w\s]", " ", title).split()[:8])
        queries.append(f'"{short_title}"')

    for q in queries[:2]:
        gh_url = f"https://api.github.com/search/repositories?q={urllib.parse.quote(q)}&sort=stars&order=desc&per_page=4"
        data = get_json(gh_url)
        if data and data.get("items"):
            for item in data["items"]:
                fn = item.get("full_name", "")
                if fn and fn.lower() not in seen:
                    seen.add(fn.lower())
                    repos.append({
                        "full_name": fn,
                        "url": item.get("html_url", f"https://github.com/{fn}"),
                        "stars": item.get("stargazers_count", 0),
                        "description": (item.get("description") or "")[:200],
                        "language": item.get("language") or "Python",
                        "official": False,
                    })
    return repos[:6]


def make_bibtex(meta: dict) -> str:
    authors = meta.get("authors") or ["Unknown Author"]
    first_last = authors[0].split()[-1].lower() if authors[0] else "author"
    first_last = re.sub(r"[^a-z0-9]", "", first_last) or "paper"
    year = meta.get("year") or "2025"
    title_words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", meta.get("title") or "research") if w.lower() not in {"with", "from", "that", "this", "using", "towards", "based"}]
    kw = title_words[0] if title_words else "work"
    cite_key = f"{first_last}{year}{kw}"
    author_str = " and ".join(authors[:8]) + (" and others" if len(authors) > 8 else "")
    venue = meta.get("venue") or ("arXiv preprint arXiv:" + str(meta["arxiv_id"]) if meta.get("arxiv_id") else "arXiv preprint")
    lines = [
        f"@article{{{cite_key},",
        f"  title={{{meta.get('title', 'Untitled Paper')}}},",
        f"  author={{{author_str}}},",
        f"  journal={{{venue}}},",
        f"  year={{{year}}},",
    ]
    if meta.get("doi"):
        lines.append(f"  url={{{meta['doi']}}},")
    elif meta.get("arxiv_id"):
        lines.append(f"  eprint={{{meta['arxiv_id']}}},")
        lines.append("  archivePrefix={arXiv},")
    lines.append("}")
    return "\n".join(lines)


def scout_paper(workdir_path: str) -> dict:
    workdir = pathlib.Path(workdir_path).resolve()
    toc_file = workdir / "toc.json"
    if not toc_file.exists():
        raise FileNotFoundError(f"Missing toc.json in {workdir}. Run extract_paper.py first.")
    toc = json.loads(toc_file.read_text(encoding="utf-8"))

    title = toc.get("title") or ""
    arxiv_id = toc.get("arxiv_id")

    # Scan ALL pages for explicit GitHub/HuggingFace URLs (code links often live in the appendix)
    all_text_sample = ""
    for p_file in sorted((workdir / "pages").glob("page_*.md")):
        all_text_sample += "\n" + p_file.read_text(encoding="utf-8", errors="replace")

    print(f"[*] Scouting literature, code repos, and 2024+ citations for: '{title}' (arXiv={arxiv_id or 'N/A'}) ...")
    arxiv_info = query_arxiv(arxiv_id, title)
    if not arxiv_id and arxiv_info.get("arxiv_id"):
        arxiv_id = arxiv_info["arxiv_id"]
    best_title = arxiv_info.get("title") or title

    oa_info, oa_citing = query_openalex(best_title, arxiv_id)
    s2_info = query_semantic_scholar(arxiv_id, oa_info.get("doi"), best_title)
    print(f"    • Semantic Scholar: {'found' if s2_info else 'not found'}"
          f"{' (' + str(s2_info.get('cited_by_count')) + ' citations)' if s2_info else ''}; "
          f"OpenAlex: {oa_info.get('cited_by_count', 'n/a')} citations")

    s2_ext = s2_info.get("external_ids") or {}
    venue = s2_info.get("venue") or oa_info.get("venue") or ("arXiv" if arxiv_id else "Conference / Preprint")
    merged_meta = {
        "title": s2_info.get("title") or oa_info.get("title") or best_title,
        # S2 / arXiv author names are complete; OpenAlex sometimes truncates them.
        "authors": s2_info.get("authors") or arxiv_info.get("authors") or oa_info.get("authors") or [],
        "year": s2_info.get("year") or oa_info.get("year") or arxiv_info.get("year"),
        "venue": venue,
        "arxiv_id": arxiv_id,
        "doi": (f"https://doi.org/{s2_ext['DOI']}" if s2_ext.get("DOI") else None) or oa_info.get("doi"),
        # OpenAlex often matches only the arXiv record (0 citations); take the best available count.
        "cited_by_count": max(s2_info.get("cited_by_count") or 0, oa_info.get("cited_by_count") or 0),
        "influential_citations": s2_info.get("influential_citations", 0),
        "semantic_scholar_url": s2_info.get("url"),
        "tldr": s2_info.get("tldr", ""),
        "abstract": arxiv_info.get("abstract") or s2_info.get("abstract") or oa_info.get("abstract") or toc.get("abstract_preview", ""),
    }
    bib, bib_src = fetch_bibtex(merged_meta["title"], merged_meta.get("doi"), arxiv_id)
    merged_meta["bibtex"] = bib or make_bibtex(merged_meta)
    merged_meta["bibtex_source"] = bib_src or "generated (verify manually)"
    if "arxiv" in merged_meta["bibtex"].lower()[:200] and venue and "arxiv" not in venue.lower():
        # DBLP is bot-protected for scripts; the arXiv DOI record is correct but cite the venue version if published.
        merged_meta["bibtex"] = (f"% NOTE: Semantic Scholar lists a published version at '{venue}'. "
                                 f"Prefer that venue's official BibTeX (e.g. from dblp.org) in your thesis.\n"
                                 + merged_meta["bibtex"])

    # Merge citing papers from Semantic Scholar + OpenAlex, de-duplicated by normalized title and arXiv/DOI id.
    s2_citing = s2_recent_citations(s2_info["s2_id"]) if s2_info.get("s2_id") else []
    citing_papers, seen_t = [], set()
    for cp in s2_citing + oa_citing:
        k = _norm_title(cp.get("title"))
        ids = set(re.findall(r"(\d{4}\.\d{4,5})", str(cp.get("url") or "")))
        if not k or k in seen_t or ids & seen_t:
            continue
        seen_t.add(k)
        seen_t |= ids
        citing_papers.append(cp)
    citing_papers.sort(key=lambda x: x.get("cited_by_count") or 0, reverse=True)
    citing_papers = citing_papers[:12]

    repos = query_github_repos(merged_meta["title"], arxiv_id, all_text_sample)
    hf = query_huggingface(arxiv_id)
    if hf.get("github_repo") and not any(r["url"].rstrip("/").lower() == hf["github_repo"].rstrip("/").lower() for r in repos):
        slug = re.sub(r"^https?://github\.com/", "", hf["github_repo"]).strip("/")
        repos.insert(0, {"full_name": slug, "url": hf["github_repo"], "stars": "Linked on HF Papers",
                         "description": "Repository linked from the HuggingFace Papers page.", "official": True})

    # Extract explicit HuggingFace links from paper text
    hf_links = sorted(set(re.findall(r"https?://huggingface\.co/[A-Za-z0-9_.\-/]+", all_text_sample)))

    report = {
        "paper": merged_meta,
        "github_repos": repos,
        "huggingface_links": hf_links,
        "huggingface": hf,
        "recent_citing_papers": citing_papers,
    }

    (workdir / "scout_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Also write a human/agent readable Markdown summary
    md_lines = [
        f"# Literature & Code Scout Report: {merged_meta['title']}",
        f"- **Authors:** {', '.join(merged_meta['authors'][:6]) or 'N/A'}",
        f"- **Year / Venue:** {merged_meta.get('year') or 'N/A'} | {merged_meta.get('venue')}",
        f"- **arXiv / DOI:** {merged_meta.get('arxiv_id') or 'N/A'} | {merged_meta.get('doi') or 'N/A'}",
        f"- **Citations:** {merged_meta.get('cited_by_count', 0)} (influential: {merged_meta.get('influential_citations', 0)}; "
        f"Semantic Scholar + OpenAlex)",
    ]
    if merged_meta.get("tldr"):
        md_lines.append(f"- **TLDR (Semantic Scholar):** {merged_meta['tldr']}")
    md_lines += ["", "## Discovered Code Repositories"]
    if repos:
        for r in repos:
            tag = "[OFFICIAL]" if r.get("official") else f"[★ {r.get('stars')}]"
            md_lines.append(f"- {tag} [{r['full_name']}]({r['url']}) — {r.get('description', '')}")
    else:
        md_lines.append("- No direct repository found via paper text / HF Papers / GitHub search (good opportunity for open-source reproduction!).")

    if hf.get("paper_page") or hf.get("models") or hf.get("datasets"):
        md_lines.append("\n## HuggingFace Artefacts Linked to this Paper")
        if hf.get("paper_page"):
            md_lines.append(f"- Paper page: {hf['paper_page']}")
        for m in hf.get("models", []):
            md_lines.append(f"- Model: [{m['id']}]({m['url']}) (downloads: {m.get('downloads')})")
        for d in hf.get("datasets", []):
            md_lines.append(f"- Dataset: [{d['id']}]({d['url']}) (downloads: {d.get('downloads')})")

    md_lines.append("\n## Recent Citing / Follow-Up Papers (2024+ 'Scoop Check' — REAL, fetched from APIs)")
    if citing_papers:
        for cp in citing_papers:
            md_lines.append(
                f"- **{cp['title']}** ({cp.get('year')}, {cp.get('venue')}, Citations: {cp.get('cited_by_count', 0)})\n"
                f"  - *Link:* {cp.get('url') or 'N/A'}\n"
                f"  - *Snippet:* {cp.get('abstract_snippet', '')}"
            )
    else:
        md_lines.append("- No 2024+ citing papers indexed yet (or paper is very recent). "
                        "Do NOT invent follow-up papers; say the scoop check is inconclusive.")

    md_lines.append(f"\n## BibTeX (source: {merged_meta['bibtex_source']})")
    md_lines.append("```bibtex\n" + merged_meta["bibtex"] + "\n```")
    (workdir / "scout_summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    print(f"[✓] Scout complete: {len(repos)} repo(s), {len(citing_papers)} recent citing paper(s), "
          f"BibTeX from {merged_meta['bibtex_source']} -> {workdir / 'scout_report.json'}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Scout official code, citations, BibTeX, and 2024-2026 follow-up papers.")
    ap.add_argument("workdir", help="Path to paper workdir")
    args = ap.parse_args()
    scout_paper(args.workdir)
