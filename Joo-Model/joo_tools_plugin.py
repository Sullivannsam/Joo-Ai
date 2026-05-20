# ================================================================
#  JOO AI — PLUGIN / TOOL SYSTEM  (Phase 9)
#  ✦ #lint   — run pylint / eslint and fold results into AI analysis
#  ✦ #format — run black / prettier and show what changed
#  ✦ #typecheck — run mypy / tsc and explain every error
#  ✦ #deps   — audit requirements.txt / package.json with pip-audit
#  Results are automatically fed back to Joo for smart commentary.
# ================================================================

import subprocess
import os
import shutil
import json
import tempfile
import re
import difflib

# ── Tool availability check ───────────────────────────────────────

def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _run(args: list[str], cwd: str | None = None, timeout: int = 60) -> tuple[str, str, int]:
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=cwd or os.getcwd(),
            timeout=timeout,
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return "", f"Tool not found: {args[0]}", 127
    except subprocess.TimeoutExpired:
        return "", f"Timed out after {timeout}s", 1
    except Exception as e:
        return "", str(e), 1


# ── LINTERS ──────────────────────────────────────────────────────

def run_pylint(path: str) -> dict:
    """Run pylint on a Python file/folder. Returns structured result."""
    if not _which("pylint"):
        return {"tool": "pylint", "available": False, "output": "pylint not installed — run: pip install pylint"}

    stdout, stderr, code = _run(
        ["pylint", "--output-format=text", "--score=yes", path],
    )
    return {
        "tool":      "pylint",
        "available": True,
        "path":      path,
        "exit_code": code,
        "output":    (stdout or stderr)[:8000],
        "passed":    code == 0,
    }


def run_eslint(path: str) -> dict:
    """Run eslint on a JS/TS file/folder."""
    if not _which("eslint"):
        return {"tool": "eslint", "available": False, "output": "eslint not installed — run: npm i -g eslint"}

    stdout, stderr, code = _run(
        ["eslint", "--format=stylish", path],
    )
    return {
        "tool":      "eslint",
        "available": True,
        "path":      path,
        "exit_code": code,
        "output":    (stdout or stderr)[:8000],
        "passed":    code == 0,
    }


def run_ruff(path: str) -> dict:
    """Run ruff (fast Python linter) if available, fallback to pylint."""
    if _which("ruff"):
        stdout, stderr, code = _run(["ruff", "check", "--output-format=text", path])
        return {
            "tool":      "ruff",
            "available": True,
            "path":      path,
            "exit_code": code,
            "output":    (stdout or stderr)[:8000],
            "passed":    code == 0,
        }
    return run_pylint(path)


def auto_lint(path: str) -> dict:
    """Choose the right linter based on file extension or directory contents."""
    if os.path.isdir(path):
        # Check what kind of files the directory contains
        has_js = any(f.endswith((".js",".ts",".jsx",".tsx")) for f in os.listdir(path))
        has_py = any(f.endswith(".py") for f in os.listdir(path))
        if has_js:
            return run_eslint(path)
        if has_py:
            return run_ruff(path)
        return run_ruff(path)  # default to ruff for unknown dirs
    ext = os.path.splitext(path)[1].lower()
    if ext in {".js", ".ts", ".jsx", ".tsx"}:
        return run_eslint(path)
    elif ext == ".py":
        return run_ruff(path)
    else:
        return {"tool": "none", "available": False, "output": f"No linter available for {ext}"}


# ── FORMATTERS ───────────────────────────────────────────────────

def run_black(path: str, check_only: bool = False) -> dict:
    """Run black on a Python file."""
    if not _which("black"):
        return {"tool": "black", "available": False, "output": "black not installed — run: pip install black"}

    args = ["black", "--diff", path] if check_only else ["black", path]
    stdout, stderr, code = _run(args)
    return {
        "tool":       "black",
        "available":  True,
        "path":       path,
        "check_only": check_only,
        "exit_code":  code,
        "output":     (stdout or stderr)[:6000],
        "reformatted": code == 0 and not check_only,
    }


def run_prettier(path: str, check_only: bool = False) -> dict:
    """Run prettier on a JS/TS/HTML/CSS file."""
    if not _which("prettier"):
        return {"tool": "prettier", "available": False, "output": "prettier not installed — run: npm i -g prettier"}

    args = ["prettier", "--check", path] if check_only else ["prettier", "--write", path]
    stdout, stderr, code = _run(args)
    return {
        "tool":       "prettier",
        "available":  True,
        "path":       path,
        "check_only": check_only,
        "exit_code":  code,
        "output":     (stdout or stderr)[:6000],
        "reformatted": code == 0 and not check_only,
    }


