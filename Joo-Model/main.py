import time
import sys
import ollama
import os
import re
import difflib
import shutil
import json
import subprocess
import tempfile
import threading

from rich.text import Text
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from config import MODEL_NAME, ASSISTANT_NAME
from prompts import (
    SYSTEM_PROMPT,
    CODING_SYSTEM_PROMPT,
    debug_prompt,
    edit_prompt,
    explain_prompt,
    test_prompt,
    refactor_prompt,
    traceback_prompt,
    verify_fix_prompt,
    chat_prompt,
    history_recall_prompt,
    KNOWN_COMMANDS,
)
from memory import add_history, get_history
from commands import handle_command

from tools import (
    create_file,
    create_folder,
    read_file,
    list_files,
    delete_file,
    find_files,
    change_directory,
    current_dir,
    execute_ai_action,
    make_backup,
    undo_file,
    save_history_entry,
    get_history_log,
    detect_traceback,
    extract_file_from_traceback,
)

# ── Phase 5: Persistent Vector Memory ─────────────────────────────
from joo_memory import (
    remember,
    recall,
    build_memory_context,
    memory_stats,
    recall_by_tag,
    forget_all,
)

# ── Phase 6: Project-Wide Audit ───────────────────────────────────
from joo_audit import run_audit, build_audit_prompt

# ── Phase 7: Git Integration ──────────────────────────────────────
from joo_git import (
    handle_commit,
    handle_review,
    handle_blame,
    is_git_repo,
    _git,
)

# ── Phase 8: AI-Powered Codebase Chat ─────────────────────────────
from joo_chat import build_chat_context, build_chat_prompt

# ── Phase 9: Plugin / Tool System ─────────────────────────────────
from joo_tools_plugin import (
    auto_lint,
    auto_format,
    auto_typecheck,
    auto_deps_audit,
    build_lint_prompt,
    build_format_prompt,
    build_typecheck_prompt,
    build_deps_prompt,
)

# ── Phase 10: Web Search Mode ──────────────────────────────────────
from joo_web import search_and_build, build_web_context, should_web_search

# ── Phase 11: Security Scanner ─────────────────────────────────────
from joo_sec import run_sec_scan, build_sec_prompt

console = Console()

# ---------------- CLEAR SCREEN ----------------
os.system("clear")

# ---------------- ANIMATED LOGO ----------------
def _animate_logo():
    frames = [
        "\033[38;2;255;80;200m 𔓕   ██╗ ██████╗  ██████╗   ☁︎  \033[0m",
        "\033[38;2;255;100;210m     ██║██╔═══██╗██╔═══██╗\033[0m",
        "\033[38;2;255;120;220m     ██║██║ 𔓕 ██║██║   ██║\033[0m",
        "\033[38;2;255;140;230m██   ██║██║   ██║██║   ██║\033[0m",
        "\033[38;2;255;160;240m╚█████╔╝╚██████╔╝╚██████╔╝\033[0m",
        "\033[38;2;255;180;250m ╚════╝  ╚═════╝  ╚═════╝ \033[0m",
        "\033[38;2;200;255;230m    .✦                       ࣪ ִֶָ☾.   \033[0m",
        "\033[38;2;180;240;255m ██████╗ ██████╗ ██████╗ ███████╗ \033[0m",
        "\033[38;2;160;220;255m██╔════╝██╔═══██╗██╔══██╗██╔════╝ \033[0m",
        "\033[38;2;150;200;255m██║     ██║   ██║██║  ██║█████╗   \033[0m",
        "\033[38;2;140;180;255m██║     ██║   ██║██║  ██║██╔══╝   \033[0m",
        "\033[38;2;130;160;255m╚██████╗╚██████╔╝██████╔╝███████╗ \033[0m",
        "\033[38;2;255;255;255m ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝ \033[0m",
    ]
    for line in frames:
        print(line)
        time.sleep(0.04)
    tagline = "✧ Joo Code, how can i help you today? :)"
    sys.stdout.write("\033[38;2;255;200;100m")
    for ch in tagline:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(0.018)
    sys.stdout.write("\033[0m\n\n")

_animate_logo()

# ================================================================
#  GLOBALS
# ================================================================
THEME = "dark"
_RECENT_FILES = {}
_SESSION_START = time.time()

LANGUAGE_MAP = {
    ".py":    "python",
    ".java":  "java",
    ".js":    "javascript",
    ".ts":    "typescript",
    ".tsx":   "typescript",
    ".jsx":   "javascript",
    ".cpp":   "cpp",
    ".c":     "c",
    ".cs":    "csharp",
    ".php":   "php",
    ".go":    "go",
    ".rs":    "rust",
    ".html":  "html",
    ".css":   "css",
    ".sh":    "bash",
    ".bash":  "bash",
    ".rb":    "ruby",
    ".swift": "swift",
    ".kt":    "kotlin",
    ".dart":  "dart",
    ".sql":   "sql",
    ".json":  "json",
    ".yaml":  "yaml",
    ".yml":   "yaml",
    ".toml":  "toml",
    ".md":    "markdown",
    ".xml":   "xml",
}

# Phase 3: sandbox runner map
SANDBOX_RUNNERS = {
    "python":     ["python3", "-c"],
    "javascript": ["node",    "-e"],
    "typescript": ["npx", "ts-node", "-e"],
    "bash":       ["bash",    "-c"],
    "ruby":       ["ruby",    "-e"],
    "php":        ["php",     "-r"],
}

# Phase 4: import patterns for RAG
IMPORT_PATTERNS = {
    "python":     [r"^(?:import|from)\s+([\w.]+)", r"from\s+([\w.]+)\s+import"],
    "javascript": [r"(?:require|import).*['\"](.+)['\"]"],
    "typescript": [r"(?:require|import).*['\"](.+)['\"]"],
    "go":         [r"\"([\w./]+)\""],
    "rust":       [r"use\s+([\w:]+)"],
    "java":       [r"import\s+([\w.]+);"],
}

# App launcher aliases
APP_ALIASES = {
    "vscode":     "code",
    "vs code":    "code",
    "code":       "code",
    "spotify":    "spotify",
    "finder":     "open .",
    "files":      "open .",
    "terminal":   "open -a Terminal",
    "chrome":     "open -a 'Google Chrome'",
    "firefox":    "open -a Firefox",
    "safari":     "open -a Safari",
    "slack":      "open -a Slack",
    "discord":    "open -a Discord",
    "steam":      "open -a Steam",
    "notion":     "open -a Notion",
    "obsidian":   "open -a Obsidian",
    "figma":      "open -a Figma",
    "xcode":      "open -a Xcode",
    "postman":    "open -a Postman",
    "tableplus":  "open -a TablePlus",
    "iterm":      "open -a iTerm",
    "iterm2":     "open -a iTerm",
    "music":      "open -a Music",
    "notes":      "open -a Notes",
    "calculator": "open -a Calculator",
}

# Phase 7: register new commands for typo correction
KNOWN_COMMANDS.extend([
    "#audit", "#commit", "#review", "#blame",
    "/memory", "/memory-clear", "/memory-stats",
    "#chat",
    "#lint", "#format", "#typecheck", "#deps",
    "#web",
    "#sec",   # Phase 11: security scanner
])


# ================================================================
#  ANIMATION HELPERS  (unchanged from v3)
# ================================================================

