"""Pinned downloads, isolation and public observations; optional native CPU task and control checks."""

from __future__ import annotations

import os
import re
from pathlib import Path

import numpy as np
import pytest

from robouse import config
from robouse.backends.robosimstudio import oracle, source
from robouse.backends.robosimstudio.backend import PUBLIC_FIELDS, RoboSimStudioBackend
from robouse.tasks import load_task

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "tasks" / "robosimstudio"


def test_manifest_pins_source_assets_examples_and_licences() -> None:
    manifest = source.manifest()
    assert manifest["revision"] == source.REVISION and manifest["repo"] == source.REPO
    paths = [f["path"] for f in manifest["files"]]
    assert len(paths) == len(set(paths))
    assert set(source.RELEASE_FILES) <= set(paths)
    assert {f"examples/06_tasks/{p}" for p in source.CASES.values()} <= set(paths)
    assert {f"{p}/__init__.py" for p in source.PACKAGES} <= set(paths)
    assert any(p.startswith("assets/") and p.endswith("LICENSE") for p in paths)
    for f in manifest["files"]:
        assert f["url"] == f"https://raw.githubusercontent.com/{source.REPO}/{source.REVISION}/{f['path']}"
        assert re.fullmatch("[0-9a-f]{64}", f["sha256"]) and f["bytes"] > 0
        assert source._inside(Path("download"), f["path"]).is_relative_to("download")


def test_missing_and_changed_sources_are_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ROBOUSE_ROBOSIMSTUDIO_SOURCE", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="fetch-assets --robosimstudio"):
        RoboSimStudioBackend({"env": "open-bag"})
    with pytest.raises(ValueError, match="robosimstudio tasks"):
        RoboSimStudioBackend({"env": "water"})
    f = tmp_path / "module.py"
    f.write_text("raise RuntimeError('changed')\n")
    monkeypatch.setattr(source, "manifest", lambda: {"files": [{"path": f.name, "sha256": "0" * 64}]})
    with pytest.raises(RuntimeError, match="differs from its pinned SHA-256"):
        source.require()


def test_fetch_checks_each_hash(tmp_path, monkeypatch) -> None:
    got = []
    monkeypatch.setattr(source, "fetch_file", lambda url, dest, sha, timeout: got.append((url, dest, sha)) or True)
    lines = []
    source.fetch(tmp_path, log=lines.append)
    assert sorted((u, p.relative_to(tmp_path).as_posix(), s) for u, p, s in got) == sorted(
        (f["url"], f["path"], f["sha256"]) for f in source.manifest()["files"]
    )
    assert "Apache-2.0" in lines[0] and str(len(got)) in lines[-1]


@pytest.mark.parametrize("path", ["../outside.py", "/tmp/outside.py", "a/../../outside.py"])
def test_invalid_download_paths_write_nothing(path, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(source, "manifest", lambda: {"files": [{"path": "LICENSE"}, {"path": path}]})
    got = []
    monkeypatch.setattr(source, "fetch_file", lambda *args, **kwargs: got.append(args))
    with pytest.raises(ValueError, match="escapes the download folder"):
        source.fetch(tmp_path)
    assert not got


def test_external_source_and_virtualenv_are_hidden_by_both_sandboxes(tmp_path, monkeypatch) -> None:
    from robouse.runner import sandbox

    moved = tmp_path / "rss"
    moved.mkdir()
    venv = tmp_path / "rss-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (venv / "bin" / "python").symlink_to("/usr/bin/python3")
    monkeypatch.setenv("ROBOUSE_ROBOSIMSTUDIO_SOURCE", str(moved))
    monkeypatch.setenv("ROBOUSE_ROBOSIMSTUDIO_PYTHON", str(venv / "bin" / "python"))
    profile = sandbox.sandbox_profile(tmp_path / "ws", (), [], [])
    args = sandbox.bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [], [])
    for p in (moved, venv):
        real = os.path.realpath(p)
        assert str(p) in config.sandbox_denied_paths()
        assert f'(deny file-read* file-write* (subpath "{real}"))' in profile
        assert args[args.index(real) - 1] == "--tmpfs"
    # A system interpreter is not a venv; never hide its entire prefix.
    monkeypatch.setenv("ROBOUSE_ROBOSIMSTUDIO_PYTHON", "/usr/bin/python3")
    assert "/usr" not in config.sandbox_denied_paths()


