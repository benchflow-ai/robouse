"""Native BenchFlow packages hold no oracle token and no absolute path of the build machine.

The token that unlocks privileged state is chosen per run on the host ($ROBOUSE_ORACLE_TOKEN): the simulator gets it
through compose interpolation and the reference solution through task.md's oracle.env. A published package must give
an agent nothing to look up.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

pytest.importorskip("benchflow.embodied.sidecar", reason="needs BenchFlow's embodied layer (not released yet)")

from robouse.engine.format import TOKEN_REF, materialize

pytestmark = pytest.mark.needs_benchflow_embodied

ROOT = Path(__file__).resolve().parents[1]
HEX32 = re.compile(r"\b[0-9a-f]{32}\b")


def _frontmatter(p: Path) -> dict:
    return yaml.safe_load(p.read_text().split("---\n", 2)[1])


def _files(pkg: Path) -> list[Path]:
    return [p for p in pkg.rglob("*") if p.is_file() and "vendor" not in p.parts]


@pytest.mark.parametrize("task", ["arc-style/arc-gravity", "vision/" + "{first}"])
def test_package_has_no_token(tmp_path, task) -> None:
    if "{first}" in task:
        task = task.format(first=sorted(p.name for p in (ROOT / "tasks" / "vision").iterdir() if p.is_dir())[0])
    pkg = materialize(ROOT / "tasks" / task, tmp_path, flat=True)
    for f in _files(pkg):
        assert not HEX32.search(f.read_text(errors="ignore")), f"a 32-hex value in {f.relative_to(pkg)}"
    compose = (pkg / "environment" / "docker-compose.yaml").read_text()
    assert f'ROBO_ORACLE_TOKEN: "{TOKEN_REF}"' in compose
    assert "ORACLE_TOKEN" not in (pkg / "oracle" / "solve.sh").read_text()
    assert _frontmatter(pkg / "task.md")["oracle"] == {"env": {"ROBOUSE_ORACLE_TOKEN": TOKEN_REF}}
    source = json.loads((pkg / ".robouse-source.json").read_text())["source"]
    assert source == f"tasks/{task}"  # relative to the checkout
    # byte-identical across builds (nothing random left in the package)
    again = materialize(ROOT / "tasks" / task, tmp_path / "again", flat=True)
    assert {p.relative_to(pkg): p.read_bytes() for p in _files(pkg)} == {
        p.relative_to(again): p.read_bytes() for p in _files(again)
    }


def test_noop_control_gets_no_token(tmp_path) -> None:
    """The negative control looks as an agent would: no token in its package, and it does not read the token the
    simulator leaves for the reference solution (BenchFlow 0.10 mints one per episode into a root-only file)."""
    pkg = materialize(ROOT / "tasks" / "arc-style" / "arc-gravity", tmp_path, noop=True, flat=True)
    assert "oracle" not in _frontmatter(pkg / "task.md")
    solve = (pkg / "oracle" / "solve.sh").read_text()
    assert "ORACLE_TOKEN=" not in solve.replace("ORACLE_TOKEN_FILE=", "")
    assert "export ROBO_ORACLE_TOKEN_FILE=/dev/null" in solve


@pytest.mark.skipif(importlib.util.find_spec("metaworld") is None, reason="needs metaworld for the vendored policies")
def test_vendored_metaworld_carries_its_licence(tmp_path) -> None:
    task = sorted(p for p in (ROOT / "tasks" / "metaworld").iterdir() if p.is_dir())[0]
    pkg = materialize(task, tmp_path, flat=True)
    lic = (pkg / "oracle" / "vendor" / "metaworld" / "LICENSE").read_text()
    assert "Copyright (c) 2019 Meta-World Team" in lic and "MIT License" in lic