def _pulse_print(text, color_rgb=(120, 255, 200), delay=0.015):
    r, g, b = color_rgb
    sys.stdout.write(f"\033[38;2;{r};{g};{b}m")
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\033[0m\n")


def _open_animation(app_name):
    frames = ["◐", "◓", "◑", "◒"]
    colors = [(255, 120, 200), (200, 120, 255), (120, 200, 255), (120, 255, 180)]
    for i in range(12):
        r, g, b = colors[i % len(colors)]
        sys.stdout.write(
            f"\r\033[38;2;{r};{g};{b}m{frames[i % 4]}  Launching {app_name}...\033[0m"
        )
        sys.stdout.flush()
        time.sleep(0.08)
    sys.stdout.write(f"\r\033[38;2;120;255;120m✔  {app_name} launched!              \033[0m\n")


def _sandbox_animation():
    steps = [
        (80,  200, 255, "⟳  Sandbox: writing temp file..."),
        (120, 255, 120, "⟳  Sandbox: executing code...   "),
        (255, 220,  80, "⟳  Sandbox: reading output...   "),
    ]
    for r, g, b, msg in steps:
        sys.stdout.write(f"\r\033[38;2;{r};{g};{b}m{msg}\033[0m")
        sys.stdout.flush()
        time.sleep(0.3)
    print()


def _audit_animation(n_files: int):
    frames = ["◐", "◓", "◑", "◒"]
    colors = [(255, 160, 80), (255, 200, 80), (80, 255, 180), (80, 200, 255)]
    for i in range(n_files * 2 + 8):
        r, g, b = colors[i % len(colors)]
        sys.stdout.write(
            f"\r\033[38;2;{r};{g};{b}m{frames[i % 4]}  Scanning {n_files} files...\033[0m"
        )
        sys.stdout.flush()
        time.sleep(0.06)
    sys.stdout.write(f"\r\033[38;2;120;255;120m✔  Scan complete!              \033[0m\n")


def _chat_animation(n_files: int):
    frames = ["◐", "◓", "◑", "◒"]
    colors = [(120, 80, 255), (160, 80, 255), (200, 80, 255), (240, 120, 255)]
    for i in range(n_files + 10):
        r, g, b = colors[i % len(colors)]
        sys.stdout.write(
            f"\r\033[38;2;{r};{g};{b}m{frames[i % 4]}  Indexing {n_files} files...\033[0m"
        )
        sys.stdout.flush()
        time.sleep(0.05)
    sys.stdout.write(f"\r\033[38;2;120;255;200m✔  Codebase indexed!           \033[0m\n")


def _web_animation():
    frames = ["◐", "◓", "◑", "◒"]
    colors = [(80, 200, 255), (80, 160, 255), (120, 80, 255), (160, 80, 255)]
    for i in range(18):
        r, g, b = colors[i % len(colors)]
        sys.stdout.write(
            f"\r\033[38;2;{r};{g};{b}m{frames[i % 4]}  Searching the web...\033[0m"
        )
        sys.stdout.flush()
        time.sleep(0.07)
    sys.stdout.write(f"\r\033[38;2;120;255;200m✔  Web results fetched!        \033[0m\n")


# ================================================================
#  HELPERS
# ================================================================

def type_print(text, delay=0.01):
    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(delay)
    print()


def _extract_code(answer, language, fallback):
    if f"```{language}" in answer:
        return answer.split(f"```{language}")[1].split("```")[0].strip()
    if "```" in answer:
        blocks = answer.split("```")
        return blocks[1].strip() if len(blocks) > 1 else fallback
    return answer.strip() or fallback


def _write_file(path, code):
    backup = make_backup(path)
    with open(path, "w") as f:
        f.write(code)
    _pulse_print(f"✔ Updated:  {path}", (120, 255, 120))
    _pulse_print(f"✔ Backup:   {backup}", (120, 200, 255))


def _strip_confidence(text):
    """Remove CONFIDENCE: X/5 lines — Joo no longer rates itself."""
    return re.sub(r"CONFIDENCE\s*:\s*\d+\s*/\s*5[^\n]*\n?", "", text, flags=re.IGNORECASE)


# ================================================================
#  PHASE 4 — RAG: RELATED FILE COLLECTOR  (unchanged)
# ================================================================

def _collect_related_files(main_path, language, max_files=4):
    patterns = IMPORT_PATTERNS.get(language, [])
    if not patterns:
        return ""

    base_dir = os.path.dirname(os.path.abspath(main_path))
    try:
        with open(main_path, "r", errors="ignore") as f:
            source = f.read()
    except Exception:
        return ""

    found_modules = set()
    for pat in patterns:
        for match in re.finditer(pat, source, re.MULTILINE):
            found_modules.add(match.group(1).replace(".", os.sep))

    related_blocks = []
    checked = 0
    for mod in found_modules:
        if checked >= max_files:
            break
        for ext in [".py", ".js", ".ts", ".go", ".java", ".rs"]:
            candidate = os.path.join(base_dir, mod + ext)
            if os.path.exists(candidate) and candidate != os.path.abspath(main_path):
                try:
                    with open(candidate, "r", errors="ignore") as f:
                        content = f.read()[:3000]
                    related_blocks.append(f"FILE: {candidate}\n```\n{content}\n```")
                    checked += 1
                    break
                except Exception:
                    pass

    if related_blocks:
        print(f"\033[38;2;120;200;255m◆ RAG: pulled {len(related_blocks)} related file(s) for context\033[0m")

    return "\n\n".join(related_blocks)


# ================================================================
#  PHASE 3 — SANDBOX CODE RUNNER  (unchanged)
# ================================================================

def _run_in_sandbox(code, language, timeout=10):
    runner = SANDBOX_RUNNERS.get(language)
    if not runner:
        return "", f"No sandbox runner for: {language}", False

    try:
        if runner[-1] in ["-c", "-e", "-r"]:
            result = subprocess.run(
                runner + [code],
                capture_output=True, text=True, timeout=timeout
            )
        else:
            ext_map = {"python": ".py", "javascript": ".js", "bash": ".sh", "ruby": ".rb"}
            ext = ext_map.get(language, ".txt")
            with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8") as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            result = subprocess.run(
                runner + [tmp_path],
                capture_output=True, text=True, timeout=timeout
            )
            os.unlink(tmp_path)

        return result.stdout.strip(), result.stderr.strip(), result.returncode == 0

    except subprocess.TimeoutExpired:
        return "", f"⚠ Sandbox timed out after {timeout}s", False
    except FileNotFoundError:
        return "", f"⚠ Runner not installed: {runner[0]}", False
    except Exception as e:
        return "", str(e), False


def _sandbox_debug_loop(path, code, language, answer, max_attempts=2):
    if language not in SANDBOX_RUNNERS:
        # Java, Go, Rust, Swift etc. need compilation — skip sandbox silently
        return answer
    for attempt in range(1, max_attempts + 1):
        fixed_code = _extract_code(answer, language, code)
        if not fixed_code or fixed_code == code:
            break

        print(f"\033[38;2;80;200;255m⟳  Sandbox run #{attempt}...\033[0m")
        _sandbox_animation()

        stdout, stderr, success = _run_in_sandbox(fixed_code, language)

        if success:
            print(f"\033[38;2;120;255;120m✔  Sandbox PASSED — code runs without errors.\033[0m")
            if stdout:
                console.print(Panel(stdout, title="[bold]Sandbox Output[/bold]", border_style="green", padding=(0, 2)))
            break
        else:
            print(f"\033[38;2;255;80;80m✘  Sandbox FAILED (attempt {attempt}) — asking Joo to adjust...\033[0m")
            if stderr:
                console.print(Panel(stderr, title="[bold]Sandbox Error[/bold]", border_style="red", padding=(0, 2)))
            if attempt < max_attempts:
                vp = verify_fix_prompt(code, fixed_code, language, stdout, stderr)
                with console.status("[bright_magenta]Joo is adjusting the fix ✦[/bright_magenta]", spinner="dots12"):
                    answer = ask_ollama(vp, system=CODING_SYSTEM_PROMPT)
                answer = _strip_confidence(answer)
            else:
                print("\033[38;2;255;160;80m⚠  Max sandbox attempts reached. Showing best attempt.\033[0m")

    return answer


# ================================================================
#  TYPO CORRECTION
# ================================================================

def _suggest_command(user_input):
    word = user_input.strip().split()[0] if user_input.strip() else ""
    if not word:
        return False
    if not (word.startswith("/") or word.startswith("#")):
        return False
    if word in KNOWN_COMMANDS:
        return False
    close = difflib.get_close_matches(word, KNOWN_COMMANDS, n=1, cutoff=0.6)
    if close:
        print(f"\033[38;2;255;200;80mDid you mean \033[1m{close[0]}\033[0m\033[38;2;255;200;80m?\033[0m")
        return True
    return False


# ================================================================
#  PRINT AI RESPONSE
# ================================================================

def print_response(answer, title=None, is_code_mode=False):
    answer = _strip_confidence(answer)
    border = "bright_magenta" if is_code_mode else "cyan"

    if "```" in answer:
        parts  = answer.split("```")
        output = Text()

        for idx, part in enumerate(parts):
            if idx % 2 == 0:
                clean_part = part.strip()
                if clean_part:
                    output.append(clean_part + "\n")
            else:
                lines = part.strip().splitlines()
                lang  = lines[0].strip().lower() if lines else "text"
                code  = "\n".join(lines[1:]) if len(lines) > 1 else part

                if lang not in LANGUAGE_MAP.values() and lang != "text":
                    lang = "text"

                console.print(Syntax(code, lang, theme="monokai", line_numbers=True))

        if str(output):
            console.print(Panel.fit(
                output,
                title=f"[bold]{title or ASSISTANT_NAME}[/bold]",
                border_style=border, padding=(1, 2)
            ))
    else:
        clean = re.sub(r"\n{3,}", "\n\n", answer.strip())
        console.print(Panel.fit(
            clean,
            title=f"[bold]{title or ASSISTANT_NAME}[/bold]",
            border_style=border, padding=(1, 2)
        ))


# ================================================================
#  ASK OLLAMA  (Phase 5: memory context injected)
# ================================================================

def ask_ollama(prompt, system=None, history_items=8, memory_query=None, fast=False):
    """
    Shows a spinner until the first token arrives (so it never looks frozen),
    then streams tokens live. Collects everything into a string for callers
    that need the full response — does NOT double-print via print_response().
    """
    base_system = system or SYSTEM_PROMPT

    if fast:
        messages = [
            {"role": "system", "content": base_system},
            {"role": "user",   "content": prompt},
        ]
    else:
        mem_context = build_memory_context(memory_query or prompt, top_k=3)
        full_system = f"{base_system}\n\n{mem_context}" if mem_context else base_system
        messages    = [{"role": "system", "content": full_system}]
        for item in get_history(min(history_items, 4)):
            messages.append({"role": "user",      "content": item["user"]})
            messages.append({"role": "assistant", "content": item["assistant"]})
        messages.append({"role": "user", "content": prompt})

    # ── Spinner runs until first token arrives ───────────────────
    _spinner_active = [True]
    _first_token    = [False]

    def _spin():
        frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
        i = 0
        while _spinner_active[0] and not _first_token[0]:
            sys.stdout.write(f"\r\033[38;2;200;120;255m{frames[i % len(frames)]}  Joo is thinking ✦\033[0m")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1

    spin_thread = threading.Thread(target=_spin, daemon=True)
    spin_thread.start()

    chunks = []
    try:
        stream = ollama.chat(model=MODEL_NAME, messages=messages, stream=True)
        for chunk in stream:
            token = chunk["message"]["content"]
            if not _first_token[0]:
                # First token — kill spinner, print clean header
                _first_token[0]    = True
                _spinner_active[0] = False
                spin_thread.join(timeout=0.2)
                sys.stdout.write(f"\r\033[K")   # clear spinner line
                sys.stdout.write("\033[38;2;180;120;255m✦ Joo\033[0m\n")
                sys.stdout.flush()
            chunks.append(token)
            sys.stdout.write(token)
            sys.stdout.flush()
    except Exception as e:
        _spinner_active[0] = False
        sys.stdout.write(f"\r\033[K")
        print(f"\033[38;2;255;80;80m✘ Ollama error: {e}\033[0m")
        return ""
    finally:
        _spinner_active[0] = False

    print()  # newline after stream ends
    return "".join(chunks).strip()


