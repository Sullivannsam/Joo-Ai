# ================================================================
#  JOO AI — SECURITY SCANNER  (Phase 11)
#  ✦ #sec <file|folder> — deep security scan
#  ✦ Finds: secrets, injection risks, broken crypto, path traversal,
#           XSS/SSRF, insecure deserialization, CVEs in deps
#  ✦ No external tools required — pure static analysis
#  ✦ Optionally leverages pip-audit / npm audit / trivy if installed
# ================================================================

import os
import re
import ast
import json
import subprocess
from collections import defaultdict

# ── File collection ───────────────────────────────────────────────

SUPPORTED_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go",
    ".rs", ".php", ".rb", ".swift", ".kt", ".cs", ".cpp", ".c",
    ".sh", ".bash", ".env", ".yaml", ".yml", ".toml", ".json",
    ".conf", ".config", ".ini", ".properties",
}

IGNORE_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    "env", ".env", "dist", "build", ".idea", ".vscode",
    "coverage", ".pytest_cache", ".mypy_cache",
}

def _collect_files(path: str, max_files: int = 80) -> list[str]:
    if os.path.isfile(path):
        return [path]
    results = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            # also catch files like .env, Dockerfile, etc.
            if ext in SUPPORTED_EXTS or fname in {
                ".env", ".env.local", ".env.production",
                "Dockerfile", "docker-compose.yml",
                "requirements.txt", "package.json",
            }:
                results.append(os.path.join(root, fname))
                if len(results) >= max_files:
                    return results
    return results


def _read(path: str, max_bytes: int = 50_000) -> str:
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read(max_bytes)
    except Exception:
        return ""


# ================================================================
#  FINDING CATEGORIES
# ================================================================

# Each entry: (regex_pattern, severity, category, description, cwe)
# severity: CRITICAL / HIGH / MEDIUM / LOW / INFO

SECRET_PATTERNS = [
    # Hardcoded credentials
    (r'(?i)(password|passwd|pwd)\s*=\s*["\'][^"\']{4,}["\']',
     "CRITICAL", "secret", "Hardcoded password literal", "CWE-798"),
    (r'(?i)(api_key|apikey|api-key)\s*=\s*["\'][^"\']{8,}["\']',
     "CRITICAL", "secret", "Hardcoded API key", "CWE-798"),
    (r'(?i)(secret|secret_key|secretkey)\s*=\s*["\'][^"\']{6,}["\']',
     "CRITICAL", "secret", "Hardcoded secret", "CWE-798"),
    (r'(?i)(token|access_token|auth_token)\s*=\s*["\'][^"\']{8,}["\']',
     "CRITICAL", "secret", "Hardcoded token", "CWE-798"),
    (r'(?i)(private_key|privatekey)\s*=\s*["\'][^"\']{8,}["\']',
     "CRITICAL", "secret", "Hardcoded private key", "CWE-798"),
    # Cloud provider keys
    (r'AKIA[0-9A-Z]{16}',
     "CRITICAL", "secret", "AWS Access Key ID pattern", "CWE-798"),
    (r'(?i)sk-[a-zA-Z0-9]{32,}',
     "CRITICAL", "secret", "OpenAI / Stripe secret key pattern", "CWE-798"),
    (r'(?i)ghp_[a-zA-Z0-9]{36}',
     "CRITICAL", "secret", "GitHub Personal Access Token pattern", "CWE-798"),
    (r'(?i)-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----',
     "CRITICAL", "secret", "Private key embedded in source", "CWE-321"),
    # Connection strings
    (r'(?i)(mongodb|postgres|mysql|redis|amqp):\/\/[^"\'>\s]{10,}',
     "HIGH", "secret", "Connection string with potential credentials", "CWE-312"),
]

