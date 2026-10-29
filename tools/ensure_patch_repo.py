#!/usr/bin/env python3
"""Materialize ``patch_repo/`` from the upstream English toolkit plus overrides.

The Russian port builds on top of ``gourry-hacks/slayers_royal_1_patch``.
That repository is *not* vendored here: it is downloaded at an exact commit,
then the handful of files this port changes (compact-glyph limit, atlas
injection hooks, script relayout) are copied over it from
``vendor/patch_repo_overrides/``.

This works without git, curl or 7-Zip: only Python 3.10+ is required.

Usage::

    python3 tools/ensure_patch_repo.py          # download/setup if missing
    python3 tools/ensure_patch_repo.py --check  # verify, never download
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def _configure_stdio() -> None:
    """Windows consoles default to cp1251/cp866; force UTF-8 so messages survive."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


_configure_stdio()

REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
OVERRIDES = REPO_ROOT / "vendor" / "patch_repo_overrides"
MARKER = PATCH_REPO / ".slayers_royal_overrides.json"

UPSTREAM_SLUG = "gourry-hacks/slayers_royal_1_patch"
BASE_COMMIT = "3ee4621fd375bb0478258d740e0b657e1778ab75"
ARCHIVE_URLS = (
    f"https://codeload.github.com/{UPSTREAM_SLUG}/zip/{BASE_COMMIT}",
    f"https://github.com/{UPSTREAM_SLUG}/archive/{BASE_COMMIT}.zip",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _override_files() -> list[Path]:
    if not OVERRIDES.is_dir():
        raise SystemExit(f"error: missing override directory {OVERRIDES}")
    files = sorted(path for path in OVERRIDES.rglob("*") if path.is_file())
    if not files:
        raise SystemExit(f"error: {OVERRIDES} is empty")
    return files


def _expected_marker() -> dict[str, object]:
    return {
        "upstream": UPSTREAM_SLUG,
        "base_commit": BASE_COMMIT,
        "overrides": {
            str(path.relative_to(OVERRIDES)): _sha256(path)
            for path in _override_files()
        },
    }


def _repo_is_complete() -> bool:
    return (PATCH_REPO / "localization" / "cli.py").is_file()


def _marker_matches() -> bool:
    if not MARKER.is_file():
        return False
    try:
        return json.loads(MARKER.read_text(encoding="utf-8")) == _expected_marker()
    except (OSError, ValueError):
        return False


def _download(url: str, destination: Path) -> None:
    print(f"[*] Скачивание upstream-тулкита: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "slayers-royal-setup"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_percent = -1
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                percent = done * 100 // total
                if percent >= last_percent + 5:
                    print(f"    {percent:3d}%  ({done // (1 << 20)} / {total // (1 << 20)} МиБ)")
                    last_percent = percent
    print(f"[✓] Скачано {destination.stat().st_size // (1 << 20)} МиБ")


def _extract_archive(archive: Path, destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="slayers_patch_repo_") as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                target = (tmp_path / member.filename).resolve()
                if not str(target).startswith(str(tmp_path.resolve())):
                    raise SystemExit(f"error: unsafe path in archive: {member.filename}")
            bundle.extractall(tmp_path)
        roots = [path for path in tmp_path.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise SystemExit("error: unexpected archive layout")
        shutil.copytree(roots[0], destination)


def _install_overrides() -> None:
    for source in _override_files():
        target = PATCH_REPO / source.relative_to(OVERRIDES)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    MARKER.write_text(json.dumps(_expected_marker(), indent=2) + "\n", encoding="utf-8")


def _verify_import() -> None:
    """Import the patched toolkit in a subprocess to catch version drift."""
    import subprocess

    # Embedded Windows Python ignores the current directory, so add it explicitly.
    code = (
        "import os, sys; sys.path.insert(0, os.getcwd()); "
        "import localization.cli, localization.glyphs, localization.script"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PATCH_REPO,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"error: patched toolkit fails to import:\n{detail}")


def setup() -> None:
    if _repo_is_complete() and _marker_matches():
        _verify_import()
        print(f"[✓] patch_repo готов: {PATCH_REPO}")
        return

    if _repo_is_complete():
        print("[*] patch_repo найден — обновляем файлы оверрадов...")
        _install_overrides()
        _verify_import()
        print(f"[✓] Оверрады обновлены: {PATCH_REPO}")
        return

    if PATCH_REPO.exists() and any(PATCH_REPO.iterdir()):
        raise SystemExit(
            f"error: {PATCH_REPO} существует, но не содержит localization/cli.py.\n"
            "Удалите или переименуйте эту папку и запустите скрипт снова."
        )

    with tempfile.TemporaryDirectory(prefix="slayers_patch_dl_") as tmp:
        archive = Path(tmp) / "patch_repo.zip"
        errors: list[str] = []
        for url in ARCHIVE_URLS:
            try:
                _download(url, archive)
                break
            except Exception as exc:  # noqa: BLE001 - report both mirrors, then fail
                errors.append(f"{url}: {exc}")
        else:
            raise SystemExit(
                "error: не удалось скачать upstream-тулкит.\n"
                "Проверьте интернет или скачайте вручную:\n"
                f"  https://github.com/{UPSTREAM_SLUG}/archive/{BASE_COMMIT}.zip\n"
                "и распакуйте содержимое в папку patch_repo/.\n" + "\n".join(errors)
            )
        _extract_archive(archive, PATCH_REPO)

    _install_overrides()
    _verify_import()
    print(f"[✓] patch_repo развёрнут: {PATCH_REPO}")
    print(f"    upstream commit: {BASE_COMMIT}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="only verify, never download")
    args = parser.parse_args()

    if args.check:
        if not _repo_is_complete():
            print(f"[!] patch_repo отсутствует: {PATCH_REPO}", file=sys.stderr)
            return 1
        if not _marker_matches():
            print("[!] patch_repo есть, но оверрады не установлены/устарели", file=sys.stderr)
            return 1
        _verify_import()
        print(f"[✓] patch_repo готов: {PATCH_REPO}")
        return 0

    setup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