# ================================================================
#  LOAD FILE FOR CODE MODE
# ================================================================

def load_code_file(query):
    path = os.path.expanduser(query)

    if not os.path.exists(path):
        print(f"\033[38;2;255;220;80m⟳ Searching: {query}...\033[0m")
        # Case-insensitive walk — find first match anywhere on system
        query_lower = query.lower()
        found_path  = None
        for root, dirs, files in os.walk("/"):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".venv", "proc", "sys", "dev"}]
            for name in files + dirs:
                if name.lower() == query_lower or query_lower in name.lower():
                    found_path = os.path.join(root, name)
                    break
            if found_path:
                break
        if found_path:
            path = found_path
            print(f"\033[38;2;120;255;120m✔ Found: {path}\033[0m")
        else:
            print("\033[38;2;255;80;80m✘ File not found anywhere on system.\033[0m")
            return None

    # If it's a directory, just confirm it exists (used by multi-file helpers)
    if os.path.isdir(path):
        return path, "", "text"

    try:
        with open(path, "r", errors="ignore") as f:
            code = f.read()
    except Exception as e:
        print(f"\033[38;2;255;80;80m✘ Cannot read file: {e}\033[0m")
        return None

    ext      = os.path.splitext(path)[1].lower()
    language = LANGUAGE_MAP.get(ext, "text")
    return path, code, language




# ================================================================
#  LOAD MULTIPLE FILES FOR CODE MODE (multi-file support)
# ================================================================

def load_multi_files(query: str) -> list[tuple[str, str, str]]:
    """
    Split query on spaces, load each token as a file.
    Returns list of (path, code, language) tuples.
    Falls back to single-file load if only one token.
    """
    tokens = query.strip().split()
    results = []
    for token in tokens:
        r = load_code_file(token)
        if r and r[1]:  # skip dirs / not-found
            results.append(r)
    return results

# ================================================================
#  /open — LAUNCH ANY APP, FILE, OR URL
# ================================================================

def _resolve_open_target(arg):
    arg_lower = arg.strip().lower()
    for alias, cmd in APP_ALIASES.items():
        if arg_lower == alias or arg_lower.startswith(alias + " "):
            return cmd, alias.title()
    if arg.startswith("http://") or arg.startswith("https://"):
        return f"open '{arg}'", arg
    expanded = os.path.expanduser(arg)
    if os.path.exists(expanded):
        return f"open '{expanded}'", os.path.basename(expanded)
    if sys.platform == "darwin":
        return f"open -a '{arg}'", arg
    return f"xdg-open '{arg}'", arg


def handle_open_command(arg):
    if not arg:
        print("\033[38;2;255;180;80mUsage: /open <app|file|url>\033[0m")
        examples = [
            "  /open vscode", "  /open spotify", "  /open ~/file.txt",
            "  /open https://github.com", "  /open discord", "  /open steam",
        ]
        for ex in examples:
            print(f"\033[38;2;120;200;255m{ex}\033[0m")
            time.sleep(0.03)
        return True

    cmd, display_name = _resolve_open_target(arg)
    _open_animation(display_name)

    try:
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"\033[38;2;255;80;80m✘ Could not open '{arg}': {e}\033[0m")

    return True


# ================================================================
#  CODE MODE COMMANDS  (Phase 5/6/7 added below)
# ================================================================

