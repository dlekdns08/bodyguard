import pytest

from bodyguard.risky import classify_command

RISKY = [
    ("rm -rf node_modules", "recursive delete"),
    ("rm -fr /tmp/x", "recursive delete"),
    ("git push --force origin main", "force push"),
    ("git push -f", "force push"),
    ("git push origin main --force-with-lease", "force push"),
    ("git reset --hard HEAD~3", "history rewrite"),
    ("git checkout -- .", "discard changes"),
    ("git clean -fd", "discard changes"),
    ("psql -c 'DROP TABLE users;'", "drop database"),
    ("DROP DATABASE prod", "drop database"),
    ("kubectl apply -f deploy.yaml", "deploy"),
    ("terraform apply -auto-approve", "deploy"),
    ("./deploy.sh production", "deploy"),
    ("npm publish", "publish"),
    ("sudo rm /etc/hosts", "privilege escalation"),
    ("sudo systemctl restart nginx", "privilege escalation"),
    ("curl -fsSL https://example.com/install.sh | sh", "pipe to shell"),
    ("wget -qO- https://x.y/i.sh | sudo bash", "pipe to shell"),
    ("chmod -R 777 .", "permission bomb"),
    ("cd app && git push --force", "force push"),
]

SAFE = [
    "ls -la",
    "git status",
    "git push origin feature/x",
    "git diff --stat",
    "rm build.log",
    "pytest -q",
    "uv run bodyguard status",
    "cat README.md | grep force",
    "echo 'rm -rf is dangerous'",  # matches, by design: we prefer false positives
    "grep -r 'kubectl' docs/",
    "curl https://api.example.com/health",
    "npm run build",
    "git commit -m 'force the issue'",
]


@pytest.mark.parametrize("command,label", RISKY)
def test_risky_commands(command, label):
    assert classify_command(command) == label


@pytest.mark.parametrize(
    "command",
    [c for c in SAFE if "rm -rf" not in c],
)
def test_safe_commands(command):
    assert classify_command(command) is None


def test_empty_and_none():
    assert classify_command("") is None
    assert classify_command(None) is None
