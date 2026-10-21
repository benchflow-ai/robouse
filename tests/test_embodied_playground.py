"""The embodied-playground suite: the pinned download of Embodied Playground's MuJoCo package, the plan format of the
reference shots, the task folders and the agent's view. The tests at the bottom need the simulator's virtualenv and
the downloaded package (docs/suites/embodied-playground.md) and skip without them: they run reference solutions and
no-op controls in process and check the camera's projection against the image."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

from robouse import config
from robouse.backends.embodied_playground import planner, source
from robouse.backends.embodied_playground.backend import PUBLIC_FIELDS

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "tasks" / "embodied-playground"
FOLDERS = sorted(p.parent for p in SUITE.glob("*/task.md"))


def _frontmatter(task: Path) -> dict:
    return yaml.safe_load((task / "task.md").read_text().split("\n---", 1)[0].removeprefix("---"))


def test_the_pinned_files_are_the_package_and_none_is_in_the_repository() -> None:
    m = source.manifest()
    assert m["revision"] == source.REVISION and m["package"] == source.PACKAGE
    assert "Apache-2.0" in m["licence"] and "CC BY 4.0" in m["licence"]
    paths = [f["path"] for f in m["files"]]
    assert len(paths) == len(set(paths))
    for f in m["files"]:
        host = "media.githubusercontent.com/media" if f["lfs"] else "raw.githubusercontent.com"
        assert f["url"] == f"https://{host}/{source.REPO}/{source.REVISION}/{f['path']}"
        assert re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) and f["bytes"] > 0
        assert f["path"] in source.RELEASE_FILES or f["path"].startswith(source.PACKAGE + "/")
    for need in ("__init__.py", "campaign_env.py", "campaign_scene.py", "env.py", "assets/panda/panda.xml"):
        assert f"{source.PACKAGE}/{need}" in paths
    assert all(f["lfs"] for f in m["files"] if f["path"].endswith((".stl", ".obj")))
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True).stdout.split()
    if tracked:  # a checkout: nothing of the package is in git
        assert not [p for p in tracked if "agentbench" in p]


def test_without_the_files_the_backend_says_how_to_fetch_them(tmp_path, monkeypatch) -> None:
    from robouse.backends.embodied_playground import EmbodiedPlaygroundBackend

    monkeypatch.setenv("ROBOUSE_EMBODIED_PLAYGROUND_SOURCE", str(tmp_path / "none"))
    with pytest.raises(FileNotFoundError, match=r"robouse fetch-assets --embodied-playground.*Apache-2\.0"):
        EmbodiedPlaygroundBackend({"ep_scenario": "warmup", "env": "marble/dual-panda/A007"})
    with pytest.raises(ValueError, match="only the Launcher family"):
        EmbodiedPlaygroundBackend({"family": "hanoi_panda", "ep_scenario": "H01"})


def test_a_changed_module_is_refused(tmp_path, monkeypatch) -> None:
    """The worker imports the downloaded modules, so each must still have its pinned hash."""
    mod = tmp_path / source.PACKAGE / "env.py"
    mod.parent.mkdir(parents=True)
    mod.write_text("print('changed')\n")
    files = [{"path": f"{source.PACKAGE}/env.py", "url": "https://example.invalid", "sha256": "0" * 64, "bytes": 1}]
    monkeypatch.setattr(source, "manifest", lambda: {"revision": source.REVISION, "files": files})
    monkeypatch.setenv("ROBOUSE_EMBODIED_PLAYGROUND_SOURCE", str(tmp_path))
    assert source.missing() == [] and source.stale() == [files[0]["path"]]
    with pytest.raises(RuntimeError, match="does not match its pinned SHA-256"):
        source.require()


def test_fetch_downloads_every_pinned_file_with_its_hash(tmp_path, monkeypatch) -> None:
    got = []
    monkeypatch.setattr(source, "fetch_file", lambda url, dest, sha, timeout: got.append((url, dest, sha)) or True)
    lines: list[str] = []
    source.fetch(tmp_path, log=lines.append)
    m = source.manifest()
    assert sorted((u, d.relative_to(tmp_path).as_posix(), s) for u, d, s in got) == sorted(
        (f["url"], f["path"], f["sha256"]) for f in m["files"]
    )
    assert "Apache-2.0" in lines[0] and lines[-1].startswith(f"{len(m['files'])} file(s) downloaded")


@pytest.mark.parametrize("path", ["../outside.py", "source/../../outside.py", "/tmp/outside.py"])
def test_fetch_writes_nothing_outside_the_download_folder(path, tmp_path, monkeypatch) -> None:
    entry = {"url": "https://example.invalid/file", "sha256": "0" * 64, "bytes": 1}
    files = [{**entry, "path": "LICENSE"}, {**entry, "path": path}]
    monkeypatch.setattr(source, "manifest", lambda: {"revision": source.REVISION, "files": files})
    got = []
    monkeypatch.setattr(source, "fetch_file", lambda url, dest, sha, timeout: got.append(dest) or True)
    with pytest.raises(ValueError, match="outside the download folder"):
        source.fetch(tmp_path / "ep", log=lambda line: None)
    assert got == []


def test_a_plan_ramps_joint_targets_and_switches_grippers_at_once() -> None:
    start = [0.0] * 7 + [1.0] + [0.5] * 7 + [1.0]
    to = [0.4] * 7 + [-1.0] + [0.5] * 7 + [1.0]
    out = planner.expand([[to, 4, 1], [to, 2, 0]], start)
    assert len(out) == 6
    assert [round(a[0], 3) for a in out] == [0.1, 0.2, 0.3, 0.4, 0.4, 0.4]
    assert all(a[7] == -1.0 and a[15] == 1.0 and a[8:15] == [0.5] * 7 for a in out)
    assert planner.ramp_steps([0.0] * 7, [0.6] + [0.0] * 6) == 50  # 0.6 rad at 0.6 rad/s, 20 ms steps


def test_the_task_folders_are_complete() -> None:
    """Each Embodied Playground task in all four conditions, at Level 0, with a reference shot for its condition."""
    assert FOLDERS, "no task folders"
    by_task: dict[str, set[int]] = {}
    for d in FOLDERS:
        fm = _frontmatter(d)
        rb = fm["robouse"]
        assert rb["id"] == d.name and rb["backend"] == "embodied_playground" and rb["family"] == "marble"
        case = rb["env"].removeprefix("marble/dual-panda/")
        assert d.name == f"ep-launch-{case.lower()}-c{rb['condition']}"
        assert rb["obs_mode"] == "vision" and rb["visible_fields"] == list(PUBLIC_FIELDS)
        assert rb["skills"] is False and rb["success_mode"] == "first" and rb["initial_mode"] == "loaded"
        assert rb["max_steps"] == 7500 and fm["agent"]["timeout_sec"] == 600
        assert set(rb["environment_parameters"]) == {
            "spring_stiffness",
            "launcher_offset_m",
            "ammunition_offset_m",
            "background",
            "background_motion",
        }
        assert rb["environment_parameters"]["spring_stiffness"] == 20.0 + 2 * rb["condition"]
        body = (d / "task.md").read_text().split("\n---", 1)[1]
        assert rb["goal"] in body and f"{rb['environment_parameters']['spring_stiffness']:g} N/m" in body
        plans = json.loads((d / "oracle" / "plan.json").read_text())
        assert plans["task"] == rb["env"] and plans["embodied_playground"].endswith(source.REVISION)
        mine = plans["conditions"][str(rb["condition"])]
        assert 0.04 <= mine["draw_m"] <= 0.11 and mine["plan"]
        assert all(len(a) == 16 and n >= 1 and ramp in (0, 1) for a, n, ramp in mine["plan"])
        by_task.setdefault(rb["env"], set()).add(rb["condition"])
    assert all(c == {1, 2, 3, 4} for c in by_task.values()), by_task


def test_the_agent_view_has_no_scene_state() -> None:
    """Level 0: the robots' own state and the clock; the launcher, projectiles and targets only in the images."""
    words = ("target", "ammo", "marble", "launcher", "draw", "handle", "block", "pos_of", "phase")
    assert not [f for f in PUBLIC_FIELDS if any(w in f for w in words)]


