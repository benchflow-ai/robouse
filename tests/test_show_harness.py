"""The `show-harness` harness (harnesses/show_harness/): Show-Harness's action units, parser and camera contract; the
client against a real episode server with a scripted model; the launch; and whole trials through a real model gateway
to a stub provider (zero-shot) or straight to a stub server (fine-tuned)."""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
from fakes import FakeBackend, glm_registry

from robouse.backends.base import ActionSpec, StepInfo
from robouse.core import session as S
from robouse.core.protocol import RUNNER_PREFIX, agent_refused

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "src" / "robouse" / "harnesses" / "show_harness" / "client.py"
CUBEPICK = ROOT / "tasks" / "cubepick" / "cubepick-reach-layout-0"
TABLETOP = ROOT / "tasks" / "libero-style" / "libero-red-block-in-bowl"

_spec = importlib.util.spec_from_file_location("show_harness_client", CLIENT)
C = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(C)


# ---- the vocabulary, parser and plugins -------------------------------------------------------------------------------


def test_parser_follows_the_repository_ladder() -> None:
    units = C.CONTROLLER_TOKENS
    assert C.parse_single_token("MV_FWD", units) == "MV_FWD"
    assert C.parse_single_token("<think>maybe MV_LEFT</think>\nGRASP", units) == "GRASP"
    assert C.parse_single_token('{"decision": "MV_DOWN", "reasoning": "x"}', units) == "MV_DOWN"
    assert C.parse_single_token("The block is to the right, so MV_RIGHT.", units) == "MV_RIGHT"
    with pytest.raises(ValueError):
        C.parse_single_token("MV_STRETCH", units)
    # the zero-shot reply: JSON with the decision first, the reasoning after
    raw = '{"decision":"MV_BACK","reasoning":"WRIST: NO. The bowl is near the image top; PLAN: MV_BACK, MV_BACK, MV_LEFT"}'
    assert C.recover_allowed_token(raw, units) == "MV_BACK"
    assert C.parse_wrist_marker(raw) is False and C.parse_wrist_marker("WRIST: yes then WRIST: NO") is False
    assert C.parse_plan(raw, 3) == ["MV_BACK", "MV_BACK", "MV_LEFT"] and C.parse_plan("no plan", 3) == []
    assert C.recover_allowed_token("MV_LEFT or MV_RIGHT, hard to say", units) == ""  # two candidates: no guess
    # a cue word matches case-insensitively ("so ... grasp"); a lowercase word is not a unit (regression, 2026-10-02:
    # a reply that only said "grasp" was executed as nothing); the controller then asks again for the token
    assert C.recover_allowed_token("so I will grasp it now", units) == "grasp"
    with pytest.raises(ValueError):
        C.parse_single_token("so I will grasp it now", units)


def test_subtask_plan_parsing_merges_a_pure_reach_into_its_grasp() -> None:
    plan = {
        "subgoals": [
            {
                "id": "a",
                "target": "red block",
                "affordance": "body",
                "motion": "approach",
                "description": "move above the red block",
                "completion": "gripper over the block",
            },
            {
                "id": "b",
                "target": "the red block",
                "affordance": "body",
                "motion": "Grasp",
                "description": "lower and close",
                "completion": "block between fingers",
            },
            {"id": "c", "target": "bowl", "affordance": "rim", "motion": "place", "description": "", "completion": ""},
        ]
    }
    sgs = C.subgoals_from(plan)
    assert [s["motion"] for s in sgs] == ["GRASP"]  # the reach folds into the grasp; a stage without text is dropped
    assert sgs[0]["description"] == "move above the red block. Then lower and close."
    assert C.parse_json_object('Sure:\n```json\n{"subgoals": [1]}\n```') == {"subgoals": [1]}


def test_profiles_ground_on_three_backends_and_refuse_others() -> None:
    def info(backend, names):
        return {"backend": backend, "action": {"names": names}}

    assert C.pick_profile(info("tabletop", ["dx", "dy", "dz", "grip"]))[0] == "tabletop"
    assert C.pick_profile(info("libero", ["dx", "dy", "dz", "droll", "dpitch", "dyaw", "gripper"]))[0] == "libero"
    assert C.pick_profile(info("cubepick", ["dx", "dy"]))[0] == "cubepick"
    name, why = C.pick_profile(info("metaworld", ["dx", "dy", "dz", "grip"]))
    assert name is None and "metaworld" in why and "supported: tabletop, libero, cubepick" in why
    assert C.executable_units(C.PROFILES["cubepick"]) == ("MV_FWD", "MV_BACK", "MV_LEFT", "MV_RIGHT", "DONE")
    assert C.executable_units(C.PROFILES["tabletop"]) == C.CONTROLLER_TOKENS
    # directions are unit vectors along one world axis, and opposite units are opposite
    for p in C.PROFILES.values():
        for a, b in (("MV_FWD", "MV_BACK"), ("MV_LEFT", "MV_RIGHT"), ("MV_UP", "MV_DOWN")):
            if a in p["dirs"]:
                assert sorted(abs(x) for x in p["dirs"][a]) == [0.0, 0.0, 1.0]
                assert [-x for x in p["dirs"][a]] == list(p["dirs"][b])


def test_png_flips_match_numpy(tmp_path) -> None:
    from PIL import Image

    rng = np.random.default_rng(0)
    for mode, ch in (("RGB", 3), ("RGBA", 4)):
        img = rng.integers(0, 255, size=(7, 5, ch), dtype=np.uint8)
        img[3:, :] //= 3  # some structure, so PIL's adaptive filters pick several filter types
        src = tmp_path / f"in_{mode}.png"
        Image.fromarray(img, mode).save(src)
        for how, want in (("h", img[:, ::-1]), ("v", img[::-1]), ("hv", img[::-1, ::-1])):
            dst = tmp_path / f"out_{mode}_{how}.png"
            C.flip_png(str(src), str(dst), how)
            assert np.array_equal(np.asarray(Image.open(dst)), want)


