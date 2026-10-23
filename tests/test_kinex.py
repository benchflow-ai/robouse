"""The `kinex` harness: the RoboEnv-compatible bridge (wire protocol, devices, stepping and what it shows on a vision
task), driven through the device driver Kinex runs; the Kinex workspace it writes; the harness launch and its
isolation; the sandbox's rule for Kinex's Python; and the trajectory of a Kinex session.

Kinex itself (Node) is not needed: the driver's two imports from Kinex's runtime Python (`kinex.driver_protocol` and
`kinex.validation`) come from a small stand-in here. The end-to-end check with Kinex 1.0.0 is in docs/run-agents.md.
"""

from __future__ import annotations

import base64
import http.client
import importlib.util
import json
import math
import os
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("imageio")

from fakes import FakeBackend

from robouse import agent_cli
from robouse.core import session as S
from robouse.harnesses.kinex import bridge as B

ROOT = Path(__file__).resolve().parents[1]
SESSION = "robouse-test-session"

KINEX_STUB = {
    "__init__.py": "",
    # what the driver uses of Kinex's runtime: the waiting request's cancellation event, and number checks
    "driver_protocol.py": "import threading\nCANCEL = threading.Event()\n\ndef cancellation():\n    return CANCEL\n",
    "validation.py": (
        "import math\n\ndef number(value, name='value'):\n"
        "    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):\n"
        "        raise ValueError(f'{name} must be a finite number')\n    return value\n"
    ),
}


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch):
    monkeypatch.setattr(S, "make_backend", FakeBackend)
    monkeypatch.delenv("ROBOUSE_RECORD_SIZE", raising=False)
    monkeypatch.delenv("ROBOUSE_ORACLE_TOKEN", raising=False)


@pytest.fixture
def kinex_stub(tmp_path, monkeypatch):
    """The folder holding the stand-in `kinex` package, first on sys.path."""
    pkg = tmp_path / "kinex-stub" / "kinex"
    pkg.mkdir(parents=True)
    for name, text in KINEX_STUB.items():
        (pkg / name).write_text(text)
    monkeypatch.syspath_prepend(str(pkg.parent))
    for mod in [m for m in sys.modules if m == "kinex" or m.startswith("kinex.")]:
        monkeypatch.delitem(sys.modules, mod)
    yield pkg.parent
    for mod in [m for m in sys.modules if m == "kinex" or m.startswith("kinex.")]:
        sys.modules.pop(mod, None)