def auto_format(path: str, check_only: bool = False) -> dict:
    """Choose the right formatter based on file extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".py":
        return run_black(path, check_only)
    elif ext in {".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json"}:
        return run_prettier(path, check_only)
    else:
        return {"tool": "none", "available": False, "output": f"No formatter available for {ext}"}


# ── TYPE CHECKERS ─────────────────────────────────────────────────

def run_mypy(path: str) -> dict:
    """Run mypy type checker on Python file/folder."""
    if not _which("mypy"):
        return {"tool": "mypy", "available": False, "output": "mypy not installed — run: pip install mypy"}

    stdout, stderr, code = _run(["mypy", "--pretty", "--show-error-codes", path])
    return {
        "tool":      "mypy",
        "available": True,
        "path":      path,
        "exit_code": code,
        "output":    (stdout or stderr)[:8000],
        "passed":    code == 0,
        "errors":    _parse_mypy_errors(stdout or stderr),
    }


def _parse_mypy_errors(output: str) -> list[dict]:
    errors = []
    for line in output.splitlines():
        m = re.match(r"^(.+):(\d+): (\w+): (.+)$", line)
        if m:
            errors.append({
                "file":     m.group(1),
                "line":     int(m.group(2)),
                "severity": m.group(3),
                "message":  m.group(4),
            })
    return errors[:30]


def run_tsc(path: str) -> dict:
    """Run TypeScript compiler type check."""
    tsc = "npx" if _which("npx") else None
    if not tsc:
        return {"tool": "tsc", "available": False, "output": "npx/tsc not installed"}

    # Find tsconfig.json walking upward
    cwd = path if os.path.isdir(path) else os.path.dirname(path)
    args = ["npx", "tsc", "--noEmit"]
    stdout, stderr, code = _run(args, cwd=cwd)
    return {
        "tool":      "tsc",
        "available": True,
        "path":      path,
        "exit_code": code,
        "output":    (stdout or stderr)[:8000],
        "passed":    code == 0,
    }


def auto_typecheck(path: str) -> dict:
    """Choose the right type checker based on extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in {".ts", ".tsx"}:
        return run_tsc(path)
    elif ext == ".py" or os.path.isdir(path):
        return run_mypy(path)
    else:
        return {"tool": "none", "available": False, "output": f"No type checker for {ext}"}


# ── DEPENDENCY AUDIT ──────────────────────────────────────────────

def run_pip_audit(path: str) -> dict:
    """Run pip-audit on requirements file or folder."""
    if not _which("pip-audit"):
        # Try pip install pip-audit silently
        return {
            "tool":      "pip-audit",
            "available": False,
            "output":    "pip-audit not installed — run: pip install pip-audit",
        }

    req_file = path
    if os.path.isdir(path):
        candidates = ["requirements.txt", "requirements-lock.txt", "requirements.in"]
        req_file = next((os.path.join(path, c) for c in candidates if os.path.exists(os.path.join(path, c))), None)
        if not req_file:
            return {"tool": "pip-audit", "available": True, "passed": False, "output": "No requirements.txt found in folder."}

    stdout, stderr, code = _run(["pip-audit", "-r", req_file, "--format", "json"], timeout=90)
    try:
        data = json.loads(stdout)
        vulns = data.get("vulnerabilities", [])
        summary = f"{len(vulns)} vulnerabilities found."
        output = json.dumps(data, indent=2)[:6000]
    except Exception:
        summary = ""
        output = (stdout or stderr)[:6000]

    return {
        "tool":      "pip-audit",
        "available": True,
        "path":      req_file,
        "exit_code": code,
        "output":    output,
        "summary":   summary,
        "passed":    code == 0,
    }


def run_npm_audit(path: str) -> dict:
    """Run npm audit on a Node project."""
    if not _which("npm"):
        return {"tool": "npm-audit", "available": False, "output": "npm not installed"}

    cwd = path if os.path.isdir(path) else os.path.dirname(path)
    stdout, stderr, code = _run(["npm", "audit", "--json"], cwd=cwd, timeout=90)
    try:
        data       = json.loads(stdout)
        meta       = data.get("metadata", {})
        vuln_count = meta.get("vulnerabilities", {})
        summary    = f"Vulnerabilities: {vuln_count}"
    except Exception:
        summary = ""

    return {
        "tool":      "npm-audit",
        "available": True,
        "path":      cwd,
        "exit_code": code,
        "output":    (stdout or stderr)[:6000],
        "summary":   summary,
        "passed":    code == 0,
    }


