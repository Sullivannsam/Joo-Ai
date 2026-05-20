# ================================================================
#  JOO AI — WEB SEARCH MODE  (Phase 10 — v2, faster)
#  ✦ Snippets-first: returns results immediately without page fetches
#  ✦ fetch_pages=True only when explicitly requested
#  ✦ Parallel page fetching (ThreadPoolExecutor) when pages needed
#  ✦ Smarter query enhancement for security/error/library topics
#  ✦ Zero external API keys needed — uses DuckDuckGo HTML scraping
# ================================================================

import re
import json
import os
import urllib.request
import urllib.parse
import urllib.error
import html
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Config ────────────────────────────────────────────────────────

MAX_RESULTS    = 6     # search results to fetch
MAX_PAGE_CHARS = 5000  # characters to pull from each page
SEARCH_TIMEOUT = 10    # seconds per HTTP request
MAX_PAGE_WORKERS = 3   # parallel page fetches

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Session-level cache to avoid re-fetching
_CACHE: dict[str, str] = {}


# ── HTTP helpers ──────────────────────────────────────────────────

def _fetch(url: str, timeout: int = SEARCH_TIMEOUT) -> str:
    if url in _CACHE:
        return _CACHE[url]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(MAX_PAGE_CHARS * 4).decode("utf-8", errors="ignore")
        _CACHE[url] = raw
        return raw
    except Exception:
        return ""


# ── HTML → plain text ─────────────────────────────────────────────

def _strip_html(raw: str) -> str:
    raw = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"\s{2,}", " ", raw)
    return raw.strip()


def _extract_text(raw: str, max_chars: int = MAX_PAGE_CHARS) -> str:
    return _strip_html(raw)[:max_chars]


# ── DuckDuckGo search ─────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = MAX_RESULTS) -> list[dict]:
    encoded = urllib.parse.quote_plus(query)
    url     = f"https://html.duckduckgo.com/html/?q={encoded}"
    raw     = _fetch(url)
    if not raw:
        return []

    results  = []
    links    = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', raw, re.DOTALL)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', raw, re.DOTALL)

    for i, (href, title) in enumerate(links[:max_results]):
        real_url = href
        if "uddg=" in href:
            try:
                parsed   = urllib.parse.urlparse(href)
                params   = urllib.parse.parse_qs(parsed.query)
                real_url = params.get("uddg", [href])[0]
                real_url = urllib.parse.unquote(real_url)
            except Exception:
                pass

        snippet = _strip_html(snippets[i]) if i < len(snippets) else ""
        title   = _strip_html(title)

        results.append({
            "title":   title[:120],
            "url":     real_url,
            "snippet": snippet[:300],
        })

    return results


# ── Parallel page fetcher ─────────────────────────────────────────

def _fetch_page_text(url: str) -> str:
    if any(url.lower().endswith(ext) for ext in [".pdf", ".zip", ".png", ".jpg", ".mp4"]):
        return ""
    raw = _fetch(url)
    return _extract_text(raw)


def _fetch_pages_parallel(urls: list[str], max_workers: int = MAX_PAGE_WORKERS) -> list[dict]:
    """Fetch multiple pages in parallel. Much faster than sequential."""
    pages = []
    results_map: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(_fetch_page_text, url): url for url in urls}
        for future in as_completed(future_to_url, timeout=15):
            url  = future_to_url[future]
            try:
                text = future.result()
                if text and len(text) > 200:
                    results_map[url] = text
            except Exception:
                pass

    # Return in original order
    for url in urls:
        if url in results_map:
            pages.append({"url": url, "text": results_map[url]})

    return pages


# ── Auto-detect "I don't know" signals ───────────────────────────

_UNKNOWN_PATTERNS = [
    r"I don.t have information",
    r"I don.t know",
    r"my knowledge cutoff",
    r"I.m not familiar with",
    r"I cannot find",
    r"no information about",
    r"haven.t heard of",
    r"not aware of",
]