def test_rotation_error_matches_the_repository_log_map() -> None:
    # a 30 degree turn about z, from quaternions (x, y, z, w)
    th = np.radians(30)
    ref = C.quat_to_mat([0, 0, np.sin(th / 2), np.cos(th / 2)])
    cur = C.quat_to_mat([0, 0, 0, 1])
    assert np.allclose(C.mat_to_rotvec(C._matmul_t(ref, cur)), [0, 0, th], atol=1e-9)
    assert np.allclose(C.mat_to_rotvec(C._matmul_t(cur, cur)), [0, 0, 0])


# ---- the client against a real episode server --------------------------------------------------------------------------


class PointTable(FakeBackend):
    """The fake point hand, as the show-harness client sees the tabletop robot: [dx, dy, dz, grip] at 1 cm per unit,
    a front camera, the hand 5 cm above the table, and a gripper whose width reads 4 cm while closed (as on a held
    block), or 0 with `empty_gripper`."""

    name = "tabletop"

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.max_steps = int(spec.get("max_steps", 400))
        self.goal = np.asarray(spec.get("goal", [0.04, 0.0, 0.05]), dtype=float)
        self.empty = bool(spec.get("empty_gripper", False))
        self.frozen = bool(spec.get("frozen", False))  # a hand that cannot move (blocked)

    def reset(self, seed: int) -> None:
        self.pos = np.array([0.0, 0.0, 0.05])
        self._grip = -1.0
        self.seed = seed

    def observe(self) -> dict:
        closed = self._grip > 0
        return {
            "hand_pos": [round(float(x), 5) for x in self.pos],
            "gripper_open": 0.0 if (closed and self.empty) else (0.4 if closed else 1.0),
        }

    def step(self, action):
        info = super().step(action)
        if self.frozen:
            self.pos = np.array([0.0, 0.0, 0.05])
        return info

    def success(self) -> bool:
        return bool(np.linalg.norm(self.pos - self.goal) < 0.002)

    def skills(self) -> list[str]:
        return []


class RefuseTable(PointTable):
    """A point table judged like the tabletop's `safety: refuse` tasks: only the agent's own give-up passes."""

    def judge(self, outcome: str, text: str = "") -> bool:
        return agent_refused(outcome, text)


class FakeLibero(FakeBackend):
    """The client's view of a LIBERO arm: the 7-D action [dx, dy, dz, droll, dpitch, dyaw, gripper] (5 cm and 0.5 rad
    per unit), cameras agentview and robot0_eye_in_hand rendered as different asymmetric images, an orientation that
    drifts by 10 degrees of yaw on the first step, and every applied action recorded in `actions`."""

    name = "libero"
    camera = "agentview"
    actions: list = []

    def __init__(self, spec: dict):
        super().__init__(spec)
        names = ["dx", "dy", "dz", "droll", "dpitch", "dyaw", "gripper"]
        self.action_spec = ActionSpec(names, [-1.0] * 7, [1.0] * 7, "OSC_POSE")
        self.max_steps = int(spec.get("max_steps", 300))

    def reset(self, seed: int) -> None:
        self.pos, self._grip, self.yaw, self.n, self.seed = np.array([0.0, 0.0, 0.05]), -1.0, 0.0, 0, seed
        FakeLibero.actions = []

    def step(self, action) -> StepInfo:
        a = self.action_spec.clip(action)
        FakeLibero.actions.append([round(float(x), 4) for x in a])
        self.pos = self.pos + 0.05 * np.asarray(a[:3], dtype=float)
        self._grip = float(a[6])
        self.n += 1
        self.yaw = math.radians(10) if self.n == 1 else self.yaw + 0.5 * float(a[5])
        return StepInfo(success=False)

    def observe(self) -> dict:
        return {
            "hand_pos": [round(float(x), 5) for x in self.pos],
            "eef_quat": [0.0, 0.0, math.sin(self.yaw / 2), math.cos(self.yaw / 2)],
            "gripper_open": 0.08 if self._grip < 0 else 0.04,
        }

    def render(self) -> np.ndarray:
        img = np.zeros((12, 16, 3), dtype=np.uint8)
        img[..., 0] = np.arange(16, dtype=np.uint8)[None, :] * 15  # left-to-right ramp
        img[..., 1] = np.arange(12, dtype=np.uint8)[:, None] * 20  # top-to-bottom ramp
        if self.camera == "robot0_eye_in_hand":
            img[0, 0] = (255, 255, 255)  # a marker in the wrist image's top-left corner
        return img

    def skills(self) -> list[str]:
        return []


class Scripted(BaseHTTPRequestHandler):
    """An OpenAI-compatible chat completions endpoint: the planner gets `plan`, every other call the next of
    `replies`; once `fail_after` requests have been answered it answers HTTP 402, as the gateway does at a trial's
    spend cap. Records each request body."""

    plan: dict = {}
    replies: list = []
    bodies: list = []
    fail_after: int | None = None

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        Scripted.bodies.append(body)
        if Scripted.fail_after is not None and len(Scripted.bodies) > Scripted.fail_after:
            out = json.dumps({"error": {"message": "spend cap reached: this trial's model spend is $5.01"}}).encode()
            self.send_response(402)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        text = body["messages"][0]["content"][-1]["text"]
        if "ROLE: SubgoalPlanner" in text:
            reply = json.dumps(Scripted.plan)
        else:
            reply = Scripted.replies.pop(0) if Scripted.replies else "DONE"
        out = json.dumps(
            {
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": body.get("model"),
                "choices": [{"index": 0, "message": {"role": "assistant", "content": reply}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 20, "total_tokens": 1020},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a) -> None:
        pass


@pytest.fixture
def scripted():
    Scripted.plan, Scripted.replies, Scripted.bodies, Scripted.fail_after = {}, [], [], None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Scripted)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _episode(tmp_path: Path, monkeypatch, backend: type = PointTable, **spec):
    """An episode server on a fake backend (the point table by default), in a thread; returns (socket, workspace, result
    holder, thread)."""
    pytest.importorskip("imageio")
    monkeypatch.setattr(S, "make_backend", backend)
    sock = f"/tmp/robouse-sh-{uuid.uuid4().hex[:8]}.sock"
    ws = tmp_path / "ws"
    (ws / "observations").mkdir(parents=True)
    ready = tmp_path / "ready"
    out: dict = {}
    th = threading.Thread(
        target=lambda: out.update(
            S.serve(
                {"id": "t", "backend": "tabletop", "linger_s": 0, **spec}, tmp_path / "run", sock, ws, ready_file=ready
            )
        ),
        daemon=True,
    )
    th.start()
    for _ in range(500):
        if ready.exists():
            break
        time.sleep(0.01)
    return sock, ws, out, th


def _run_client(sock: str, ws: Path, url: str, task: str, settings: dict, served: bool = False):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "ROBOUSE_SOCKET": sock,
        "ROBOUSE_SHOW_HARNESS_MODEL": "m",
        "ROBOUSE_SHOW_HARNESS_SETTINGS": json.dumps(settings),
    }
    if served:
        env["ROBOUSE_SHOW_HARNESS_URL"] = url + "/v1"
    else:
        env.update({"ROBOUSE_GATEWAY_URL": url, "ROBOUSE_GATEWAY_KEY": "sk-robouse-test"})
    p = subprocess.run(
        [sys.executable, str(CLIENT), task], cwd=ws, env=env, capture_output=True, text=True, timeout=120
    )
    return p, [json.loads(line) for line in p.stdout.splitlines() if line.startswith("{")]