def handle_code_mode(user_input):
    raw_parts = user_input.strip().split()
    cmd       = raw_parts[0].lower()

    time_limit = None
    if cmd == "#edit" and len(raw_parts) >= 4 and raw_parts[1] == "-t":
        try:
            time_limit = float(raw_parts[2])
            query      = " ".join(raw_parts[3:])
        except ValueError:
            print("\033[38;2;255;80;80m✘ Usage: #edit -t <seconds> file.py\033[0m")
            return True
    else:
        query = " ".join(raw_parts[1:]) if len(raw_parts) > 1 else ""

    # ── #debug ───────────────────────────────────────────────────
    if cmd == "#debug":
        if not query:
            print("Usage: #debug file.py [file2.py ...]")
            return True
        files = load_multi_files(query)
        if not files:
            return True
        for path, code, language in files:
            print(f"\033[38;2;200;120;255m◆ Debugging: {path}\033[0m")
            related = _collect_related_files(path, language)
            answer  = ask_ollama(debug_prompt(path, code, language, related), system=CODING_SYSTEM_PROMPT, memory_query=f"debug {language} {query}")
            answer  = _strip_confidence(answer)
            answer  = _sandbox_debug_loop(path, code, language, answer)
            print_response(answer, title=f"✦ Joo Debug — {os.path.basename(path)}", is_code_mode=True)
            fixed_code = _extract_code(answer, language, code)
            if input(f"\n\033[38;2;255;220;80mApply fix to {os.path.basename(path)}? (y/n): \033[0m").strip().lower() == "y":
                _write_file(path, fixed_code)
            remember(f"#debug {path}", answer[:800], tags=["bug", language])
            save_history_entry(f"#debug {path}", answer[:200])
        return True

    # ── #edit ────────────────────────────────────────────────────
    if cmd == "#edit":
        if not query:
            print("Usage: #edit file.py [file2.py ...]  OR  #edit -t 30 file.py")
            return True
        files = load_multi_files(query)
        if not files:
            return True
        if time_limit:
            print(f"\033[38;2;255;200;80m⚡ Quick mode — aiming for {time_limit}s response\033[0m")
        for path, code, language in files:
            print(f"\033[38;2;200;120;255m◆ Editing: {path}\033[0m")
            related = _collect_related_files(path, language)
            t_start = time.time()
            answer  = ask_ollama(edit_prompt(path, code, language, time_limit, related), system=CODING_SYSTEM_PROMPT, memory_query=f"edit {language} {query}")
            elapsed = time.time() - t_start
            print(f"\033[38;2;120;200;255m⏱  Responded in {elapsed:.1f}s\033[0m")
            answer = _strip_confidence(answer)
            answer = _sandbox_debug_loop(path, code, language, answer)
            print_response(answer, title=f"✦ Joo Edit — {os.path.basename(path)}", is_code_mode=True)
            fixed_code = _extract_code(answer, language, code)
            if input(f"\n\033[38;2;255;220;80mApply changes to {os.path.basename(path)}? (y/n): \033[0m").strip().lower() == "y":
                _write_file(path, fixed_code)
            else:
                print("\033[38;2;255;160;80m✔ No changes applied.\033[0m")
            remember(f"#edit {path}", answer[:800], tags=["style", language])
            save_history_entry(f"#edit {path}", answer[:200])
        return True

    # ── #explain ─────────────────────────────────────────────────
    if cmd == "#explain":
        if not query:
            print("Usage: #explain file.py [file2.py ...]")
            return True
        files = load_multi_files(query)
        if not files:
            return True
        for path, code, language in files:
            print(f"\033[38;2;200;120;255m◆ Explaining: {path}\033[0m")
            related = _collect_related_files(path, language)
            answer  = ask_ollama(explain_prompt(path, code, language, related), system=CODING_SYSTEM_PROMPT, memory_query=query)
            answer  = _strip_confidence(answer)
            print_response(answer, title=f"✦ Joo Explain — {os.path.basename(path)}", is_code_mode=True)
            remember(f"#explain {path}", answer[:800])
            save_history_entry(f"#explain {path}", answer[:200])
        return True

    # ── #test ────────────────────────────────────────────────────
    if cmd == "#test":
        if not query:
            print("Usage: #test file.py [file2.py ...]")
            return True
        files = load_multi_files(query)
        if not files:
            return True
        for path, code, language in files:
            print(f"\033[38;2;200;120;255m◆ Generating tests: {path}\033[0m")
            related = _collect_related_files(path, language)
            answer  = ask_ollama(test_prompt(path, code, language, related), system=CODING_SYSTEM_PROMPT, memory_query=f"test {language}")
            answer  = _strip_confidence(answer)
            print_response(answer, title=f"✦ Joo Test — {os.path.basename(path)}", is_code_mode=True)
            test_path = path.replace(f".{path.split('.')[-1]}", f"_test.{path.split('.')[-1]}")
            if input(f"\n\033[38;2;255;220;80mSave tests to {os.path.basename(test_path)}? (y/n): \033[0m").strip().lower() == "y":
                test_code = _extract_code(answer, language, "")
                with open(test_path, "w") as f:
                    f.write(test_code)
                _RECENT_FILES[os.path.basename(test_path)] = "new"
                print(f"\033[38;2;80;255;140m📄 Tests saved: {test_path}  ✦ NEW\033[0m")
            remember(f"#test {path}", answer[:800], tags=["testing", language])
            save_history_entry(f"#test {path}", answer[:200])
        return True

    # ── #refactor ────────────────────────────────────────────────
    if cmd == "#refactor":
        if not query:
            print("Usage: #refactor file.py [file2.py ...]")
            return True
        files = load_multi_files(query)
        if not files:
            return True
        for path, code, language in files:
            print(f"\033[38;2;200;120;255m◆ Refactoring: {path}\033[0m")
            related = _collect_related_files(path, language)
            answer  = ask_ollama(refactor_prompt(path, code, language, related), system=CODING_SYSTEM_PROMPT, memory_query=f"refactor {language}")
            answer  = _strip_confidence(answer)
            print_response(answer, title=f"✦ Joo Refactor — {os.path.basename(path)}", is_code_mode=True)
            fixed_code = _extract_code(answer, language, code)
            if input(f"\n\033[38;2;255;220;80mApply refactor to {os.path.basename(path)}? (y/n): \033[0m").strip().lower() == "y":
                _write_file(path, fixed_code)
            else:
                print("\033[38;2;255;160;80m✔ No changes applied.\033[0m")
            remember(f"#refactor {path}", answer[:800], tags=["refactor", language])
            save_history_entry(f"#refactor {path}", answer[:200])
        return True

    # ── #compare ────────────────────────────────────────────────
    if cmd == "#compare":
        if not query:
            print("Usage: #compare file.py")
            return True
        path   = os.path.expanduser(query)
        backup = f"{path}.bak1"

        if not os.path.exists(backup):
            print(f"\033[38;2;255;220;80m⚠ No backup found for {path}\033[0m")
            return True

        with open(path,   "r") as f: current = f.readlines()
        with open(backup, "r") as f: old     = f.readlines()

        diff = list(difflib.unified_diff(old, current, fromfile="backup", tofile="current", lineterm=""))
        if not diff:
            print("\033[38;2;120;255;120m✔ No differences found.\033[0m")
            return True

        console.print(Syntax("".join(diff), "diff", theme="monokai", line_numbers=True))
        return True

    # ── #run — Phase 3: execute any file in sandbox ──────────────
    if cmd == "#run":
        if not query:
            print("Usage: #run file.py")
            return True
        result = load_code_file(query)
        if not result:
            return True
        path, code, language = result

        if language not in SANDBOX_RUNNERS:
            print(f"\033[38;2;255;180;80m⚠ No sandbox runner available for {language}\033[0m")
            return True

        print(f"\033[38;2;80;200;255m⟳  Running {path}...\033[0m")
        _sandbox_animation()

        stdout, stderr, success = _run_in_sandbox(code, language)

        if success:
            _pulse_print("✔ Execution PASSED", (120, 255, 120))
            if stdout:
                console.print(Panel(stdout, title="[bold]Output[/bold]", border_style="green", padding=(0, 2)))
            else:
                print("\033[38;2;180;180;180m(no output)\033[0m")
        else:
            _pulse_print("✘ Execution FAILED", (255, 80, 80))
            console.print(Panel(stderr or "(no error message)", title="[bold]Error[/bold]", border_style="red", padding=(0, 2)))

        save_history_entry(f"#run {path}", (stdout or stderr)[:200])
        return True

    # ── #search ─────────────────────────────────────────────────
    if cmd == "#search":
        parts   = query.split()
        pattern = parts[0] if parts else ""
        dir_    = parts[1] if len(parts) > 1 else "."
        if not pattern:
            print("Usage: #search <pattern> [dir]")
            return True
        try:
            result = subprocess.run(["grep", "-rn", "--color=never", pattern, dir_], capture_output=True, text=True)
            if result.stdout:
                console.print(Syntax(result.stdout, "text", theme="monokai", line_numbers=False))
            else:
                print(f"\033[38;2;255;220;80m⚠ No matches for '{pattern}'\033[0m")
        except Exception as e:
            print(f"\033[38;2;255;80;80m✘ Search failed: {e}\033[0m")
        return True

    # ── #info ───────────────────────────────────────────────────
    if cmd == "#info":
        if not query:
            print("Usage: #info file.py")
            return True
        path = os.path.expanduser(query)
        if not os.path.exists(path):
            print(f"\033[38;2;255;80;80m✘ Not found: {path}\033[0m")
            return True
        stat      = os.stat(path)
        size      = stat.st_size
        mtime     = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
        ext       = os.path.splitext(path)[1]
        lang      = LANGUAGE_MAP.get(ext.lower(), "unknown")
        try:
            with open(path, "r", errors="ignore") as f:
                line_count = len(f.readlines())
        except Exception:
            line_count = "?"
        for line in [
            f"  ✦ File:      {path}",
            f"  ✦ Language:  {lang}",
            f"  ✦ Lines:     {line_count}",
            f"  ✦ Size:      {size} bytes",
            f"  ✦ Modified:  {mtime}",
        ]:
            _pulse_print(line, (120, 255, 200))
        return True

    # ────────────────────────────────────────────────────────────────
    # PHASE 6 — #audit <folder>
    # ────────────────────────────────────────────────────────────────
    if cmd == "#audit":
        folder = query.strip() or "."
        folder = os.path.expanduser(folder)
        if not os.path.isdir(folder):
            print(f"\033[38;2;255;80;80m✘ Not a directory: {folder}\033[0m")
            return True

        print(f"\033[38;2;255;200;80m◆ Phase 6 — Project Audit: {os.path.abspath(folder)}\033[0m")

        # Run static analysis (fast, no AI)
        report = run_audit(folder)
        n      = report["files_scanned"]

        _audit_animation(n)

        console.print(Panel(
            f"[bold]Files scanned:[/bold] {n}  "
            f"[bold]Issues:[/bold] {report['total_issues']}  "
            f"[bold red]HIGH: {report['high_count']}[/bold red]  "
            f"[bold yellow]MED: {report['medium_count']}[/bold yellow]  "
            f"[dim]LOW: {report['low_count']}[/dim]  "
            f"[bold]TODOs:[/bold] {report['total_todos']}  "
            f"[bold]Untested:[/bold] {len(report['untested'])}",
            title="[bold bright_yellow]✦ Joo Audit — Quick Stats[/bold bright_yellow]",
            border_style="yellow",
        ))

        # Ask Joo to analyse the full report
        audit_prompt_text = build_audit_prompt(report)
        answer = ask_ollama(audit_prompt_text, system=CODING_SYSTEM_PROMPT, memory_query="audit project", fast=True)
        answer = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Audit Report", is_code_mode=True)

        remember(f"#audit {folder}", answer[:800], tags=["architecture", "security"])
        save_history_entry(f"#audit {folder}", answer[:200])
        return True

    # ────────────────────────────────────────────────────────────────
    # PHASE 7 — #commit
    # ────────────────────────────────────────────────────────────────
    if cmd == "#commit":
        if not is_git_repo():
            print("\033[38;2;255;80;80m✘ Not inside a git repository.\033[0m")
            return True

        print("\033[38;2;120;200;255m◆ Phase 7 — Reading git diff...\033[0m")
        prompt_text, err = handle_commit(query)

        if err:
            print(f"\033[38;2;255;220;80m{err}\033[0m")
            return True

        answer = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query="git commit style")
        answer = _strip_confidence(answer).strip()

        # Strip any accidental code fences
        answer = re.sub(r"```[a-z]*\n?", "", answer).replace("```", "").strip()

        console.print(Panel(
            answer,
            title="[bold bright_green]✦ Joo Commit Message[/bold bright_green]",
            border_style="green",
            padding=(1, 2),
        ))

        choice = input("\n\033[38;2;255;220;80mUse this message? (y/n/e to edit): \033[0m").strip().lower()
        if choice == "y":
            subprocess.run(["git", "commit", "-m", answer])
            _pulse_print("✔ Committed!", (120, 255, 120))
        elif choice == "e":
            # Write to tmp file and open editor
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
            tmp.write(answer)
            tmp.close()
            editor = os.environ.get("EDITOR", "nano")
            subprocess.run([editor, tmp.name])
            with open(tmp.name) as f:
                edited = f.read().strip()
            os.unlink(tmp.name)
            if edited:
                subprocess.run(["git", "commit", "-m", edited])
                _pulse_print("✔ Committed with edited message!", (120, 255, 120))
        else:
            print("\033[38;2;255;160;80m✔ No commit made.\033[0m")

        remember(f"#commit", answer[:400], tags=["git"])
        save_history_entry("#commit", answer[:200])
        return True

    # ────────────────────────────────────────────────────────────────
    # PHASE 7 — #review [base-branch | diff-file]
    # ────────────────────────────────────────────────────────────────
    if cmd == "#review":
        if not is_git_repo() and not (query and os.path.exists(query)):
            print("\033[38;2;255;80;80m✘ Not a git repo and no diff file given.\033[0m")
            return True

        print(f"\033[38;2;120;200;255m◆ Phase 7 — Code Review: {query or 'current branch vs main'}\033[0m")
        prompt_text, err = handle_review(query)

        if err:
            print(f"\033[38;2;255;220;80m{err}\033[0m")
            return True

        answer = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query="code review best practices")
        answer = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Code Review", is_code_mode=True)

        remember(f"#review {query}", answer[:800], tags=["git", "architecture"])
        save_history_entry(f"#review {query}", answer[:200])
        return True

    # ────────────────────────────────────────────────────────────────
    # PHASE 7 — #blame file.py[:10-25] [bug description]
    # ────────────────────────────────────────────────────────────────
    if cmd == "#blame":
        if not query:
            print("Usage: #blame file.py  OR  #blame file.py:10-50  OR  #blame file.py 'bug description'")
            return True

        if not is_git_repo():
            print("\033[38;2;255;80;80m✘ Not inside a git repository.\033[0m")
            return True

        # Separate file path from optional bug description
        parts        = query.split(None, 1)
        file_arg     = parts[0]
        bug_desc     = parts[1].strip().strip("'\"") if len(parts) > 1 else ""

        print(f"\033[38;2;120;200;255m◆ Phase 7 — Blame Investigation: {file_arg}\033[0m")
        prompt_text, err = handle_blame(file_arg, bug_desc)

        if err:
            print(f"\033[38;2;255;220;80m{err}\033[0m")
            return True

        answer = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query=f"bug blame {file_arg}")
        answer = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Blame Analysis", is_code_mode=True)

        remember(f"#blame {file_arg}", answer[:800], tags=["bug", "git"])
        save_history_entry(f"#blame {file_arg}", answer[:200])
        return True

    # ────────────────────────────────────────────────────────────────
    # PHASE 8 — #chat <question about the repo>
    # Usage:  #chat how does authentication work?
    #         #chat ~/myproject how does the payment flow work?
    # ────────────────────────────────────────────────────────────────
    if cmd == "#chat":
        if not query:
            print("Usage: #chat <question>")
            print("Example: #chat how does authentication work?")
            print("Example: #chat ~/myproject where is the rate limiter?")
            return True

        # Allow optional leading path argument
        parts = query.split(None, 1)
        if len(parts) > 1 and os.path.isdir(os.path.expanduser(parts[0])):
            root     = os.path.expanduser(parts[0])
            question = parts[1]
        else:
            root     = os.getcwd()
            question = query

        print(f"\033[38;2;200;80;255m◆ Phase 8 — Codebase Chat: indexing {root}...\033[0m")

        context, total_files, used = build_chat_context(root, question)
        if not context:
            print("\033[38;2;255;80;80m✘ No source files found in that directory.\033[0m")
            return True

        _chat_animation(total_files)
        console.print(Panel(
            f"[bold]Files found:[/bold] {total_files}  "
            f"[bold]Files used in context:[/bold] {used}  "
            f"[dim]Root: {root}[/dim]",
            title="[bold bright_magenta]✦ Joo Codebase Chat[/bold bright_magenta]",
            border_style="magenta",
        ))

        prompt_text = build_chat_prompt(question, context)
        answer      = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query=question, fast=True)
        answer      = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Chat", is_code_mode=True)

        remember(f"#chat {question[:80]}", answer[:800], tags=["architecture", "project"])
        save_history_entry(f"#chat {question[:80]}", answer[:200])
        return True

    # ────────────────────────────────────────────────────────────────
    # PHASE 9 — #lint / #format / #typecheck / #deps
    # ────────────────────────────────────────────────────────────────

    if cmd == "#lint":
        if not query:
            print("Usage: #lint file.py  OR  #lint ./src")
            return True
        path   = os.path.expanduser(query)
        print(f"\033[38;2;255;200;80m◆ Phase 9 — Lint: {path}\033[0m")
        result = auto_lint(path)
        if not result.get("available"):
            print(f"\033[38;2;255;80;80m✘ {result['output']}\033[0m")
            return True
        source = ""
        if os.path.isfile(path):
            try:
                with open(path, "r", errors="ignore") as f:
                    source = f.read(6000)
            except Exception:
                pass
        _status = "✔ PASSED" if result.get("passed") else "✘ ISSUES FOUND"
        console.print(Panel(
            f"[bold]Tool:[/bold] {result['tool']}  [bold]Status:[/bold] {_status}",
            title="[bold bright_yellow]✦ Joo Lint[/bold bright_yellow]",
            border_style="yellow",
        ))
        prompt_text = build_lint_prompt(result, source)
        answer      = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query=f"lint {path}", fast=True)
        answer      = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Lint Analysis", is_code_mode=True)
        remember(f"#lint {path}", answer[:800], tags=["style"])
        save_history_entry(f"#lint {path}", answer[:200])
        return True

    if cmd == "#format":
        if not query:
            print("Usage: #format file.py  OR  #format --check file.py")
            return True
        check_only = "--check" in query
        path       = os.path.expanduser(query.replace("--check", "").strip())
        print(f"\033[38;2;80;255;200m◆ Phase 9 — Format: {path} {'(check only)' if check_only else ''}\033[0m")
        before = ""
        if os.path.isfile(path):
            try:
                with open(path, "r", errors="ignore") as f:
                    before = f.read()
            except Exception:
                pass
        result = auto_format(path, check_only=check_only)
        if not result.get("available"):
            print(f"\033[38;2;255;80;80m✘ {result['output']}\033[0m")
            return True
        after = before
        if result.get("reformatted") and os.path.isfile(path):
            try:
                with open(path, "r", errors="ignore") as f:
                    after = f.read()
            except Exception:
                pass
        console.print(Panel(
            f"[bold]Tool:[/bold] {result['tool']}  [bold]Reformatted:[/bold] {result.get('reformatted', False)}",
            title="[bold bright_cyan]✦ Joo Format[/bold bright_cyan]",
            border_style="cyan",
        ))
        prompt_text = build_format_prompt(result, before, after)
        answer      = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query="code formatting", fast=True)
        answer      = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Format Analysis", is_code_mode=True)
        remember(f"#format {path}", answer[:800], tags=["style"])
        save_history_entry(f"#format {path}", answer[:200])
        return True

    if cmd == "#typecheck":
        if not query:
            print("Usage: #typecheck file.py  OR  #typecheck file.ts")
            return True
        path   = os.path.expanduser(query)
        print(f"\033[38;2;120;255;120m◆ Phase 9 — Type Check: {path}\033[0m")
        result = auto_typecheck(path)
        if not result.get("available"):
            print(f"\033[38;2;255;80;80m✘ {result['output']}\033[0m")
            return True
        source = ""
        if os.path.isfile(path):
            try:
                with open(path, "r", errors="ignore") as f:
                    source = f.read(6000)
            except Exception:
                pass
        _status = "✔ PASSED" if result.get("passed") else "✘ ERRORS"
        console.print(Panel(
            f"[bold]Tool:[/bold] {result['tool']}  [bold]Status:[/bold] {_status}",
            title="[bold bright_green]✦ Joo Type Check[/bold bright_green]",
            border_style="green",
        ))
        prompt_text = build_typecheck_prompt(result, source)
        answer      = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query=f"type errors {path}", fast=True)
        answer      = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Type Check Analysis", is_code_mode=True)
        remember(f"#typecheck {path}", answer[:800], tags=["style", "bug"])
        save_history_entry(f"#typecheck {path}", answer[:200])
        return True

    if cmd == "#deps":
        path   = os.path.expanduser(query.strip() or ".")
        print(f"\033[38;2;255;160;80m◆ Phase 9 — Dependency Audit: {path}\033[0m")
        result = auto_deps_audit(path)
        if not result.get("available"):
            print(f"\033[38;2;255;80;80m✘ {result['output']}\033[0m")
            return True
        _status = "✔ Clean" if result.get("passed") else "✘ Vulnerabilities found"
        console.print(Panel(
            f"[bold]Tool:[/bold] {result['tool']}  "
            f"[bold]Path:[/bold] {result.get('path', path)}  "
            f"[bold]Status:[/bold] {_status}",
            title="[bold bright_red]✦ Joo Deps Audit[/bold bright_red]",
            border_style="red",
        ))
        prompt_text = build_deps_prompt(result)
        answer      = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query="dependency vulnerability", fast=True)
        answer      = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Deps Analysis", is_code_mode=True)
        remember(f"#deps {path}", answer[:800], tags=["security", "deps"])
        save_history_entry(f"#deps {path}", answer[:200])
        return True

    # ────────────────────────────────────────────────────────────────
    # PHASE 10 — #web <query>
    # Searches the web and uses results as RAG context for the answer
    # ────────────────────────────────────────────────────────────────
    if cmd == "#web":
        if not query:
            print("Usage: #web <question>")
            print("Example: #web how to use FastAPI dependency injection")
            print("Example: #web ModuleNotFoundError numpy install")
            print("Tip:     Add --deep for full page fetching (slower but thorough)")
            return True

        deep_mode = "--deep" in query
        clean_query = query.replace("--deep", "").strip()

        print(f"\033[38;2;80;160;255m◆ Web Search: {clean_query}"
              f"{' (deep mode)' if deep_mode else ' (fast mode)'}\033[0m")

        result_holder: dict = {}

        def _do_search():
            pt, raw = search_and_build(clean_query, fetch_pages=deep_mode)
            result_holder["prompt"] = pt
            result_holder["raw"]    = raw

        t = threading.Thread(target=_do_search, daemon=True)
        t.start()
        _web_animation()
        t.join()

        raw         = result_holder.get("raw", {})
        prompt_text = result_holder.get("prompt", "")

        if raw.get("error") and not raw.get("results"):
            print(f"\033[38;2;255;80;80m✘ Web search failed: {raw['error']}\033[0m")
            return True

        n_results = len(raw.get("results", []))
        n_pages   = len(raw.get("pages", []))
        mode_label = "deep — pages fetched" if deep_mode else "fast — snippets only"
        console.print(Panel(
            f"[bold]Results:[/bold] {n_results}  "
            f"[bold]Pages:[/bold] {n_pages}  "
            f"[dim]Query: {raw.get('enhanced_query', clean_query)}  [{mode_label}][/dim]",
            title="[bold bright_blue]✦ Joo Web Search[/bold bright_blue]",
            border_style="blue",
        ))

        answer = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query=clean_query, fast=True)
        answer = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Web Answer", is_code_mode=True)

        # Offer deep mode if answer looks incomplete
        if not deep_mode and should_web_search(answer):
            choice = input("\n\033[38;2;255;220;80m⚡ Fetch full pages for deeper answer? (y/n): \033[0m").strip().lower()
            if choice == "y":
                print("\033[38;2;80;160;255m⟳  Fetching pages in parallel...\033[0m")
                from joo_web import web_search, build_web_context, build_web_prompt
                raw2     = web_search(clean_query, fetch_pages=True)
                context2 = build_web_context(raw2)
                prompt2  = build_web_prompt(clean_query, context2)
                answer2  = ask_ollama(prompt2, system=CODING_SYSTEM_PROMPT, memory_query=clean_query, fast=True)
                answer2  = _strip_confidence(answer2)
                print_response(answer2, title="✦ Joo Web Answer (Deep)", is_code_mode=True)
                answer = answer2

        remember(f"#web {clean_query[:80]}", answer[:800], tags=["deps", "general"])
        save_history_entry(f"#web {clean_query[:80]}", answer[:200])
        return True

    # ────────────────────────────────────────────────────────────────
    # PHASE 11 — #sec <file|folder>
    # Deep security scan: secrets, injection, crypto, CVEs, XSS, SSRF
    # ────────────────────────────────────────────────────────────────
    if cmd == "#sec":
        if not query:
            print("Usage: #sec <file.py|folder>")
            print("Example: #sec app.py")
            print("Example: #sec ./src")
            print()
            print("Scans for:")
            print("  ✦ Hardcoded secrets / API keys / passwords")
            print("  ✦ Injection risks (SQL, command, eval, SSTI)")
            print("  ✦ Broken crypto (MD5, SHA1, weak ciphers, bad TLS)")
            print("  ✦ Insecure deserialization (pickle, yaml.load)")
            print("  ✦ XSS / SSRF vulnerabilities")
            print("  ✦ Auth weaknesses (debug mode, JWT bypass, weak keys)")
            print("  ✦ Dependency CVEs (via pip-audit/npm audit if installed)")
            return True

        path = os.path.expanduser(query.strip())
        if not os.path.exists(path):
            print(f"\033[38;2;255;80;80m✘ Not found: {path}\033[0m")
            return True

        print(f"\033[38;2;255;80;80m◆ Phase 11 — Security Scan: {os.path.abspath(path)}\033[0m")

        report = run_sec_scan(path)
        n      = report["files_scanned"]
        _audit_animation(n)

        crit  = report["critical_count"]
        high  = report["high_count"]
        med   = report["medium_count"]
        total = report["total_findings"]

        border_color = "bright_red" if crit > 0 else ("yellow" if high > 0 else "green")
        console.print(Panel(
            f"[bold]Files:[/bold] {n}  "
            f"[bold red]CRITICAL: {crit}[/bold red]  "
            f"[bold yellow]HIGH: {high}[/bold yellow]  "
            f"[bold]MEDIUM: {med}[/bold]  "
            f"[bold]Total:[/bold] {total}  "
            f"[bold]Secrets:[/bold] {report['secrets_count']}  "
            f"[bold]CVEs:[/bold] {len(report['dep_cves'])}",
            title=f"[bold {border_color}]✦ Joo Security Scan[/bold {border_color}]",
            border_style=border_color,
        ))

        prompt_text = build_sec_prompt(report)
        answer      = ask_ollama(prompt_text, system=CODING_SYSTEM_PROMPT, memory_query="security vulnerability", fast=True)
        answer      = _strip_confidence(answer)
        print_response(answer, title="✦ Joo Security Report", is_code_mode=True)

        remember(f"#sec {path}", answer[:800], tags=["security"])
        save_history_entry(f"#sec {path}", answer[:200])
        return True

    return False


