# ================================================================
#  JOO AI — GIT INTEGRATION  (Phase 7)
#  ✦ #commit  — Joo writes the commit message from your diff
#  ✦ #review  — reviews a PR diff or current staged changes
#  ✦ #blame   — traces a bug to the exact commit that introduced it
# ================================================================

import subprocess
import os
import re

# ----------------------------------------------------------------
#  GIT HELPERS
# ----------------------------------------------------------------

def _git(*args, cwd=None) -> tuple[str, str, int]:
    """Run a git command. Returns (stdout, stderr, returncode)."""
    cwd = cwd or os.getcwd()
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return "", "git is not installed or not in PATH", 1
    except subprocess.TimeoutExpired:
        return "", "git command timed out", 1


def is_git_repo(path: str = ".") -> bool:
    _, _, code = _git("rev-parse", "--is-inside-work-tree", cwd=path)
    return code == 0


def get_root(path: str = ".") -> str:
    out, _, _ = _git("rev-parse", "--show-toplevel", cwd=path)
    return out or os.getcwd()


# ----------------------------------------------------------------
#  #commit — staged diff → commit message
# ----------------------------------------------------------------

def get_staged_diff() -> str:
    """Return the current staged diff (git diff --cached)."""
    diff, err, code = _git("diff", "--cached", "--stat")
    if code != 0:
        return ""
    full_diff, _, _ = _git("diff", "--cached")
    return f"{diff}\n\n{full_diff}"


def get_unstaged_diff() -> str:
    """Return unstaged changes."""
    diff, _, _ = _git("diff")
    return diff


def get_recent_log(n: int = 5) -> str:
    """Return last n commit messages for style context."""
    log, _, _ = _git("log", f"--oneline", f"-{n}")
    return log


def build_commit_prompt(diff: str, recent_log: str = "") -> str:
    if not diff:
        return ""

    style_block = f"""
━━━ RECENT COMMIT STYLE (match this tone/format) ━━━━━━━━━━━━━
{recent_log}
""" if recent_log else ""

    return f"""
━━━ TASK: WRITE A GIT COMMIT MESSAGE ━━━━━━━━━━━━━━━━━━━━━━━━

{style_block}
RULES:
  ✦ First line: imperative mood, max 72 chars (e.g. "Fix login timeout bug")
  ✦ Blank line, then a body explaining WHAT changed and WHY (not HOW)
  ✦ Use conventional commit types if the project already uses them:
     feat / fix / refactor / test / docs / chore / perf / ci
  ✦ Be specific. No vague messages like "update stuff" or "changes"
  ✦ Group related changes into one clear message
  ✦ If the diff is large, use bullet points in the body for clarity
  ✦ Never mention file names unless critical for understanding

OUTPUT FORMAT:
  Return ONLY the commit message text — no explanation, no markdown fences.
  Start directly with the subject line.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIFF:
{diff[:6000]}
"""


# ----------------------------------------------------------------
#  #review — PR / diff code review
# ----------------------------------------------------------------

def get_branch_diff(base: str = "main") -> str:
    """Diff current branch vs base branch."""
    diff, err, code = _git("diff", f"{base}...HEAD")
    if code != 0:
        # Try 'master' as fallback
        diff, err, code = _git("diff", f"master...HEAD")
    return diff if code == 0 else ""


def get_diff_from_file(path: str) -> str:
    """Read a diff file directly."""
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read(40_000)
    except Exception:
        return ""


def build_review_prompt(diff: str, context: str = "") -> str:
    if not diff:
        return ""

    context_block = f"""
━━━ REVIEW CONTEXT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{context}
""" if context else ""

    return f"""
━━━ TASK: EXPERT CODE REVIEW ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{context_block}
REVIEW CATEGORIES — examine the diff for ALL of these:

1. BUGS & LOGIC ERRORS
   ✦ Anything that will cause incorrect behavior
   → Trace each bug to its root cause
   ✔ Provide the exact fix

2. SECURITY VULNERABILITIES
   ⚠ Injection, auth bypass, hardcoded secrets, unsafe deserialization
   ⚠ Any new surface area that could be exploited

3. PERFORMANCE
   ⚠ N+1 queries, unnecessary allocations, blocking calls
   ⚠ Missing indexes, inefficient algorithms

4. DESIGN & ARCHITECTURE
   ◆ Does this change fit the existing patterns?
   ◆ Is abstraction at the right level?
   ◆ Are responsibilities separated cleanly?

5. CODE QUALITY
   ✦ Naming clarity, function length, nesting depth
   ✦ Error handling completeness
   ✦ Missing edge case coverage

6. TESTS
   ⚠ Are new behaviors tested?
   ⚠ Are edge cases covered?
   ★ What test is most critically missing?

OUTPUT FORMAT:
━━━ REVIEW SUMMARY ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✦ Overall verdict: APPROVE / REQUEST CHANGES / NEEDS DISCUSSION
  ✦ Risk level: LOW / MEDIUM / HIGH
  ✦ One-paragraph summary of what this change does

━━━ BLOCKING ISSUES (must fix before merge) ━━━━━━━━━━━━━━━━━━
  [List only real blockers with file:line and exact fix]

━━━ NON-BLOCKING SUGGESTIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [Improvements worth making but not required]

━━━ POSITIVE OBSERVATIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  [What was done well — Joo always acknowledges good work]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIFF TO REVIEW:
{diff[:8000]}
"""