def auto_deps_audit(path: str) -> dict:
    """Auto-select deps auditor."""
    if os.path.isdir(path):
        has_pkg  = os.path.exists(os.path.join(path, "package.json"))
        has_reqs = any(os.path.exists(os.path.join(path, r)) for r in ["requirements.txt", "requirements.in"])
        if has_pkg:
            return run_npm_audit(path)
        if has_reqs:
            return run_pip_audit(path)
        return {"tool": "none", "available": False, "output": "No package.json or requirements.txt found."}
    ext = os.path.splitext(path)[1]
    if ext in {".txt", ".in"}:
        return run_pip_audit(path)
    return run_npm_audit(path)


# ── Prompt builders ───────────────────────────────────────────────

def build_lint_prompt(result: dict, source: str = "") -> str:
    tool    = result["tool"]
    path    = result.get("path", "")
    output  = result.get("output", "")
    passed  = result.get("passed", False)

    if not result.get("available"):
        return f"Tool '{tool}' is not installed: {output}"

    source_block = f"\nSOURCE FILE:\n```\n{source[:4000]}\n```\n" if source else ""

    return f"""
━━━ TASK: LINT ANALYSIS — {tool.upper()} ━━━━━━━━━━━━━━━━━━━━━━
FILE:   {path}
STATUS: {"✔ PASSED" if passed else "✘ FAILED"}

{source_block}
LINT OUTPUT:
{output}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For each issue reported by the linter:
  ✦ Explain what the rule means in plain English
  ✦ Show the problematic code and the fixed version
  ✦ Group related issues together
  ✦ Prioritize: HIGH impact issues first
  ✦ At the end: give 1-3 structural improvements

If the lint passed cleanly, note what was checked and any
near-misses or style improvements still worth considering.
"""


def build_format_prompt(result: dict, before: str = "", after: str = "") -> str:
    tool    = result["tool"]
    path    = result.get("path", "")
    output  = result.get("output", "")

    if not result.get("available"):
        return f"Formatter '{tool}' not installed: {output}"

    diff_block = ""
    if before and after and before != after:
        diff = list(difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="before", tofile="after",
        ))
        diff_block = f"\nDIFF:\n```diff\n{''.join(diff[:100])}\n```\n"
    elif output:
        diff_block = f"\nFORMATTER OUTPUT:\n{output[:3000]}\n"

    return f"""
━━━ TASK: FORMAT ANALYSIS — {tool.upper()} ━━━━━━━━━━━━━━━━━━━
FILE:        {path}
REFORMATTED: {result.get("reformatted", False)}

{diff_block}

Explain every formatting change made:
  ✦ What style rule each change enforces
  ✦ Why it improves readability or consistency
  ✦ Any changes the developer might want to revert (rare)
Keep explanations short — one line per change group is ideal.
"""


def build_typecheck_prompt(result: dict, source: str = "") -> str:
    tool    = result["tool"]
    path    = result.get("path", "")
    output  = result.get("output", "")
    errors  = result.get("errors", [])
    passed  = result.get("passed", False)

    if not result.get("available"):
        return f"Type checker '{tool}' not installed: {output}"

    source_block = f"\nSOURCE FILE:\n```\n{source[:4000]}\n```\n" if source else ""

    return f"""
━━━ TASK: TYPE ERROR ANALYSIS — {tool.upper()} ━━━━━━━━━━━━━━━
FILE:   {path}
STATUS: {"✔ PASSED" if passed else f"✘ {len(errors)} ERROR(S)"}

{source_block}
TYPE CHECKER OUTPUT:
{output}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For each type error:
  ✦ Explain the root cause in plain English
  ✦ Show the fix with before/after code
  ✦ Note if the type annotation or the logic needs changing
  ✦ Flag any errors that indicate a real runtime bug

If type-safe: confirm what was checked and suggest stricter
modes (e.g. --strict for mypy) if appropriate.
"""


def build_deps_prompt(result: dict) -> str:
    tool    = result["tool"]
    path    = result.get("path", "")
    output  = result.get("output", "")
    summary = result.get("summary", "")
    passed  = result.get("passed", False)

    if not result.get("available"):
        return f"Deps tool '{tool}' not installed: {output}"

    return f"""
━━━ TASK: DEPENDENCY AUDIT — {tool.upper()} ━━━━━━━━━━━━━━━━━
FILE:   {path}
STATUS: {"✔ No vulnerabilities" if passed else f"✘ VULNERABILITIES FOUND — {summary}"}

AUDIT OUTPUT:
{output}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For each vulnerability:
  ✦ Severity and CVE (if present)
  ✦ What the package does and how the vuln could be exploited
  ✦ Exact fix: version to upgrade to
  ✦ If no fix available: workaround or alternative package

At the end, rank packages by risk level and give a priority
upgrade order. Include the exact pip/npm install command.
"""