class Episode:
    """An episode server (the fake backend: a point hand that moves 1 cm per unit of action per step) in a thread, the
    bridge in front of it on loopback HTTP, and the Kinex workspace the bridge wrote."""

    def __init__(self, tmp: Path, sock_dir: Path, **spec):
        self.sock = str(sock_dir / f"e{len(list(sock_dir.iterdir()))}.sock")
        self.run = tmp / "run"
        self.ws = tmp / "ws"
        self.ws.mkdir(parents=True)
        ready = tmp / "ready"
        self.out: dict = {}
        spec = {"id": "t", "backend": "fake", "linger_s": 1, "max_steps": 200, **spec}
        self.th = threading.Thread(
            target=lambda: self.out.update(S.serve(spec, self.run, self.sock, self.ws, ready_file=ready)), daemon=True
        )
        self.th.start()
        for _ in range(500):
            if ready.exists():
                break
            time.sleep(0.01)
        self.srv = None
        self.bridge = B.Bridge(lambda r: agent_cli._send(r, path=self.sock), SESSION, "http://127.0.0.1:0")
        self.bridge.start()
        self.srv = B.http_server(self.bridge, "127.0.0.1", 0)
        self.port = self.srv.server_address[1]
        self.bridge.endpoint = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.kinex = self.ws / ".kinex"
        self.bridge.write_kinex(
            self.kinex, (ROOT / "src" / "robouse" / "harnesses" / "kinex" / "driver.py").read_text()
        )

    def driver(self, name: str):
        """The device's driver.py, loaded as Kinex would run it (its own folder, its connection.json)."""
        path = self.kinex / "devices" / name / "driver.py"
        spec = importlib.util.spec_from_file_location(f"kinex_driver_{name}_{id(self)}", path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def call(self, name: str, action: str = "read", args: dict | None = None) -> dict:
        return self.driver(name).dispatch(action, args or {})

    def post(self, body: dict, headers: dict | None = None) -> tuple[int, dict]:
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("POST", "/", json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
        raw = r.read()
        c.close()
        return r.status, (json.loads(raw) if raw.startswith(b"{") else {})

    def request(self, op: str, args: dict | None = None, **over) -> dict:
        body = {
            "protocol": "roboenv/1",
            "session": SESSION,
            "generation": 0,
            "request_id": "test-" + os.urandom(4).hex(),
            "deadline_s": 30,
            "op": op,
            "args": args or {},
            **over,
        }
        return self.post(body)[1]

    def trace(self) -> list[dict]:
        return [json.loads(line) for line in (self.run / "trace.jsonl").read_text().splitlines()]

    def close(self) -> None:
        if not self.bridge.finished:
            agent_cli._send({"op": "give_up", "text": "[runner] test over", "runner": True}, path=self.sock)
        self.th.join(timeout=20)
        if self.srv is not None:
            self.srv.shutdown()


@pytest.fixture
def episode(tmp_path, sock_dir, kinex_stub):
    made: list[Episode] = []

    def make(**spec) -> Episode:
        ep = Episode(tmp_path / f"ep{len(made)}", sock_dir, **spec)
        made.append(ep)
        return ep

    yield make
    for ep in made:
        ep.close()


def _png(data: bytes) -> tuple[int, int]:
    return B.png_size(data)


# ---- the devices --------------------------------------------------------------------------------------------------


def test_an_arm_task_is_a_world_an_arm_a_gripper_and_its_cameras(episode) -> None:
    ep = episode()
    assert {n: d["kind"] for n, d in ep.bridge.devices.items()} == {
        "world": "world",
        "arm": "arm",
        "gripper": "gripper",
        "front_camera": "camera",
    }
    profiles = {p.parent.name: json.loads(p.read_text()) for p in sorted((ep.kinex / "devices").glob("*/profile.yaml"))}
    assert {n: p["type"] for n, p in profiles.items()} == {
        "arm": "joint",
        "front_camera": "rgb",
        "gripper": "gripper",
        "world": "world",
    }
    assert all(p["loaded"] is True and p["access"]["driver"]["persistent"] is True for p in profiles.values())
    # every action Kinex requires of each type (core device/interface.ts requiredActions)
    need = {
        "world": {"read", "wait", "load", "unload", "status"},
        "arm": {"read", "write", "stop", "load", "unload", "status", "fk", "ik"},
        "gripper": {"read", "write", "stop", "load", "unload", "status"},
        "front_camera": {"read", "load", "unload", "status"},
    }
    for n, p in profiles.items():
        assert need[n] <= set(p["access"]["driver"]["actions"]), n
    arm = profiles["arm"]["intrinsics"]
    assert [(j["name"], j["type"]) for j in arm["model"]["joints"]] == [
        ("x", "prismatic"),
        ("y", "prismatic"),
        ("z", "prismatic"),
    ]
    assert arm["home"] == {"x": 0.0, "y": 0.0, "z": 0.0} and arm["kinematics"]["frame"] == "hand"
    assert profiles["gripper"]["extrinsics"]["mount"]["parent"] == "arm"
    assert profiles["gripper"]["intrinsics"]["control"]["bounds"] == {"min": -1.0, "max": 1.0}
    cam = profiles["front_camera"]["intrinsics"]["color"]
    assert (cam["width"], cam["height"]) == (48, 32)  # the fake backend's image
    # a state task: `robo info` gives no camera calibration, so neither does the profile
    assert cam["projection"] == "???" and profiles["front_camera"]["extrinsics"]["mount"] == "???"
    assert "extrinsics" not in profiles["world"]
    assert ep.bridge.catalog().splitlines()[1:] == [
        "  world: world",
        "  arm: joint from arm.ee_delta, hand at [0.0, 0.0, 0.0]",
        "  gripper: gripper from gripper",
        "  front_camera: rgb from camera front, 48x32, no calibration",
    ]
    manifest = json.loads((ep.kinex / "workspace.yaml").read_text())
    assert manifest["identity"]["platform"] == "sim" and manifest["sim"]["simulator"] == "fake"
    conn = json.loads((ep.kinex / "devices" / "arm" / "connection.json").read_text())
    assert conn["session"] == SESSION and conn["endpoint"] == ep.bridge.endpoint and conn["kind"] == "arm"
    assert (ep.kinex / "devices" / "arm" / "connection.json").stat().st_mode & 0o077 == 0


def test_the_arm_follows_its_references_while_the_world_waits(episode) -> None:
    ep = episode()
    assert ep.call("arm") == {
        "ok": True,
        "positions": [0.0, 0.0, 0.0],
        "velocities": [],
        "efforts": [],
        "faults": [],
        "timestamp": 0.0,
    }
    w = ep.call(
        "arm", "write", {"actions": [[0.02, 0.0, 0.0], [0.04, 0.01, 0.0], [0.05, 0.01, 0.0]], "duration_s": 0.3}
    )
    assert w["ok"] and w["execution_id"].startswith("driver-") and w["state"]["positions"] == [0.0, 0.0, 0.0]
    assert ep.bridge.steps == 0  # a write moves nothing: time passes only in a wait
    r = ep.call("world", "wait", {"duration_s": 1.0})
    assert r == {"ok": True, "time_s": pytest.approx(1.0), "waited_s": pytest.approx(1.0)}
    assert ep.bridge.steps == 20  # 1 s at the default 0.05 s per step
    pos = ep.call("arm")["positions"]
    assert max(abs(a - b) for a, b in zip(pos, [0.05, 0.01, 0.0], strict=True)) <= 0.0006
    assert ep.bridge.response() == pytest.approx(0.01, rel=0.05)  # the fake hand: 1 cm per unit per step
    world = ep.call("world")
    assert world["time_s"] == pytest.approx(1.0) and world["budget"] == pytest.approx({"used_s": 1.0, "max_s": 10.0})
    g = ep.call("gripper", "write", {"actions": [1.0], "duration_s": 0.1})
    assert g["ok"] and g["state"]["aperture_m"] is None
    ep.call("world", "wait", {"duration_s": 0.2})
    grip = ep.call("gripper")
    assert grip["command"] == 1.0 and grip["gripper_open"] is False  # what `robo observe` reports, as it reports it
    # every step the bridge sent is an ordinary request in the episode's trace, marked as the bridge's
    acts = [e for e in ep.trace() if e["req"]["op"] == "act"]
    assert acts and all(e["req"]["via"] == "roboenv-bridge" and isinstance(e["req"]["sent"], float) for e in acts)
    assert sum(e["resp"]["result"]["executed_steps"] for e in acts) == ep.bridge.steps == 24


def test_camera_reads_are_robo_observe_images(episode) -> None:
    ep = episode()
    f = ep.call("front_camera", "read", {"output": "file"})
    assert f["ok"] and Path(f["file"]).parent == ep.ws / "observations" and f["camera"] == "front"
    b = ep.call("front_camera", "read", {"output": "base64"})
    assert _png(base64.b64decode(b["color"])) == (48, 32)
    a = ep.call("front_camera", "read", {"output": "array"})  # arrays cross the JSON boundary as a PNG
    assert _png(base64.b64decode(a["color"])) == (48, 32)
    reads = [e["req"] for e in ep.trace() if e["req"]["op"] == "observe" and e["req"].get("image")]
    assert [r["camera"] for r in reads] == ["front"] * 3


def test_a_vision_task_shows_the_hand_and_the_images_never_the_objects(episode, monkeypatch) -> None:
    """The fake backend's `goal` is object state: hidden on a vision task. The bridge sees only what `robo` shows, so no
    profile, device reading or reply carries it; the camera's calibration is in its profile because `robo info` gives
    it on vision tasks."""
    f, w, h = 40.0, 48, 32
    pos = [0.5, -0.4, 0.6]

    class Calibrated(FakeBackend):
        def camera_info(self, names):
            return [{"name": n, "width": w, "height": h, "projection": _mujoco_projection(f, w, h, pos)} for n in names]

    monkeypatch.setattr(S, "make_backend", Calibrated)
    ep = episode(obs_mode="vision", goal=[0.07, 0.03, 0.0])
    assert "goal" not in ep.bridge.state and set(ep.bridge.state) == {"hand_pos", "gripper_open"}
    ep.call("arm", "write", {"actions": [[0.02, 0.0, 0.0]], "duration_s": 0.1})
    ep.call("world", "wait", {"duration_s": 0.5})
    replies = [
        ep.call("arm"),
        ep.call("gripper"),
        ep.call("world"),
        ep.request("devices.list"),
        ep.request("environment.describe"),
        ep.request("simulation.status"),
    ]
    text = json.dumps(replies) + "".join(p.read_text() for p in ep.kinex.rglob("*.yaml"))
    assert "goal" not in text and "0.07" not in text
    cam = json.loads((ep.kinex / "devices" / "front_camera" / "profile.yaml").read_text())
    proj = cam["intrinsics"]["color"]["projection"]
    assert (proj["fx"], proj["fy"], proj["skew"]) == (pytest.approx(f), pytest.approx(f), pytest.approx(0.0, abs=1e-9))
    assert (proj["cx"], proj["cy"]) == (pytest.approx(w / 2 - 0.5), pytest.approx(h / 2 - 0.5))
    assert cam["extrinsics"]["mount"]["translation_m"] == pytest.approx(pos)
    # images are saved only when a camera is read: the bridge's own observations render nothing to the workspace
    assert not list((ep.ws / "observations").glob("*.png"))


def _mujoco_projection(f: float, w: int, h: int, pos: list[float], xmat=None) -> list[list[float]]:
    """robouse.core.cameras.mujoco_camera's matrix for a camera at `pos` whose axes (OpenGL: x right, y up, z back) are
    the columns of `xmat` (MuJoCo's cam_xmat); by default the identity, a camera looking straight down."""
    import numpy as np

    r = np.eye(3) if xmat is None else np.asarray(xmat, dtype=float)
    ext = np.hstack([r.T, (-r.T @ np.asarray(pos, float))[:, None]])
    k = np.array([[f, 0, -w / 2], [0, -f, -h / 2], [0, 0, -1.0]])
    return (k @ ext).tolist()


def test_calibration_recovers_the_camera_from_robo_info_s_matrix() -> None:
    import numpy as np

    # a tilted camera: optical axes in the world, then the OpenGL axes MuJoCo uses (y up, z back)
    a = math.radians(35)
    z_opt = np.array([0.0, math.cos(a), -math.sin(a)])  # looks forward and down
    x_opt = np.array([1.0, 0.0, 0.0])
    y_opt = np.cross(z_opt, x_opt)
    gl = np.stack([x_opt, -y_opt, -z_opt], axis=1)  # columns: camera axes in the world
    pos = [0.1, -0.6, 0.5]
    proj = _mujoco_projection(300.0, 320, 240, pos, xmat=gl)
    intr, mount = B.calibration(proj)
    assert intr["fx"] == pytest.approx(300.0) and intr["fy"] == pytest.approx(300.0)
    assert intr["cx"] == pytest.approx(159.5) and intr["cy"] == pytest.approx(119.5)
    assert mount["translation_m"] == pytest.approx(pos)
    x, y, z, wq = mount["rotation_xyzw"]
    rot = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * wq), 2 * (x * z + y * wq)],
            [2 * (x * y + z * wq), 1 - 2 * (x * x + z * z), 2 * (y * z - x * wq)],
            [2 * (x * z - y * wq), 2 * (y * z + x * wq), 1 - 2 * (x * x + y * y)],
        ]
    )
    assert rot[:, 2] == pytest.approx(z_opt) and rot[:, 0] == pytest.approx(x_opt)  # optical z forward, x right
    # a world point projects to the same pixel through both, with Kinex's pixel centres half a pixel up and left
    p = np.array([0.15, -0.2, 0.05])
    uvw = np.asarray(proj) @ np.append(p, 1.0)
    c = rot.T @ (p - np.asarray(pos))
    u = intr["fx"] * c[0] / c[2] + intr["cx"]
    v = intr["fy"] * c[1] / c[2] + intr["cy"]
    assert (u, v) == (pytest.approx(uvw[0] / uvw[2] - 0.5), pytest.approx(uvw[1] / uvw[2] - 0.5))


