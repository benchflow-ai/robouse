"""Pinned RoboSimStudio source and robot models, downloaded separately from the Robo Use package."""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from ... import config
from ...lib.download import fetch as fetch_file
from ...lib.download import sha256_file

REPO = "robosimstudio/robosimstudio"
REVISION = "eb3d46a839bf8d9b8df6e9c3f0205e141f5b3f7f"
HERE = Path(__file__).resolve()
CASES = {"open-bag": "06_bag_scored.py", "hook-band": "07_band_scored.py"}
PACKAGES = (
    "robosimstudio",
    "robosimstudio_bench",
    "robosimstudio_materials",
    "robosimstudio_policy_agent",
    "robosimstudio_real2sim_agent",
    "robosimstudio_studio",
)
RELEASE_FILES = (".python-version", "pyproject.toml", "uv.lock", "README.md", "LICENSE", "NOTICE", "CITATION.cff")
LICENCE_NOTE = (
    "RoboSimStudio's code is Apache-2.0; its robot models and other third-party material retain their "
    "MIT, BSD and Apache licences (the downloaded NOTICE and licence files). Robo Use bundles none of them."
)


def manifest_path() -> Path:
    shipped = HERE.parents[2] / "assets_provenance" / "robosimstudio.json"
    return shipped if shipped.is_file() else HERE.parents[4] / "assets" / "robosimstudio" / "provenance.json"


def manifest() -> dict:
    return json.loads(manifest_path().read_text())


def download_bytes() -> int:
    return sum(f["bytes"] for f in manifest()["files"])


def root() -> Path:
    return config.path("ROBOUSE_ROBOSIMSTUDIO_SOURCE", config.cache_dir() / "robosimstudio")


def missing() -> list[str]:
    base = root()
    return [f["path"] for f in manifest()["files"] if not (base / f["path"]).is_file()]


def require() -> Path:
    """Require every pinned file and verify the Python sources the trusted worker will import."""
    gone = missing()
    if gone:
        raise FileNotFoundError(
            f"RoboSimStudio files not found in {root()} (e.g. {gone[0]}); run "
            "`robouse fetch-assets --robosimstudio` and follow the suite's Python setup"
        )
    base = root()
    for f in manifest()["files"]:
        if f["path"].endswith(".py") and sha256_file(base / f["path"]) != f["sha256"]:
            raise RuntimeError(
                f"{base / f['path']} differs from its pinned SHA-256; run `robouse fetch-assets --robosimstudio`"
            )
    return base


def _inside(dest: Path, rel: str) -> Path:
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"RoboSimStudio manifest path escapes the download folder: {rel!r}")
    return dest / path


def fetch(dest: Path | None = None, log: Callable[[str], object] = print) -> Path:
    """Fetch missing or changed files, eight at a time, checking every SHA-256."""
    dest = Path(dest) if dest else root()
    files = [(f, _inside(dest, f["path"])) for f in manifest()["files"]]
    log(LICENCE_NOTE)
    with ThreadPoolExecutor(max_workers=8) as pool:
        changed = list(
            pool.map(lambda item: fetch_file(item[0]["url"], item[1], item[0]["sha256"], timeout=120), files)
        )
    log(f"{sum(changed)} file(s) downloaded; RoboSimStudio {REVISION[:12]} in {dest}")
    return dest