# ================================================================
#  TRACEBACK AUTO-FIX  (unchanged from v3)
# ================================================================

def handle_traceback(user_input):
    if not detect_traceback(user_input):
        return False

    print("\033[38;2;255;220;80m⚡ Traceback detected — entering auto-fix mode...\033[0m")

    detected_path = extract_file_from_traceback(user_input)
    code_context  = ""

    if detected_path and os.path.exists(detected_path):
        print(f"\033[38;2;120;255;120m✔ Found file: {detected_path}\033[0m")
        with open(detected_path, "r") as f:
            code_context = f.read()
        code_section = f"\nSOURCE FILE ({detected_path}):\n{code_context}"
    else:
        code_section = "\n(File not found — analyzing traceback only)"

    answer = ask_ollama(
        traceback_prompt(user_input, code_section),
        system=CODING_SYSTEM_PROMPT,
        memory_query="traceback bug fix",
    )
    answer = _strip_confidence(answer)

    if detected_path and os.path.exists(detected_path) and code_context:
        ext      = os.path.splitext(detected_path)[1].lower()
        language = LANGUAGE_MAP.get(ext, "")
        if language in SANDBOX_RUNNERS:
            answer = _sandbox_debug_loop(detected_path, code_context, language, answer)

    print_response(answer, title="✦ Joo Auto-Fix", is_code_mode=True)

    if detected_path and os.path.exists(detected_path) and code_context and "```" in answer:
        choice = input("\n\033[38;2;255;220;80mApply fix to file? (y/n): \033[0m").strip().lower()
        if choice == "y":
            lang  = LANGUAGE_MAP.get(os.path.splitext(detected_path)[1].lower(), "")
            fixed = _extract_code(answer, lang, "")
            if fixed:
                backup = make_backup(detected_path)
                with open(detected_path, "w") as f:
                    f.write(fixed)
                _pulse_print(f"✔ Fixed: {detected_path}", (120, 255, 120))
                _pulse_print(f"✔ Backup: {backup}", (120, 200, 255))

    remember(user_input[:300], answer[:800], tags=["bug"])
    save_history_entry(user_input[:120], answer[:200])
    return True