def should_web_search(joo_response: str) -> bool:
    lower = joo_response.lower()
    return any(re.search(p, lower, re.IGNORECASE) for p in _UNKNOWN_PATTERNS)


# ── Query enhancer ────────────────────────────────────────────────

def _enhance_query(raw_query: str) -> str:
    q = raw_query.strip()

    # Security queries → add site hints
    if any(kw in q.lower() for kw in ["cve", "vulnerability", "exploit", "security"]):
        return f"{q} security advisory"

    # Error messages → add fix hint
    if any(kw in q.lower() for kw in ["error", "exception", "traceback", "undefined", "cannot", "failed", "typeerror"]):
        return f"{q} solution fix"

    # Package/library name alone → add docs hint
    if re.match(r"^[\w-]+$", q) and len(q) < 40:
        return f"{q} documentation"

    return q


# ── Main search function ──────────────────────────────────────────

def web_search(query: str, fetch_pages: bool = False) -> dict:
    """
    Run a web search.
    fetch_pages=False (default) — fast: snippets only, answer in ~2s
    fetch_pages=True            — deep: fetches top 3 pages in parallel
    """
    enhanced = _enhance_query(query)
    results  = _ddg_search(enhanced, max_results=MAX_RESULTS)

    if not results:
        return {
            "query":   query,
            "results": [],
            "pages":   [],
            "error":   "No results found (network issue or DDG blocked).",
        }

    pages = []
    if fetch_pages:
        urls  = [r["url"] for r in results[:3]]
        pages = _fetch_pages_parallel(urls)
        # Attach title from search results to each page
        url_to_title = {r["url"]: r["title"] for r in results}
        for p in pages:
            p["title"] = url_to_title.get(p["url"], p["url"])

    return {
        "query":           query,
        "enhanced_query":  enhanced,
        "results":         results,
        "pages":           pages,
        "error":           None,
    }


# ── RAG context builder ───────────────────────────────────────────

def build_web_context(search_result: dict) -> str:
    query   = search_result.get("query", "")
    results = search_result.get("results", [])
    pages   = search_result.get("pages", [])
    error   = search_result.get("error")

    if error and not results:
        return f"WEB SEARCH ERROR: {error}"

    lines = [
        f"━━━ WEB SEARCH CONTEXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"QUERY: {query}",
        f"",
        "── SEARCH RESULTS ─────────────────────────────────────",
    ]

    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}")
        lines.append(f"    URL: {r['url']}")
        lines.append(f"    {r['snippet']}")
        lines.append("")

    if pages:
        lines.append("── PAGE CONTENTS (top results, truncated) ───────────────")
        for p in pages:
            lines.append(f"\nSOURCE: {p['url']}")
            lines.append(f"TITLE:  {p.get('title', '')}")
            lines.append(p["text"][:MAX_PAGE_CHARS])
            lines.append("···")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ── Prompt builder ────────────────────────────────────────────────

def build_web_prompt(user_question: str, web_context: str) -> str:
    return f"""
{web_context}

━━━ DEVELOPER QUESTION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{user_question}

━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Answer the question using the web search results above as context.

Guidelines:
  ✦ Prefer information from official docs, GitHub, or reputable sources
  ✦ If sources conflict, mention the discrepancy
  ✦ Always cite which source (URL or title) your answer comes from
  ✦ Show code examples if relevant
  ✦ If the web results don't fully answer the question, say so clearly

Structure:
  1. Direct answer
  2. Step-by-step explanation or code example
  3. Source citations
  4. Gotchas / caveats worth knowing
"""


# ── Convenience function ──────────────────────────────────────────

def search_and_build(question: str, fetch_pages: bool = False) -> tuple[str, dict]:
    """
    Search the web and return (prompt_string, raw_result_dict).
    fetch_pages defaults to False for speed — set True for deep answers.
    """
    result  = web_search(question, fetch_pages=fetch_pages)
    context = build_web_context(result)
    prompt  = build_web_prompt(question, context)
    return prompt, result