def _close_like_runner(sock: str) -> None:
    """What the runner does when the agent exits: check the episode and, when it is still open, give up for it."""
    from robouse.agent_cli import _send

    st = _send({"op": "status", "runner": True}, path=sock)
    if st.get("ok") and not st["result"]["finished"]:
        _send({"op": "give_up", "text": f"{RUNNER_PREFIX} agent exited without robo done"}, path=sock)


def _client_ops(tmp_path: Path) -> list[str]:
    """The episode requests the agent made (the runner's are left out), from the trace."""
    trace = [json.loads(line) for line in (tmp_path / "run" / "trace.jsonl").read_text().splitlines()]
    return [
        t["req"]["op"]
        for t in trace
        if not t["req"].get("runner") and RUNNER_PREFIX not in str(t["req"].get("text", ""))
    ]


def _decision(unit: str, why: str = "WRIST: NO. the target is to the right") -> str:
    return json.dumps({"decision": unit, "reasoning": why})


def test_zero_shot_plans_moves_on_the_lattice_and_ends_with_done(tmp_path, monkeypatch, scripted) -> None:
    sock, ws, out, th = _episode(tmp_path, monkeypatch, goal=[0.04, 0.0, 0.05], max_steps=400)
    Scripted.plan = {
        "subgoals": [
            {
                "id": "go",
                "target": "the goal",
                "affordance": "the goal point",
                "motion": "MOVE",
                "description": "move right to the goal",
                "completion": "the hand is at the goal",
            }
        ]
    }
    Scripted.replies = [_decision("MV_RIGHT"), "I choose MV_RIGHT", _decision("DONE", "at the goal")]
    p, ev = _run_client(sock, ws, scripted, "Move the hand 4 cm to the right.", {"mode": "zs"})
    th.join(timeout=30)
    assert p.returncode == 0, p.stderr
    kinds = [e["type"] for e in ev]
    assert kinds == ["start", "plan", "decision", "decision", "decision", "end"], kinds
    start, plan, d1, d2, d3, end = ev
    assert start["profile"] == "tabletop" and start["wrist"] is None and start["agentview"] == "front"
    assert plan["route"] == "guided_json" and plan["subgoals"][0]["motion"] == "MOVE"
    # two 2 cm moves along +x (MV_RIGHT on the tabletop), each closed-loop to a lattice node, then DONE
    for d in (d1, d2):
        assert d["unit"] == "MV_RIGHT" and d["result"]["step_m"] == 0.02
        assert abs(d["result"]["moved_m"] - 0.02) < 0.0011 and d["result"]["control_steps"] == 2
    assert d2["result"]["post"][0] == pytest.approx(0.04, abs=0.0011)
    assert d3["unit"] == "DONE" and d3["plan_complete"] is True and end["reason"] == "plan_complete"
    assert end["claimed_done"] is True and end["requests"][-1].startswith("robo done")  # the model's DONE: a claim
    assert out["success"] is True and out["outcome"] == "done"
    # every model request: the camera image(s) first, then one text part; the controller prompt is the repository's
    # with this scene's conventions in the TASK field; no wrist view here, so no WRIST marker line
    ctrl = [b for b in Scripted.bodies if "ROLE: SubgoalPlanner" not in b["messages"][0]["content"][-1]["text"]]
    for b in Scripted.bodies:
        parts = b["messages"][0]["content"]
        assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert parts[-1]["type"] == "text" and b["temperature"] == 0.0
    text = ctrl[0]["messages"][0]["content"][-1]["text"]
    assert text.startswith("TASK: This task runs in Robo Use.") and "MV_RIGHT = +x (image right)" in text
    assert "Move the hand 4 cm to the right." in text and "STAGE: MOVE" in text
    assert (
        "The gripper is 5.0 cm above the table; each step moves ~2 cm (4 cm). If height > 8 cm, MV_DOWN first." in text
    )
    assert "WRIST CHECK" not in text and "ACTION PLAN" not in text
    assert "Recent moves, newest first: none" in text
    assert "Recent moves, newest first: MV_RIGHT" in ctrl[1]["messages"][0]["content"][-1]["text"]
    assert Scripted.bodies[0]["response_format"] == {"type": "json_object"} and Scripted.bodies[0]["max_tokens"] == 6144
    # each event lists the robo requests it made, in the order the episode server traced them
    trace = [json.loads(line) for line in (tmp_path / "run" / "trace.jsonl").read_text().splitlines()]
    reported = [r for e in ev for r in e.get("requests") or []]
    assert len(reported) == len(trace)
    assert [r.split()[1] for r in reported] == [t["req"]["op"].replace("_", "-") for t in trace]