INJECTION_PATTERNS = [
    (r'\beval\s*\(',
     "CRITICAL", "injection", "eval() — arbitrary code execution", "CWE-94"),
    (r'\bexec\s*\(',
     "HIGH", "injection", "exec() — code injection risk", "CWE-94"),
    (r'os\.system\s*\(',
     "HIGH", "injection", "os.system() — command injection risk, use subprocess with args list", "CWE-78"),
    (r'subprocess\.(call|run|Popen).*shell\s*=\s*True',
     "HIGH", "injection", "subprocess shell=True — command injection if input unsanitized", "CWE-78"),
    (r'__import__\s*\(',
     "HIGH", "injection", "Dynamic __import__() — code injection vector", "CWE-94"),
    # SQL injection
    (r'(?i)(execute|query|cursor\.execute)\s*\(\s*[f"\'].*%',
     "CRITICAL", "sql_injection", "String-interpolated SQL query — use parameterized queries", "CWE-89"),
    (r'(?i)(execute|query)\s*\(\s*[f"\'].*\{',
     "CRITICAL", "sql_injection", "f-string in SQL query — use parameterized queries", "CWE-89"),
    (r'(?i)SELECT.{0,100}WHERE.{0,50}\+\s*[a-z_]',
     "HIGH", "sql_injection", "SQL string concatenation — injection risk", "CWE-89"),
    # Path traversal
    (r'open\s*\(\s*[a-z_]*path',
     "MEDIUM", "path_traversal", "File open with unsanitized path variable", "CWE-22"),
    (r'os\.path\.join.*request\.(args|form|data|json)',
     "HIGH", "path_traversal", "Path built from user input — traversal risk", "CWE-22"),
    # Template injection
    (r'render_template_string\s*\(\s*[a-z_]*',
     "HIGH", "injection", "Jinja2 render_template_string with variable — SSTI risk", "CWE-94"),
]

CRYPTO_PATTERNS = [
    (r'\bmd5\b',
     "HIGH", "crypto", "MD5 is cryptographically broken — use SHA-256 or better", "CWE-327"),
    (r'\bsha1\b',
     "MEDIUM", "crypto", "SHA-1 is cryptographically weak — use SHA-256 or better", "CWE-327"),
    (r'(?i)des\.new|DES\(',
     "CRITICAL", "crypto", "DES encryption — broken cipher, use AES-256", "CWE-327"),
    (r'(?i)RC4',
     "HIGH", "crypto", "RC4 cipher — broken, use AES-GCM or ChaCha20", "CWE-327"),
    (r'random\.(random|randint|choice)\(',
     "MEDIUM", "crypto", "random module — not cryptographically secure, use secrets module", "CWE-338"),
    (r'(?i)ssl\.PROTOCOL_TLS[Vv]1\b|PROTOCOL_SSLv[23]',
     "HIGH", "crypto", "Deprecated TLS/SSL version — use TLS 1.2+ or TLSv1_2+", "CWE-326"),
    (r'verify\s*=\s*False',
     "HIGH", "crypto", "SSL certificate verification disabled — MITM risk", "CWE-295"),
]

DESERIALIZATION_PATTERNS = [
    (r'pickle\.loads?\s*\(',
     "CRITICAL", "deserialization", "pickle.load() — arbitrary code execution on untrusted data", "CWE-502"),
    (r'yaml\.load\s*\([^,)]+\)',
     "HIGH", "deserialization", "yaml.load() without Loader= — use yaml.safe_load()", "CWE-502"),
    (r'marshal\.loads?\s*\(',
     "HIGH", "deserialization", "marshal.load() — unsafe deserialization", "CWE-502"),
    (r'jsonpickle\.decode\s*\(',
     "HIGH", "deserialization", "jsonpickle.decode() — can execute arbitrary code", "CWE-502"),
]

XSS_SSRF_PATTERNS = [
    (r'innerHTML\s*=\s*(?!["\'`])',
     "HIGH", "xss", "innerHTML with dynamic value — XSS risk, use textContent", "CWE-79"),
    (r'dangerouslySetInnerHTML',
     "HIGH", "xss", "React dangerouslySetInnerHTML — XSS risk if input unsanitized", "CWE-79"),
    (r'document\.write\s*\(',
     "HIGH", "xss", "document.write() with dynamic content — XSS risk", "CWE-79"),
    (r'(?i)requests\.(get|post|put)\s*\(\s*[a-z_]*url',
     "MEDIUM", "ssrf", "HTTP request with URL from variable — SSRF risk if user-controlled", "CWE-918"),
    (r'(?i)urllib\.request\.urlopen\s*\(\s*[a-z_]',
     "MEDIUM", "ssrf", "urlopen with variable URL — SSRF risk if user-controlled", "CWE-918"),
]

AUTH_PATTERNS = [
    (r'(?i)if\s+.*password\s*==\s*["\']',
     "HIGH", "auth", "Plain-text password comparison — use bcrypt/argon2", "CWE-256"),
    (r'(?i)jwt\.decode\s*\(.*verify.*false',
     "CRITICAL", "auth", "JWT signature verification disabled", "CWE-347"),
    (r'(?i)@app\.route.*methods.*["\']GET["\'].*(?:delete|remove|drop)',
     "HIGH", "auth", "Destructive action on GET request — should be POST+CSRF protected", "CWE-352"),
    (r'(?i)debug\s*=\s*True',
     "HIGH", "auth", "Debug mode enabled — never use in production (exposes stack traces)", "CWE-94"),
    (r'(?i)SECRET_KEY\s*=\s*["\'](?:dev|test|secret|changeme|default)["\']',
     "CRITICAL", "auth", "Weak/default SECRET_KEY — replace with cryptographically random value", "CWE-798"),
]

