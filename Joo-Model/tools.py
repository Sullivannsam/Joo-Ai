import time
import shutil
import os
import re
import json


FILE_CACHE = {}

# ---------------- CACHE ----------------
CACHE = {}
CACHE_TIME = {}
CACHE_TTL = 300

# ---------------- HISTORY PATH ----------------
HISTORY_PATH = os.path.expanduser("~/.joo/history.json")

# ---------------- COLORS ----------------
GREEN   = "\033[38;2;120;255;120m"
RED     = "\033[38;2;255;80;80m"
CYAN    = "\033[38;2;120;200;255m"
YELLOW  = "\033[38;2;255;220;80m"
ORANGE  = "\033[38;2;255;160;80m"
BLUE    = "\033[38;2;120;160;255m"
MAGENTA = "\033[38;2;255;120;200m"
RESET   = "\033[0m"


# ---------------- CREATE FILE ----------------
def create_file(path, content=""):
    with open(path, "w") as f:
        f.write(content)
    return f"{GREEN}✔ Created file: {path}{RESET}"


# ---------------- CREATE FOLDER ----------------
def create_folder(path):
    os.makedirs(path, exist_ok=True)
    return f"{GREEN}✔ Created folder: {path}{RESET}"


# ---------------- READ FILE ----------------
def read_file(path):
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception as e:
        return f"{RED}Error reading file: {e}{RESET}"


# ---------------- LIST FILES ----------------
def list_files(path="."):
    try:
        return os.listdir(path)
    except Exception as e:
        return f"{YELLOW}UNKNOWN DIRECTORY: {e}{RESET}"


# ---------------- DELETE FILE ----------------
def delete_file(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
        return f"{RED}✔ Deleted folder: {path}{RESET}"

    if os.path.isfile(path):
        os.remove(path)
        return f"{RED}✔ Deleted file: {path}{RESET}"

    return f"{RED}Not found: {path}{RESET}"


# ---------------- VERSION STACK BACKUP ----------------
def make_backup(path):
    """Save versioned backup: .bak1 is newest, .bak5 is oldest. Returns backup path."""
    MAX = 5
    # shift old backups down
    for i in range(MAX - 1, 0, -1):
        src = f"{path}.bak{i}"
        dst = f"{path}.bak{i+1}"
        if os.path.exists(src):
            shutil.copy2(src, dst)
    # save current as .bak1
    backup_path = f"{path}.bak1"
    shutil.copy2(path, backup_path)
    return backup_path


# ---------------- UNDO FILE ----------------
def undo_file(path):
    """Restore from .bak1, shift stack forward."""
    backup = f"{path}.bak1"
    if not os.path.exists(backup):
        return f"{YELLOW}⚠ No backup found for: {path}{RESET}"

    # restore
    shutil.copy2(backup, path)

    # shift stack: bak2 → bak1, bak3 → bak2, etc.
    MAX = 5
    for i in range(1, MAX):
        src = f"{path}.bak{i+1}"
        dst = f"{path}.bak{i}"
        if os.path.exists(src):
            shutil.copy2(src, dst)
            os.remove(src)
        else:
            if os.path.exists(dst):
                os.remove(dst)
            break

    return f"{GREEN}✔ Restored: {path}{RESET}"


# ---------------- FIND FILES ----------------
def find_files(keyword, path="/"):
    global FILE_CACHE

    if keyword in FILE_CACHE:
        return FILE_CACHE[keyword]

    search_paths = ["/home", "/run/media", "/mnt", "/media"]
    skip_dirs    = ["/proc", "/sys", "/dev", "/run", "/tmp"]
    results      = set()

    for base in search_paths:
        if not os.path.exists(base):
            continue
        for root, dirs, files in os.walk(base):
            if any(root.startswith(skip) for skip in skip_dirs):
                continue
            for file in files:
                if keyword.lower() in file.lower():
                    results.add(os.path.join(root, file))

    if not results:
        return []

    output = list(results)[:50]
    FILE_CACHE[keyword] = output
    return output


# ---------------- CHANGE DIRECTORY ----------------
def change_directory(path):
    try:
        os.chdir(path)
        return f"{GREEN}✔ Changed directory to: {os.getcwd()}{RESET}"
    except Exception as e:
        return f"{RED}Error: {e}{RESET}"


# ---------------- CURRENT DIR ----------------
def current_dir():
    return f"{CYAN}{os.getcwd()}{RESET}"


# ---------------- PERSISTENT HISTORY ----------------
def save_history_entry(user, assistant):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    history = []
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, "r") as f:
                history = json.load(f)
        except:
            history = []
    history.append({
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "user": user,
        "assistant": assistant
    })
    # keep last 100 entries
    history = history[-100:]
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def get_history_log(limit=20):
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r") as f:
            history = json.load(f)
        return history[-limit:]
    except:
        return []


# ---------------- DETECT TRACEBACK ----------------
def detect_traceback(text):
    """Returns True if the input looks like a Python or Java traceback."""
    python_signs = ["Traceback (most recent call last)", "File \"", "Error:", "Exception:"]
    java_signs   = ["Exception in thread", "at ", ".java:"]
    text_lower   = text.lower()
    for s in python_signs + java_signs:
        if s.lower() in text_lower:
            return True
    return False


def extract_file_from_traceback(text):
    """Try to extract the file path mentioned in a Python traceback."""
    match = re.search(r'File "([^"]+)"', text)
    if match:
        return match.group(1)
    return None


# ---------------- EXECUTE AI JSON ----------------
def execute_ai_json(data):
    try:
        if data["type"] == "chat":
            print(data["message"])
            return True

        if data["type"] != "tool":
            print(f"{RED}Invalid type{RESET}")
            return False

        tool = data.get("tool")
        args = data.get("args", {})
        path    = args.get("path")
        content = args.get("content", "")

        if tool == "create_file":
            with open(path, "w") as f:
                f.write(content)
            print(f"{GREEN}✔ Created file: {path}{RESET}")
            return True

        if tool == "create_folder":
            os.makedirs(path, exist_ok=True)
            print(f"{GREEN}✔ Created folder: {path}{RESET}")
            return True

        if tool == "read_file":
            with open(path, "r") as f:
                print(CYAN + f.read() + RESET)
            return True

        if tool == "delete_file":
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            print(f"{RED}✔ Deleted: {path}{RESET}")
            return True

        if tool == "list_files":
            print(os.listdir(path or "."))
            return True

        if tool == "change_directory":
            os.chdir(path)
            print(f"{GREEN}✔ Changed dir: {os.getcwd()}{RESET}")
            return True

        print(f"{RED}Unknown tool{RESET}")
        return False

    except Exception as e:
        print(f"{RED}Tool error: {e}{RESET}")
        return False


# ---------------- AI ACTION ----------------
def execute_ai_action(text):
    if "ACTION:" not in text:
        return False

    try:
        action_match  = re.search(r"ACTION:\s*(\w+)", text)
        path_match    = re.search(r"PATH:\s*(.+)", text)

        if not action_match or not path_match:
            print(f"{RED}Invalid tool format{RESET}")
            return False

        action  = action_match.group(1)
        path    = path_match.group(1).strip()

        content_match = re.search(r"CONTENT:\s*(.*)", text)
        content = content_match.group(1).strip() if content_match else ""

        print(f"{MAGENTA}Action: {action} → {path}{RESET}")
        return True

    except Exception as e:
        print(f"{RED}Tool error: {e}{RESET}")
        return False
