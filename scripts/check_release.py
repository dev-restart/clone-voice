"""Check Git publication candidates without displaying sensitive file contents."""

import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


MAX_FILE_BYTES = 10 * 1024 * 1024
PRIVATE_NAMES = {"ai_text_settings.json", "ai_text_connections.json", "cookies.txt"}
PRIVATE_DIRECTORIES = {"storage", "vendor", "pretrained_models", "models", ".venv", "node_modules", ".svelte-kit", "test-results", "playwright-report", "storybook-static"}
PRIVATE_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".ckpt", ".pt", ".pth", ".safetensors", ".onnx", ".bin", ".gguf", ".npz", ".wav", ".mp3", ".m4a", ".mp4", ".webm", ".flac"}
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "AI API token": re.compile(rb"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{30,}|nvapi-[A-Za-z0-9_-]{30,})\b"),
}


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *arguments])


# Short product demos are published on purpose; any other media file stays private.
PUBLIC_MEDIA_DIRECTORY = PurePosixPath("docs/media")
PUBLIC_MEDIA_SUFFIXES = {".mp4", ".webm", ".gif"}


def private_path(name: str) -> bool:
    path = PurePosixPath(name)
    if PUBLIC_MEDIA_DIRECTORY in path.parents and path.suffix.lower() in PUBLIC_MEDIA_SUFFIXES:
        return False
    return (
        bool(set(path.parts) & PRIVATE_DIRECTORIES)
        or (path.name.startswith(".env") and path.name != ".env.example")
        or path.name in PRIVATE_NAMES
        or ("cookie" in path.name.lower() and path.suffix == ".txt")
        or path.suffix.lower() in PRIVATE_SUFFIXES
        or any(path.name.endswith(suffix + tail) for suffix in (".db", ".sqlite", ".sqlite3") for tail in ("-wal", "-shm", "-journal"))
    )


def scan(root: Path, *, staged: bool = False) -> tuple[int, list[str]]:
    entries = {}
    if staged:
        # Inspect the actual index, even when the working copy was cleaned later.
        for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
            if not entry:
                continue
            metadata, encoded_name = entry.split(b"\t", 1)
            mode, object_id, stage = metadata.decode().split()
            name = encoded_name.decode()
            entries[name] = (mode, object_id, stage)
    else:
        paths = git(root, "ls-files", "-z") + git(root, "ls-files", "--others", "--exclude-standard", "-z")
        entries = {name.decode(): None for name in paths.split(b"\0") if name}

    findings = []
    scanned = 0
    for name, entry in sorted(entries.items()):
        path = root / name
        if not staged and not path.exists() and not path.is_symlink():
            continue  # A deleted tracked file is not part of this working-tree snapshot.
        scanned += 1
        if private_path(name):
            findings.append(f"{name}: runtime/media/credential file")
            continue
        if staged:
            mode, object_id, stage = entry
            if stage != "0" or mode not in {"100644", "100755"}:
                findings.append(f"{name}: unresolved merge, symlink or submodule")
                continue
            size = int(git(root, "cat-file", "-s", object_id))
        else:
            if path.is_symlink() or not path.is_file():
                findings.append(f"{name}: symlink or unsupported file")
                continue
            size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            findings.append(f"{name}: file exceeds 10 MiB")
            continue
        data = git(root, "cat-file", "blob", entry[1]) if staged else path.read_bytes()
        for label, pattern in SECRET_PATTERNS.items():
            match = pattern.search(data)
            if match:
                line = data[:match.start()].count(b"\n") + 1
                findings.append(f"{name}:{line}: {label}")
    return scanned, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Inspect all files in the Git index instead of the working tree.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        count, findings = scan(root, staged=args.staged)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Release check failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    if findings:
        print("Release check blocked publication candidates:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"Release check passed: {count} {'index' if args.staged else 'working-tree'} files. Pattern scan; not a complete secret audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
