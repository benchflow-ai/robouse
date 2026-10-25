"""The `jev` harness (harnesses/jev/): the nav profile's state, questions and commands; the client against a real nav
episode server and a local stand-in for TypeSafe's System One endpoint (tests/jev_stand_in.py, not Jev); its retries
and its failures; the launch and where TypeSafe's key may go; and a whole trial with its trajectory and cost. No test
reaches TypeSafe."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import jev_stand_in as stand_in
import pytest

from robouse.core import session as S
from robouse.core.protocol import RUNNER_PREFIX
from robouse.harnesses import jev as J
from robouse.tasks import load_task

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "src" / "robouse" / "harnesses" / "jev" / "client.py"
NAV = ROOT / "tasks" / "nav"
EASY = NAV / "nav-h01-oven"  # the stand-in's literal reading of the criteria reaches the oven in about 20 decisions
KEY = "ts-test-not-a-real-key"

_spec = importlib.util.spec_from_file_location("jev_client", CLIENT)
C = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(C)


def _nav_episode(tmp_path: Path, task: Path = EASY) -> S.Episode:
    return S.Episode(load_task(task).spec, tmp_path / "probe")


# ---- the nav profile ----------------------------------------------------------------------------------------------------


def test_bearing_words_follow_the_backend_and_say_which_way_round() -> None:
    from robouse.backends.nav.backend import bearing_word as backend_word

    for deg in (0, 15, 22, 23, 44, 46, 90, 120, -30, -100, -150):
        assert C.bearing_word(deg) == backend_word(deg), deg
    # behind says on which hand, so it asks for one turn, as in the study's state
    assert backend_word(170) == backend_word(-170) == "behind"
    assert (C.bearing_word(170), C.bearing_word(-170)) == ("behind_left", "behind_right")
    assert C.bearing_word(370) == "ahead" and C.wrap(-200) == 160.0


def test_the_state_is_the_observation_with_the_arithmetic_done(tmp_path) -> None:
    """From a real nav observation: the target block (the observation's `goal`), the way past the wall with its own
    bearing, free space as observed, the last command in words; no furniture list, no world coordinates."""
    ep = _nav_episode(tmp_path, NAV / "nav-h00-fridge")  # the fridge is behind a wall, to the right
    observed = ep.observe(False)["state"]
    mem = C.NavMemory()
    state = C.nav_state(observed, "Find the fridge", mem)
    assert list(state) == ["task", "goal", "target", "way_to_target", "free_space", "robot"]
    assert state["goal"] == "Find the fridge" and state["task"] == C.NAV_TASK
    g = observed["goal"]
    assert state["target"] == {**g, "bearing": C.bearing_word(g["bearing_deg"])}
    way = state["way_to_target"]
    assert (
        way["blocked"] is True and way["blocked_by"] == "wall" and observed["way_to_target"]["open_sides"] == ["left"]
    )
    # the backend's "left" way past is 45 degrees counter-clockwise of the line to the target
    assert way["open_sides"] == [
        {"side": "left", "bearing": C.bearing_word(g["bearing_deg"] + 45), "bearing_deg": C.wrap(g["bearing_deg"] + 45)}
    ]
    assert state["free_space"] == observed["free_space"]
    assert state["robot"]["last_drive"] == {"x": "none", "y": "none", "yaw": "none"}
    assert {k: v for k, v in state["robot"].items() if k != "last_drive"} == {
        k: v for k, v in observed["robot"].items() if k != "last_drive"
    }
    text = json.dumps(state)
    assert "objects" not in state and '"pos"' not in text and "spawn" not in text
    assert observed["way_to_target"]["open_sides"] == ["left"]  # the observation itself is left as it was


def test_going_around_keeps_the_side_the_robot_began_to_go_round() -> None:
    mem = C.NavMemory()
    blocked = {
        "blocked": True,
        "open_sides": [{"side": "left", "bearing_deg": 40.0}, {"side": "right", "bearing_deg": -50.0}],
    }
    assert mem.going_around(dict(blocked)) is None  # nothing decided yet
    mem.last_drive = {"x": "none", "y": "none", "yaw": "turn_right"}  # it turned toward the right way past
    assert mem.going_around(dict(blocked)) == "right"
    mem.last_drive = {"x": "none", "y": "none", "yaw": "turn_left"}  # kept, whatever the next decisions do
    assert mem.going_around(dict(blocked)) == "right"
    only_left = {"blocked": True, "open_sides": [{"side": "left", "bearing_deg": 10.0}]}
    assert mem.going_around(only_left) is None  # the right way past closed: forgotten
    mem.last_drive = {"x": "forward", "y": "none", "yaw": "none"}  # drove at the left way past while it was ahead
    assert mem.going_around(dict(only_left)) == "left"
    clear = {"blocked": False}
    for _ in range(6):  # 3 s clear: still kept
        mem.going_around(clear)
    assert mem.side == "left"
    mem.going_around(clear)
    assert mem.side is None


def test_the_questions_are_the_drive_skill_s_choices_and_the_task(tmp_path) -> None:
    info = _nav_episode(tmp_path).info()
    assert C.nav_check(info) is None
    drive = next(s for s in info["embodiment"]["skills"] if s["name"] == "drive")
    choices = {a["name"]: tuple(a["choices"]) for a in drive["args"] if a.get("type") == "enum"}
    q = C.nav_questions()
    assert list(q) == ["drive.x", "drive.y", "drive.yaw", "task"]
    for axis, opts in choices.items():
        assert q[f"drive.{axis}"]["type"] == "choice" and tuple(q[f"drive.{axis}"]["criteria"]) == opts
    assert list(q["task"]["criteria"]) == ["continue", "finished"]  # Jev leans to the first option: not finishing
    for question in q.values():
        assert question["instructions"]["question"].endswith("?")
        for opt in question["criteria"].values():
            assert set(opt) == {"what", "not_for", "examples"} and opt["examples"]
    assert json.loads(json.dumps(q)) == q  # plain JSON, as the request carries it
    # other robots, and a nav task without its skills, are refused before anything moves
    assert "tabletop" in C.nav_check({**info, "backend": "tabletop"})
    assert "drive" in C.nav_check({**info, "skills": []})


def test_commands_from_the_answers() -> None:
    def answers(x, y, yaw, task, p=0.93):
        a = {f"drive.{k}": {"type": "choice", "choice": v} for k, v in (("x", x), ("y", y), ("yaw", yaw))}
        a["task"] = {"type": "choice", "choice": task, "probabilities": {task: p}}
        return a

    assert C.nav_command(answers("forward", "none", "turn_left", "continue")) == {
        "op": "skill",
        "name": "drive",
        "args": ["forward", "none", "turn_left", "0.5"],
    }
    assert C.nav_command(answers("forward", "none", "none", "finished")) == {
        "op": "done",
        "text": "jev: the task is finished (p 0.93)",
    }


def test_malformed_answers_are_refused() -> None:
    q = C.nav_questions()
    good = {
        qid: {"type": "choice", "choice": next(iter(x["criteria"])), "confidence": 1.0, "probabilities": {}}
        for qid, x in q.items()
    }
    assert C.check_answers({"answers": good}, q) == good
    for bad in (
        {},
        {"answers": {k: v for k, v in good.items() if k != "task"}},
        {"answers": {**good, "drive.x": {**good["drive.x"], "choice": "sideways"}}},
        {"answers": {**good, "drive.y": {"type": "noul", "noul": 0.5}}},
        {"answers": {**good, "drive.yaw": {"type": "choice", "choice": "none"}}},  # no probabilities
        {"answers": {**good, "task": {**good["task"], "probabilities": {"continue": "0.9"}}}},
        {"answers": {**good, "task": {**good["task"], "choice": ["continue"]}}},
        {"answers": {**good, "task": {**good["task"], "confidence": "high"}}},
    ):
        with pytest.raises(C.ApiError):
            C.check_answers(bad, q)


def test_the_request_carries_finite_numbers_only() -> None:
    """TypeSafe refuses NaN and infinity (HTTP 400): they go as null."""
    state = {"a": float("nan"), "b": [1.5, float("inf")], "c": {"d": -float("inf"), "e": "x"}, "f": None}
    assert C.finite(state) == {"a": None, "b": [1.5, None], "c": {"d": None, "e": "x"}, "f": None}
    json.dumps(C.finite(state), allow_nan=False)


def test_cost_is_priced_by_the_version_that_answered() -> None:
    prices = {"jev-1.13.0": {"input": 0.042, "output": 0.0}, "jev-latest": {"input": 1.0, "output": 1.0}}
    usage = {"input_tokens": 2000, "output_tokens": 30}
    assert C.usage_cost(usage, prices, "jev-1.13.0", "jev-latest") == pytest.approx(2000 * 0.042 / 1e6)
    assert C.usage_cost(usage, prices, "jev-9.0.0", "jev-latest") == pytest.approx(2030 / 1e6)
    assert C.usage_cost(usage, {}, "jev-1.13.0") is None


# ---- the client against a real nav episode and the stand-in ------------------------------------------------------------


@pytest.fixture
def typesafe():
    """The stand-in endpoint in a thread; yields its base URL. Requests are recorded in stand_in.StandIn.requests."""
    stand_in.StandIn.requests, stand_in.StandIn.fail, stand_in.StandIn.log_path = [], [], None
    srv = stand_in.serve()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _serve(tmp_path: Path, task: Path = EASY):
    sock = f"/tmp/robouse-jev-{uuid.uuid4().hex[:8]}.sock"
    ws = tmp_path / "ws"
    (ws / "observations").mkdir(parents=True)
    ready = tmp_path / "ready"
    out: dict = {}
    spec = {**load_task(task).spec, "linger_s": 0}
    th = threading.Thread(
        target=lambda: out.update(S.serve(spec, tmp_path / "run", sock, ws, ready_file=ready)), daemon=True
    )
    th.start()
    for _ in range(500):
        if ready.exists():
            break
        time.sleep(0.01)
    return sock, ws, out, th


def _client(sock: str, ws: Path, url: str, key: str = KEY, prices: dict | None = None):
    env = {
        "ROBOUSE_SOCKET": sock,
        "TYPESAFE_API_KEY": key,
        "TYPESAFE_BASE_URL": url,
        "ROBOUSE_JEV_CONFIG": json.dumps({"model": "jev-latest", "profile": "nav", "prices": prices or {}}),
        "ROBOUSE_TASK_LANGUAGE": "Find the oven",
    }
    p = subprocess.run(
        [sys.executable, "-I", "-S", str(CLIENT)], cwd=ws, env=env, capture_output=True, text=True, timeout=300
    )
    return p, [json.loads(line) for line in p.stdout.splitlines() if line.startswith("{")]


def _close_like_runner(sock: str) -> None:
    from robouse.agent_cli import _send

    st = _send({"op": "status", "runner": True}, path=sock)
    if st.get("ok") and not st["result"]["finished"]:
        _send({"op": "give_up", "text": f"{RUNNER_PREFIX} agent exited without robo done"}, path=sock)


def _ops(tmp_path: Path) -> list[str]:
    trace = [json.loads(line) for line in (tmp_path / "run" / "trace.jsonl").read_text().splitlines()]
    return [
        t["req"]["op"] for t in trace if not t["req"].get("runner") and RUNNER_PREFIX not in str(t["req"].get("text"))
    ]


def test_the_client_drives_a_nav_episode_until_jev_answers_finished(tmp_path, typesafe) -> None:
    sock, ws, out, th = _serve(tmp_path)
    prices = {"stand-in": {"input": 0.042, "output": 0.0}}
    p, ev = _client(sock, ws, typesafe, prices=prices)
    th.join(timeout=30)
    assert p.returncode == 0, p.stderr
    assert out["outcome"] == "done" and out["success"] is True
    start, decisions, end = ev[0], [e for e in ev if e["type"] == "decision"], ev[-1]
    assert start["type"] == "start" and start["questions"] == C.nav_questions() and start["goal"] == "Find the oven"
    assert start["requests"] == ["robo info"]
    assert end["type"] == "end" and end["claimed_done"] is True and end["decisions"] == len(decisions)
    # one observe and one command per decision; the last command is Jev's "finished"
    ops = _ops(tmp_path)
    assert ops == ["info", *(["observe", "skill"] * (len(decisions) - 1)), "observe", "done"]
    assert all(d["requests"][0] == "robo observe" for d in decisions)
    assert decisions[-1]["command"].startswith('robo done "jev: the task is finished') and decisions[-1]["ok"]
    for d in decisions:
        assert set(d["answers"]) == {"drive.x", "drive.y", "drive.yaw", "task"}
        for a in d["answers"].values():
            assert a["choice"] in a["probabilities"] and 0 <= a["confidence"] <= 1
        assert d["usage"]["input_tokens"] > 0 and d["cost_usd"] == pytest.approx(d["usage"]["input_tokens"] * 0.042e-6)
        assert d["model"] == "stand-in" and d["attempts"] == 1
    assert end["cost_usd"] == pytest.approx(sum(d["cost_usd"] for d in decisions))
    # what TypeSafe got: the key as a bearer token, the model, the profile's questions and the state; nothing else
    reqs = stand_in.StandIn.requests
    assert len(reqs) == len(decisions) and all(r["bearer"] for r in reqs)
    for r, d in zip(reqs, decisions, strict=True):
        assert set(r["body"]) == {"model", "state", "questions"} and r["body"]["model"] == "jev-latest"
        assert r["body"]["questions"] == C.nav_questions() and r["body"]["state"] == d["state"]
    assert KEY not in p.stdout + p.stderr


def test_rate_limits_are_retried(tmp_path, typesafe) -> None:
    stand_in.StandIn.fail = [(429, {"retry-after": "0"}), (529, {"retry-after": "0"})]
    sock, ws, out, th = _serve(tmp_path)
    p, ev = _client(sock, ws, typesafe)
    th.join(timeout=30)
    assert p.returncode == 0 and out["outcome"] == "done"
    assert [(e["status"], e["attempt"]) for e in ev if e["type"] == "retry"] == [(429, 1), (529, 2)]
    assert next(e for e in ev if e["type"] == "decision")["attempts"] == 3


def test_a_refused_key_stops_without_a_claim(tmp_path, typesafe) -> None:
    """TypeSafe refuses the key: the client exits 1 having moved nothing and claimed nothing, and the runner closes the
    episode (an infrastructure failure, not a score)."""
    stand_in.StandIn.fail = [(401, {})]
    sock, ws, out, th = _serve(tmp_path)
    p, ev = _client(sock, ws, typesafe)
    assert p.returncode == 1
    err = ev[-1]
    assert err["type"] == "error" and err["status"] == 401 and "HTTP 401" in err["error"] and err["attempts"] == 1
    assert err["requests"] == ["robo observe"]
    _close_like_runner(sock)
    th.join(timeout=30)
    assert _ops(tmp_path) == ["info", "observe"] and out["outcome"] == "gave_up" and out["steps_used"] == 0
    assert str(out["agent_text"]).startswith(RUNNER_PREFIX)


def test_a_redirect_is_not_followed(tmp_path, typesafe) -> None:
    """urllib would resend the Authorization header to wherever a redirect points: the client stops instead."""
    seen: list = []

    class Elsewhere(stand_in.StandIn):
        def do_GET(self) -> None:
            seen.append(self.headers.get("Authorization"))
            self._send(200, {})

        do_POST = do_GET

    other = stand_in.ThreadingHTTPServer(("127.0.0.1", 0), Elsewhere)
    threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        where = f"http://127.0.0.1:{other.server_address[1]}/v1/systemone"
        stand_in.StandIn.fail = [(302, {"Location": where})]
        sock, ws, out, th = _serve(tmp_path)
        p, ev = _client(sock, ws, typesafe)
        assert p.returncode == 1 and ev[-1]["type"] == "error" and ev[-1]["status"] == 302
        assert seen == []  # nothing, and no key, went to the redirect's target
        _close_like_runner(sock)
        th.join(timeout=30)
    finally:
        other.shutdown()


def test_unexpected_failures_are_reported(tmp_path) -> None:
    """A reply that is not JSON, or a configuration that is not, ends the client with an error event, not a
    traceback."""
    import socketserver

    sock = f"/tmp/robouse-jev-{uuid.uuid4().hex[:8]}.sock"

    class Garbage(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            self.rfile.readline()
            self.wfile.write(b"not json\n")

    srv = socketserver.ThreadingUnixStreamServer(sock, Garbage)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        p, ev = _client(sock, tmp_path, "http://127.0.0.1:9")
        assert p.returncode == 1 and ev[-1]["type"] == "error" and "info failed: robo request failed" in ev[-1]["error"]
        env = {"ROBOUSE_SOCKET": sock, "TYPESAFE_API_KEY": KEY, "ROBOUSE_JEV_CONFIG": "{not json"}
        p = subprocess.run([sys.executable, "-I", "-S", str(CLIENT)], env=env, capture_output=True, text=True)
        err = json.loads(p.stdout.splitlines()[-1])
        assert p.returncode == 1 and err["type"] == "error" and err["error"].startswith("JSONDecodeError")
        assert "Traceback" not in p.stderr
    finally:
        srv.shutdown()
        srv.server_close()
        Path(sock).unlink(missing_ok=True)


def test_a_failed_done_with_the_episode_open_is_a_harness_failure(tmp_path, typesafe) -> None:
    """Jev answers finished, but the `robo done` request gets no reply and the episode is still open: the client exits
    1, like a failed drive, so the runner records a harness failure (not scored) instead of a trial scored 0."""
    import socketserver

    ep = _nav_episode(tmp_path)
    info, observed = ep.info(), ep.observe(False)
    observed["state"]["goal"]["arrived"] = True  # the stand-in answers finished
    sock = f"/tmp/robouse-jev-{uuid.uuid4().hex[:8]}.sock"
    ops: list[str] = []

    class Episode(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            op = json.loads(self.rfile.readline())["op"]
            ops.append(op)
            if op in ("info", "observe"):  # done: the connection closes without a reply
                result = info if op == "info" else observed
                self.wfile.write((json.dumps({"ok": True, "result": result}) + "\n").encode())

    srv = socketserver.ThreadingUnixStreamServer(sock, Episode)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        p, ev = _client(sock, tmp_path, typesafe)
    finally:
        srv.shutdown()
        srv.server_close()
        Path(sock).unlink(missing_ok=True)
    assert ops == ["info", "observe", "done"]
    assert ev[-2]["type"] == "decision" and ev[-2]["command"].startswith("robo done") and not ev[-2]["ok"]
    assert p.returncode == 1 and ev[-1]["type"] == "error" and ev[-1]["error"] == "done failed: empty response"


def test_a_robot_without_a_profile_is_refused_before_anything_moves(tmp_path, monkeypatch, typesafe) -> None:
    from fakes import FakeBackend

    monkeypatch.setattr(S, "make_backend", FakeBackend)
    sock = f"/tmp/robouse-jev-{uuid.uuid4().hex[:8]}.sock"
    ws = tmp_path / "ws"
    (ws / "observations").mkdir(parents=True)
    ready, out = tmp_path / "ready", {}
    spec = {"id": "t", "backend": "fake", "linger_s": 0}
    th = threading.Thread(
        target=lambda: out.update(S.serve(spec, tmp_path / "run", sock, ws, ready_file=ready)), daemon=True
    )
    th.start()
    for _ in range(500):
        if ready.exists():
            break
        time.sleep(0.01)
    p, ev = _client(sock, ws, typesafe)
    assert p.returncode == 2 and "nav suite" in ev[-1]["error"] and not stand_in.StandIn.requests
    _close_like_runner(sock)
    th.join(timeout=30)
    assert _ops(tmp_path) == ["info"]


# ---- the launch and the key ---------------------------------------------------------------------------------------------


def test_the_launch_gives_the_key_to_the_client_only(tmp_path, monkeypatch) -> None:
    from robouse import harnesses
    from robouse.harnesses import interface as iface
    from robouse.runner import trial

    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", "http://127.0.0.1:9")
    ws = tmp_path / "ws"
    (ws / ".robouse").mkdir(parents=True)
    task = load_task(EASY)
    launch = harnesses.build("jev", "", "PROMPT", ws, task, {"PATH": "/usr/bin", "_ROBOUSE_TRIAL_DIR": "x"})
    from robouse.lib.python_runtime import stdlib_python

    assert launch.cmd == [*stdlib_python(), str(ws / ".robouse" / "jev_client.py")]
    assert Path(launch.cmd[-1]).read_text() == CLIENT.read_text()
    env = launch.env
    assert env["TYPESAFE_API_KEY"] == KEY and env["TYPESAFE_BASE_URL"] == "http://127.0.0.1:9"
    assert env["ROBOUSE_TASK_LANGUAGE"] == "Find the oven" and "_ROBOUSE_TRIAL_DIR" not in env
    cfg = json.loads(env["ROBOUSE_JEV_CONFIG"])
    assert cfg["model"] == "jev-latest" and cfg["profile"] == "nav"
    assert cfg["prices"]["jev-1.13.0"] == {
        "input": 0.042,
        "output": 0.0,
        "source": "docs.typesafe.ai/models 2026-10-20",
    }
    assert launch.notes == {
        "model": "jev-latest",
        "model_id": "typesafe/jev-latest",
        "provider": "typesafe",
        "server": "http://127.0.0.1:9",
        "profile": "nav",
    }
    assert J.api_model("typesafe/jev-1.14.0") == J.api_model("jev-1.14.0") == "jev-1.14.0"
    with pytest.raises(ValueError, match="TypeSafe's models"):
        trial.image_input_plan("jev", "glm/glm-5.3")  # refused before any trial folder exists
    with pytest.raises(ValueError, match="no MCP client"):
        iface.check("jev", "mcp")
    # no other process gets a TYPESAFE_ variable: other agents, the episode server, the verifier
    environ = {"TYPESAFE_API_KEY": KEY, "TYPESAFE_BASE_URL": "http://x", "PATH": "/bin"}
    assert trial.agent_env(environ) == trial.without_provider_keys(environ) == {"PATH": "/bin"}
    # a task no profile drives, and a missing key, stop the trial before the client starts
    with pytest.raises(ValueError, match="nav suite.*arc-gravity runs on the tabletop backend"):
        harnesses.build("jev", "", "P", ws, load_task(ROOT / "tasks" / "arc-style" / "arc-gravity"), {})
    monkeypatch.delenv("TYPESAFE_API_KEY")
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        harnesses.build("jev", "", "P", ws, task, {})
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):  # `robouse run` refuses before any trial folder
        trial.check_model("jev", "")
    assert trial.image_input_plan("jev", "") == {
        "harness": "jev",
        "model": "typesafe/jev-latest",
        "image_input": False,
        "image_input_reason": "the jev client sends Jev text only",
    }


def test_a_key_with_a_line_break_is_refused_without_being_quoted(tmp_path, monkeypatch, typesafe) -> None:
    """A key with a line break inside (two lines of a key file, say) cannot go in an HTTP header, and http.client's
    error for it quotes the whole header, which the client would report on stdout, in the trial folder. The runner
    refuses such a key before any trial folder exists, and the client before any request, without quoting it."""
    from robouse.runner import trial

    bad = f"{KEY}\n{KEY}"
    sock, ws, out, th = _serve(tmp_path)
    p, ev = _client(sock, ws, typesafe, key=bad)
    _close_like_runner(sock)
    th.join(timeout=30)
    assert KEY not in p.stdout + p.stderr
    assert p.returncode == 1 and ev[-1]["type"] == "error" and not stand_in.StandIn.requests
    assert _ops(tmp_path) == [] and out["steps_used"] == 0  # stopped before any robo request
    monkeypatch.setenv("TYPESAFE_API_KEY", bad)
    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY") as refused:
        trial.check_model("jev", "")
    assert KEY not in str(refused.value)


def test_a_whole_trial_records_every_decision(tmp_path, monkeypatch, typesafe) -> None:
    """robouse's own runner on a nav task: the trajectory has one step per decision with Jev's answers, every robo
    request owned by its decision, and the trial's cost from pricing.json."""
    from robouse.runner import run_trial

    monkeypatch.setenv(
        "ROBOUSE_SANDBOX", "0"
    )  # the records are under test; tests/test_harness_isolation.py has the rest
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    monkeypatch.setenv("TYPESAFE_BASE_URL", typesafe)
    job = tmp_path / "job"
    res = run_trial(load_task(EASY), "jev", "", job, timeout=300)
    assert res["exception"] is None, res
    assert res["reward"] == 1.0 and res["outcome"] == "done"
    d = job / res["trial"]
    cfg, result = json.loads((d / "config.json").read_text()), json.loads((d / "result.json").read_text())
    assert (cfg["harness"], cfg["model"], cfg["image_input"]) == ("jev", "typesafe/jev-latest", False)
    assert result["agent_info"]["model_info"] == {"name": "typesafe/jev-latest", "provider": "typesafe"}
    assert KEY not in json.dumps(cfg) + json.dumps(result) + (d / "agent" / "stdout.jsonl").read_text()
    traj = json.loads((d / "agent" / "trajectory.json").read_text())
    steps = traj["steps"]
    assert steps[0] == {**steps[0], "source": "user", "message": "Find the oven"}
    assert steps[1]["extra"]["jev"]["questions"] == C.nav_questions()
    decisions = [s for s in steps if "answers" in (s.get("extra") or {}).get("jev", {})]
    n = len(stand_in.StandIn.requests)
    assert len(decisions) == n and all(s["llm_call_count"] == 1 for s in decisions)
    for s in decisions:
        jev = s["extra"]["jev"]
        assert (
            set(jev["answers"]) == {"drive.x", "drive.y", "drive.yaw", "task"}
            and jev["state"]["target"]["label"] == "oven"
        )
        assert [c["arguments"]["op"] for c in s["tool_calls"]] in (["observe", "skill"], ["observe", "done"])
        assert s["metrics"]["prompt_tokens"] == jev["usage"]["input_tokens"] and s["model_name"] == "stand-in"
    assert decisions[-1]["message"].startswith('robo done "jev: the task is finished')
    assert "not reported by the client" not in traj["notes"]
    trace_n = len((d / "episode" / "trace.jsonl").read_text().splitlines())
    assert sum(len(s.get("tool_calls") or []) for s in steps) == trace_n - 1  # all but the runner's status check
    fm = traj["final_metrics"]
    tokens = sum(s["metrics"]["prompt_tokens"] for s in decisions)
    assert fm["total_prompt_tokens"] == tokens and fm["extra"]["model_calls"] == n
    # pricing.json has no price for the stand-in's name, so each decision is priced as the model asked for, and so
    # is the trial: input tokens at Jev's price, output tokens free
    for s in decisions:
        assert s["metrics"]["cost_usd"] == pytest.approx(s["metrics"]["prompt_tokens"] * 0.042 / 1e6)
    assert fm["total_cost_usd"] == pytest.approx(tokens * 0.042 / 1e6)
    assert result["cost"]["cost_usd"] == pytest.approx(round(tokens * 0.042 / 1e6, 5))
    assert result["cost"]["cost_source"].startswith("pricing.json (docs.typesafe.ai/models")


def test_the_trajectory_of_a_trial_that_failed_on_the_api(tmp_path) -> None:
    """A client that stopped on an API error: its last step says why, and no decision is invented."""
    from robouse.runner import atif

    events = [
        {"type": "start", "t": 1.0, "goal": "Find the oven", "questions": {"task": {}}, "requests": ["robo info"]},
        {"type": "retry", "t": 1.1, "status": 429, "attempt": 1, "wait_s": 0.5},
        {"type": "error", "t": 2.0, "error": "TypeSafe HTTP 401 failed: bad key", "requests": ["robo observe"]},
    ]
    trace = [{"t": 0.1, "steps": 0, "req": {"op": "info"}, "resp": {"ok": True, "result": {}}}]
    trace += [{"t": 0.2, "steps": 0, "req": {"op": "observe"}, "resp": {"ok": True, "result": {"state": {}}}}]
    steps, meta, left = atif._parse_jev(events, [0, 1], trace)
    assert [s["source"] for s in steps] == ["user", "agent", "agent"] and left == []
    assert steps[-1]["message"] == "jev error: TypeSafe HTTP 401 failed: bad key"
    assert [c["command"] for s in steps for c in s["calls"]] == ["robo info", "robo observe"]
    assert atif._jev_final(meta) is None  # no answer, no model call