# ---- time, budget and the episode's end ---------------------------------------------------------------------------


def test_waits_use_the_step_budget_and_the_end_is_the_episode_s(episode) -> None:
    ep = episode(max_steps=30)
    assert ep.call("world", "wait", {"duration_s": 1.0})["waited_s"] == pytest.approx(1.0)
    r = ep.call("world", "wait", {"duration_s": 1.0})
    assert r["waited_s"] == pytest.approx(0.5) and ep.bridge.finished and ep.bridge.outcome == "budget_exhausted"
    late = ep.call("arm", "write", {"actions": [[0.0, 0.0, 0.1]], "duration_s": 0.1})
    assert late["ok"] is False and late["code"] == "episode_finished" and late["details"]["effects"] == "none"
    assert ep.call("arm")["ok"]  # reads still answer, from the last state
    st = ep.request("simulation.status")["result"]
    assert st["terminal"] is True and st["reason"] == "budget_exhausted" and "success" not in st
    assert st["budget"]["used"] == st["budget"]["max"] == 30


def test_a_wait_the_episode_ends_in_says_so(episode) -> None:
    """A world wait that the episode's end cuts short tells Kinex, as the other device calls do: terminal, and the
    simulation status with why the episode ended."""
    ep = episode(max_steps=10)
    r = ep.call("world", "wait", {"duration_s": 1.0})
    assert r["ok"] and r["waited_s"] == pytest.approx(0.5) and r["terminal"] is True
    assert r["simulation"]["reason"] == "budget_exhausted" and r["simulation"]["budget"]["used"] == 10