# ================================================================
#  LOCAL COMMAND HANDLER  (Phase 5 memory commands added)
# ================================================================

def handle_local_commands(user_input):
    global THEME, _RECENT_FILES

    if not user_input.startswith("/"):
        return False

    parts = user_input.strip().split(" ", 1)
    cmd   = parts[0]
    arg   = parts[1].strip() if len(parts) > 1 else ""

    # ── /open ────────────────────────────────────────────────────
    if cmd == "/open":
        return handle_open_command(arg)

    # ─────────────────────────────────────────────────────────────
    # PHASE 5 — /memory commands
    # ─────────────────────────────────────────────────────────────
    if cmd == "/memory":
        sub_parts = arg.strip().split(None, 1)
        sub       = sub_parts[0].lower() if sub_parts else ""
        rest      = sub_parts[1].strip() if len(sub_parts) > 1 else ""

        if sub == "stats" or sub == "":
            stats = memory_stats()
            lines = [
                f"  ✦ Total memories: {stats['total']}",
                f"  ✦ Stored at:      {stats['path']}",
                f"  ✦ Oldest:         {stats['oldest'] or 'n/a'}",
                f"  ✦ Newest:         {stats['newest'] or 'n/a'}",
                f"  ✦ Top tags:       {', '.join(f'{t}({c})' for t, c in stats['top_tags'])}",
            ]
            print()
            for line in lines:
                _pulse_print(line, (120, 255, 200))
            print()
            return True

        if sub == "recall":
            if not rest:
                print("Usage: /memory recall <query>")
                return True
            hits = recall(rest, top_k=5)
            if not hits:
                print("\033[38;2;255;220;80m⚠ No relevant memories found.\033[0m")
                return True
            console.print(f"\n[bright_cyan]── Memory Recall: '{rest}' ─────────────────[/bright_cyan]")
            for i, m in enumerate(hits, 1):
                console.print(f"[dim]#{i}  {m['time']}  tags: {', '.join(m.get('tags', []))}[/dim]")
                console.print(f"[bright_magenta]you:[/bright_magenta] {m['user'][:100]}")
                console.print(f"[bright_cyan]joo:[/bright_cyan] {m['response'][:150]}\n")
            return True

        if sub == "tag":
            if not rest:
                print("Usage: /memory tag <tag>   (e.g. bug, style, git, testing)")
                return True
            hits = recall_by_tag(rest)
            if not hits:
                print(f"\033[38;2;255;220;80m⚠ No memories tagged '{rest}'.\033[0m")
                return True
            console.print(f"\n[bright_cyan]── Memories tagged '{rest}' ──────────────[/bright_cyan]")
            for m in hits[:10]:
                console.print(f"[dim]{m['time']}[/dim]  [bright_magenta]{m['user'][:80]}[/bright_magenta]")
            return True

        if sub == "clear":
            confirm = input("\033[38;2;255;80;80m⚠ Wipe ALL persistent memories? (y/n): \033[0m").strip().lower()
            if confirm == "y":
                forget_all()
                _pulse_print("✔ All memories cleared.", (120, 255, 120))
            else:
                print("\033[38;2;255;160;80m✔ Cancelled.\033[0m")
            return True

        print("Usage: /memory [stats | recall <query> | tag <tag> | clear]")
        return True

    # ── /help / /options ──────────────────────────────────────────
    if cmd in ["/option", "/options", "/help"]:
        gradient = [
            "\033[38;2;255;80;200m",
            "\033[38;2;220;80;240m",
            "\033[38;2;180;100;255m",
            "\033[38;2;130;140;255m",
            "\033[38;2;80;180;255m",
            "\033[38;2;80;220;230m",
        ]
        reset = "\033[0m"

        def _ml(text: str) -> str:
            """Pad/trim text to exactly 62 chars between ║ borders."""
            t = text[:62]
            return "║" + t + " " * (62 - len(t)) + "║"

        def grad(text, idx):
            return gradient[idx % len(gradient)] + text + reset

        B = "╔" + "═" * 62 + "╗"
        E = "╚" + "═" * 62 + "╝"
        SP = _ml("")
        lines = [
            (B,  0),
            (SP, 0),
            (_ml("   ✦ JOO AI v5 — COMMAND MENU ✦"), 0),
            (SP, 0),
            (_ml("  ── FILES ─────────────────────────────────────────────"), 1),
            (_ml("  /find <name>       → case-insensitive file/folder search"), 1),
            (_ml("  /cd <path>         → change directory"), 1),
            (_ml("  /ls [path]         → list files"), 1),
            (_ml("  /pwd               → current path"), 1),
            (SP, 0),
            (_ml("  ── CREATE / DELETE ────────────────────────────────────"), 2),
            (_ml("  /create-f <dir>    → create folder"), 2),
            (_ml("  /create-fs <file>  → create file"), 2),
            (_ml("  /delete <path>     → delete (y/n confirm)"), 2),
            (_ml("  /undo <file>       → restore last backup"), 2),
            (SP, 0),
            (_ml("  ── READ / HISTORY ──────────────────────────────────────"), 3),
            (_ml("  /read <file>       → read file content"), 3),
            (_ml("  /history           → show past sessions"), 3),
            (_ml("  /history-clear     → delete all history"), 3),
            (_ml("  /history go <n>    → jump to history entry #n"), 3),
            (SP, 0),
            (_ml("  ── PHASE 5: MEMORY ────────────────────────────────────"), 4),
            (_ml("  /memory            → show memory stats"), 4),
            (_ml("  /memory recall q   → find memories matching query q"), 4),
            (_ml("  /memory tag <tag>  → browse by tag (bug/style/git/...)"), 4),
            (_ml("  /memory clear      → wipe all persistent memories"), 4),
            (SP, 0),
            (_ml("  ── LAUNCH APPS ────────────────────────────────────────"), 4),
            (_ml("  /open vscode       → launch VS Code"), 4),
            (_ml("  /open spotify      → launch Spotify"), 4),
            (_ml("  /open https://...  → open URL in browser"), 4),
            (SP, 0),
            (_ml("  ── THEME / SYSTEM ─────────────────────────────────────"), 4),
            (_ml("  /theme dark/light  → switch UI theme"), 4),
            (_ml("  /clear             → clear screen"), 4),
            (_ml("  /uptime            → session uptime"), 4),
            (_ml("  /exit              → exit Joo"), 4),
            (SP, 0),
            (_ml("  ── CODE MODE (#) — multi-file: cmd f1.py f2.py ... ────"), 5),
            (_ml("  #debug  file(s)    → deep bug analysis + fix"), 5),
            (_ml("  #edit   file(s)    → improve code quality"), 5),
            (_ml("  #edit -t 30 f.py   → quick edit (time limit)"), 5),
            (_ml("  #explain file(s)   → layered explanation"), 5),
            (_ml("  #test   file(s)    → generate unit tests"), 5),
            (_ml("  #refactor file(s)  → clean up code"), 5),
            (_ml("  #compare file.py   → diff vs last backup"), 5),
            (_ml("  #run file.py       → execute in sandbox"), 5),
            (_ml("  #search pat [dir]  → grep pattern in files"), 5),
            (_ml("  #info file.py      → file stats"), 5),
            (SP, 0),
            (_ml("  ── PHASE 6: PROJECT AUDIT ─────────────────────────────"), 0),
            (_ml("  #audit [folder]    → full project scan ✦ NEW"), 0),
            (_ml("    finds: dead code, circular imports, naming issues,"), 0),
            (_ml("    missing tests, security risks, magic numbers"), 0),
            (SP, 0),
            (_ml("  ── PHASE 7: GIT INTEGRATION ───────────────────────────"), 0),
            (_ml("  #commit            → Joo writes commit message ✦ NEW"), 0),
            (_ml("  #commit file.diff  → write message from diff file"), 0),
            (_ml("  #review            → review current branch vs main"), 0),
            (_ml("  #review main       → review vs specific branch"), 0),
            (_ml("  #blame file.py     → trace bug to origin commit ✦ NEW"), 0),
            (_ml("  #blame file.py:10-50 'desc'  → focused blame"), 0),
            (SP, 0),
            (_ml("  ── PHASE 8: CODEBASE CHAT ─────────────────────────────"), 0),
            (_ml("  #chat <question>   → ask anything about your repo"), 0),
            (_ml("  #chat ~/proj q     → chat about a specific project"), 0),
            (_ml("    reads entire repo, maps call chains, plain English"), 0),
            (SP, 0),
            (_ml("  ── PHASE 9: PLUGIN / TOOL SYSTEM ──────────────────────"), 0),
            (_ml("  #lint file.py      → run ruff/pylint/eslint + explain"), 0),
            (_ml("  #format file.py    → run black/prettier + explain diff"), 0),
            (_ml("  #typecheck file.py → run mypy/tsc + explain errors"), 0),
            (_ml("  #deps [folder]     → pip-audit / npm audit + fixes"), 0),
            (SP, 0),
            (_ml("  ── PHASE 10: WEB SEARCH MODE ──────────────────────────"), 0),
            (_ml("  #web <question>    → search web, pull docs, answer"), 0),
            (_ml("    DuckDuckGo + page scraping as RAG — never stale ✦"), 0),
            (SP, 0),
            (E, 0),
        ]

        print()
        for text, color_idx in lines:
            sys.stdout.write(grad(text, color_idx) + "\n")
            sys.stdout.flush()
            time.sleep(0.010)
        print()
        return True

    # ── /find ─────────────────────────────────────────────────────
    if cmd == "/find":
        if not arg:
            print("Usage: /find .py  OR  /find MyFolder  OR  /find iloveyou.java")
            return True

        SKIP_DIRS = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            "proc", "sys", "dev", "run", "snap", "boot", "lost+found",
        }
        query_lower = arg.lower()
        found = []

        def _walk_find(search_root):
            try:
                for dirpath, dirs, fnames in os.walk(search_root, followlinks=False):
                    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
                    for name in fnames + dirs:
                        if query_lower in name.lower():
                            found.append(os.path.join(dirpath, name))
                        if len(found) >= 200:
                            return
            except PermissionError:
                pass

        # 1. Search cwd first
        sys.stdout.write(f"\033[38;2;120;200;255m⟳  Searching {os.getcwd()}...\033[0m\r")
        sys.stdout.flush()
        _walk_find(os.getcwd())

        # 2. Not found? Expand to drive root, then home, then /
        if not found:
            cwd_parts = [p for p in os.getcwd().split(os.sep) if p]
            search_roots = []
            # Detect /run/media/<user>/<drive> — Linux external drive
            if len(cwd_parts) >= 4 and cwd_parts[0] == "run" and cwd_parts[1] == "media":
                drive_root = os.sep + os.path.join(*cwd_parts[:4])
                search_roots.append(drive_root)
            search_roots.append(os.path.expanduser("~"))
            search_roots.append("/")

            for sroot in search_roots:
                if not os.path.exists(sroot):
                    continue
                sys.stdout.write(f"\033[38;2;120;200;255m⟳  Searching {sroot}...\033[0m\r")
                sys.stdout.flush()
                _walk_find(sroot)
                if found:
                    break

        sys.stdout.write(" " * 70 + "\r")
        sys.stdout.flush()

        if not found:
            print(f"\033[38;2;255;220;80m⚠ Nothing matched \'{arg}\' anywhere on the system.\033[0m")
        else:
            for f in found[:50]:
                tag = "\U0001f4c1" if os.path.isdir(f) else "\U0001f4c4"
                print(f"\033[38;2;120;255;200m{tag} {f}\033[0m")
            if len(found) > 50:
                print(f"\033[38;2;180;180;180m  ... and {len(found)-50} more\033[0m")
        return True

    # ── /cd ───────────────────────────────────────────────────────
    if cmd == "/cd":
        if not arg:
            print("Usage: /cd path")
            return True
        path = os.path.abspath(os.path.expanduser(arg))
        print(change_directory(path))
        return True

    # ── /create-fs ────────────────────────────────────────────────
    if cmd == "/create-fs":
        if not arg:
            print("Usage: /create-fs file.py")
            return True
        path = os.path.expanduser(arg)
        result = create_file(path)
        name   = os.path.basename(path)
        _RECENT_FILES[name] = "new"
        print(result)
        print(f"\033[38;2;80;255;140m  📄 ✦ NEW FILE CREATED: {name}\033[0m")
        return True

    # ── /create-f ────────────────────────────────────────────────
    if cmd == "/create-f":
        if not arg:
            print("Usage: /create-f folder")
            return True
        path = os.path.expanduser(arg)
        result = create_folder(path)
        name   = os.path.basename(path)
        _RECENT_FILES[name] = "folder_new"
        print(result)
        print(f"\033[38;2;80;200;255m  📁 ✦ NEW FOLDER CREATED: {name}\033[0m")
        return True

    # ── /read ────────────────────────────────────────────────────
    if cmd == "/read":
        content = read_file(os.path.expanduser(arg))
        ext     = os.path.splitext(arg)[1].lower()
        lang    = LANGUAGE_MAP.get(ext, "text")
        console.print(Syntax(content, lang, theme="monokai", line_numbers=True))
        return True

    # ── /ls ──────────────────────────────────────────────────────
    if cmd == "/ls":
        items = list_files(os.path.expanduser(arg or "."))

        if isinstance(items, str):
            print(items)
            return True

        if not items:
            print("\033[38;2;255;255;0m⚠ Empty directory\033[0m")
            return True

        display_items = list(items)
        for name, status in _RECENT_FILES.items():
            if status == "deleted" and name not in display_items:
                display_items.append(name)

        print()
        for i in display_items:
            full_path = os.path.join(os.getcwd(), i)
            status    = _RECENT_FILES.get(i)
            if status == "folder_new":
                print(f"\033[38;2;80;200;255m📁 {i}  ✦ NEW FOLDER\033[0m")
            elif status == "new":
                print(f"\033[38;2;80;255;140m📄 {i}  ✦ NEW\033[0m")
            elif status == "deleted":
                print(f"\033[38;2;255;80;80m🗑  {i}  ✦ DELETED\033[0m")
            elif os.path.isdir(full_path):
                print(f"\033[38;2;120;160;255m📁 {i}\033[0m")
            else:
                print(f"\033[38;2;255;160;80m📄 {i}\033[0m")
        print()
        return True

    # ── /delete ──────────────────────────────────────────────────
    if cmd == "/delete":
        if not arg:
            print("Usage: /delete <path>")
            return True
        path = os.path.expanduser(arg)
        if not os.path.exists(path):
            print(f"\033[38;2;255;80;80m✘ Not found: {path}\033[0m")
            return True

        is_dir = os.path.isdir(path)
        kind   = "folder" if is_dir else "file"
        print(f"\033[38;2;255;80;80m⚠ You are about to delete this {kind}:\033[0m")
        print(f"\033[38;2;255;120;120m   {path}\033[0m")
        if is_dir:
            print(f"\033[38;2;255;80;80m  ⚠ This will delete ALL contents inside.\033[0m")

        confirm = input(f"\033[38;2;255;80;80m  Confirm delete? (y/n): \033[0m").strip().lower()
        if confirm == "y":
            name = os.path.basename(path)
            try:
                if is_dir:
                    shutil.rmtree(path)
                    print(f"\033[38;2;255;80;80m🗑  Folder deleted: {path}\033[0m")
                else:
                    print(delete_file(path))
                _RECENT_FILES[name] = "deleted"
            except Exception as e:
                print(f"\033[38;2;255;80;80m✘ Delete failed: {e}\033[0m")
        else:
            print("\033[38;2;255;160;80m✔ Cancelled. Nothing was deleted.\033[0m")
        return True

    # ── /undo ────────────────────────────────────────────────────
    if cmd == "/undo":
        if not arg:
            print("Usage: /undo file.py")
            return True
        path = os.path.expanduser(arg)
        print(undo_file(path))
        return True

    # ── /history ─────────────────────────────────────────────────
    if cmd == "/history":
        sub_parts = arg.strip().split()
        sub_cmd   = sub_parts[0].lower() if sub_parts else ""

        if sub_cmd == "go":
            try:
                n = int(sub_parts[1]) - 1
            except (IndexError, ValueError):
                print("Usage: /history go <number>")
                return True
            entries = get_history_log(50)
            if not entries or n < 0 or n >= len(entries):
                print("\033[38;2;255;80;80m✘ History entry not found.\033[0m")
                return True
            entry  = entries[n]
            print(f"\033[38;2;120;200;255m⟳ Recalling entry #{n+1}...\033[0m")
            answer = ask_ollama(history_recall_prompt(entry))
            answer = _strip_confidence(answer)
            print_response(answer, title=f"✦ History #{n+1}", is_code_mode=False)
            return True

        entries = get_history_log(30)
        if not entries:
            print("\033[38;2;255;220;80m⚠ No history found.\033[0m")
            return True

        console.print("\n[bright_cyan]── Session History ────────────────────────────────[/bright_cyan]")
        for idx, e in enumerate(entries, 1):
            t   = e.get("time", "")
            msg = e.get("user", "")[:80]
            console.print(f"[dim]#{idx:>2}  {t}[/dim]  [bright_magenta]you:[/bright_magenta] {msg}")
        console.print("[bright_cyan]──────────────────────────────────────────────────[/bright_cyan]")
        console.print("[dim]Tip: /history go <n> to jump to an entry[/dim]\n")
        return True

    # ── /history-clear ───────────────────────────────────────────
    if cmd == "/history-clear":
        confirm = input("\033[38;2;255;80;80m⚠ Delete ALL history? (y/n): \033[0m").strip().lower()
        if confirm == "y":
            candidates = [
                os.path.expanduser("~/.joo_history.json"),
                os.path.expanduser("~/.joo/history.json"),
                "joo_history.json", "history.json",
            ]
            cleared = False
            for hpath in candidates:
                if os.path.exists(hpath):
                    try:
                        with open(hpath, "w") as f:
                            f.write("[]")
                        print(f"\033[38;2;120;255;120m✔ History cleared: {hpath}\033[0m")
                        cleared = True
                    except Exception as e:
                        print(f"\033[38;2;255;80;80m✘ Could not clear {hpath}: {e}\033[0m")
            if not cleared:
                print("\033[38;2;255;220;80m⚠ No history file found — in-memory history reset.\033[0m")
        else:
            print("\033[38;2;255;160;80m✔ Cancelled.\033[0m")
        return True

    # ── /pwd ─────────────────────────────────────────────────────
    if cmd == "/pwd":
        print(f"\033[38;2;120;200;255m{os.getcwd()}\033[0m")
        return True

    # ── /clear ───────────────────────────────────────────────────
    if cmd == "/clear":
        os.system("clear")
        return True

    # ── /uptime ──────────────────────────────────────────────────
    if cmd == "/uptime":
        elapsed = int(time.time() - _SESSION_START)
        h, rem  = divmod(elapsed, 3600)
        m, s    = divmod(rem, 60)
        _pulse_print(f"✦ Session uptime: {h:02d}h {m:02d}m {s:02d}s", (120, 255, 200))
        return True

    # ── /theme ───────────────────────────────────────────────────
    if cmd == "/theme":
        global THEME
        if arg.lower() in ["dark", "light"]:
            THEME = arg.lower()
            print(f"\033[38;2;120;255;200m✔ Theme set to {THEME}\033[0m")
        else:
            print("\033[38;2;255;180;120mUsage: /theme dark OR /theme light\033[0m")
        return True

    # ── /exit ────────────────────────────────────────────────────
    if cmd == "/exit":
        _pulse_print("✔ Exiting Joo... Goodbye! ✦", (120, 255, 180), delay=0.025)
        sys.exit(0)

    return False