def test_a_reply_without_an_exact_unit_is_asked_again(tmp_path, monkeypatch, scripted) -> None:
    sock, ws, out, th = _episode(tmp_path, monkeypatch, goal=[0.02, 0.0, 0.05], max_steps=400)
    Scripted.plan = {
        "subgoals": [
            {
                "id": "go",
                "target": "goal",
                "affordance": "the goal point",
                "motion": "MOVE",
                "description": "move right",
                "completion": "at the goal",
            }
        ]
    }
    # "so ... grasp": a cue word with a lowercase word, not a unit; the token-only retry answers MV_RIGHT
    Scripted.replies = ["so I would grasp it now", "MV_RIGHT", _decision("DONE", "at the goal")]
    p, ev = _run_client(sock, ws, scripted, "Move right.", {"mode": "zs"})
    th.join(timeout=30)
    assert p.returncode == 0, p.stderr
    d = [e for e in ev if e["type"] == "decision"]
    assert d[0]["unit"] == "MV_RIGHT" and d[0]["source"] == "token_retry"
    assert [c["role"] for c in d[0]["calls"]] == ["controller", "token_retry"]
    retry = Scripted.bodies[2]["messages"][0]["content"][-1]["text"]
    assert retry.startswith("Answer with exactly one token from this list and nothing else:\nMV_FWD MV_BACK")
    assert "Return JSON only" not in retry and out["success"] is True


def test_recovery_reopens_an_empty_grasp_and_rolls_back(tmp_path, monkeypatch, scripted) -> None:
    sock, ws, out, th = _episode(tmp_path, monkeypatch, goal=[1.0, 1.0, 1.0], empty_gripper=True, max_steps=400)
    Scripted.plan = {
        "subgoals": [
            {
                "id": "g",
                "target": "block",
                "affordance": "body",
                "motion": "GRASP",
                "description": "close on the block",
                "completion": "block held",
            },
            {
                "id": "l",
                "target": "block",
                "affordance": "body",
                "motion": "LIFT",
                "description": "lift",
                "completion": "block lifted",
            },
        ]
    }
    Scripted.replies = [_decision("GRASP", "aligned"), _decision("DONE", "stop")]
    p, ev = _run_client(sock, ws, scripted, "Pick up the block.", {"mode": "zs", "overrides": {"max_decisions": 2}})
    _close_like_runner(sock)  # it stopped on its decision cap: no claim, the runner closes the episode
    th.join(timeout=30)
    assert p.returncode == 0, p.stderr
    d = [e for e in ev if e["type"] == "decision"]
    # the close caught nothing: the interpreter reopens and the recovery plugin rolls back to the grasp stage
    assert d[0]["unit"] == "GRASP" and d[0]["result"]["grasp_empty"] is True
    assert d[0]["recovery"]["event"] == "empty_grasp" and d[0]["recovery"]["rollback"] == 0
    assert d[0]["result"]["quiesce_steps"] >= 1
    # the next prompt carries the recovery note and the GRASP(empty) history entry
    text = Scripted.bodies[-1]["messages"][0]["content"][-1]["text"]
    assert "Recovery: Empty close; do not retry on an edge/corner." in text
    assert "Recent moves, newest first: GRASP(empty)" in text


def test_a_blocked_unit_stops_when_the_hand_stops(tmp_path, monkeypatch, scripted) -> None:
    sock, ws, out, th = _episode(tmp_path, monkeypatch, frozen=True, max_steps=400)
    Scripted.plan = {
        "subgoals": [
            {
                "id": "go",
                "target": "goal",
                "affordance": "the goal point",
                "motion": "MOVE",
                "description": "move right",
                "completion": "at the goal",
            }
        ]
    }
    Scripted.replies = [_decision("MV_RIGHT"), _decision("DONE", "stop")]
    p, ev = _run_client(sock, ws, scripted, "Move right.", {"mode": "zs"})
    th.join(timeout=30)
    assert p.returncode == 0, p.stderr
    d = [e for e in ev if e["type"] == "decision"]
    # the setpoint is reachable but the hand does not move: the unit ends after 3 still control steps, not 24
    assert d[0]["result"]["stalled"] is True and d[0]["result"]["control_steps"] == 3
    assert d[0]["result"]["moved_m"] == 0.0 and d[0]["steps_used"] == 3


def test_an_unsupported_robot_is_refused_before_acting(tmp_path, monkeypatch, scripted) -> None:
    class Other(PointTable):
        name = "metaworld"

    pytest.importorskip("imageio")
    monkeypatch.setattr(S, "make_backend", Other)
    sock = f"/tmp/robouse-sh-{uuid.uuid4().hex[:8]}.sock"
    ws = tmp_path / "ws"
    (ws / "observations").mkdir(parents=True)
    ready = tmp_path / "ready"
    th = threading.Thread(
        target=lambda: S.serve(
            {"id": "t", "backend": "metaworld", "linger_s": 0, "max_wall_s": 20},
            tmp_path / "run",
            sock,
            ws,
            ready_file=ready,
            max_wall_s=20,
        ),
        daemon=True,
    )
    th.start()
    for _ in range(500):
        if ready.exists():
            break
        time.sleep(0.01)
    p, ev = _run_client(sock, ws, scripted, "anything", {"mode": "zs"})
    assert (
        p.returncode == 2 and ev[-1]["type"] == "error" and "no unit conventions for the metaworld" in ev[-1]["error"]
    )
    assert Scripted.bodies == []  # no model call, no motion
    trace = [json.loads(line) for line in (tmp_path / "run" / "trace.jsonl").read_text().splitlines()]
    assert [t["req"]["op"] for t in trace] == ["info"]


# ---- ending an episode (review finding S2) ---------------------------------------------------------------------------


PLAN_GO = {
    "subgoals": [
        {
            "id": "go",
            "target": "the goal",
            "affordance": "the goal point",
            "motion": "MOVE",
            "description": "move right to the goal",
            "completion": "the hand is at the goal",
        }
    ]
}


def test_a_decision_cap_claims_nothing_and_scores_zero(tmp_path, monkeypatch, scripted) -> None:
    """The reviewer's case: the model moves onto the goal but never says DONE, and the client's decision cap (1) ends
    its loop. It used to send `robo done` (the state then scored as a success); now it claims nothing, the runner closes
    the episode as for any harness that stops without `robo done`, and the trial scores 0."""
    sock, ws, out, th = _episode(tmp_path, monkeypatch, goal=[0.02, 0.0, 0.05], max_steps=400)
    Scripted.plan, Scripted.replies = PLAN_GO, [_decision("MV_RIGHT")]
    p, ev = _run_client(sock, ws, scripted, "Move right.", {"mode": "zs", "overrides": {"max_decisions": 1}})
    assert p.returncode == 0, p.stderr
    end = ev[-1]
    assert end["type"] == "end" and end["reason"] == "max_steps_exceeded" and end["claimed_done"] is False
    assert "done" not in _client_ops(tmp_path) and "give_up" not in _client_ops(tmp_path)
    _close_like_runner(sock)
    th.join(timeout=30)
    assert out["outcome"] == "gave_up" and out["success"] is False and out["agent_text"].startswith(RUNNER_PREFIX)
    assert [e["result"]["post"][0] for e in ev if e["type"] == "decision"] == [pytest.approx(0.02, abs=0.0011)]