def test_simulation_stop_is_robo_done_and_never_reveals_the_verdict(episode) -> None:
    ep = episode(goal=[0.0, 0.0, 0.0])
    reply = ep.request("simulation.stop")
    assert reply["ok"] and reply["result"]["terminal"] is True and reply["result"]["success"] is None
    ep.th.join(timeout=20)
    result = json.loads((ep.run / "result.json").read_text())
    assert result["outcome"] == "done" and result["success"] is True
    assert ep.trace()[-1]["req"]["op"] == "done" and ep.trace()[-1]["req"]["via"] == "roboenv-bridge"


def test_moves_made_with_robo_reset_the_arm_s_reference(episode) -> None:
    """The agent may also drive the robot with `robo`. The bridge then holds the arm where it now is, instead of pulling
    it back to the reference it held before."""
    ep = episode()
    ep.call("arm", "write", {"actions": [[0.03, 0.0, 0.0]], "duration_s": 0.1})
    ep.call("world", "wait", {"duration_s": 0.5})
    assert agent_cli._send({"op": "act", "action": [1, 0, 0, -1], "repeat": 3}, path=ep.sock)["ok"]
    here = ep.call("arm")["positions"]
    assert here[0] == pytest.approx(0.06, abs=0.001)
    ep.call("world", "wait", {"duration_s": 0.5})
    assert ep.call("arm")["positions"][0] == pytest.approx(here[0], abs=0.001)
    # the same when the first device call after the move is a camera read, whose observation shows the new steps
    assert agent_cli._send({"op": "act", "action": [1, 0, 0, -1], "repeat": 2}, path=ep.sock)["ok"]
    assert ep.call("front_camera", "read", {"output": "file"})["ok"]
    ep.call("world", "wait", {"duration_s": 0.5})
    assert ep.call("arm")["positions"][0] == pytest.approx(0.08, abs=0.001)


def test_stop_cancel_and_a_cancelled_wait(episode) -> None:
    import kinex.driver_protocol as dp

    ep = episode()
    w = ep.call("arm", "write", {"actions": [[0.1 * i / 50, 0.0, 0.0] for i in range(1, 51)], "duration_s": 5.0})
    ep.call("world", "wait", {"duration_s": 0.5})
    assert ep.request("devices.cancel", {"execution_id": w["execution_id"]})["result"]["data"] == {"stopped": True}
    held = ep.call("arm")["positions"]
    ep.call("world", "wait", {"duration_s": 0.5})
    assert ep.call("arm")["positions"] == pytest.approx(held, abs=0.0006)  # holds where it was stopped
    stop = ep.call("gripper", "stop")
    assert stop == {"ok": True, "stopped": True, "behavior": "hold", "affected_devices": ["gripper"]}
    # Kinex cancels a world wait through the driver (its request's cancellation event): it ends within one slice
    dp.CANCEL.set()
    try:
        r = ep.call("world", "wait", {"duration_s": 5.0})
    finally:
        dp.CANCEL.clear()
    assert r["ok"] is False and "interrupted" in r["error"] and ep.bridge.steps == 20


# ---- the wire protocol --------------------------------------------------------------------------------------------