MISC_PATTERNS = [
    (r'(?i)#\s*(nosec|noqa\s*:\s*S)',
     "INFO", "suppression", "Security check suppressed — review if intentional", "N/A"),
    (r'(?i)CORS.*allow_origins.*\*',
     "MEDIUM", "cors", "CORS wildcard origin (*) — restrict to known domains in production", "CWE-942"),
    (r'(?i)allow_all_origins\s*=\s*True',
     "MEDIUM", "cors", "CORS allow all origins — restrict in production", "CWE-942"),
    (r'(?i)(print|console\.log)\s*\(.*(?:password|token|secret|key)',
     "MEDIUM", "logging", "Sensitive value possibly logged — remove or mask", "CWE-532"),
]

ALL_PATTERNS = (
    SECRET_PATTERNS +
    INJECTION_PATTERNS +
    CRYPTO_PATTERNS +
    DESERIALIZATION_PATTERNS +
    XSS_SSRF_PATTERNS +
    AUTH_PATTERNS +
    MISC_PATTERNS
)


# ================================================================
#  PER-FILE SCANNER
# ================================================================

def _scan_file(path: str) -> dict:
    source = _read(path)
    lines  = source.splitlines()
    ext    = os.path.splitext(path)[1].lower()

    findings = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip pure comments (but still check for nosec markers)
        is_comment = stripped.startswith(("#", "//", "*", "--"))

        for pattern, severity, category, desc, cwe in ALL_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                # Don't skip comments for secret patterns — secrets in comments are still leaks
                if is_comment and category not in ("secret", "suppression"):
                    continue
                findings.append({
                    "line":     i,
                    "severity": severity,
                    "category": category,
                    "detail":   desc,
                    "cwe":      cwe,
                    "snippet":  line.strip()[:120],
                })

    return {
        "path":     path,
        "lines":    len(lines),
        "findings": findings,
    }


# ================================================================
#  DEPENDENCY CVE CHECK (opportunistic — uses installed tools)
# ================================================================