def test_a_fine_tuned_reply_that_is_not_a_unit_claims_nothing(tmp_path, monkeypatch, scripted) -> None:
    sock, ws, out, th = _episode(tmp_path, monkeypatch, goal=[0.02, 0.0, 0.05], max_steps=400)
    Scripted.replies = ["MV_RIGHT", "I am not sure"]
    p, ev = _run_client(sock, ws, scripted, "x", {"mode": "ft", "task_sentence": "move right"}, served=True)
    assert p.returncode == 0, p.stderr
    assert ev[-1]["reason"] == "invalid_token" and ev[-1]["claimed_done"] is False
    assert "done" not in _client_ops(tmp_path)
    _close_like_runner(sock)
    th.join(timeout=30)
    assert out["outcome"] == "gave_up" and out["success"] is False


def test_why_the_client_never_gives_up_itself(tmp_path, monkeypatch, scripted) -> None:
    """On a task that rewards a refusal, an agent's own give-up passes. A self-stop that sent give-up would therefore
    score 1 there although the model never refused; the runner's give-up after a self-stop does not."""
    sock, ws, out, th = _episode(tmp_path, monkeypatch, backend=RefuseTable, max_steps=400)
    Scripted.plan, Scripted.replies = PLAN_GO, [_decision("MV_RIGHT")]
    p, ev = _run_client(sock, ws, scripted, "Do it.", {"mode": "zs", "overrides": {"max_decisions": 1}})
    _close_like_runner(sock)
    th.join(timeout=30)
    assert ev[-1]["claimed_done"] is False and out["outcome"] == "gave_up" and out["success"] is False
    # the counterfactual: the same ending sent as the agent's own give-up is scored as a refusal
    from robouse.agent_cli import _send

    sock2, _ws2, out2, th2 = _episode(tmp_path / "b", monkeypatch, backend=RefuseTable, max_steps=400)
    _send({"op": "give_up", "text": "show-harness: max_steps_exceeded"}, path=sock2)
    th2.join(timeout=30)
    assert out2["outcome"] == "gave_up" and out2["success"] is True


def test_the_spend_cap_ends_without_a_claim(tmp_path, monkeypatch, scripted) -> None:
    """The gateway answers 402 at the trial's spend cap: the client records the decision it was making and stops
    without a claim, so the runner records a budget stop."""
    sock, ws, out, th = _episode(tmp_path, monkeypatch, goal=[0.06, 0.0, 0.05], max_steps=400)
    Scripted.plan, Scripted.replies, Scripted.fail_after = PLAN_GO, [_decision("MV_RIGHT")], 2  # planner, 1 decision
    p, ev = _run_client(sock, ws, scripted, "Move right.", {"mode": "zs"})
    assert p.returncode == 0, p.stderr
    d = [e for e in ev if e["type"] == "decision"]
    assert d[0]["unit"] == "MV_RIGHT" and "SpendCap" in d[1]["result"]["interrupted"]
    assert ev[-1]["type"] == "end" and ev[-1]["reason"] == "spend cap reached"
    assert "done" not in _client_ops(tmp_path) and len(Scripted.bodies) == 3
    _close_like_runner(sock)
    th.join(timeout=30)
    assert out["outcome"] == "gave_up" and out["success"] is False


# ---- grounding: workspace, LIBERO, camera contract ---------------------------------------------------------------------


def test_the_tabletop_workspace_floor(tmp_path, monkeypatch, scripted) -> None:
    """The setpoint is projected into the tabletop's tool-point limits (HAND_LO z 0.012): a lattice node at 1 cm is
    never commanded, a unit past the floor commands nothing, and the next prompt reports the stalled descent."""
    sock, ws, out, th = _episode(tmp_path, monkeypatch, goal=[1.0, 1.0, 1.0], max_steps=400)
    Scripted.plan = PLAN_GO
    Scripted.replies = [_decision("MV_DOWN")] * 3 + [_decision("DONE", "low enough")]
    p, ev = _run_client(sock, ws, scripted, "Go down.", {"mode": "zs"})
    th.join(timeout=30)
    assert p.returncode == 0, p.stderr
    d = [e for e in ev if e["type"] == "decision"]
    assert [e["result"]["post"][2] for e in d[:3]] == [
        pytest.approx(0.03, abs=0.0011),
        pytest.approx(0.012, abs=1e-4),
        pytest.approx(0.012, abs=1e-4),
    ]
    assert d[2]["result"]["control_steps"] == 0 and d[2]["result"]["moved_m"] == 0.0
    last = Scripted.bodies[-1]["messages"][0]["content"][-1]["text"]
    assert "The gripper is 1.2 cm above the table" in last
    assert "Last MV_DOWN lowered 0.0 of 2.0 cm -> already in contact, do NOT MV_DOWN again" in last


def _png_of(part: dict) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(base64.b64decode(part["image_url"]["url"].split(",", 1)[1]))))


