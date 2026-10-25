#!/usr/bin/env python3
"""Rebuild the RoboSimStudio download manifest from a clean checkout at the pinned revision.

    python tools/assets/pin_robosimstudio.py --checkout /path/to/robosimstudio

Hashes the six library packages, robot assets, release files and the two scored examples. No upstream file is copied
into Robo Use. Keep the upstream checkout outside the repository; the generated manifest contains public URLs only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from robouse.backends.robosimstudio.source import CASES, PACKAGES, RELEASE_FILES, REPO, REVISION  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    checkout = parser.parse_args().checkout.resolve()

    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(checkout), *args], text=True).strip()

    if git("rev-parse", "HEAD") != REVISION or git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"need a clean RoboSimStudio checkout at {REVISION}")
    examples = {f"examples/06_tasks/{name}" for name in CASES.values()}
    prefixes = tuple(p + "/" for p in (*PACKAGES, "assets"))
    paths = [p for p in git("ls-files").splitlines() if p.startswith(prefixes) or p in RELEASE_FILES or p in examples]
    files = []
    for rel in sorted(paths):
        body = (checkout / rel).read_bytes()
        if body.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise SystemExit(f"{rel} is a Git LFS pointer; resolve it before pinning")
        files.append(
            {
                "path": rel,
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
                "url": f"https://raw.githubusercontent.com/{REPO}/{REVISION}/{rel}",
            }
        )
    record = {
        "repo": REPO,
        "revision": REVISION,
        "license": "Apache-2.0 AND MIT AND BSD-2-Clause AND BSD-3-Clause",
        "note": "Code and models are downloaded at run time, with their original licence files; no third-party source "
        "or models are bundled. See the downloaded NOTICE for each asset and source.",
        "files": files,
    }
    dest = ROOT / "assets" / "robosimstudio" / "provenance.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2) + "\n")
    print(f"{len(files)} files, {sum(f['bytes'] for f in files) / 1e6:.2f} MB -> {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