def _check_deps_cves(folder: str) -> list[dict]:
    """Run pip-audit or npm audit if available. Returns list of CVE findings."""
    results = []

    # ── pip-audit ─────────────────────────────────────────────────
    req_file = os.path.join(folder if os.path.isdir(folder) else os.path.dirname(folder), "requirements.txt")
    if os.path.exists(req_file):
        try:
            proc = subprocess.run(
                ["pip-audit", "--requirement", req_file, "--format=json"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode == 0 or proc.stdout.strip():
                data = json.loads(proc.stdout or "[]")
                for dep in data:
                    for vuln in dep.get("vulns", []):
                        results.append({
                            "tool": "pip-audit",
                            "package": dep.get("name", "?"),
                            "version": dep.get("version", "?"),
                            "id": vuln.get("id", "?"),
                            "description": vuln.get("description", "")[:200],
                            "fix_versions": vuln.get("fix_versions", []),
                        })
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    # ── npm audit ─────────────────────────────────────────────────
    pkg_dir = folder if os.path.isdir(folder) else os.path.dirname(folder)
    pkg_json = os.path.join(pkg_dir, "package.json")
    if os.path.exists(pkg_json):
        try:
            proc = subprocess.run(
                ["npm", "audit", "--json"],
                capture_output=True, text=True, timeout=30, cwd=pkg_dir,
            )
            if proc.stdout.strip():
                data = json.loads(proc.stdout)
                vulns = data.get("vulnerabilities", {})
                for name, info in list(vulns.items())[:10]:
                    sev = info.get("severity", "unknown").upper()
                    results.append({
                        "tool": "npm-audit",
                        "package": name,
                        "version": str(info.get("range", "?")),
                        "id": str(info.get("via", ["?"])[0] if info.get("via") else "?")[:40],
                        "description": info.get("title", "")[:200],
                        "fix_versions": [info.get("fixAvailable", False)],
                    })
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    return results


# ================================================================
#  MAIN SCAN RUNNER
# ================================================================

def run_sec_scan(path: str) -> dict:
    """
    Full security scan. Returns structured report dict.
    """
    path  = os.path.abspath(os.path.expanduser(path))
    files = _collect_files(path)

    file_reports = [_scan_file(f) for f in files]
    dep_cves     = _check_deps_cves(path)

    all_findings = [f for r in file_reports for f in r["findings"]]

    critical = [f for f in all_findings if f["severity"] == "CRITICAL"]
    high     = [f for f in all_findings if f["severity"] == "HIGH"]
    medium   = [f for f in all_findings if f["severity"] == "MEDIUM"]
    secrets  = [f for f in all_findings if f["category"] == "secret"]

    # Count unique categories
    category_counts: dict[str, int] = defaultdict(int)
    for f in all_findings:
        category_counts[f["category"]] += 1

    return {
        "path":             path,
        "files_scanned":    len(files),
        "total_findings":   len(all_findings),
        "critical_count":   len(critical),
        "high_count":       len(high),
        "medium_count":     len(medium),
        "secrets_count":    len(secrets),
        "category_counts":  dict(category_counts),
        "file_reports":     file_reports,
        "dep_cves":         dep_cves,
    }


# ================================================================
#  PROMPT BUILDER
# ================================================================

def build_sec_prompt(report: dict) -> str:
    path     = report["path"]
    n_files  = report["files_scanned"]
    total    = report["total_findings"]
    critical = report["critical_count"]
    high     = report["high_count"]
    medium   = report["medium_count"]
    secrets  = report["secrets_count"]
    cats     = report["category_counts"]
    cves     = report["dep_cves"]

    lines = [
        "━━━ TASK: SECURITY AUDIT REPORT ━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"TARGET:   {path}",
        f"FILES:    {n_files} scanned",
        f"FINDINGS: {total} total  "
        f"[CRITICAL: {critical}  HIGH: {high}  MEDIUM: {medium}]",
        f"SECRETS:  {secrets} hardcoded secrets/keys detected",
        "",
        "CATEGORY BREAKDOWN:",
    ]
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        lines.append(f"  {cat:<20} {count} findings")
    lines.append("")

    # ── Critical findings (full detail) ──────────────────────────
    critical_findings = [
        (r["path"], f)
        for r in report["file_reports"]
        for f in r["findings"]
        if f["severity"] == "CRITICAL"
    ]
    if critical_findings:
        lines.append("★ CRITICAL FINDINGS:")
        for fpath, f in critical_findings[:20]:
            rel = os.path.relpath(fpath, report["path"]) if os.path.isdir(report["path"]) else os.path.basename(fpath)
            lines.append(f"  [{f['cwe']}] {rel}:{f['line']}")
            lines.append(f"  → {f['detail']}")
            lines.append(f"  Code: {f['snippet']}")
            lines.append("")

    # ── High findings ─────────────────────────────────────────────
    high_findings = [
        (r["path"], f)
        for r in report["file_reports"]
        for f in r["findings"]
        if f["severity"] == "HIGH"
    ]
    if high_findings:
        lines.append("⚠ HIGH FINDINGS:")
        for fpath, f in high_findings[:15]:
            rel = os.path.relpath(fpath, report["path"]) if os.path.isdir(report["path"]) else os.path.basename(fpath)
            lines.append(f"  [{f['cwe']}] {rel}:{f['line']}  {f['detail']}")
        lines.append("")

    # ── CVE findings from pip-audit / npm audit ───────────────────
    if cves:
        lines.append("◆ DEPENDENCY CVEs:")
        for cve in cves[:10]:
            lines.append(
                f"  [{cve['tool']}] {cve['package']} {cve['version']}  "
                f"ID: {cve['id']}"
            )
            if cve.get("description"):
                lines.append(f"  → {cve['description'][:120]}")
        lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "Produce a structured security report with these sections:",
        "",
        "SECTION 1 — THREAT SUMMARY",
        "  ✦ Overall risk level: CRITICAL / HIGH / MEDIUM / LOW",
        "  ✦ Top 3 most dangerous issues RIGHT NOW",
        "  ✦ Are any of these actively exploitable?",
        "",
        "SECTION 2 — CRITICAL & HIGH ISSUES (fix immediately)",
        "  For each critical/high finding:",
        "  → Explain the vulnerability in plain English",
        "  → Show the exact secure code fix",
        "  → CWE reference and real-world exploit scenario",
        "",
        "SECTION 3 — SECRETS & CREDENTIAL EXPOSURE",
        "  ✦ Where are secrets hardcoded?",
        "  ✔ Migration plan: move to environment variables / secret manager",
        "  ⚠ Should these secrets be rotated immediately?",
        "",
        "SECTION 4 — DEPENDENCY VULNERABILITIES",
        "  ✦ CVEs found in dependencies",
        "  ✔ Exact version upgrades to fix each",
        "",
        "SECTION 5 — QUICK FIXES (30 min or less each)",
        "  List the 5 fastest security improvements with code examples",
        "",
        "SECTION 6 — HARDENING CHECKLIST",
        "  What additional security controls are missing for this type of app?",
        "",
    ]

    return "\n".join(lines)