# ================================================================
#  MAIN LOOP
# ================================================================

while True:
    try:
        user_input = input("\033[38;2;255;120;200m\n╰┈✦ \033[0m").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        _pulse_print("✔ Exiting Joo... Goodbye! ✦", (120, 255, 180), delay=0.025)
        break

    if not user_input:
        continue

    if user_input.startswith("#"):
        handle_code_mode(user_input)
        continue

    if user_input.startswith("/"):
        if _suggest_command(user_input):
            continue
        if handle_local_commands(user_input):
            continue
        print(f"\033[38;2;255;80;80m✘ Unknown command. Type /help to see all commands.\033[0m")
        continue

    if handle_traceback(user_input):
        continue

    try:
        answer = ask_ollama(chat_prompt(user_input), memory_query=user_input)
        answer = _strip_confidence(answer)

        if execute_ai_action(answer):
            continue

        # Streaming already printed the raw text live.
        # Only re-render in a panel if there are code blocks to syntax-highlight.
        if "```" in answer:
            print_response(answer, is_code_mode=True)

        # Phase 5: persist every general chat turn too
        add_history(user_input, answer)
        remember(user_input, answer)
        save_history_entry(user_input, answer)

    except Exception as e:
        console.print(f"[bright_red]✘ Error:[/bright_red] {e}")
