# ================================================================
#  JOO AI — PERSISTENT VECTOR MEMORY  (Phase 5)
#  ✦ Remembers coding patterns, style preferences, bugs, project context
#  ✦ Zero external dependencies — pure JSON + cosine similarity
#  ✦ Survives restarts. Grows smarter over time.
# ================================================================

import os
import json
import math
import time
import re
from collections import Counter

MEMORY_PATH = os.path.expanduser("~/.joo/vector_memory.json")
MEMORY_MAX  = 500   # max stored memories before oldest pruned

# ----------------------------------------------------------------
#  TINY VECTORIZER — TF-IDF-style bag-of-words, no dependencies
# ----------------------------------------------------------------

_STOPWORDS = {
    "a","an","the","and","or","but","in","on","at","to","for","of",
    "is","it","be","was","are","this","that","with","as","by","from",
    "have","has","had","not","do","does","did","will","would","can",
    "could","should","my","your","we","i","you","they","he","she",
    "what","how","why","when","where","which","if","then","else",
}

def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z_#/][a-zA-Z0-9_#/]*", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]

def _vec(tokens: list[str]) -> dict[str, float]:
    counts = Counter(tokens)
    total  = sum(counts.values()) or 1
    return {t: c / total for t, c in counts.items()}

def _cosine(a: dict, b: dict) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot  = sum(a[k] * b[k] for k in keys)
    na   = math.sqrt(sum(v * v for v in a.values()))
    nb   = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


# ----------------------------------------------------------------
#  MEMORY STORE
# ----------------------------------------------------------------

def _load() -> list[dict]:
    if not os.path.exists(MEMORY_PATH):
        return []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save(memories: list[dict]) -> None:
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
    tmp_path = MEMORY_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(memories, f, indent=2)
    os.replace(tmp_path, MEMORY_PATH)  # atomic write — never corrupts on crash


# ----------------------------------------------------------------
#  PUBLIC API
# ----------------------------------------------------------------

def remember(user_text: str, joo_response: str, tags: list[str] | None = None) -> None:
    """Store a conversation turn as a memory with vector embedding."""
    memories = _load()

    combined = f"{user_text} {joo_response}"
    tokens   = _tokenize(combined)
    vec      = _vec(tokens)

    entry = {
        "time":     time.strftime("%Y-%m-%d %H:%M:%S"),
        "user":     user_text[:500],
        "response": joo_response[:1000],
        "tags":     list(dict.fromkeys(tags or _auto_tag(user_text, joo_response))),
        "vector":   vec,
    }

    memories.append(entry)

    # Prune oldest if over limit
    if len(memories) > MEMORY_MAX:
        memories = memories[-MEMORY_MAX:]

    _save(memories)


def recall(query: str, top_k: int = 5, min_score: float = 0.12) -> list[dict]:
    """Return the top_k most relevant memories for the given query."""
    if not query or not query.strip():
        return []
    memories = _load()
    if not memories:
        return []

    qvec = _vec(_tokenize(query))
    scored = []
    for m in memories:
        score = _cosine(qvec, m.get("vector", {}))
        if score >= min_score:
            scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored[:top_k]]


def recall_by_tag(tag: str) -> list[dict]:
    """Return all memories matching a tag (e.g. 'bug', 'style', 'project')."""
    return [m for m in _load() if tag.lower() in [t.lower() for t in m.get("tags", [])]]


def memory_stats() -> dict:
    """Return stats about the memory store."""
    memories = _load()
    tag_counts: Counter = Counter()
    for m in memories:
        for t in m.get("tags", []):
            tag_counts[t] += 1
    return {
        "total":    len(memories),
        "path":     MEMORY_PATH,
        "top_tags": tag_counts.most_common(8),
        "oldest":   memories[0]["time"]  if memories else None,
        "newest":   memories[-1]["time"] if memories else None,
    }


def forget_all() -> None:
    """Wipe all vector memories."""
    _save([])


def build_memory_context(query: str, top_k: int = 4) -> str:
    """
    Build a compact context block from relevant memories.
    Inject this into prompts so Joo 'remembers' past sessions.
    """
    hits = recall(query, top_k=top_k)
    if not hits:
        return ""

    lines = ["━━━ MEMORY CONTEXT (Phase 5 — Persistent Memory) ━━━━━━"]
    for i, m in enumerate(hits, 1):
        lines.append(f"\n[Memory #{i}  |  {m['time']}  |  tags: {', '.join(m.get('tags', []))}]")
        lines.append(f"  YOU:  {m['user'][:200]}")
        lines.append(f"  JOO:  {m['response'][:300]}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ----------------------------------------------------------------
#  AUTO-TAGGER — classifies memories without ML
# ----------------------------------------------------------------

_TAG_RULES = [
    (["bug", "error", "fix", "traceback", "exception", "crash", "fail"],   "bug"),
    (["style", "naming", "format", "convention", "pep8", "lint"],           "style"),
    (["pattern", "architecture", "design", "structure", "class", "module"], "architecture"),
    (["performance", "slow", "optimize", "speed", "cache", "memory"],       "performance"),
    (["security", "injection", "vuln", "auth", "token", "password"],        "security"),
    (["test", "unittest", "pytest", "assert", "coverage", "mock"],          "testing"),
    (["refactor", "clean", "smell", "duplicate", "extract"],                "refactor"),
    (["git", "commit", "diff", "branch", "merge", "pr", "review"],          "git"),
    (["import", "dependency", "package", "module", "install"],              "deps"),
    (["project", "folder", "directory", "workspace", "setup"],              "project"),
]

def _auto_tag(user_text: str, joo_response: str) -> list[str]:
    combined = (user_text + " " + joo_response).lower()
    tags = []
    for keywords, tag in _TAG_RULES:
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    return tags or ["general"]
