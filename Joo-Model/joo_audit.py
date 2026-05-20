# ================================================================
#  JOO AI — PROJECT-WIDE AUDIT  (Phase 6)
#  ✦ #audit <folder> — scans ALL files at once
#  ✦ Finds: dead code, circular imports, naming issues,
#           missing tests, security risks, style violations
# ================================================================

import os
import re
import ast
import json
import subprocess
from collections import defaultdict

# ----------------------------------------------------------------
#  FILE COLLECTION
# ----------------------------------------------------------------

SUPPORTED_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go",
    ".rs", ".php", ".rb", ".swift", ".kt", ".cs", ".cpp", ".c",
}

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".mypy_cache",
}

def collect_files(folder: str, max_files: int = 60) -> list[str]:
    """Walk a folder and return all supported source files."""
    results = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in SUPPORTED_EXTS:
                results.append(os.path.join(root, fname))
                if len(results) >= max_files:
                    return results
    return results


def read_file_safe(path: str, max_bytes: int = 40_000) -> str:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read(max_bytes)
    except Exception:
        return ""


# ----------------------------------------------------------------
#  PYTHON-SPECIFIC AST ANALYSIS
# ----------------------------------------------------------------

def _python_dead_functions(source: str) -> list[str]:
    """Find functions defined but never called in same file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    defined  = set()
    called   = set()

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and node.name not in ("main", "setUp", "tearDown"):
                defined.add(node.name)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)

    return sorted(defined - called)


def _python_imports(source: str) -> list[str]:
    """Extract all imported module names from Python source."""
    mods = []
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mods.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    mods.append(node.module.split(".")[0])
    except SyntaxError:
        pass
    return mods


# ----------------------------------------------------------------
#  UNIVERSAL PATTERN SCANNERS
# ----------------------------------------------------------------

SECURITY_PATTERNS = [
    (r"eval\s*\(",                         "eval() — arbitrary code execution risk"),
    (r"exec\s*\(",                         "exec() — arbitrary code execution risk"),
    (r"os\.system\s*\(",                   "os.system() — prefer subprocess with args"),
    (r"shell\s*=\s*True",                  "shell=True in subprocess — injection risk"),
    (r"password\s*=\s*['\"][^'\"]+['\"]",  "Hardcoded password literal"),
    (r"secret\s*=\s*['\"][^'\"]+['\"]",    "Hardcoded secret literal"),
    (r"api_key\s*=\s*['\"][^'\"]+['\"]",   "Hardcoded API key"),
    (r"token\s*=\s*['\"][^'\"]+['\"]",     "Hardcoded token literal"),
    (r"md5\s*\(",                          "MD5 is cryptographically broken"),
    (r"sha1\s*\(",                         "SHA-1 is cryptographically weak"),
    (r"pickle\.load",                      "pickle.load() — unsafe deserialization"),
    (r"yaml\.load\s*\([^,)]+\)",           "yaml.load() without Loader — use safe_load()"),
    (r"SELECT.*\%s",                       "String-interpolated SQL — use parameterized queries"),
    (r"innerHTML\s*=",                     "innerHTML assignment — XSS risk"),
    (r"dangerouslySetInnerHTML",           "dangerouslySetInnerHTML — XSS risk"),
]

NAMING_PATTERNS = [
    (r"\bdef [a-z][A-Z]",           "camelCase function name — prefer snake_case (Python)"),
    (r"\bclass [a-z]",              "Lowercase class name — classes should be PascalCase"),
    (r"\b(l|O|I)\s*=",             "Ambiguous variable name (l, O, or I)"),
    (r"\b(data|info|stuff|temp2?|foo|bar|baz|x2|y2)\s*=", "Vague variable name"),
    (r"\bfunction [A-Z]",          "PascalCase function in JS — use camelCase for functions"),
]

COMPLEXITY_PATTERNS = [
    (r"(?m)^( {4}){5,}",   "Deep nesting (5+ levels) — consider extracting a function"),
    (r"(?m)^( {8}){3,}",   "Very deep nesting — refactor needed"),
]

TODO_PATTERN  = re.compile(r"#\s*(TODO|FIXME|HACK|XXX|BUG|NOCOMMIT)[:\s]?(.*)", re.IGNORECASE)
MAGIC_PATTERN = re.compile(r"(?<!['\"\w])\b(\d{2,})\b(?!['\"\w])")


# ----------------------------------------------------------------
#  PER-FILE ANALYSIS
# ----------------------------------------------------------------

def analyze_file(path: str) -> dict:
    source = read_file_safe(path)
    ext    = os.path.splitext(path)[1].lower()
    lines  = source.splitlines()

    result = {
        "path":     path,
        "lines":    len(lines),
        "issues":   [],   # list of {"type", "severity", "line", "detail"}
        "todos":    [],
        "imports":  [],
    }

    def add(type_, severity, detail, line=None):
        result["issues"].append({"type": type_, "severity": severity, "detail": detail, "line": line})

    # ── Security scan ──────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        for pattern, msg in SECURITY_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                add("security", "HIGH", msg, i)

    # ── Naming scan ────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        for pattern, msg in NAMING_PATTERNS:
            if re.search(pattern, line):
                add("naming", "LOW", msg, i)

    # ── Complexity scan ────────────────────────────────────────────
    for pattern, msg in COMPLEXITY_PATTERNS:
        for m in re.finditer(pattern, source):
            lineno = source[:m.start()].count("\n") + 1
            add("complexity", "MEDIUM", msg, lineno)

    # ── TODO / FIXME extraction ────────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = TODO_PATTERN.search(line)
        if m:
            result["todos"].append({"line": i, "tag": m.group(1), "text": m.group(2).strip()})

    # ── Magic numbers ──────────────────────────────────────────────
    safe_numbers = {"0", "1", "2", "100", "1000"}
    for i, line in enumerate(lines, 1):
        if re.search(r"^\s*#", line):
            continue
        for m in MAGIC_PATTERN.finditer(line):
            if m.group(1) not in safe_numbers:
                add("magic_number", "LOW", f"Magic number {m.group(1)} — consider a named constant", i)
                break  # one per line max

    # ── Missing error handling ─────────────────────────────────────
    if ext == ".py":
        for i, line in enumerate(lines, 1):
            if re.search(r"except\s*:", line):
                add("error_handling", "MEDIUM", "Bare except: catches everything including KeyboardInterrupt", i)
            if re.search(r"except\s+Exception\s*:", line) and "log" not in line.lower():
                add("error_handling", "LOW", "Caught Exception without logging — silent failure risk", i)

    # ── Python dead code ───────────────────────────────────────────
    if ext == ".py":
        dead = _python_dead_functions(source)
        if dead:
            for fn in dead[:5]:
                add("dead_code", "LOW", f"Function '{fn}' defined but never called in this file", None)
        result["imports"] = _python_imports(source)

    # ── Missing tests heuristic ────────────────────────────────────
    # (detected at folder level, not per file)

    return result


# ----------------------------------------------------------------
#  CIRCULAR IMPORT DETECTION  (Python)
# ----------------------------------------------------------------

def detect_circular_imports(files: list[str]) -> list[tuple[str, str]]:
    """Build import graph and find cycles (Python only)."""
    graph     = defaultdict(set)
    name_map  = {}  # module name → file path

    for path in files:
        if not path.endswith(".py"):
            continue
        mod = os.path.splitext(os.path.basename(path))[0]
        name_map[mod] = path
        source = read_file_safe(path)
        for imp in _python_imports(source):
            graph[mod].add(imp)

    cycles = []
    def dfs(node, visited, stack):
        visited.add(node)
        stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                dfs(neighbor, visited, stack)
            elif neighbor in stack and (neighbor, node) not in cycles:
                cycles.append((node, neighbor))
        stack.discard(node)

    visited = set()
    for mod in list(graph.keys()):
        if mod not in visited:
            dfs(mod, visited, set())

    return cycles


# ----------------------------------------------------------------
#  MISSING TESTS DETECTION
# ----------------------------------------------------------------

def find_missing_tests(files: list[str]) -> list[str]:
    """Return source files that have no corresponding test file."""
    test_names = set()
    source_files = []

    for path in files:
        base = os.path.basename(path)
        name = os.path.splitext(base)[0]
        if name.startswith("test_") or name.endswith("_test") or name.startswith("spec_"):
            test_names.add(name.replace("test_", "").replace("_test", "").replace("spec_", ""))
        else:
            source_files.append(path)

    untested = []
    for path in source_files:
        name = os.path.splitext(os.path.basename(path))[0]
        if name not in test_names and not name.startswith("__"):
            untested.append(path)

    return untested


# ----------------------------------------------------------------
#  AUDIT RUNNER
# ----------------------------------------------------------------

def run_audit(folder: str) -> dict:
    """
    Full project audit. Returns a structured report dict.
    """
    folder   = os.path.abspath(os.path.expanduser(folder))
    files    = collect_files(folder)
    analyses = [analyze_file(f) for f in files]
    cycles   = detect_circular_imports(files)
    untested = find_missing_tests(files)

    total_issues = sum(len(a["issues"]) for a in analyses)
    total_todos  = sum(len(a["todos"])  for a in analyses)

    high   = [i for a in analyses for i in a["issues"] if i["severity"] == "HIGH"]
    medium = [i for a in analyses for i in a["issues"] if i["severity"] == "MEDIUM"]
    low    = [i for a in analyses for i in a["issues"] if i["severity"] == "LOW"]

    return {
        "folder":        folder,
        "files_scanned": len(files),
        "total_issues":  total_issues,
        "total_todos":   total_todos,
        "high_count":    len(high),
        "medium_count":  len(medium),
        "low_count":     len(low),
        "circular":      cycles,
        "untested":      untested,
        "file_reports":  analyses,
    }


# ----------------------------------------------------------------
#  AUDIT PROMPT BUILDER
# ----------------------------------------------------------------

def build_audit_prompt(report: dict) -> str:
    """Format the audit report into a structured prompt for Joo."""
    folder  = report["folder"]
    n_files = report["files_scanned"]
    n_iss   = report["total_issues"]
    high    = report["high_count"]
    med     = report["medium_count"]
    low     = report["low_count"]

    lines = [
        f"━━━ TASK: PROJECT-WIDE AUDIT ANALYSIS ━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"FOLDER:  {folder}",
        f"FILES:   {n_files} scanned",
        f"ISSUES:  {n_iss} total  [HIGH: {high}  MEDIUM: {med}  LOW: {low}]",
        f"",
    ]

    # ── Circular imports ──────────────────────────────────────────
    if report["circular"]:
        lines.append("⚠ CIRCULAR IMPORTS DETECTED:")
        for a, b in report["circular"][:10]:
            lines.append(f"   {a}  ↔  {b}")
        lines.append("")

    # ── Missing tests ─────────────────────────────────────────────
    if report["untested"]:
        lines.append("⚠ FILES WITHOUT TESTS:")
        for f in report["untested"][:10]:
            lines.append(f"   {f}")
        lines.append("")

    # ── Top HIGH severity issues ──────────────────────────────────
    high_issues = [
        (a["path"], i)
        for a in report["file_reports"]
        for i in a["issues"]
        if i["severity"] == "HIGH"
    ]
    if high_issues:
        lines.append("★ HIGH-SEVERITY ISSUES:")
        for path, issue in high_issues[:15]:
            loc = f"line {issue['line']}" if issue.get("line") else "file-level"
            lines.append(f"   [{issue['type'].upper()}] {path}:{loc}")
            lines.append(f"   → {issue['detail']}")
        lines.append("")

    # ── Per-file digest ───────────────────────────────────────────
    lines.append("◆ PER-FILE DIGEST:")
    for a in report["file_reports"]:
        if not a["issues"] and not a["todos"]:
            continue
        rel = os.path.relpath(a["path"], report["folder"])
        iss_str   = f"{len(a['issues'])} issues" if a["issues"] else "✔ clean"
        todos_str = f"  [{len(a['todos'])} TODOs]" if a["todos"] else ""
        lines.append(f"   {rel}  ({a['lines']} lines)  →  {iss_str}{todos_str}")
        for iss in a["issues"][:4]:  # top 4 per file
            loc = f":{iss['line']}" if iss.get("line") else ""
            lines.append(f"      ⚠ [{iss['severity']}] {iss['type']}{loc}: {iss['detail'][:80]}")
        if a["todos"]:
            for t in a["todos"][:3]:
                lines.append(f"      📝 {t['tag']} line {t['line']}: {t['text'][:60]}")
    lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "Using the full audit data above, produce a structured report:",
        "",
        "SECTION 1 — EXECUTIVE SUMMARY",
        "  ✦ Overall health score (1-10) with one-sentence verdict",
        "  ✦ Top 3 problems to fix RIGHT NOW",
        "",
        "SECTION 2 — CRITICAL FINDINGS",
        "  For each HIGH-severity issue:",
        "  → Root cause explanation",
        "  ✔ Exact fix (code snippet if needed)",
        "  ⚠ What happens if left unfixed",
        "",
        "SECTION 3 — ARCHITECTURE OBSERVATIONS",
        "  ◆ Circular import chains and how to break them",
        "  ◆ Dead code that can be safely deleted",
        "  ◆ Module structure improvements",
        "",
        "SECTION 4 — TESTING GAPS",
        "  ★ Which untested files carry the most risk",
        "  ✔ What test strategy to prioritize first",
        "",
        "SECTION 5 — QUICK WINS",
        "  List 5 fast improvements (< 30 min each) with biggest impact",
        "",
        "SECTION 6 — PRIORITIZED ACTION PLAN",
        "  Order all fixes by: impact × effort. Start with max impact / min effort.",
        "",
    ]

    return "\n".join(lines)
