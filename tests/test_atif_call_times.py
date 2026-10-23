"""The trajectory gives each robo request to the tool call that sent it, by Claude Code's own timestamps.

Counting the robo commands a call wrote cannot see the requests of a loop or of a script the agent wrote; Claude Code
stamps the event that makes each tool call and the one that returns its result, and the episode's trace stamps each
request, so the clock places every request in its call. These trials are built by hand: a shell call per assistant
message, its output as an agent filtering robo's output with grep would see it, and the trace the server would write.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from robouse.runner import atif
from robouse.runner.robo_calls import robo_commands, unexplained

T0 = 1_792_600_000.0  # the episode's start on the clock


def _stamp(x: float) -> str:
    return datetime.fromtimestamp(T0 + x, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _state(step: int) -> dict:
    return {"state": {"hand_pos": [0.0, round(step / 1000, 4), 0.2]}, "steps_used": step}


def _trial(
    path: Path,
    calls: list[tuple[str, str, float, float]],
    trace: list[tuple[float, int, dict]],
    *,
    stamped: bool = True,
    result_late: float = 0.03,
) -> Path:
    """A Claude Code trial: `calls` are (command, output, start, end) and `trace` (t, steps after, request), all in
    seconds from the episode's start; episode/result.json is written `result_late` after the episode's end."""
    (path / "agent").mkdir(parents=True)
    (path / "episode").mkdir()
    (path / "config.json").write_text(json.dumps({"harness": "claude-code", "model": "claude-opus-5-5", "task": "t"}))
    events: list[dict] = [{"type": "system", "subtype": "init", "session_id": "s", "model": "claude-opus-5-5"}]
    for k, (cmd, out, a, b) in enumerate(calls):
        use = {"type": "tool_use", "id": f"call{k}", "name": "Bash", "input": {"command": cmd}}
        events.append({"type": "assistant", "timestamp": _stamp(a), "message": {"id": f"msg{k}", "content": [use]}})
        res = {"type": "tool_result", "tool_use_id": f"call{k}", "content": out}
        events.append({"type": "user", "timestamp": _stamp(b), "message": {"content": [res]}})
    if not stamped:
        for ev in events:
            ev.pop("timestamp", None)
    (path / "agent" / "stdout.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    lines = []
    for t, steps, req in trace:
        result = {"outcome": "done"} if req["op"] == "done" else _state(steps)
        lines.append({"t": t, "steps": steps, "req": req, "resp": {"ok": True, "result": result}})
    (path / "episode" / "trace.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    last = max(s for _, s, _ in trace)
    frames = [{"i": i, "t": round(i * 0.02, 3), "step": 2 * i} for i in range(last // 2 + 1)]
    (path / "episode" / "frames.jsonl").write_text("".join(json.dumps(f) + "\n" for f in frames))
    end = max(t for t, _, _ in trace) + 0.5
    result = path / "episode" / "result.json"
    result.write_text(json.dumps({"wall_time_s": end, "steps_used": last, "max_steps": 900, "outcome": "done"}))
    os.utime(result, (T0 + end + result_late, T0 + end + result_late))
    return path


def _lines_by_call(path: Path) -> tuple[dict[str, list[int]], dict]:
    """Each tool call's trace lines (1-based), as the trajectory gives them, and the trajectory."""
    traj, _ = atif.build(path)
    out: dict[str, list[int]] = {}
    for st in traj["steps"]:
        v = (st.get("extra") or {}).get("video") or {}
        for call in st.get("tool_calls") or []:
            lo, hi = v.get("trace_lines") or (0, -1)
            out[call["tool_call_id"]] = list(range(lo, hi + 1))
    return out, traj


def _mv(x: float, y: float, z: float, grip: float | None = 1.0) -> dict:
    return {"op": "move_to", "pos": [x, y, z], "grip": grip, "max_steps": 100, "tol": 0.01}


def _act(*a: float, repeat: int = 1) -> dict:
    return {"op": "act", "action": list(a), "repeat": repeat}


OBSERVE = {"op": "observe", "image": False, "camera": None}