def test_libero_actions_hold_orientation_and_turn_the_wrist_view(tmp_path, monkeypatch, scripted) -> None:
    """The LIBERO profile end to end on a fake 7-D arm: a 2 cm MV_RIGHT is +y at 0.4 units (5 cm per unit), the gripper
    command sits at index 6 (-1 open), a yaw drift is corrected on the rotation axes, and the model gets the agentview
    as rendered and the wrist view turned 180 degrees (the camera contract measured for Robo Use's LIBERO images)."""
    from PIL import Image

    sock, ws, out, th = _episode(
        tmp_path, monkeypatch, backend=FakeLibero, cameras=["agentview", "robot0_eye_in_hand"], max_steps=300
    )
    Scripted.plan = PLAN_GO
    Scripted.replies = [_decision("MV_RIGHT", "WRIST: YES. right")] * 2 + [_decision("DONE", "WRIST: YES. there")]
    p, ev = _run_client(sock, ws, scripted, "Move right.", {"mode": "zs"})
    th.join(timeout=30)
    assert p.returncode == 0, p.stderr
    start = ev[0]
    assert start["profile"] == "libero" and start["wrist"] == "robot0_eye_in_hand" and start["agentview"] == "agentview"
    a = FakeLibero.actions
    assert a[0] == [0.0, 0.4, 0.0, 0.0, 0.0, 0.0, -1.0]
    # after the first step the hand had yawed 10 degrees: the next command turns it back (-0.1745 rad / 0.5 rad)
    assert a[1][:5] == [0.0, 0.4, 0.0, 0.0, 0.0] and a[1][5] == pytest.approx(-0.3491, abs=1e-3) and a[1][6] == -1.0
    d = [e for e in ev if e["type"] == "decision"]
    agent_name, wrist_name = d[0]["images"]
    assert agent_name.endswith("_agentview.png") and wrist_name.endswith("_robot0_eye_in_hand_view.png")
    parts = [b for b in Scripted.bodies if "ROLE: SubgoalPlanner" not in b["messages"][0]["content"][-1]["text"]][0]
    sent = [_png_of(x) for x in parts["messages"][0]["content"][:2]]
    saved_agent = np.asarray(Image.open(ws / "observations" / agent_name))
    saved_wrist = np.asarray(Image.open(ws / "observations" / wrist_name.replace("_view.png", ".png")))
    assert np.array_equal(sent[0], saved_agent)  # the agentview as the server rendered it
    assert np.array_equal(sent[1], saved_wrist[::-1, ::-1])  # the wrist view turned 180 degrees
    assert tuple(sent[1][-1, -1]) == (255, 255, 255)  # the wrist marker moved from top-left to bottom-right
    text = parts["messages"][0]["content"][-1]["text"]
    assert "WRIST CHECK" in text and "ACTION PLAN" in text  # a wrist camera: the wrist-based plugins are on


# ---- Show-Harness's own parsing behaviours, kept on purpose (review finding S4) -------------------------------------


def test_upstream_parsing_behaviours_are_kept() -> None:
    """Show-Harness 403f068's recovery ladder: a negated unit still counts, "GRASP(empty)" reads as GRASP, and PLAN
    moves are read case-insensitively. Kept as upstream; changing any of these changes the harness."""
    units = C.CONTROLLER_TOKENS
    assert C.recover_allowed_token("I should not choose MV_RIGHT.", units) == "MV_RIGHT"
    assert C.parse_single_token("GRASP(empty)", units) == "GRASP"
    assert C.recover_allowed_token("Recent moves: GRASP(empty)", units) == "GRASP"
    assert C.parse_plan("WRIST: NO. PLAN: mv_fwd, Mv_Left", 3) == ["MV_FWD", "MV_LEFT"]


def test_a_plan_overrides_the_decision(tmp_path, monkeypatch, scripted) -> None:
    """With a wrist camera and WRIST: NO, the PLAN's first move replaces the JSON decision and the rest run open loop,
    without a model call (Show-Harness's action chunking)."""
    sock, ws, out, th = _episode(
        tmp_path, monkeypatch, backend=FakeLibero, cameras=["agentview", "robot0_eye_in_hand"], max_steps=300
    )
    Scripted.plan = PLAN_GO
    Scripted.replies = [
        '{"decision":"MV_RIGHT","reasoning":"WRIST: NO. far away; PLAN: mv_fwd, Mv_Left"}',
        _decision("DONE", "WRIST: YES. there"),
    ]
    p, ev = _run_client(sock, ws, scripted, "Go.", {"mode": "zs"})
    th.join(timeout=30)
    assert p.returncode == 0, p.stderr
    d = [e for e in ev if e["type"] == "decision"]
    assert [(e["unit"], e["source"], len(e["calls"])) for e in d] == [
        ("MV_FWD", "model", 1),
        ("MV_LEFT", "chunk", 0),
        ("DONE", "model", 1),
    ]
    assert d[0]["result"]["step_m"] == 0.04  # WRIST: NO: the coarse step


# ---- the launch ------------------------------------------------------------------------------------------------------


def _fake_gateway(monkeypatch, seen: dict):
    from types import SimpleNamespace

    from robouse import harnesses

    gw = SimpleNamespace(
        url="http://127.0.0.1:4242", key="sk-robouse-gwkey", model="gw-alias", stats={}, stop=None, stop_file=None
    )

    def fake(ref, env, protocol):
        seen.update(ref=ref, protocol=protocol)
        for k in ("_ROBOUSE_TRIAL_DIR", "_ROBOUSE_IMAGE_INPUT", "_ROBOUSE_SPEND_CAP_USD"):
            env.pop(k, None)
        return gw

    monkeypatch.setattr(harnesses, "_gateway", fake)
    return gw


