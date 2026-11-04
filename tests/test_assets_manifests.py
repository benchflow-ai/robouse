"""The robot-mesh manifests and their packaged names agree, without BenchFlow installed.

The BenchFlow task format (engine/format.py) copies every manifest into the simulator image under its packaged name.
When the ROBOTIS hand added a fourth manifest, the format still named three, and every BenchFlow run stopped with
"zip() argument 2 is longer than argument 1" before a container started; its tests skip without BenchFlow, so nothing
caught it. These checks run everywhere.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from robouse import assets

ROOT = Path(__file__).resolve().parents[1]


def test_every_manifest_has_one_packaged_name() -> None:
    found = assets.manifests()
    assert len(found) == len(assets.PACKAGED_MANIFESTS)
    assert len(set(assets.PACKAGED_MANIFESTS)) == len(assets.PACKAGED_MANIFESTS)


def test_the_wheel_ships_each_manifest_under_its_packaged_name() -> None:
    """pyproject's force-include maps each checkout manifest to assets_provenance/<packaged name>, in order."""
    build = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["hatch"]["build"]
    includes = {**build.get("force-include", {}), **build.get("targets", {}).get("wheel", {}).get("force-include", {})}
    shipped = {Path(src).resolve(): Path(dst).name for src, dst in ((ROOT / s, d) for s, d in includes.items())}
    for checkout_path, name in zip(assets.manifests(), assets.PACKAGED_MANIFESTS, strict=True):
        assert checkout_path.is_file(), checkout_path
        assert shipped.get(checkout_path.resolve()) == name, (checkout_path, name)