def test_the_wire_protocol_needs_the_session_and_the_loopback_host(episode) -> None:
    ep = episode()
    c = http.client.HTTPConnection("127.0.0.1", ep.port, timeout=10)
    c.request("GET", "/")
    ident = json.loads(c.getresponse().read())
    assert ident == {"protocol": "roboenv/1", "generation": 0}  # the session is the endpoint's capability
    assert ep.request("health")["ok"]
    assert ep.request("health", session="robouse-other")["error"]["code"] == "session_mismatch"
    assert ep.request("health", generation=1)["error"]["code"] == "episode_changed"
    assert ep.request("devices.reset")["error"]["code"] == "unsupported_op"
    assert ep.request("devices.call", {"device": "arm", "action": "fly", "args": {}})["error"]["code"] == (
        "unsupported_action"
    )
    assert ep.request("devices.call", {"device": "base", "action": "read", "args": {}})["error"]["code"] == (
        "unknown_device"
    )
    assert ep.post({"op": "health"})[1]["error"]["code"] == "invalid_request"
    assert ep.post({"op": "health"}, {"Origin": "http://evil.example"})[0] == 403
    assert ep.post({"op": "health"}, {"Host": "localhost:1"})[0] == 403  # a rebound name is refused
    listed = ep.request("devices.list")["result"]
    assert listed["schema_version"] == "roboenv/devices/1" and [d["name"] for d in listed["devices"]] == sorted(
        ep.bridge.devices
    )
    arm = ep.request("devices.describe", {"device": "arm"})["result"]
    assert arm["actions"]["write"] == {"supported": True, "read_only": False}
    # camera images over HTTP, as RoboEnv serves them, under the session
    art = ep.request("devices.call", {"device": "front_camera", "action": "read", "args": {}})["result"]["data"]
    for session, code in (("robouse-other", 404), (SESSION, 200)):
        c = http.client.HTTPConnection("127.0.0.1", ep.port, timeout=10)
        c.request("GET", f"/artifacts/{session}/0/{art['artifact']}")
        r = c.getresponse()
        body = r.read()
        assert r.status == code
    assert _png(body) == (48, 32)


# ---- the launch ---------------------------------------------------------------------------------------------------


def _launch_env(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from robouse import harnesses

    gw = SimpleNamespace(
        url="http://127.0.0.1:4242", key="sk-robouse-gwkey", model="gw-alias", stats={}, stop=None, stop_file=None
    )
    seen: dict = {}

    def fake_gateway(ref, env, protocol):
        seen.update(ref=ref, protocol=protocol)
        return gw

    monkeypatch.setattr(harnesses, "_gateway", fake_gateway)
    monkeypatch.setenv("GLM_API_KEY", "sk-SECRET")  # the runner's environment; never the agent's
    exe = tmp_path / "kinex-1.0.0" / "node_modules" / "kinex" / "bin" / "kinex.mjs"  # an npm install, as documented
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    venv = tmp_path / "kinex-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python3").write_text("")
    monkeypatch.setenv("ROBOUSE_KINEX", str(exe))
    monkeypatch.setenv("ROBOUSE_KINEX_NODE", "/opt/node/bin/node")
    monkeypatch.setenv("ROBOUSE_KINEX_VENV", str(venv))
    ws = tmp_path / "ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    env = {
        "PATH": "/usr/bin",
        "HOME": "/home/u",
        "ROBOUSE_INTERFACE": "cli",
        "_ROBOUSE_IMAGE_INPUT": "1",
        "_ROBOUSE_TRIAL_DIR": str(tmp_path),
        "_ROBOUSE_SPEND_CAP_USD": "5",
    }
    return gw, seen, exe, venv, ws, env


def test_kinex_launch_is_isolated_and_holds_no_key(tmp_path, monkeypatch) -> None:
    pytest.importorskip("benchflow")  # the model registry
    from robouse.harnesses import build
    from robouse.harnesses.kinex import PROMPT_PREFIX
    from robouse.tasks import Task

    gw, seen, exe, venv, ws, env = _launch_env(tmp_path, monkeypatch)
    launch = build("kinex", "", "do it", ws, Task(tmp_path, {"robouse": {"id": "t"}}, "do it"), env)
    assert seen["ref"].id == "glm/glm-5.3" and seen["protocol"] == "anthropic-messages"
    root = ws / ".robouse" / "kinex"
    agent = root / "config" / "agent"
    prov = json.loads((agent / "models.json").read_text())["providers"]["robouse"]
    assert (
        prov["baseUrl"] == gw.url and prov["api"] == "anthropic-messages" and prov["apiKey"] == "$ROBOUSE_GATEWAY_KEY"
    )
    assert prov["models"][0]["id"] == "gw-alias" and prov["models"][0]["input"] == ["text", "image"]
    settings = json.loads((agent / "settings.json").read_text())
    assert settings["defaultProvider"] == "robouse" and settings["defaultModel"] == "gw-alias"
    # Kinex's bundled web search: configured as a package that loads nothing, and never installed (PI_OFFLINE)
    assert settings["packages"] == [
        {"source": "npm:pi-web-search", "extensions": [], "skills": [], "prompts": [], "themes": []}
    ]
    e = launch.env
    assert e["KINEX_CONFIG_DIR"] == str(root / "config") and e["KINEX_DATA_DIR"] == str(root / "data")
    assert e["HOME"].startswith(str(root)) and all(e[k].startswith(str(root)) for k in e if k.startswith("XDG_"))
    assert e["PI_OFFLINE"] == "1" and e["ROBOUSE_GATEWAY_KEY"] == gw.key
    assert e["ROBOENV_ENDPOINT"].startswith("http://127.0.0.1:") and e["ROBOENV_SESSION"].startswith("robouse-")
    assert not any(k.startswith("_ROBOUSE") for k in e)  # the runner's private variables
    assert "sk-SECRET" not in json.dumps(launch.cmd) + json.dumps(e)
    assert not any(s in f.read_text() for f in root.rglob("*") if f.is_file() for s in ("sk-SECRET", gw.key))
    # Kinex's managed Python is the shared environment, linked
    assert (ws / ".kinex" / "python" / ".venv").resolve() == venv.resolve()
    # the npm install every Kinex trial runs is read-only to the agent, and Python's bytecode stays in this trial
    assert launch.read_only == [Path(os.path.realpath(tmp_path / "kinex-1.0.0" / "node_modules"))]
    assert e["PYTHONPYCACHEPREFIX"] == str(root / "pycache")
    cmd = launch.cmd
    assert (
        cmd[1] == str(ws / ".robouse" / "bin" / "roboenv_bridge.py")
        and (ws / ".robouse" / "bin" / "kinex_driver.py").is_file()
    )
    i = cmd.index("--run")
    assert cmd[i + 1 : i + 6] == ["/opt/node/bin/node", os.path.realpath(exe), "run", "--yolo", "--mode"]
    assert cmd[cmd.index("--provider") + 1] == "robouse" and cmd[cmd.index("--model") + 1] == "gw-alias"
    assert cmd[-2] == "--" and cmd[-1] == PROMPT_PREFIX + "do it"
    assert launch.notes["model_id"] == "glm/glm-5.3" and launch.notes["collect"] == [
        ["kinex/data/agent/sessions", "agent/pi_session.jsonl"]
    ]


