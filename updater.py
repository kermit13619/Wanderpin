"""Self-update from GitHub Releases.

A release must have two assets:
  Wanderpin-Setup.zip         - the same zip the installer ships
  Wanderpin-Setup.zip.sha256  - its SHA-256 (made by make_release.ps1)

The tag is the version, e.g. v1.2.0. The repo must be public.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

ZIP_NAME = "Wanderpin-Setup.zip"
UA = {"User-Agent": "Wanderpin-updater", "Accept": "application/vnd.github+json"}
ALLOWED_DOWNLOAD_HOSTS = ("https://github.com/", "https://objects.githubusercontent.com/",
                          "https://release-assets.githubusercontent.com/")


def parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _get(url: str, timeout: float = 15) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def check(repo: str, current: str) -> Optional[dict]:
    """Return info about a newer release, or None if up to date / not configured."""
    if not repo or "YOUR-GITHUB-NAME" in repo:
        return None
    rel = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest"))
    tag = rel.get("tag_name") or ""
    if parse_version(tag) <= parse_version(current):
        return None
    assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
    if ZIP_NAME not in assets or ZIP_NAME + ".sha256" not in assets:
        return None
    return {
        "version": tag.lstrip("vV"),
        "notes": (rel.get("body") or "").strip()[:2000],
        "zip_url": assets[ZIP_NAME],
        "sha_url": assets[ZIP_NAME + ".sha256"],
    }


def install(info: dict, app_dir: Path, python_exe: str) -> None:
    """Download, verify and unpack a release over app_dir. Raises on any problem,
    leaving the current install untouched."""
    for u in (info["zip_url"], info["sha_url"]):
        if not u.startswith(ALLOWED_DOWNLOAD_HOSTS):
            raise RuntimeError("Refusing to download from an unexpected address.")

    expected = _get(info["sha_url"]).decode("ascii", "ignore").split()[0].strip().lower()
    data = _get(info["zip_url"], timeout=120)
    actual = hashlib.sha256(data).hexdigest()
    if len(expected) != 64 or actual != expected:
        raise RuntimeError("The download didn't match its checksum, so it wasn't installed.")

    with tempfile.TemporaryDirectory(prefix="wanderpin-update-") as tmp:
        tmp = Path(tmp)
        zpath = tmp / ZIP_NAME
        zpath.write_bytes(data)
        out = tmp / "x"
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():  # block ../ tricks
                target = (out / name).resolve()
                if not str(target).startswith(str(out.resolve())):
                    raise RuntimeError("Update contains an unsafe path.")
            z.extractall(out)

        found = list(out.rglob("app.py"))
        if len(found) != 1 or not (found[0].parent / "static" / "index.html").is_file():
            raise RuntimeError("Update package is missing app files.")
        src = found[0].parent

        # Stage the new files next to the live ones, then swap them in.
        stage = app_dir.parent / "app.new"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        for f in src.glob("*.py"):
            shutil.copy2(f, stage / f.name)
        shutil.copytree(src / "static", stage / "static")
        for extra in ("README.md", "uninstall.bat"):
            if (src / extra).is_file():
                shutil.copy2(src / extra, app_dir.parent / extra)

        req = src / "requirements.txt"
        if req.is_file():
            subprocess.run([python_exe, "-m", "pip", "install", "-q", "-r", str(req)], check=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    backup = app_dir.parent / "app.old"
    shutil.rmtree(backup, ignore_errors=True)
    os.replace(app_dir, backup)
    try:
        os.replace(stage, app_dir)
    except OSError:
        os.replace(backup, app_dir)  # put the old version back
        raise


def restart(app_dir: Path, python_exe: str) -> None:
    """Start the new version in a fresh window; the caller then exits."""
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen([python_exe, str(app_dir / "app.py"), "--after-update"],
                     cwd=str(app_dir.parent), creationflags=flags, close_fds=True)
    sys.stdout.flush()