def test_a_script_the_agent_wrote_owns_its_requests(tmp_path) -> None:
    """A heredoc writes a script that loops over robo move-to; a later call edits it and runs it again before a robo
    observe of its own. The requests the script sent belong to the calls that ran it, and the next call starts with its
    own grip, not with the previous call's observe."""
    script = (
        "cat > /tmp/arc.sh <<'EOF'\nfor a in 10 20 30; do\n"
        '  python3 -c "print(0, $a / 100)" | { read X Y; robo move-to $X $Y 0.2 --grip 1 | grep -E "reached|hand_pos"; }\n'
        "done\nEOF\nbash /tmp/arc.sh"
    )
    moved = "reached: True\n  hand_pos: [0.0, 0.1, 0.2]\n"
    calls = [
        ("robo observe", "state:\n  hand_pos: [0.0, 0.0, 0.2]\nsteps_used: 0", 1.0, 1.4),
        (script, moved * 3, 2.0, 3.2),
        (
            "sed -i 's/10 20 30/40 50/' /tmp/arc.sh; bash /tmp/arc.sh; robo observe | grep steps_used",
            moved * 2 + "steps_used: 100",
            4.0,
            5.2,
        ),
        (
            'robo grip -1 --steps 15 | grep touching; robo act 0 0 0 0 -1 --repeat 5 | grep touching',
            "  touching: []\n  touching: []",
            6.0,
            7.0,
        ),
        ('robo done "hood open"', "outcome: done", 8.0, 8.6),
    ]
    trace = [
        (1.1, 0, OBSERVE),
        (2.2, 20, _mv(0, 0.1, 0.2)),
        (2.5, 40, _mv(0, 0.2, 0.2)),
        (2.8, 60, _mv(0, 0.3, 0.2)),
        (4.2, 80, _mv(0, 0.4, 0.2)),
        (4.5, 100, _mv(0, 0.5, 0.2)),
        (4.8, 100, OBSERVE),
        (6.2, 115, {"op": "grip", "value": -1.0, "steps": 15}),
        (6.5, 120, _act(0, 0, 0, 0, -1, repeat=5)),
        (8.1, 120, {"op": "done", "text": "hood open"}),
    ]
    got, traj = _lines_by_call(_trial(tmp_path / "t", calls, trace))
    assert got == {"call0": [1], "call1": [2, 3, 4], "call2": [5, 6, 7], "call3": [8, 9], "call4": [10]}
    assert "by the transcript's timestamps" in traj["notes"]


def test_a_loop_owns_all_its_requests(tmp_path) -> None:
    """A shell loop of robo act and robo observe whose output, filtered by grep, shows no robo result to count."""
    loop = (
        "for i in 1 2 3 4; do robo act 0 0 0 0 0 0.01 0 0 --repeat 1 >/dev/null; "
        "robo observe | grep -E \"tip_pos\" | tr '\\n' ' '; echo; done"
    )
    calls = [
        ("robo info; robo observe", "task: t\nstate:\n  hand_pos: [0.0, 0.0, 0.2]\nsteps_used: 0", 1.0, 1.5),
        (loop, "  arm: {'tip_pos': [5.75, -0.85, 0.89]}\n" * 4, 2.0, 4.0),
        (
            "robo act 0 0 0 0 0 -0.03 0 0 --repeat 6 >/dev/null; robo observe | grep -E \"progress\"",
            "  progress: {'buttons_pressed': ['reset']}",
            5.0,
            5.8,
        ),
        ('robo done "pressed the reset button"', "outcome: done", 7.0, 7.5),
    ]
    trace = [(1.1, 0, {"op": "info"}), (1.2, 0, OBSERVE)]
    for k in range(4):
        trace += [(2.1 + 0.4 * k, 2 + 2 * k, _act(0, 0, 0, 0, 0, 0.01, 0, 0)), (2.3 + 0.4 * k, 2 + 2 * k, OBSERVE)]
    trace += [(5.1, 14, _act(0, 0, 0, 0, 0, -0.03, 0, 0, repeat=6)), (5.4, 14, OBSERVE)]
    trace += [(7.1, 14, {"op": "done", "text": "pressed the reset button"})]
    got, _ = _lines_by_call(_trial(tmp_path / "t", calls, trace))
    assert got == {"call0": [1, 2], "call1": list(range(3, 11)), "call2": [11, 12], "call3": [13]}


def test_a_helper_run_by_its_path_owns_its_requests(tmp_path) -> None:
    """A one-line helper the agent wrote (robo observe through grep) and runs by its path, after literal commands."""
    calls = [
        (
            "cat > /tmp/s.sh <<'EOF'\nrobo observe | grep -E \"hand_pos|kettle\"\nEOF\nchmod +x /tmp/s.sh; robo grip 1; /tmp/s.sh",
            "  hand_pos: [0.0, 0.01, 0.2]",
            1.0,
            2.0,
        ),
        ("robo move-to 0.1 0 0.1 >/dev/null; /tmp/s.sh", "  hand_pos: [0.0, 0.02, 0.2]", 3.0, 4.0),
        ('robo done "kettle moved"', "outcome: done", 5.0, 5.5),
    ]
    trace = [
        (1.2, 15, {"op": "grip", "value": 1.0, "steps": 15}),
        (1.5, 15, OBSERVE),
        (3.2, 25, _mv(0.1, 0, 0.1, None)),
        (3.6, 25, OBSERVE),
        (5.1, 25, {"op": "done", "text": "kettle moved"}),
    ]
    got, _ = _lines_by_call(_trial(tmp_path / "t", calls, trace))
    assert got == {"call0": [1, 2], "call1": [3, 4], "call2": [5]}


