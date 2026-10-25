"""Reference controls for the two fixed upstream examples. Every movement uses the episode socket.

Only the reference solution's token reveals material geometry for choosing a grasp. All movement still goes
through the public 16-value action vector, native IK and servos, contact physics and the normal step budget.
"""

from __future__ import annotations

import numpy as np

from ...agent_cli import _send


class _Finished(Exception):
    pass


def _request(message: dict) -> dict:
    response = _send(message)
    if not response.get("ok"):
        if "finished" in str(response.get("error", "")):
            raise _Finished
        raise RuntimeError(f"RoboSimStudio oracle: {response.get('error')}")
    result = response["result"]
    if str(result.get("episode", "")).startswith("finished"):
        raise _Finished
    return result


def oracle_main(env: str) -> None:
    info = _request({"op": "info"})
    action = np.asarray(info["neutral_action"], dtype=float)
    hz = float(info["control_hz"])
    cap = int(info.get("max_repeat", 50))

    def tick(steps: int) -> None:
        while steps:
            count = min(steps, cap)
            _request({"op": "act", "action": action.tolist(), "repeat": count})
            steps -= count

    def go(target, quat=None, speed: float = 0.06) -> None:
        state = _request({"op": "observe"})["state"]
        pos = np.asarray(state["right_tcp_pos"])
        rotation = np.asarray(state["right_tcp_quat"])
        target = np.asarray(target, dtype=float)
        quat = np.asarray(quat if quat is not None else action[11:15], dtype=float)
        if np.dot(rotation, quat) < 0:
            quat = -quat
        steps = max(40, int(np.ceil(np.linalg.norm(target - pos) * hz / speed)))
        for i in range(1, steps + 1):
            fraction = i / steps
            action[8:11] = pos + fraction * (target - pos)
            q = rotation + fraction * (quat - rotation)
            action[11:15] = q / np.linalg.norm(q)
            tick(1)
        tick(25)

    def close_gripper() -> None:
        action[15] = 1.0
        tick(60)

    try:
        tick(30)
        scene = _request({"op": "observe"})["state"]["scene"]
        if env == "open-bag":
            x, y, z = scene["lip"]
            go((x, y, z + 0.075), (0, 1, 0, 0))
            go((x, y, z))
            close_gripper()
            go((x, y, z + 0.055))
            go((x, y + 0.06, z + 0.055), speed=0.04)
            tick(60)
        elif env == "hook-band":
            origin = np.array([0.6, 0.0, 0.75])
            x, _, z = np.asarray(scene["band_bottom"]) - origin
            go(origin + [x - 0.05, -0.20, z + 0.02], (0, np.sqrt(0.5), 0, np.sqrt(0.5)), speed=0.1)
            close_gripper()
            targets = (
                [x - 0.005, -0.20, z + 0.02],
                [x - 0.005, -0.20, 0.105],
                [0.082, -0.20, 0.105],
                [0.082, -0.20, 0.120],
                [x - 0.06, -0.20, 0.120],
            )
            for target in targets:
                go(origin + target, speed=0.05)
            tick(120)
        else:
            raise ValueError(f"unsupported RoboSimStudio reference task {env!r}")
        _request({"op": "done", "text": f"RoboSimStudio reference: {env}"})
    except _Finished:
        return