def test_kinex_needs_its_launcher_and_its_python(tmp_path, monkeypatch) -> None:
    pytest.importorskip("benchflow")
    from robouse.harnesses import build
    from robouse.tasks import Task

    gw, seen, exe, venv, ws, env = _launch_env(tmp_path, monkeypatch)
    task = Task(tmp_path, {"robouse": {"id": "t"}}, "do it")
    monkeypatch.setenv("ROBOUSE_KINEX_VENV", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="Python environment is missing.*uv venv"):
        build("kinex", "", "do it", ws, task, dict(env))
    monkeypatch.delenv("ROBOUSE_KINEX")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(RuntimeError, match="Kinex is not installed"):
        build("kinex", "", "do it", ws, task, dict(env))
    assert "ref" not in seen  # refused before the model gateway starts


def test_the_bridge_writes_the_workspace_and_runs_kinex(episode, kinex_stub, tmp_path) -> None:
    """`roboenv_bridge.py --run CMD` from the workspace: the Kinex workspace is there before CMD starts, the devices
    answer while it runs, and its exit code is the bridge's."""
    ep = episode()
    ws = tmp_path / "run-ws"
    (ws / ".robouse" / "bin").mkdir(parents=True)
    for src, dst in (("bridge.py", "roboenv_bridge.py"), ("driver.py", "kinex_driver.py")):
        (ws / ".robouse" / "bin" / dst).write_text((ROOT / "src" / "robouse" / "harnesses" / "kinex" / src).read_text())
    (ws / ".robouse" / "bin" / "robo_cli.py").write_text((ROOT / "src" / "robouse" / "agent_cli.py").read_text())
    from robouse.harnesses.kinex import _free_port

    child = (
        "import importlib.util, json, sys\n"
        "spec = importlib.util.spec_from_file_location('d', '.kinex/devices/world/driver.py')\n"
        "d = importlib.util.module_from_spec(spec); spec.loader.exec_module(d)\n"
        "print(json.dumps(d.dispatch('wait', {'duration_s': 0.25})))\n"
        "sys.exit(3)\n"
    )
    out = tmp_path / "child.out"
    env = {
        **os.environ,
        "ROBOUSE_SOCKET": ep.sock,
        "ROBOENV_ENDPOINT": f"http://127.0.0.1:{_free_port()}",
        "ROBOENV_SESSION": "robouse-run-session",
        "PYTHONPATH": str(kinex_stub),
    }
    import subprocess

    with open(out, "w") as f:
        rc = subprocess.call(
            [sys.executable, ".robouse/bin/roboenv_bridge.py", "--run", sys.executable, "-c", child],
            cwd=ws,
            env=env,
            stdout=f,
            timeout=60,
        )
    assert rc == 3
    assert json.loads(out.read_text().splitlines()[-1]) == {
        "ok": True,
        "time_s": pytest.approx(0.25),
        "waited_s": pytest.approx(0.25),
    }
    assert sorted(p.name for p in (ws / ".kinex" / "devices").iterdir()) == ["arm", "front_camera", "gripper", "world"]


# ---- the sandbox and the trajectory -------------------------------------------------------------------------------


def test_agents_can_read_kinex_s_python_but_not_change_it(tmp_path, monkeypatch) -> None:
    from robouse.runner import sandbox

    cache = tmp_path / "cache"
    venv = cache / "kinex-venv"
    (venv / "bin").mkdir(parents=True)
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(cache))
    real = os.path.realpath(venv)
    assert real in sandbox._programs() and os.path.realpath(cache) in sandbox._denied([])
    prof = sandbox.sandbox_profile(tmp_path / "ws")
    assert f'(allow file-read* (subpath "{real}"))' in prof
    assert f'(allow file-read* file-write* (subpath "{real}"))' not in prof
    args = sandbox.bwrap_args(tmp_path / "ws", str(tmp_path / "sock"), [])
    pairs = list(zip(args, args[1:], strict=False))
    assert ("--ro-bind", real) in pairs and args.index(real) > args.index(os.path.realpath(cache))


