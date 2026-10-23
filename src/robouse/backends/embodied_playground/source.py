"""Embodied Playground's own simulation code, downloaded at run time: never stored in the repository or the package.

Embodied Playground (github.com/Winniechen2002/Embodied-Playground) licenses its original code under Apache-2.0 and its
original documentation and independently authored non-code assets under CC BY 4.0; third-party material keeps its own
terms (its LICENSING.md). Its Launcher tasks run on its own MuJoCo package, `agentbench_mujoco`: the scene builders, the
passive spring launcher, the damage and fracture models, the success rule, a Franka Panda model from MuJoCo Menagerie
(Apache-2.0) and a few textures. Robo Use includes none of it. `robouse fetch-assets --embodied-playground` downloads
that package and the release's licence files, listed with their SHA-256 in assets/embodied-playground/provenance.json
(packaged as robouse/assets_provenance/embodied-playground.json), from one pinned commit, into
<cache>/embodied-playground. $ROBOUSE_EMBODIED_PLAYGROUND_SOURCE overrides the location. The folder keeps the
repository's layout; the worker imports the package from it after checking every module's hash.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from ... import config
from ...lib.download import fetch as fetch_file
from ...lib.download import sha256_file

HERE = Path(__file__).resolve()
REPO = "Winniechen2002/Embodied-Playground"
REVISION = "45993d432ae58a9f3dd05dc2ff3c6e16eb39198f"  # main on 2026-10-19
PACKAGE = "source/agentbench/agentbench_mujoco"  # the package the Launcher tasks run on
RELEASE_FILES = ("LICENSE", "NOTICE", "LICENSING.md", "THIRD_PARTY_NOTICES.md", "LICENSES/CC-BY-4.0.txt")
LICENCE_NOTE = (
    "Embodied Playground's original code is Apache-2.0 and its original non-code assets CC BY 4.0; third-party "
    "material keeps its own terms (LICENSING.md, THIRD_PARTY_NOTICES.md; the Panda model is MuJoCo Menagerie's, "
    "Apache-2.0). Robo Use does not include it: it is downloaded for you to use under those terms."
)


def manifest_path() -> Path:
    """The pinned file list: the packaged copy in an installed wheel, else the checkout's."""
    shipped = HERE.parents[2] / "assets_provenance" / "embodied-playground.json"
    if shipped.is_file():
        return shipped
    return HERE.parents[4] / "assets" / "embodied-playground" / "provenance.json"


def manifest() -> dict:
    return json.loads(manifest_path().read_text())


def root() -> Path:
    """Where the downloaded files are: $ROBOUSE_EMBODIED_PLAYGROUND_SOURCE, else <cache>/embodied-playground."""
    override = config.env("ROBOUSE_EMBODIED_PLAYGROUND_SOURCE")
    return Path(override) if override else config.cache_dir() / "embodied-playground"


def package_parent() -> Path:
    """The folder to put on sys.path to import `agentbench_mujoco`."""
    return root() / PurePosixPath(PACKAGE).parent


def download_bytes() -> int:
    return sum(int(f.get("bytes", 0)) for f in manifest()["files"])


def missing() -> list[str]:
    """Manifest files that are not in the download folder."""
    base = root()
    return [f["path"] for f in manifest()["files"] if not (base / f["path"]).is_file()]


def stale() -> list[str]:
    """Manifest files that are there but whose SHA-256 differs from the pin (a changed or partial file)."""
    base = root()
    out = []
    for f in manifest()["files"]:
        p = base / f["path"]
        if p.is_file() and sha256_file(p) != f["sha256"]:
            out.append(f["path"])
    return out


def require() -> Path:
    """The download folder, after checking that every manifest file is there and every Python module still matches
    its pinned hash (the worker imports them)."""
    gone = missing()
    if gone:
        raise FileNotFoundError(
            f"Embodied Playground files not found in {root()} (e.g. {gone[0]}); run `robouse fetch-assets "
            f"--embodied-playground` once (about {download_bytes() / 1e6:.1f} MB). {LICENCE_NOTE}"
        )
    base = root()
    for f in manifest()["files"]:
        if f["path"].endswith(".py") and sha256_file(base / f["path"]) != f["sha256"]:
            raise RuntimeError(
                f"{base / f['path']} does not match its pinned SHA-256; run `robouse fetch-assets "
                "--embodied-playground` to download it again"
            )
    return base


def _inside(dest: Path, rel: str) -> Path:
    """Where a manifest file goes: `rel` must be a relative path without `..`, so that it stays inside `dest`."""
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"the Embodied Playground manifest names a path outside the download folder: {rel!r}")
    return dest / p


def fetch(dest: Path | None = None, log: Callable[[str], object] = print) -> Path:
    """Download the manifest files that are missing or differ from their pinned hash (eight at a time). Every path is
    checked before the first download."""
    m = manifest()
    dest = Path(dest) if dest else root()
    files = [(f, _inside(dest, f["path"])) for f in m["files"]]
    log(LICENCE_NOTE)
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(lambda fp: fetch_file(fp[0]["url"], fp[1], fp[0]["sha256"], timeout=120), files))
    log(f"{sum(got)} file(s) downloaded; Embodied Playground {m['revision'][:12]} in {dest}")
    return dest
