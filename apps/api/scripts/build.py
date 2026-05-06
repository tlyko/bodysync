"""Build deterministic Lambda zips: apps/api/dist/{handler}.zip.

Per ADR-002 lambda packaging:
- pip install -r handlers/{fn}/requirements.txt --target dist/_build/{fn}/
  --platform manylinux2014_aarch64 --only-binary=:all:   (ARM64 wheels)
- copy handlers/{fn}/*.py + shared/ → dist/_build/{fn}/
- zip → dist/{fn}.zip with sorted filenames + fixed mtime so
  source_code_hash doesn't churn between runs of the same source.

Usage:
    python scripts/build.py             # all handlers in handlers/
    python scripts/build.py google_auth # specific
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HANDLERS_DIR = ROOT / "handlers"
SHARED_DIR = ROOT / "shared"
DIST_DIR = ROOT / "dist"
BUILD_DIR = DIST_DIR / "_build"

# Fixed timestamp baked into every zip entry — keeps source_code_hash stable
# across repeated builds when source content is unchanged. 2020-01-01 UTC.
FIXED_MTIME = (2020, 1, 1, 0, 0, 0)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def _install_deps(handler_dir: Path, target: Path) -> None:
    requirements = handler_dir / "requirements.txt"
    if not requirements.exists():
        return
    target.mkdir(parents=True, exist_ok=True)
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements),
            "--target",
            str(target),
            "--platform",
            "manylinux2014_aarch64",
            "--only-binary=:all:",
            "--upgrade",
            "--quiet",
        ]
    )


def _copy_sources(handler_dir: Path, target: Path) -> None:
    # handler files (not __pycache__, not requirements.txt)
    for src in handler_dir.glob("*.py"):
        shutil.copy2(src, target / src.name)
    # shared/ as a sibling import target
    shared_target = target / "shared"
    if shared_target.exists():
        shutil.rmtree(shared_target)
    shutil.copytree(
        SHARED_DIR,
        shared_target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def _walk_files(root: Path) -> list[Path]:
    files = [
        p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    ]
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def _zip_deterministic(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in _walk_files(source):
            rel = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(filename=rel, date_time=FIXED_MTIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            # 0o644 file perms — preserve executable bit only for handler? not needed
            info.external_attr = (0o644 & 0xFFFF) << 16
            with path.open("rb") as f:
                zf.writestr(info, f.read())


def build(handler_name: str) -> Path:
    handler_dir = HANDLERS_DIR / handler_name
    if not handler_dir.is_dir():
        raise SystemExit(f"handler not found: {handler_dir}")

    work = BUILD_DIR / handler_name
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    _install_deps(handler_dir, work)
    _copy_sources(handler_dir, work)

    output = DIST_DIR / f"{handler_name}.zip"
    _zip_deterministic(work, output)
    print(f"built {output} ({output.stat().st_size:,} bytes)")
    return output


def discover_handlers() -> list[str]:
    return sorted(
        p.name
        for p in HANDLERS_DIR.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "handler.py").exists()
    )


def main() -> None:
    if len(sys.argv) > 1:
        handlers = sys.argv[1:]
    else:
        handlers = discover_handlers()
    if not handlers:
        print("no handlers to build")
        return
    for name in handlers:
        build(name)


if __name__ == "__main__":
    main()