def test_short_evenly_spaced_calls_are_told_apart_by_their_commands(tmp_path) -> None:
    """Two clock offsets put every request inside a call (the first call sent nothing): the one under which each call's
    own command explains its request wins, even when the result file's time points at the other."""
    calls = [
        ("ls", "notes.txt", 0.0, 1.0),
        ("robo move-to 0.1 0 0.1", "reached: True", 2.0, 3.0),
        ("robo move-to 0.2 0 0.1", "reached: True", 4.0, 5.0),
    ]
    trace = [(2.5, 10, _mv(0.1, 0, 0.1, None)), (4.5, 20, _mv(0.2, 0, 0.1, None))]
    got, _ = _lines_by_call(_trial(tmp_path / "t", calls, trace, result_late=-2.0))
    assert got["call1"] == [1] and got["call2"] == [2] and got.get("call0") == []


def test_when_the_commands_cannot_tell_the_result_file_time_does(tmp_path) -> None:
    """The same command in three calls, the first of which sent nothing (it hit an error first): both offsets explain
    every request, and the result file, written just after the episode ended, places the episode's start."""
    calls = [
        ("cd /nowhere && robo act 0 0 0 1 0 0 0 0", "cd: no such file or directory", 0.0, 1.0),
        ("robo act 0 0 0 1 0 0 0 0", "executed_steps: 1", 2.0, 3.0),
        ("robo act 0 0 0 1 0 0 0 0", "executed_steps: 1", 4.0, 5.0),
    ]
    trace = [(2.5, 1, _act(0, 0, 0, 1, 0, 0, 0, 0)), (4.5, 2, _act(0, 0, 0, 1, 0, 0, 0, 0))]
    got, _ = _lines_by_call(_trial(tmp_path / "t", calls, trace))
    assert got["call1"] == [1] and got["call2"] == [2] and got.get("call0") == []


def test_without_timestamps_the_commands_are_counted_as_before(tmp_path) -> None:
    calls = [
        ("robo observe", "state:\n  hand_pos: [0.0, 0.0, 0.2]\nsteps_used: 0", 1.0, 1.4),
        ("robo move-to 0.1 0 0.1", "reached: True\nstate:\n  hand_pos: [0.0, 0.01, 0.2]\nsteps_used: 10", 2.0, 3.0),
    ]
    trace = [(1.1, 0, OBSERVE), (2.5, 10, _mv(0.1, 0, 0.1, None))]
    got, traj = _lines_by_call(_trial(tmp_path / "t", calls, trace, stamped=False))
    assert got == {"call0": [1], "call1": [2]}
    assert "by the transcript's timestamps" not in traj["notes"]


def test_robo_commands_read_as_the_shell_reads_them() -> None:
    line = (
        'cd /tmp && for i in 1 2; do robo act 0 0 1 --repeat $i | tail -2; done; robo grip -1 --steps 8 >/dev/null; '
        'X=$(robo observe | grep hand); robo done "it\'s; done" 2>&1; robo move-to --help'
    )
    cmds = robo_commands(line)
    assert [(c.op, c.loop, c.req is None) for c in cmds] == [
        ("act", True, True),
        ("grip", False, False),
        ("observe", False, True),
        ("done", False, False),
    ]
    assert cmds[1].req == {"op": "grip", "value": -1.0, "steps": 8}
    assert cmds[3].req == {"op": "done", "text": "it's; done"}
    assert unexplained("robo grip -1 --steps 8", [{"op": "grip", "value": -1.0, "steps": 8}]) == 0
    assert unexplained("robo grip -1 --steps 8", [{"op": "grip", "value": 1.0, "steps": 8}]) == 1
    assert unexplained("bash /tmp/s.sh", [OBSERVE, _act(1, 0, 0)]) == 0
    assert unexplained("cd /tmp/ws; /tmp/s.sh | grep kettle", [OBSERVE]) == 0
    assert unexplained("cd /tmp/ws; ls -la /tmp", [OBSERVE]) == 1
