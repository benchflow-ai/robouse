"""Clients must run and retain their output with a different Python first on PATH, including inside Seatbelt."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from robouse import harnesses
from robouse.runner import sandbox, trial
from robouse.tasks import load_task

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "tasks" / "nav" / "nav-h01-oven"


@pytest.fixture
def client_env(tmp_path, sock_dir, monkeypatch):
    # A silent launcher reproduces the symptom without relying on a particular macOS Command Line Tools version.
    silent = tmp_path / "path"
    silent.mkdir()
    python = silent / "python3"
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o755)
    monkeypatch.setenv("PATH", f"{silent}:/usr/bin:/bin:/usr/sbin:/sbin")
    monkeypatch.setenv("ROBOUSE_MOLMOACT2_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("ROBOUSE_VLA_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("ROBOUSE_VLA_PYTHON", raising=False)
    monkeypatch.delenv("ROBOUSE_VLA_POLICY_CONFIG", raising=False)
    monkeypatch.setenv("ROBOUSE_SHOW_HARNESS_URL", "http://127.0.0.1:9/v1")
    monkeypatch.delenv("ROBOUSE_SHOW_HARNESS_CONFIG", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "launcher-test-key")
    # No model is called: clients stop after their first robot request finds no episode server.
    return {**os.environ, "ROBOUSE_SOCKET": str(sock_dir / "missing.sock")}


def _run(cmd, ws, env, tmp_path, sandboxed, message=None):
    record = tmp_path / "private-trial"
    record.mkdir(exist_ok=True)
    if sandboxed:
        if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
            pytest.skip("the macOS Seatbelt regression")
        cmd, name = sandbox.wrap(cmd, ws, env["ROBOUSE_SOCKET"], [record])
        assert name == "macos-seatbelt"
    # The runner opens the files outside the sandbox; an agent may write its inherited descriptors, not open them.
    with (record / "stdout").open("w") as out, (record / "stderr").open("w") as err:
        result = subprocess.run(cmd, cwd=ws, env=env, input=message, text=True, stdout=out, stderr=err, timeout=20)
    return result.returncode, (record / "stdout").read_text(), (record / "stderr").read_text()


@pytest.mark.parametrize("sandboxed", [False, True])
@pytest.mark.parametrize("harness,model", [("molmoact2", ""), ("vla", ""), ("show-harness", "local"), ("jev", "")])
def test_policy_clients_keep_their_output(tmp_path, client_env, harness, model, sandboxed):
    ws = tmp_path / "workspace with spaces"
    (ws / ".robouse").mkdir(parents=True)
    task = load_task(TASK)
    launch = harnesses.build(harness, model, task.instruction, ws, task, client_env)
    rc, out, err = _run(launch.cmd, ws, launch.env, tmp_path, sandboxed)
    assert rc != 0 and out, (out, err)
    event = json.loads(out)
    assert event["type"] == "error" and event["error"], (out, err)


@pytest.mark.parametrize("sandboxed", [False, True])
@pytest.mark.parametrize("interface", ["cli", "mcp"])
def test_workspace_robo_ignores_path_and_python_settings(tmp_path, client_env, monkeypatch, sandboxed, interface):
    # The wrapper must quote the copied client's path, and PYTHONHOME/PYTHONPATH must not affect the stdlib client.
    parent = tmp_path / "workspace parent with spaces"
    parent.mkdir()
    make_temp = trial.tempfile.mkdtemp
    monkeypatch.setattr(trial.tempfile, "mkdtemp", lambda **kw: make_temp(dir=parent, **kw))
    ws = trial._make_workspace(load_task(TASK))
    env = {**client_env, "PYTHONHOME": str(tmp_path / "not-a-python-install"), "PYTHONPATH": str(ws)}
    (ws / "sitecustomize.py").write_text("raise RuntimeError('workspace sitecustomize was loaded')\n")
    (ws / "json.py").write_text("raise RuntimeError('workspace json was loaded')\n")
    if interface == "mcp":
        cmd = [str(ws / ".robouse" / "bin" / "robo"), "mcp"]
        message = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'
    else:
        cmd, message = [str(ws / ".robouse" / "bin" / "robo"), "--help"], None
    try:
        rc, out, err = _run(cmd, ws, env, tmp_path, sandboxed, message)
        assert rc == 0 and not err, (out, err)
        if interface == "mcp":
            assert "observe" in [t["name"] for t in json.loads(out)["result"]["tools"]]
        else:
            assert "robo observe" in out
    finally:
        shutil.rmtree(ws)


def test_vla_still_uses_the_requested_python(tmp_path, client_env, monkeypatch):
    import shlex

    executable = tmp_path / "custom python"
    executable.write_text(f'#!/bin/sh\necho custom-python >&2\nexec {shlex.quote(sys.executable)} "$@"\n')
    executable.chmod(0o755)
    monkeypatch.setenv("ROBOUSE_VLA_PYTHON", str(executable))
    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    task = load_task(TASK)
    launch = harnesses.build("vla", "", task.instruction, ws, task, client_env)
    rc, out, err = _run(launch.cmd, ws, launch.env, tmp_path, False)
    assert rc != 0 and json.loads(out)["type"] == "error" and err.strip() == "custom-python"