def test_agents_can_read_kinex_s_install_but_not_change_it(tmp_path) -> None:
    """Every Kinex trial runs Kinex's npm install: the node_modules folder of its launcher, with Kinex's packages and
    the Python helpers its tools and drivers import. A file an agent left there (a changed module, a __pycache__ file)
    would run in a later trial, so the sandbox lets agents read it, never write it."""
    from robouse.harnesses.kinex import install
    from robouse.runner import sandbox

    mods = tmp_path / "kinex-1.0.0" / "node_modules"
    exe = mods / "kinex" / "bin" / "kinex.mjs"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    real = os.path.realpath(mods)
    assert install(["/opt/node/bin/node", os.path.realpath(exe)]) == Path(real)
    assert install([str(tmp_path / "bin" / "kinex")]) is None  # a launcher outside an npm install
    ws = tmp_path / "ws"
    ws.mkdir()
    prof = sandbox.sandbox_profile(ws, read_only=[mods])
    rule = f'(deny file-write* (subpath "{real}"))'
    assert rule in prof and f'(allow file-read* file-write* (subpath "{real}"))' not in prof
    # later rules win: after the workspace's
    assert prof.index(rule) > prof.index(f'(allow file-read* file-write* (subpath "{os.path.realpath(ws)}"))')
    args = sandbox.bwrap_args(ws, str(tmp_path / "sock"), [], read_only=[mods])
    assert ("--ro-bind", real) in list(zip(args, args[1:], strict=False))
    # never a folder that holds the workspace (it stays writable), nor one inside a denied folder (it stays hidden)
    assert sandbox._read_only([tmp_path], ws, []) == []
    assert sandbox._read_only([mods], ws, [os.path.realpath(tmp_path / "kinex-1.0.0")]) == []
    assert sandbox._read_only([mods, tmp_path / "missing"], ws, []) == [real]


def test_the_trajectory_gives_each_kinex_tool_call_the_requests_it_made(tmp_path) -> None:
    """A Kinex session (Pi's format) timestamps each tool call's result; the bridge stamps its requests with the time it
    sent them. Each request belongs to the tool call running then; the bridge's start-up requests to none."""
    from robouse.runner import atif

    trial = tmp_path / "t"
    for d in ("agent", "episode"):
        (trial / d).mkdir(parents=True)
    t0 = 1_800_000_000.0
    trace = [
        {"t": 0.1, "steps": 0, "req": {"op": "info", "via": "roboenv-bridge", "sent": t0 + 0.1}, "resp": {"ok": True}},
        *(
            {
                "t": 2.0 + 0.01 * i,
                "steps": i + 1,
                "req": {
                    "op": "act",
                    "action": [0, 0, 0, -1],
                    "repeat": 1,
                    "via": "roboenv-bridge",
                    "sent": t0 + 2.0 + 0.01 * i,
                },
                "resp": {"ok": True, "result": {"executed_steps": 1, "steps_used": i + 1}},
            }
            for i in range(5)
        ),
        {
            "t": 4.0,
            "steps": 5,
            "req": {"op": "done", "text": "ok"},
            "resp": {"ok": True, "result": {"outcome": "done"}},
        },
    ]
    (trial / "episode" / "trace.jsonl").write_text("\n".join(json.dumps(e) for e in trace))
    (trial / "episode" / "result.json").write_text(
        json.dumps({"outcome": "done", "steps_used": 5, "wall_time_s": 99.0})
    )

    def msg(role, ms, content, **kw):
        return {"type": "message", "message": {"role": role, "content": content, "timestamp": ms, **kw}}

    ms = lambda s: int((t0 + s) * 1000)
    session = [
        {"type": "session", "version": 3, "id": "s", "cwd": "/ws"},
        msg("user", ms(1.0), "PROMPT"),
        msg(
            "assistant",
            ms(1.5),
            [
                {
                    "type": "toolCall",
                    "id": "a",
                    "name": "device",
                    "arguments": {"deviceID": "world", "action": "wait", "args": {"duration_s": 0.25}},
                }
            ],
        ),
        msg("toolResult", ms(2.5), [{"type": "text", "text": "{}"}], toolCallId="a"),
        msg(
            "assistant",
            ms(3.0),
            [{"type": "toolCall", "id": "b", "name": "bash", "arguments": {"command": "robo done ok"}}],
        ),
        msg("toolResult", ms(4.5), [{"type": "text", "text": "outcome: done"}], toolCallId="b"),
    ]
    (trial / "agent" / "pi_session.jsonl").write_text("\n".join(json.dumps(e) for e in session))
    (trial / "config.json").write_text(json.dumps({"harness": "kinex", "task": "t"}))
    traj, _ = atif.build(trial)
    calls = [s for s in traj["steps"] if s.get("tool_calls")]
    counts = [s["observation"]["results"][0]["extra"].get("robo_requests") for s in calls]
    assert [s["tool_calls"][0]["function_name"] for s in calls] == ["device", "bash"] and counts == [5, 1]
    assert "Pi session" in traj["notes"] and "1 robo request(s) in the trace could not be matched" in traj["notes"]


# ---- a whole trial under the sandbox ------------------------------------------------------------------------------


@pytest.fixture
def outside_tmp():
    """A folder outside /tmp, which bubblewrap replaces with an empty one."""
    import shutil
    import tempfile

    base = Path(tempfile.mkdtemp(dir="/var/tmp"))
    yield base
    shutil.rmtree(base, ignore_errors=True)