def test_tasks_keep_native_goals_first_success_and_fixed_layouts() -> None:
    tasks = [load_task(p.parent) for p in sorted(SUITE.glob("*/task.md"))]
    assert {t.spec["env"] for t in tasks} == set(source.CASES)
    for task in tasks:
        assert task.spec["backend"] == "robosimstudio" and task.spec["max_steps"] == 1200
        assert task.spec["success_mode"] == "first" and task.spec["skills"] is False
        assert task.spec["obs_mode"] == "vision" and task.spec["visible_fields"] == list(PUBLIC_FIELDS)
        text = (task.path / "task.md").read_text()
        assert "seeds do not randomize" in text and "0 open, 1 closed" in text
        assert "material" not in " ".join(PUBLIC_FIELDS)


def test_worker_uses_private_bytecode_and_kernel_caches(tmp_path, monkeypatch) -> None:
    from robouse.backends.robosimstudio import backend

    captured = {}

    class FakeWorker:
        def __init__(self, *args, **kwargs):
            captured.update(kwargs["env"])

        def call(self, cmd, **kwargs):
            return {"neutral_action": [0.0] * 16}

        def close(self):
            pass

    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(source, "require", lambda: tmp_path / "source")
    monkeypatch.setattr(backend, "StdioWorker", FakeWorker)
    b = RoboSimStudioBackend({"env": "open-bag"})
    b.close()
    assert captured["ROBOSIMSTUDIO_DEVICE"] == "cpu"
    assert captured["PYTHONPATH"] == str(tmp_path / "source")
    for key in ("PYTHONPYCACHEPREFIX", "WARP_CACHE_PATH"):
        assert Path(captured[key]).is_relative_to(config.cache_dir())


READY = config.sim_python("robosimstudio").exists() and not source.missing()
needs_sim = pytest.mark.skipif(not READY, reason="needs RoboSimStudio's CPU virtualenv and pinned source")


@needs_sim
@pytest.mark.parametrize("case", source.CASES)
def test_native_reference_scores_one_and_full_budget_hold_scores_zero(case, tmp_path, monkeypatch) -> None:
    from robouse.core.session import Episode

    spec = load_task(SUITE / f"rss-{case}").spec
    ep = Episode(spec, tmp_path / "oracle", secrets={"oracle_token": "reference"})
    try:
        public = ep.handle({"op": "observe"})["result"]["state"]
        assert set(public) == set(PUBLIC_FIELDS) and "scene" not in public
        monkeypatch.setattr(oracle, "_send", lambda req: ep.handle({**req, "token": "reference"}))
        oracle.oracle_main(case)
        assert ep.finished and ep.result["success"] and ep.result["outcome"] == "success_reached", ep.result
    finally:
        ep.close()
    ep = Episode(spec, tmp_path / "hold")
    try:
        hold = ep.backend.hold_action()
        for _ in range(24):
            response = ep.handle({"op": "act", "action": hold, "repeat": 50})
            assert response["ok"], response
        assert ep.finished and not ep.result["success"] and ep.result["steps_used"] == 1200, ep.result
    finally:
        ep.close()


@needs_sim
def test_camera_pose_action_validation_and_reset() -> None:
    b = RoboSimStudioBackend({"env": "hook-band", "max_steps": 100})
    try:
        b.reset(0)
        assert b.embodiment().validate().dim == 16
        pose = b.privileged_state()["scene"]["band_bottom"]
        camera = b.camera_info(["overview"])[0]
        u, v, depth = np.asarray(camera["projection"]) @ np.r_[pose, 1]
        image = b.render()
        assert image.shape == (320, 480, 3) and image.dtype == np.uint8
        assert 0 < u / depth < 480 and 0 < v / depth < 320 and depth > 0
        assert image.std() > 5
        action = b.hold_action()
        action[3:7] = [0, 0, 0, 0]
        with pytest.raises(RuntimeError, match="quaternion must have nonzero length"):
            b.step(action)
        assert b.observe()["step_index"] == 0
        action = b.hold_action()
        action[3:7] = (np.asarray(action[3:7]) * 0.5).tolist()
        b.step(action)
        assert np.linalg.norm(b.hold_action()[3:7]) == pytest.approx(1)
        b.reset(999)
        assert b.observe()["step_index"] == 0 and not b.success()
    finally:
        b.close()