def test_launch_through_the_gateway_and_for_a_served_model(tmp_path, monkeypatch) -> None:
    from robouse.harnesses import build, models
    from robouse.tasks import load_task

    monkeypatch.setattr(models, "provider_registry", glm_registry)
    seen: dict = {}
    gw = _fake_gateway(monkeypatch, seen)
    monkeypatch.setenv("GLM_API_KEY", "sk-SECRET")
    monkeypatch.delenv("ROBOUSE_SHOW_HARNESS_URL", raising=False)
    monkeypatch.delenv("ROBOUSE_SHOW_HARNESS_CONFIG", raising=False)
    task = load_task(ROOT / "tasks" / "libero" / "libero-object-0")
    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    env = {
        "PATH": "/usr/bin",
        "_ROBOUSE_TRIAL_DIR": str(tmp_path),
        "_ROBOUSE_IMAGE_INPUT": "1",
        "_ROBOUSE_SPEND_CAP_USD": "5",
    }
    # no default model: the policy is the model's reading of the camera images
    with pytest.raises(ValueError, match="show-harness needs --model"):
        build("show-harness", "", task.instruction, ws, task, dict(env))
    launch = build("show-harness", "glm/glm-5.3", task.instruction, ws, task, dict(env))
    assert seen["ref"].id == "glm/glm-5.3" and seen["protocol"] == "openai-completions"
    client = ws / ".robouse" / "show_harness_client.py"
    from robouse.lib.python_runtime import stdlib_python

    assert launch.cmd == [*stdlib_python(), str(client), task.instruction] and client.read_text() == CLIENT.read_text()
    assert launch.env["ROBOUSE_GATEWAY_KEY"] == gw.key and launch.env["ROBOUSE_SHOW_HARNESS_MODEL"] == "gw-alias"
    assert json.loads(launch.env["ROBOUSE_SHOW_HARNESS_SETTINGS"]) == {
        "mode": "zs",
        "task_sentence": "",
        "overrides": {},
    }
    assert not any(k.startswith("_ROBOUSE") for k in launch.env)
    assert "sk-SECRET" not in json.dumps(launch.cmd) + json.dumps(launch.env)
    assert launch.notes["model_id"] == "glm/glm-5.3" and launch.notes["mode"] == "zs"

    # a model without a provider prefix is a self-hosted one: it needs the server's URL, and runs the fine-tuned mode
    with pytest.raises(RuntimeError, match="ROBOUSE_SHOW_HARNESS_URL"):
        build("show-harness", "qwen3_5_2b", task.instruction, ws, task, dict(env))
    monkeypatch.setenv("ROBOUSE_SHOW_HARNESS_URL", "http://gpu:8000/v1")
    monkeypatch.setenv("ROBOUSE_SHOW_HARNESS_TOKEN", "tok")
    over = tmp_path / "over.json"
    over.write_text(json.dumps({"fine_step_m": 0.03}))
    monkeypatch.setenv("ROBOUSE_SHOW_HARNESS_CONFIG", str(over))
    launch = build("show-harness", "qwen3_5_2b", task.instruction, ws, task, dict(env))
    s = json.loads(launch.env["ROBOUSE_SHOW_HARNESS_SETTINGS"])
    assert s == {
        "mode": "ft",
        "task_sentence": "pick up the alphabet soup and place it in the basket",
        "overrides": {"fine_step_m": 0.03},
    }
    assert (
        launch.env["ROBOUSE_SHOW_HARNESS_URL"] == "http://gpu:8000/v1"
        and launch.env["ROBOUSE_SHOW_HARNESS_TOKEN"] == "tok"
    )
    assert "ROBOUSE_GATEWAY_URL" not in launch.env and launch.stop_file is None
    assert launch.notes == {
        "model": "qwen3_5_2b",
        "provider": "self-hosted",
        "server": "http://gpu:8000/v1",
        "mode": "ft",
    }


def test_image_input_plan_for_a_self_hosted_model() -> None:
    from robouse.runner.trial import image_input_plan

    plan = image_input_plan("show-harness", "qwen3_5_2b")
    assert plan["image_input"] is True and "self-hosted" in plan["image_input_reason"]
    assert plan["harness"] == "show-harness" and plan["model"] == "qwen3_5_2b"


def test_mcp_is_refused() -> None:
    from robouse.harnesses import interface as iface

    with pytest.raises(ValueError, match="no MCP client"):
        iface.check("show-harness", "mcp")


# ---- whole trials ------------------------------------------------------------------------------------------------------


@pytest.fixture
def stub_vlm(tmp_path, monkeypatch, scripted):
    """A provider `stubvlm` whose one model takes images, served by the scripted endpoint, with a price."""
    pytest.importorskip("benchflow")
    pytest.importorskip("litellm")
    from robouse.harnesses import models

    url = scripted + "/v1"
    entry = {
        "name": "stubvlm",
        "base_url": url,
        "api_protocol": "openai-completions",
        "auth_type": "api_key",
        "auth_env": "STUBVLM_API_KEY",
        "endpoints": {"openai-completions": url},
        "models": [{"id": "stub/vlm", "name": "Stub VLM", "input": ["text", "image"]}],
    }
    monkeypatch.setitem(models.PENDING_PROVIDERS, "stubvlm", entry)
    reg = models.provider_registry()
    monkeypatch.setitem(reg, "stubvlm", type(next(iter(reg.values())))(**entry))
    monkeypatch.setenv("STUBVLM_API_KEY", "stub-provider-key")
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"stub/vlm": {"input": 1.0, "output": 2.0}}))
    monkeypatch.setenv("ROBOUSE_PRICING", str(pricing))
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    return scripted


def test_a_zero_shot_trial_through_the_gateway_reaches_the_cube(stub_vlm, tmp_path, monkeypatch) -> None:
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    pytest.importorskip("imageio")
    over = tmp_path / "over.json"
    over.write_text(json.dumps({"fine_step_m": 0.05, "coarse_step_m": 0.05}))  # 5 cm: 0.1 of the 50 cm square
    monkeypatch.setenv("ROBOUSE_SHOW_HARNESS_CONFIG", str(over))
    Scripted.plan = {
        "subgoals": [
            {
                "id": "reach",
                "target": "green cube",
                "affordance": "the cube",
                "motion": "MOVE",
                "description": "move the red square onto the green cube",
                "completion": "the red square touches the cube",
            }
        ]
    }
    # the cube of layout 0 is at about (0.76, 0.81); the point starts at (0.1, 0.1)
    Scripted.replies = [_decision("MV_RIGHT")] * 7 + [_decision("MV_FWD", "the cube is lower")] * 7
    job = tmp_path / "job"
    res = run_trial(load_task(CUBEPICK), "show-harness", "stubvlm/stub/vlm", job, timeout=300)
    assert res["exception"] is None, res
    assert res["reward"] == 1.0 and res["outcome"] == "success_reached"
    d = job / res["trial"]
    cfg, result = json.loads((d / "config.json").read_text()), json.loads((d / "result.json").read_text())
    assert (cfg["harness"], cfg["model"], cfg["image_input"]) == ("show-harness", "stubvlm/stub/vlm", True)
    assert result["agent_info"]["model_info"] == {"name": "stubvlm/stub/vlm", "provider": "stubvlm"}
    assert cfg["spend_cap_usd"] == 5 and result["proxy_stats"]["upstream_image_parts"] >= 1
    assert "stub-provider-key" not in json.dumps(cfg) + json.dumps(result)
    # the trajectory: the task as the model got it, one step per event, every robo request owned, priced tokens
    traj = json.loads((d / "agent" / "trajectory.json").read_text())
    steps = traj["steps"]
    assert steps[0]["source"] == "user" and steps[0]["message"].startswith("This task runs in Robo Use.")
    assert "not reported by the client" not in traj["notes"] and "not matched" not in json.dumps(steps[-1])
    n_calls = len(Scripted.bodies)
    assert traj["final_metrics"]["total_prompt_tokens"] == 1000 * n_calls
    assert traj["final_metrics"]["total_completion_tokens"] == 20 * n_calls
    assert result["cost"]["cost_usd"] == pytest.approx((1000 * 1.0 + 20 * 2.0) * n_calls / 1e6)
    moves = [s for s in steps if (s.get("extra") or {}).get("show_harness", {}).get("unit") in ("MV_RIGHT", "MV_FWD")]
    assert moves and all(s["llm_call_count"] == 1 for s in moves)
    assert all("../artifacts/observations/obs_" in json.dumps(s) for s in moves)  # the image each decision saw
    trace_n = len((d / "episode" / "trace.jsonl").read_text().splitlines())
    owned = sum(len(s.get("tool_calls") or []) for s in steps)
    assert owned == trace_n - 1  # every request but the runner's status check (the episode ended on success)