FAKE_KINEX = r"""#!/usr/bin/env python3
# Stands in for `kinex run`: loads each device's driver as Kinex would (its folder, its connection.json) with a
# stand-in for Kinex's runtime Python, drives the robot through them, writes what it saw, and ends the episode.
import importlib.util, json, os, pathlib, subprocess, sys

ws = pathlib.Path.cwd()
stub = ws / ".robouse" / "kinex-stub" / "kinex"
stub.mkdir(parents=True, exist_ok=True)
for name, text in json.loads(sys.argv[sys.argv.index("--stub") + 1]).items():
    (stub / name).write_text(text)
sys.path.insert(0, str(stub.parent))

def driver(name):
    spec = importlib.util.spec_from_file_location("d_" + name, ws / ".kinex" / "devices" / name / "driver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.dispatch

seen = {"devices": sorted(p.name for p in (ws / ".kinex" / "devices").iterdir() if p.is_dir())}
seen["venv"] = (ws / ".kinex" / "python" / ".venv" / "bin" / "python3").exists()
arm, world, cam = driver("arm"), driver("world"), driver("front_camera")
seen["write"] = arm("write", {"actions": [[0.05, 0.2, 0.25]], "duration_s": 0.2})["ok"]  # 5 cm along x
seen["wait"] = world("wait", {"duration_s": 1.0})
seen["arm"] = arm("read", {})["positions"]
seen["camera"] = len(cam("read", {"output": "base64"}).get("color", ""))
try:
    open(ws / ".kinex" / "python" / ".venv" / "planted.txt", "w").write("x")
    seen["venv_writable"] = True
except OSError:
    seen["venv_writable"] = False
# this stand-in sits in an npm install, as Kinex does: try to leave a file there, and import the install's Python helper
# from a child process with this environment, as Kinex's tools do
install = next(p for p in pathlib.Path(__file__).resolve().parents if p.name == "node_modules")
try:
    open(install / "kinex" / "planted.txt", "w").write("x")
    seen["install_writable"] = True
except OSError:
    seen["install_writable"] = False
helpers = install / "@kinex" / "core" / "assets" / "python"
subprocess.run([sys.executable, "-c", "import kinex_helper"], env={**os.environ, "PYTHONPATH": str(helpers)}, check=True)
prefix = pathlib.Path(os.environ.get("PYTHONPYCACHEPREFIX", "/nonexistent")).resolve()
seen["pycache"] = [str(p.relative_to(ws.resolve())) for p in [prefix] if any(p.rglob("kinex_helper*.pyc"))]
print(json.dumps(seen))
subprocess.run(["robo", "done", "fake kinex"], check=True)
"""


def test_a_kinex_trial_runs_under_the_sandbox(tmp_path, monkeypatch, outside_tmp) -> None:
    """The whole launch under this platform's sandbox (Seatbelt on macOS, bubblewrap on Linux), with a stand-in for
    Kinex: the bridge serves on its loopback port, the drivers reach it, the devices move the robot through the episode
    server, and Kinex's Python environment (linked into the workspace) and its install can be read but not changed.
    Python's bytecode for the install's helpers stays in the trial's workspace."""
    pytest.importorskip("mujoco")
    pytest.importorskip("benchflow")  # the model registry
    from types import SimpleNamespace

    from robouse import harnesses
    from robouse.runner import run_trial, sandbox
    from robouse.tasks import load_task

    if not (sys.platform == "darwin" or (sys.platform.startswith("linux") and sandbox.bwrap_works())):
        pytest.skip("needs the macOS Seatbelt sandbox or working bubblewrap on Linux")
    monkeypatch.delenv("ROBOUSE_SANDBOX", raising=False)
    cache = outside_tmp / "cache"
    venv = cache / "kinex-venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python3").symlink_to(sys.executable)
    monkeypatch.setenv("ROBOUSE_CACHE_DIR", str(cache))
    install = outside_tmp / "kinex-1.0.0" / "node_modules"  # an npm install, with a Python helper as @kinex/core has
    exe = install / "kinex" / "bin" / "fake-kinex"
    exe.parent.mkdir(parents=True)
    helpers = install / "@kinex" / "core" / "assets" / "python"
    helpers.mkdir(parents=True)
    (helpers / "kinex_helper.py").write_text("VALUE = 1\n")
    # an explicit interpreter: macOS's /usr/bin/python3 shim loses its output under Seatbelt when stdout is a file in
    # the (denied) trial folder
    exe.write_text(FAKE_KINEX.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
    exe.chmod(0o755)
    monkeypatch.setenv("ROBOUSE_KINEX", str(exe))
    gw = SimpleNamespace(
        url="http://127.0.0.1:9", key="sk-robouse-test", model="m", stats={}, stop=None, stop_file=None
    )
    monkeypatch.setattr(harnesses, "_gateway", lambda ref, env, protocol: gw)
    import robouse.harnesses.kinex as K

    real_build = K.build

    def build(model, prompt, workspace, task, env):  # the stand-in gets the stand-in kinex package as an argument
        launch = real_build(model, prompt, workspace, task, env)
        i = launch.cmd.index("--run")
        launch.cmd[i + 2 : i + 2] = ["--stub", json.dumps(KINEX_STUB)]
        return launch

    monkeypatch.setattr(K, "build", build)
    res = run_trial(load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"), "kinex", "glm/glm-5.3", tmp_path / "job")
    trial = tmp_path / "job" / res["trial"]
    cfg = json.loads((trial / "config.json").read_text())
    assert cfg["sandbox"] != "none" and res["exception"] is None, res
    seen = json.loads((trial / "agent" / "stdout.jsonl").read_text().splitlines()[-1])
    assert seen["devices"] == ["arm", "front_camera", "gripper", "world"] and seen["venv"] is True
    assert seen["write"] is True and seen["wait"]["ok"] is True and seen["wait"]["waited_s"] == pytest.approx(1.0)
    assert seen["arm"][0] == pytest.approx(0.05, abs=0.001) and seen["camera"] > 1000
    assert seen["venv_writable"] is False and not (venv / "planted.txt").exists()
    assert seen["install_writable"] is False and not (install / "kinex" / "planted.txt").exists()
    # the helper's bytecode went to the trial's own folder, never next to it in the install
    assert seen["pycache"] == [".robouse/kinex/pycache"] and not list(install.rglob("__pycache__"))
    assert res["outcome"] == "done" and res["steps"] == 20
    assert "roboenv bridge: task arc-gravity" in (trial / "agent" / "stderr.txt").read_text()
