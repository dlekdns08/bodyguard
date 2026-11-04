"""Classify shell commands as risky. Small, explicit, easy to extend."""

from __future__ import annotations

import re

# (label, compiled regex). Order matters only for the label that is reported.
RISKY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("recursive delete", re.compile(r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*[rR])\b")),
    ("recursive delete", re.compile(r"\brm\s+-r\b")),
    ("force push", re.compile(r"\bgit\s+push\b.*(\s--force\b|\s-f\b|\s--force-with-lease\b)")),
    ("history rewrite", re.compile(r"\bgit\s+reset\s+--hard\b")),
    ("history rewrite", re.compile(r"\bgit\s+(rebase|filter-branch|filter-repo)\b")),
    ("discard changes", re.compile(r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)")),
    ("discard changes", re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f")),
    ("destructive git", re.compile(r"\bgit\s+branch\s+-D\b")),
    ("drop database", re.compile(r"\bdrop\s+(table|database|schema|index)\b", re.IGNORECASE)),
    ("truncate table", re.compile(r"\btruncate\s+(table\s+)?\w", re.IGNORECASE)),
    ("delete rows", re.compile(r"\bdelete\s+from\b", re.IGNORECASE)),
    ("deploy", re.compile(r"\b(kubectl|oc)\s+(apply|delete|rollout|scale)\b")),
    ("deploy", re.compile(r"\bterraform\s+(apply|destroy)\b")),
    ("deploy", re.compile(r"\b(pulumi\s+(up|destroy)|cdk\s+deploy|sam\s+deploy|serverless\s+deploy|sls\s+deploy)\b")),
    ("deploy", re.compile(r"\b(fly|flyctl|vercel|netlify|railway|heroku)\s+deploy\b")),
    ("deploy", re.compile(r"\b(helm\s+(install|upgrade|uninstall)|docker\s+(push|system\s+prune))\b")),
    ("deploy", re.compile(r"(^|[\s;&|]|\./)deploy(\.sh|\.py)?(\s|$)")),
    ("publish", re.compile(r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b|\buv\s+publish\b|\bcargo\s+publish\b")),
    ("pipe to shell", re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b")),
    ("privilege escalation", re.compile(r"(^|\s|&&|;|\|)\s*sudo\s")),
    ("disk/partition", re.compile(r"\b(mkfs|dd\s+if=|fdisk|diskutil\s+erase)\b")),
    ("permission bomb", re.compile(r"\bchmod\s+(-R\s+)?777\b")),
    ("mass kill", re.compile(r"\bkill(all)?\s+-9\b|\bpkill\b")),
    ("package removal", re.compile(r"\b(apt(-get)?|brew|yum|dnf|pip|uv\s+pip)\s+(remove|uninstall|purge)\b")),
    ("secrets/env", re.compile(r"\brm\b.*\.env\b")),
]


def classify_command(command: str | None) -> str | None:
    """Return a short label when the command looks risky, else ``None``."""
    if not command:
        return None
    text = " ".join(command.split())
    for label, pattern in RISKY_PATTERNS:
        if pattern.search(text):
            return label
    return None