# ----------------------------------------------------------------
#  #blame — trace a bug to the commit that introduced it
# ----------------------------------------------------------------

def get_git_blame(path: str, line_range: tuple[int, int] | None = None) -> str:
    """Run git blame on a file, optionally for a line range."""
    args = ["blame", "--date=short", "-w"]
    if line_range:
        args += [f"-L{line_range[0]},{line_range[1]}"]
    args.append(path)
    out, err, code = _git(*args)
    return out if code == 0 else f"Could not blame {path}: {err}"


def get_commit_detail(commit_hash: str) -> str:
    """Return full commit info: message, diff, author, date."""
    show, _, _ = _git("show", "--stat", commit_hash)
    diff, _, _ = _git("show", commit_hash)
    return f"{show}\n\n{diff[:4000]}"


def get_log_for_file(path: str, n: int = 20) -> str:
    """Git log for a specific file."""
    log, _, _ = _git("log", f"-{n}", "--oneline", "--", path)
    return log


def parse_blame_hashes(blame_output: str) -> list[str]:
    """Extract unique commit hashes from blame output."""
    hashes = re.findall(r"^([0-9a-f]{8,40})", blame_output, re.MULTILINE)
    return list(dict.fromkeys(hashes))  # deduplicated, order preserved


def build_blame_prompt(
    bug_description: str,
    path: str,
    blame_output: str,
    commit_details: list[str],
    file_log: str,
) -> str:
    commits_block = "\n\n".join(
        f"=== COMMIT {i+1} ===\n{detail}" for i, detail in enumerate(commit_details[:5])
    )

    return f"""
━━━ TASK: BUG ORIGIN INVESTIGATION ━━━━━━━━━━━━━━━━━━━━━━━━━━

BUG DESCRIPTION:
{bug_description}

FILE: {path}

STEP 1 — BLAME ANALYSIS
  Read the git blame output carefully.
  ✦ Which lines are most likely related to the bug?
  → Who changed them? When?
  ★ Identify the EXACT commit hash most likely responsible.

STEP 2 — COMMIT ARCHAEOLOGY
  For the suspected commit(s):
  ✦ What change was introduced?
  → Why was it likely introduced? (feature, fix, refactor?)
  ⚠ What assumption did it make that turned out to be wrong?
  ◆ Was this always a bug, or did a later change expose it?

STEP 3 — ROOT CAUSE VERDICT
  ★ In plain English: WHEN was this bug introduced, WHAT caused it,
    and WHY it wasn't caught sooner.

STEP 4 — THE FIX
  ✔ Show the exact fix needed now.
  ✔ Suggest a regression test to prevent this class of bug recurring.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GIT LOG FOR FILE:
{file_log}

GIT BLAME:
{blame_output[:3000]}

COMMIT DETAILS:
{commits_block[:5000]}
"""


# ----------------------------------------------------------------
#  ENTRY POINTS  (called by main.py handle_code_mode)
# ----------------------------------------------------------------

def handle_commit(args: str) -> tuple[str, str]:
    """
    Returns (prompt_for_joo, error_message).
    args can be empty (use staged diff) or a diff file path.
    """
    if args and os.path.exists(args):
        diff = get_diff_from_file(args)
    else:
        diff = get_staged_diff()
        if not diff:
            diff = get_unstaged_diff()

    if not diff:
        return "", "⚠ No staged or unstaged changes found. Stage your changes with 'git add' first."

    recent_log = get_recent_log(5)
    return build_commit_prompt(diff, recent_log), ""


def handle_review(args: str) -> tuple[str, str]:
    """
    Returns (prompt_for_joo, error_message).
    args: optional base branch name or path to a .diff file.
    """
    if args and os.path.exists(args):
        diff = get_diff_from_file(args)
        context = f"Reviewing diff file: {args}"
    elif args:
        diff    = get_branch_diff(base=args)
        context = f"Comparing current branch vs {args}"
    else:
        diff    = get_branch_diff()
        context = "Comparing current branch vs main/master"

    if not diff:
        return "", "⚠ No diff found. Try: #review main OR #review path/to/file.diff"

    return build_review_prompt(diff, context), ""


def handle_blame(args: str, bug_description: str = "") -> tuple[str, str]:
    """
    Returns (prompt_for_joo, error_message).
    args: 'file.py' or 'file.py:10-25' for line range.
    """
    path       = args
    line_range = None

    if ":" in args:
        parts = args.rsplit(":", 1)
        path  = parts[0]
        try:
            nums = [int(x) for x in parts[1].split("-")]
            line_range = (nums[0], nums[-1])
        except ValueError:
            pass

    if not os.path.exists(path):
        return "", f"⚠ File not found: {path}"

    if not is_git_repo():
        return "", "⚠ Not inside a git repository."

    blame  = get_git_blame(path, line_range)
    hashes = parse_blame_hashes(blame)[:5]
    commit_details = [get_commit_detail(h) for h in hashes]
    file_log = get_log_for_file(path)

    if not bug_description:
        bug_description = f"Investigating suspicious code in {path}"

    return build_blame_prompt(bug_description, path, blame, commit_details, file_log), ""
