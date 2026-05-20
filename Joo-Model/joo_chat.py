# ================================================================
#  JOO AI — AI-POWERED CODEBASE CHAT  (Phase 8)
#  ✦ Ask anything about your repo in plain English
#  ✦ Reads the whole project, maps call chains, answers directly
#  ✦ Similar to Cursor's codebase chat — but lives in your terminal
# ================================================================

import os
import re
import ast
from collections import defaultdict

# ── Extensions that are worth reading ────────────────────────────
CHAT_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go",
    ".rs", ".php", ".rb", ".swift", ".kt", ".cs", ".cpp", ".c",
    ".sh", ".bash", ".html", ".css", ".json", ".yaml", ".yml",
    ".toml", ".md", ".env.example", ".sql",
}

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".mypy_cache", ".next",
}

MAX_FILES      = 80
MAX_FILE_BYTES = 30_000   # per-file read cap
MAX_TOTAL_CHARS = 120_000  # total context cap before trimming


# ── File collection ───────────────────────────────────────────────

def collect_repo_files(root: str) -> list[str]:
    results = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in CHAT_EXTS:
                results.append(os.path.join(dirpath, fname))
                if len(results) >= MAX_FILES:
                    return results
    return results


def _read_safe(path: str) -> str:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read(MAX_FILE_BYTES)
    except Exception:
        return ""


# ── Call chain mapper (Python) ────────────────────────────────────

def _map_call_chain_python(files: list[str]) -> dict[str, list[str]]:
    """
    Returns {function_name: [called_functions, ...]} for Python files.
    Used to answer "how does X work?" questions with actual call chains.
    """
    graph: dict[str, list[str]] = defaultdict(list)

    for path in files:
        if not path.endswith(".py"):
            continue
        source = _read_safe(path)
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                caller = node.name
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            graph[caller].append(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            graph[caller].append(child.func.attr)

    # deduplicate
    return {k: list(dict.fromkeys(v)) for k, v in graph.items()}


def _format_call_chain(graph: dict[str, list[str]], max_entries: int = 40) -> str:
    if not graph:
        return ""
    lines = ["── CALL CHAIN MAP (Python) ─────────────────────────────"]
    for fn, calls in list(graph.items())[:max_entries]:
        if calls:
            lines.append(f"  {fn}()  →  {', '.join(calls[:8])}")
    return "\n".join(lines)


# ── Index builder ─────────────────────────────────────────────────

def _build_symbol_index(files: list[str]) -> str:
    """
    Lightweight symbol index: lists all function/class definitions
    with their file so Joo knows where things live.
    """
    lines = ["── SYMBOL INDEX ────────────────────────────────────────"]
    for path in files:
        if not path.endswith(".py"):
            continue
        source = _read_safe(path)
        rel    = os.path.relpath(path)
        try:
            tree = ast.parse(source)
            defs = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.append(f"def {node.name}()")
                elif isinstance(node, ast.ClassDef):
                    defs.append(f"class {node.name}")
            if defs:
                lines.append(f"  {rel}: {', '.join(defs[:12])}")
        except SyntaxError:
            pass
    return "\n".join(lines)


# ── Relevance scorer ─────────────────────────────────────────────

def _score_file(path: str, source: str, query_tokens: set[str]) -> float:
    """
    Score a file for relevance to a query.
    Higher = more likely to contain the answer.
    """
    name_tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", os.path.basename(path).lower()))
    text_tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", source.lower()))

    name_hit  = len(query_tokens & name_tokens) * 3.0
    text_hit  = len(query_tokens & text_tokens) * 1.0
    size_pen  = min(len(source) / 10_000, 2.0)  # slight penalty for huge files

    return name_hit + text_hit - size_pen


def _pick_relevant_files(files: list[str], query: str, top_k: int = 20) -> list[str]:
    """Return the top_k files most relevant to the query."""
    query_tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", query.lower()))
    scored = []
    for path in files:
        source = _read_safe(path)
        score  = _score_file(path, source, query_tokens)
        scored.append((score, path))
    scored.sort(reverse=True)
    return [p for _, p in scored[:top_k]]


# ── Context assembler ─────────────────────────────────────────────

def build_chat_context(root: str, query: str) -> tuple[str, int, int]:
    """
    Build the full codebase context for the AI.
    Returns (context_string, total_files, relevant_files_used).
    """
    root  = os.path.abspath(os.path.expanduser(root))
    files = collect_repo_files(root)
    if not files:
        return "", 0, 0

    # Always include relevant files, fill remaining budget with others
    relevant = _pick_relevant_files(files, query, top_k=20)
    others   = [f for f in files if f not in relevant]

    call_chain = _map_call_chain_python(files)
    symbol_idx = _build_symbol_index(files)

    parts = [
        f"━━━ CODEBASE CHAT CONTEXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"ROOT:  {root}",
        f"TOTAL FILES FOUND: {len(files)}",
        f"",
        symbol_idx,
        "",
        _format_call_chain(call_chain),
        "",
        "━━━ FILE CONTENTS (most relevant first) ━━━━━━━━━━━━━━━",
        "",
    ]

    total_chars = sum(len(p) for p in parts)
    files_used  = 0

    dropped = 0
    for path in relevant + others:
        if total_chars >= MAX_TOTAL_CHARS:
            dropped += 1
            continue
        source = _read_safe(path)
        if not source.strip():
            continue
        rel     = os.path.relpath(path, root)
        block   = f"── FILE: {rel} ({'relevant' if path in relevant else 'other'}) ──\n{source}\n"
        parts.append(block)
        total_chars += len(block)
        files_used  += 1

    parts.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(parts), len(files), files_used


# ── Prompt builder ────────────────────────────────────────────────

def build_chat_prompt(question: str, context: str) -> str:
    return f"""
{context}

━━━ DEVELOPER QUESTION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{question}

━━━ YOUR TASK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Answer the question using ONLY the codebase shown above.

Guidelines:
  ✦ Trace the actual call chain step-by-step when relevant
  ✦ Cite exact file names and line contents as evidence
  ✦ Use plain English — no unnecessary jargon
  ✦ If you show code snippets, use ``` fences
  ✦ If the answer spans multiple files, explain the full flow
  ✦ If the question is unanswerable from the code, say so clearly

Structure your answer:
  1. Direct answer (1-2 sentences)
  2. How it works (step-by-step trace with file references)
  3. Key files involved
  4. Any caveats or edge cases worth noting
"""
