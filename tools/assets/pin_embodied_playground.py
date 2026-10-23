#!/usr/bin/env python3
"""Write assets/embodied-playground/provenance.json: the Embodied Playground files the embodied-playground suite uses,
pinned to one commit of github.com/Winniechen2002/Embodied-Playground with a SHA-256 per file.

None of these files is stored in git or in the package; `robouse fetch-assets --embodied-playground` downloads them into
~/.cache/robouse/embodied-playground and checks each hash.

    python tools/assets/pin_embodied_playground.py [--dest /tmp/ep]   # downloads the files to hash them

The files: every file of the MuJoCo package the Launcher tasks run on (source/agentbench/agentbench_mujoco: the Python
modules, the Panda model and its meshes, the textures and the Panda model's licence and provenance), plus the release's
licence files. Files the repository keeps in Git LFS (the meshes) are downloaded from GitHub's LFS media host; their
SHA-256 is the LFS object id, which the download is checked against.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from robouse.backends.embodied_playground.source import PACKAGE, RELEASE_FILES, REPO, REVISION  # noqa: E402

API = f"https://api.github.com/repos/{REPO}/git/trees/{REVISION}?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPO}/{REVISION}"
MEDIA = f"https://media.githubusercontent.com/media/{REPO}/{REVISION}"
LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dest", type=Path, help="folder to download into (default: a temporary folder)")
    a = ap.parse_args()
    dest = a.dest or Path(tempfile.mkdtemp(prefix="ep-pin-"))
    tree = json.loads(_get(API))
    if tree.get("truncated"):
        raise SystemExit("the GitHub tree listing is truncated; list the package folder by folder instead")
    paths = list(RELEASE_FILES) + sorted(
        t["path"] for t in tree["tree"] if t["type"] == "blob" and t["path"].startswith(PACKAGE + "/")
    )
    files = []
    for rel in paths:
        url = f"{RAW}/{rel}"
        body = _get(url)
        lfs = body.startswith(LFS_POINTER)
        if lfs:  # a pointer: the object is on the LFS media host, and its oid is the file's SHA-256
            fields = dict(line.split(" ", 1) for line in body.decode().splitlines() if " " in line)
            oid = fields["oid"].removeprefix("sha256:")
            url = f"{MEDIA}/{rel}"
            body = _get(url)
            if hashlib.sha256(body).hexdigest() != oid:
                raise SystemExit(f"{rel}: the LFS object does not match its pointer's oid")
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(body)
        files.append(
            {"path": rel, "url": url, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(), "lfs": lfs}
        )
        print(f"{len(body):>9}  {rel}")
    record = {
        "repository": f"https://github.com/{REPO}",
        "revision": REVISION,
        "package": PACKAGE,
        "licence": (
            "Original code: Apache-2.0 (LICENSE). Original documentation and independently authored non-code assets: "
            "CC BY 4.0 (LICENSES/CC-BY-4.0.txt). Third-party material keeps its own terms (LICENSING.md, "
            "THIRD_PARTY_NOTICES.md); the Panda model under assets/panda is MuJoCo Menagerie's franka_emika_panda "
            "(Apache-2.0; its LICENSE and UPSTREAM.json are in the folder). Copyright (c) 2026 Chen Feng."
        ),
        "note": (
            "The Embodied Playground files the embodied-playground suite uses. Not stored in git or in the package; "
            "`robouse fetch-assets --embodied-playground` downloads them into ~/.cache/robouse/embodied-playground. "
            "Written by tools/assets/pin_embodied_playground.py."
        ),
        "files": files,
    }
    out = REPO_ROOT / "assets" / "embodied-playground" / "provenance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1) + "\n")
    print(f"{len(files)} files, {sum(f['bytes'] for f in files) / 1e6:.2f} MB; wrote {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