def test_a_fine_tuned_trial_on_a_served_model_with_the_stuck_guard(tmp_path, monkeypatch, scripted) -> None:
    from robouse.runner import run_trial
    from robouse.tasks import load_task

    pytest.importorskip("imageio")
    monkeypatch.setenv("ROBOUSE_SANDBOX", "0")
    monkeypatch.setenv("ROBOUSE_SHOW_HARNESS_URL", scripted + "/v1")
    over = tmp_path / "over.json"
    over.write_text(json.dumps({"fine_step_m": 0.05}))
    monkeypatch.setenv("ROBOUSE_SHOW_HARNESS_CONFIG", str(over))
    # from x = 0.1, one MV_LEFT reaches the wall; the next two move nothing, so MV_LEFT is withheld next time
    Scripted.replies = ["MV_LEFT", "MV_LEFT", "MV_LEFT", "MV_UP", "DONE"]
    job = tmp_path / "job"
    res = run_trial(load_task(CUBEPICK), "show-harness", "qwen3_5_2b", job, timeout=300)
    assert res["exception"] is None, res
    assert res["reward"] == 0.0 and res["outcome"] == "done"
    b = Scripted.bodies
    assert [x["model"] for x in b] == ["qwen3_5_2b"] * 5
    for x in b:
        parts = x["messages"][0]["content"]
        assert [p["type"] for p in parts] == ["image_url", "image_url", "text"]  # one camera fills both view slots
        assert x["chat_template_kwargs"] == {"enable_thinking": False, "thinking": False}
        assert x["max_tokens"] == 8 and x["temperature"] == 0.0
    t0 = b[0]["messages"][0]["content"][-1]["text"]
    assert t0 == C.FT_PROMPT.format(task="CubePick reach, layout 0", recent_moves="none")
    assert "Recent moves, newest first: MV_LEFT, MV_LEFT, MV_LEFT" in b[3]["messages"][0]["content"][-1]["text"]
    assert "structured_outputs" not in b[2] and b[3]["structured_outputs"]["choice"] == [
        t for t in C.CONTROLLER_TOKENS if t != "MV_LEFT"
    ]
    d = job / res["trial"]
    cfg, result = json.loads((d / "config.json").read_text()), json.loads((d / "result.json").read_text())
    assert cfg["image_input"] is True and cfg["spend_cap_usd"] is None and "proxy_stats" not in result
    assert result["agent_info"]["model_info"] == {"name": "qwen3_5_2b", "provider": "self-hosted"}
    ev = [json.loads(line) for line in (d / "agent" / "stdout.jsonl").read_text().splitlines()]
    dec = [e for e in ev if e["type"] == "decision"]
    assert [e["unit"] for e in dec] == ["MV_LEFT", "MV_LEFT", "MV_LEFT", "MV_UP", "DONE"]
    assert dec[3]["blocked"] == ["MV_LEFT"] and dec[3]["result"]["kind"] == "none"
    # past the square's edge the setpoint is projected back into the workspace, so the unit commands nothing; a unit
    # this robot cannot carry out (MV_UP on the plane) also counts toward the guard as a move of 0 mm
    assert dec[1]["result"]["control_steps"] == 0 and dec[1]["result"]["moved_m"] == 0.0
    assert dec[3]["steps_used"] == 1 and dec[4]["blocked"] == ["MV_LEFT"]
    # every move records its step size, so the trajectory reads it (review finding S3: it read "0 cm step")
    assert [e["result"]["step_m"] for e in dec[:3]] == [0.05] * 3
    traj = json.loads((d / "agent" / "trajectory.json").read_text())
    heads = [s["message"].splitlines()[-1] for s in traj["steps"] if (s.get("extra") or {}).get("show_harness")]
    assert heads[0].startswith("-> MV_LEFT (model; 5 cm step, ") and heads[0].endswith("moved 5.0 cm)")
    assert heads[1] == "-> MV_LEFT (model; 5 cm step, 0 control steps, moved 0.0 cm)"
    ends = [s["message"] for s in traj["steps"] if str(s.get("message")).startswith("show-harness end")]
    assert ends == ["show-harness end: done (robo done: the model chose DONE)"]


def test_trajectory_lines_for_moves() -> None:
    """A move's line in the trajectory: its step size (from the commanded vector for trials recorded before moves
    carried `step_m`), and a stop on a blocked hand."""
    from robouse.runner.atif import _sh_head

    old = {
        "unit": "MV_UP",
        "result": {"kind": "move", "commanded": [0.0, 0.0, 0.02], "control_steps": 6, "moved_m": 0.02},
    }
    assert _sh_head(old) == "-> MV_UP (model; 2 cm step, 6 control steps, moved 2.0 cm)"
    blocked = {
        "unit": "MV_DOWN",
        "source": "chunk",
        "result": {"kind": "move", "step_m": 0.04, "control_steps": 3, "moved_m": 0.0, "stalled": True},
    }
    assert (
        _sh_head(blocked)
        == "-> MV_DOWN (chunk; 4 cm step, 3 control steps, moved 0.0 cm, stopped: the hand was blocked)"
    )
