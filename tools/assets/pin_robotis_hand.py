#!/usr/bin/env python3
"""Write assets/robotis/hx5_d20.json: ROBOTIS's HX5-D20 hand (right, rev2) for the dexhand suite, pinned to one commit
of github.com/ROBOTIS-GIT/robotis_hand (Apache-2.0) with a SHA-256 per file.

The files are not stored in git (about 8 MB of meshes); `robouse fetch-assets --all` (or `--robot robotis_hx5_d20`)
downloads them into ~/.cache/robouse/menagerie/robotis_hx5_d20, keeping the repository's layout so that the MuJoCo
model's relative mesh folder resolves.

    python tools/assets/pin_robotis_hand.py

The files: the repository's LICENSE and README.md, the MuJoCo model robotis_hand_description/mujoco/hx5_d20_rev2/
hx5_d20_right.xml, and the meshes it loads (robotis_hand_description/meshes/hx5_d20_rev2/hx5_d20_right/).
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

REPO = "ROBOTIS-GIT/robotis_hand"
COMMIT = "6f9e22a5fc86fe2f0947a44405e52e776c8c08c8"  # main on 2026-09-28
FOLDER = "robotis_hx5_d20"
MODEL = "robotis_hand_description/mujoco/hx5_d20_rev2/hx5_d20_right.xml"
MESHES = "robotis_hand_description/meshes/hx5_d20_rev2/hx5_d20_right/"
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}"


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main() -> None:
    tree = json.loads(_get(f"https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1"))
    meshes = sorted(t["path"] for t in tree["tree"] if t["type"] == "blob" and t["path"].startswith(MESHES))
    files = []
    for rel in ["LICENSE", "README.md", MODEL, *meshes]:
        body = _get(f"{RAW}/{rel}")
        files.append(
            {
                "path": f"{FOLDER}/{rel}",
                "url": f"{RAW}/{rel}",
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            }
        )
        print(f"{len(body):>9}  {rel}")
    record = {
        "repository": f"https://github.com/{REPO}",
        "commit": COMMIT,
        "note": (
            "ROBOTIS's HX5-D20 hand (right, rev2) for the dexhand suite. Not stored in git; `robouse fetch-assets --all` "
            "downloads it into ~/.cache/robouse/menagerie/robotis_hx5_d20. Written by tools/assets/pin_robotis_hand.py."
        ),
        "robots": {FOLDER: {"suite": "dexhand", "license": "Apache-2.0", "license_file": f"{FOLDER}/LICENSE"}},
        "files": files,
    }
    out = Path(__file__).resolve().parents[2] / "assets" / "robotis" / "hx5_d20.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=1) + "\n")
    print(f"{len(files)} files, {sum(f['bytes'] for f in files) / 1e6:.1f} MB -> {out}")


if __name__ == "__main__":
    main()