def test_a_moved_download_folder_is_denied_to_agents(tmp_path, monkeypatch) -> None:
    """The worker imports the downloaded package outside the sandbox; moved out of robouse's cache by
    ROBOUSE_EMBODIED_PLAYGROUND_SOURCE, it is denied to agents as the cache is."""
    from robouse.runner import sandbox

    moved = tmp_path / "ep-package"
    moved.mkdir()
    monkeypatch.setenv("ROBOUSE_EMBODIED_PLAYGROUND_SOURCE", str(moved))
    real = os.path.realpath(moved)
    assert str(moved) in config.sandbox_denied_paths() and real in sandbox._denied([])
    assert f'(deny file-read* file-write* (subpath "{real}"))' in sandbox.sandbox_profile(tmp_path / "ws", (), [], [])
    args = sandbox.bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [], [])
    assert args[args.index(real) - 1] == "--tmpfs"


# ---- with the simulator's virtualenv and the downloaded package ----------------------------------------------------

READY = config.sim_python("embodied_playground", "embodied-playground").exists() and not source.missing()
needs_sim = pytest.mark.skipif(
    not READY, reason="needs the embodied-playground virtualenv and `robouse fetch-assets --embodied-playground`"
)


@needs_sim
@pytest.mark.parametrize("task", [d.name for d in FOLDERS])
def test_reference_solution_scores_1_and_noop_0(task, tmp_path, monkeypatch) -> None:
    from robouse import agent_cli
    from robouse.backends.embodied_playground import oracle_main
    from robouse.core.gl import auto_select
    from robouse.core.session import Episode
    from robouse.tasks import load_task

    auto_select()
    spec = load_task(SUITE / task).spec
    ep = Episode(spec, tmp_path / "oracle")
    monkeypatch.setattr(agent_cli, "_send", lambda req, path=None: ep.handle(req))
    oracle_main(str(SUITE / task / "oracle" / "plan.json"))
    assert ep.finished and ep.result["success"] and ep.result["outcome"] == "success_reached", ep.result
    ep.close()
    ep = Episode(spec, tmp_path / "noop")
    ep.handle({"op": "done", "text": "noop control"})
    assert ep.finished and not ep.result["success"]
    ep.close()


@needs_sim
def test_the_camera_matrix_puts_the_target_on_its_pixels() -> None:
    import numpy as np

    from robouse.backends.embodied_playground import EmbodiedPlaygroundBackend
    from robouse.core.gl import auto_select

    auto_select()
    fm = _frontmatter(SUITE / "ep-launch-a007-c1")
    b = EmbodiedPlaygroundBackend(fm["robouse"])
    try:
        b.reset(0)
        assert set(b.observe()) == set(PUBLIC_FIELDS)
        target = b.privileged_state()["scene"]["targets"][0]["pos"]
        cam = b.camera_info(["front_left"])[0]
        u, v, w = np.asarray(cam["projection"]) @ np.r_[target, 1.0]
        img = b.render().astype(int)
        green = (img[..., 1] > 120) & (img[..., 0] < 0.8 * img[..., 1]) & (img[..., 2] < 0.8 * img[..., 1])
        ys, xs = np.nonzero(green[max(0, int(v / w) - 25) : int(v / w) + 25, max(0, int(u / w) - 25) : int(u / w) + 25])
        assert len(xs) > 30, "no target-coloured pixels around the projected point"
        assert b.embodiment().validate().name == "dual-panda-launcher"
    finally:
        b.close()
