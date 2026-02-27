from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".cff",
    ".ini",
    ".cfg",
    ".sh",
    ".do",
    ".ipynb",
}

ABSOLUTE_PATH_PATTERNS = [
    re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    re.compile(r"Box Sync"),
]

SECRET_PATTERNS = [
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
]


def git_tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    )
    return [root / line for line in result.stdout.splitlines() if line.strip()]


def scan_text(content: str, path: Path) -> list[str]:
    findings: list[str] = []
    for pattern in ABSOLUTE_PATH_PATTERNS:
        if pattern.search(content):
            findings.append(f"{path}: absolute-local-path pattern `{pattern.pattern}`")
    for pattern in SECRET_PATTERNS:
        if pattern.search(content):
            findings.append(f"{path}: secret-like pattern `{pattern.pattern}`")
    return findings


def scan_ipynb(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"{path}: failed to parse notebook JSON ({exc})"]

    for i, cell in enumerate(nb.get("cells", []), start=1):
        source = "".join(cell.get("source", []))
        for finding in scan_text(source, path):
            findings.append(f"{finding} (cell {i} source)")

        outputs = cell.get("outputs", [])
        if outputs:
            findings.append(f"{path}: notebook has retained outputs in cell {i}")

        for output in outputs:
            if "text" in output:
                text = (
                    "".join(output["text"])
                    if isinstance(output["text"], list)
                    else str(output["text"])
                )
                for finding in scan_text(text, path):
                    findings.append(f"{finding} (cell {i} output)")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit repository for path/secret/policy issues")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    root = args.root.resolve()
    findings: list[str] = []

    for path in git_tracked_files(root):
        if not path.exists() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue

        if path.suffix.lower() == ".ipynb":
            findings.extend(scan_ipynb(path))
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(content, path))

    if findings:
        print("Repository audit failed with findings:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print("Repository audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
