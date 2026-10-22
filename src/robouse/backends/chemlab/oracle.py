"""chemlab reference solutions. Each drives the gripper only through the episode socket, like an agent, from what
`robo observe` reports (part positions, joint states, readouts) and the task's published geometry."""

from __future__ import annotations

import math

import numpy as np

from .scene import HAND_SIZE
from .tasks import TASKS, Task

# The Franka Hand's size, as the task instructions give it (scene.HAND_SIZE)
FINGERTIP = HAND_SIZE["tip"]  # the fingertips reach this far beyond the tool point
FINGER_HALF_WIDTH = HAND_SIZE["finger_width"] / 2
PALM = HAND_SIZE["palm"]  # the hand's body begins this far behind the tool point
HANDLE_RADIUS = 0.006  # the shaker hood's handle, a 12 mm bar
HX_LID_TOP = 0.1403  # the top of the moisture analyzer's closed lid, its rim (as the camera shows it)
TIP_GRASP_BACK = 0.008  # the shaker's handle held by the fingertips only, clear of the hood's window behind it
SHAKER_LET_GO = 42.0  # degrees: the hood's angle up to which the hand holds its handle


class _Finished(Exception):
    pass


class _Robot:
    def __init__(self):
        from robouse.agent_cli import _send

        self._send = _send
        self.grip_value = -1.0

    def req(self, r: dict) -> dict:
        resp = self._send(r)
        if not resp.get("ok"):
            raise RuntimeError(f"{r.get('op')}: {resp.get('error')}")
        res = resp.get("result") or {}
        if isinstance(res, dict) and "episode" in res:
            raise _Finished()
        return res

    def obs(self) -> dict:
        return self.req({"op": "observe"})["state"]

    def part(self, label: str) -> dict:
        return self.obs()["parts"][label]

    def move(self, p, g: float | None = None, tol: float = 0.003, tries: int = 3) -> dict:
        if g is not None:
            self.grip_value = g
        res: dict = {}
        for _ in range(tries):
            res = self.req(
                {"op": "move_to", "pos": [float(x) for x in p], "grip": self.grip_value, "max_steps": 150, "tol": tol}
            )
            if res.get("reached"):
                break
        return res

    def act(self, dx=0.0, dy=0.0, dz=0.0, dtwist=0.0, repeat: int = 1) -> dict:
        a = [float(dx), float(dy), float(dz), float(dtwist), float(self.grip_value)]
        return self.req({"op": "act", "action": a, "repeat": int(repeat)})

    def grip(self, g: float, steps: int = 15) -> None:
        self.grip_value = g
        self.req({"op": "grip", "value": float(g), "steps": steps})

    def twist_to(self, deg: float, tol: float = 1.0) -> None:
        """Turn the gripper about its tool axis to an absolute twist (degrees), 5 degrees per full-speed step."""
        for _ in range(60):
            now = self.obs()["hand_twist_deg"]
            err = deg - now
            if abs(err) <= tol:
                return
            n = max(1, min(50, int(abs(err) // 5)))
            self.act(dtwist=float(np.clip(err / (5.0 * n), -1, 1)), repeat=n)

    def wait(self, steps: int) -> None:
        while steps > 0:
            n = min(50, steps)
            self.act(repeat=n)
            steps -= n


def _sash(rb: _Robot, task: Task) -> None:
    """Close the gripper around the handle bar from the front, lift it along the rails to the stop, let go."""
    h = np.array(rb.part("sash")["handle_pos"])
    rb.move(h + [0, -0.12, 0], -1.0, tol=0.006)
    rb.move(h + [0, -0.002, 0], -1.0, tol=0.003)
    rb.grip(1.0, 15)
    axis = np.array([0.0, math.sin(math.radians(5)), math.cos(math.radians(5))])
    for _ in range(6):
        p = rb.part("sash")
        err = 0.457 - p["opening_m"]
        if abs(err) < 0.003:
            break
        target = np.array(rb.obs()["hand_pos"]) + axis * err * 1.0038
        rb.move(target, 1.0, tol=0.002)
    rb.grip(-1.0, 12)
    hp = np.array(rb.obs()["hand_pos"])
    rb.move(hp + [0, -0.12, 0], -1.0, tol=0.01)
    rb.wait(60)


def _balance(rb: _Robot, task: Task) -> None:
    """Push the open top door shut by the ridge across its top, with the closed fingers turned across the door and
    their tips on its glass, so that the fingertip pads' flat sides meet the ridge; lift off, then wait for the
    balance to settle."""
    rb.grip(1.0, 15)
    rb.twist_to(90.0)
    h = np.array(rb.part("top door")["handle_pos"])  # the ridge's centre: 8 mm deep, standing 5 mm on the glass
    z = h[2] - 0.002 + FINGERTIP  # the fingertips on the glass
    behind = h[1] + 0.004 + FINGER_HALF_WIDTH + 0.006
    rb.move([h[0], behind, z + 0.06], 1.0, tol=0.006)
    rb.move([h[0], behind, z], 1.0, tol=0.002)
    shut = h[1] - rb.part("top door")["opening_m"] + 0.004 + FINGER_HALF_WIDTH  # the fingers against the shut ridge
    rb.move([h[0], shut - 0.002, z], 1.0, tol=0.002)
    rb.move([h[0], shut + 0.002, z + 0.03], 1.0, tol=0.004)
    rb.move([h[0], shut + 0.03, z + 0.08], 1.0, tol=0.01)
    for _ in range(10):
        if rb.obs().get("readouts", {}).get("balance.status") == "STABLE":
            break
        rb.wait(25)


def _knob(label: str, target_deg: float, readout: str, want: float, per_deg: float):
    """Close the open gripper around the knob from above, turn it, read the display and correct, let go."""

    def run(rb: _Robot, task: Task) -> None:
        k = np.array(rb.part(label)["knob_pos"])
        rb.move([k[0], k[1], k[2] + 0.1], -1.0, tol=0.004)
        rb.move([k[0], k[1], k[2] + 0.004], -1.0, tol=0.002)
        rb.grip(1.0, 15)
        start = rb.obs()["hand_twist_deg"] - rb.part(label)["angle_deg"]
        rb.twist_to(start + target_deg, tol=0.5)
        for _ in range(4):
            shown = rb.obs().get("readouts", {}).get(readout)
            if shown is None or abs(shown - want) < 0.5 * per_deg * 4:
                break
            rb.twist_to(rb.obs()["hand_twist_deg"] + (want - shown) / per_deg, tol=0.3)
        rb.grip(-1.0, 12)
        hp = rb.obs()["hand_pos"]
        rb.move([hp[0], hp[1], hp[2] + 0.1], -1.0, tol=0.01)

    return run


def _oven_door(rb: _Robot, task: Task) -> None:
    """Push the open door shut by its outer face near its top edge, following its arc with the hand along the door:
    the fingers on the door's top 4 cm, the hand just above the door's top edge."""
    door = rb.part("door")
    hinge = np.array(door["hinge_xy"])
    r, z = 0.3, door["top_z"] - PALM + 0.008  # push 0.3 m from the hinge
    out = (
        -0.063 - FINGER_HALF_WIDTH - 0.004
    )  # the outer face is 0.063 m in front of the hinge line; half a finger; a gap

    def at(theta: float, off: float) -> np.ndarray:
        c, s = math.cos(theta), math.sin(theta)
        lx, ly = -r, off
        return hinge + [c * lx - s * ly, s * lx + c * ly]

    theta = math.radians(door["angle_deg"])
    rb.grip(1.0, 15)
    p = at(theta, out - 0.05)
    rb.move([p[0], p[1], 0.75], 1.0, tol=0.006)
    rb.twist_to(90.0 - math.degrees(theta), tol=1.0)
    rb.move([p[0], p[1], z], 1.0, tol=0.004)
    for _ in range(40):
        theta = math.radians(rb.part("door")["angle_deg"])
        if theta < math.radians(0.4):
            break
        nxt = max(theta - math.radians(8), math.radians(-3))
        rb.twist_to(90.0 - math.degrees(max(nxt, 0.0)), tol=2.0)
        p = at(nxt, out)
        rb.move([p[0], p[1], z], 1.0, tol=0.003, tries=1)
    hp = np.array(rb.obs()["hand_pos"])
    rb.move(hp + [0, -0.08, 0], 1.0, tol=0.01)
    rb.move(hp + [0, -0.08, 0.15], 1.0, tol=0.01)
    rb.wait(10)


def _hx_lid(rb: _Robot, task: Task) -> None:
    """Push the lid's front face along the lid's diagonal until it is fully open, with the fingers on the face's top
    part and the hand above the lid."""
    rb.grip(1.0, 15)
    rb.twist_to(90.0)
    f = np.array(rb.part("lid")["front_face_pos"])
    start = np.array([f[0], f[1] - FINGER_HALF_WIDTH - 0.0075, HX_LID_TOP - PALM + 0.003])
    rb.move(start + [0, 0, 0.12], 1.0, tol=0.005)
    rb.move(start, 1.0, tol=0.003)
    u = np.array([0.0, 0.80066215, 0.59911611])
    for _ in range(6):
        lift = rb.part("lid")["lift_m"]
        if lift >= 0.106:
            break
        hp = np.array(rb.obs()["hand_pos"])
        rb.move(hp + u * ((0.1085 - lift) * 1.6691 + 0.008), 1.0, tol=0.003, tries=1)
    hp = np.array(rb.obs()["hand_pos"])
    rb.move(hp - u * 0.02, 1.0, tol=0.005)
    rb.move(hp - u * 0.02 + [0, -0.06, 0.05], 1.0, tol=0.01)


def _shaker_hood(rb: _Robot, task: Task) -> None:
    """Close the gripper around the hood's handle bar from the front, by the fingertips, and swing the hood up along
    its arc to 42 degrees; then let go, turn the closed fingers flat (90 degrees about the tool axis) and push the
    handle on along its arc with the fingertips, pressed on its front, to 83 degrees (the gas springs hold the hood
    wherever it is let go). The hand keeps its orientation while the hood turns, so holding the handle further would
    bring the hood's front window into the lower finger and then its lower lip into the hand."""
    hood = rb.part("hood")
    hinge = np.array(hood["hinge_yz"])
    h = np.array(hood["handle_pos"])
    rel = h[1:] - hinge

    def handle_at(theta: float) -> np.ndarray:
        c, s = math.cos(theta), math.sin(theta)
        y, z = rel
        return np.array([h[0], hinge[0] + y * c + z * s, hinge[1] - y * s + z * c])

    hold = np.array([0.0, -TIP_GRASP_BACK, 0.0])
    rb.move(h + [0, -0.12, 0], -1.0, tol=0.006)
    rb.move(h + hold, -1.0, tol=0.003)
    rb.grip(1.0, 15)
    for _ in range(30):
        theta = math.radians(rb.part("hood")["angle_deg"])
        if theta >= math.radians(SHAKER_LET_GO):
            break
        nxt = min(theta + math.radians(6), math.radians(SHAKER_LET_GO + 1))
        rb.move(handle_at(nxt) + hold, 1.0, tol=0.004, tries=1)
    rb.grip(-1.0, 12)
    hp = np.array(rb.obs()["hand_pos"])
    rb.move(hp + [0, -0.05, 0], -1.0, tol=0.006)
    rb.grip(1.0, 15)
    rb.twist_to(90.0)
    push = np.array([0.0, -(HANDLE_RADIUS + FINGERTIP), 0.003])  # the fingertips on the handle's front
    theta = math.radians(rb.part("hood")["angle_deg"])
    rb.move(handle_at(theta) + push + [0, -0.02, 0], 1.0, tol=0.004)
    push += [0.0, 0.002, 0.0]  # pressed on the handle
    rb.move(handle_at(theta) + push, 1.0, tol=0.002)
    for _ in range(50):
        theta = math.radians(rb.part("hood")["angle_deg"])
        if theta >= math.radians(83):
            break
        rb.move(handle_at(min(theta + math.radians(5), math.radians(86))) + push, 1.0, tol=0.002, tries=1)
    hp = np.array(rb.obs()["hand_pos"])
    rb.move(hp + [0, -0.1, 0], 1.0, tol=0.01)


PLANS = {
    "sash": _sash,
    "balance": _balance,
    "knob_temperature": _knob("temperature knob", 360.0, "display.set_temperature", 100.0, 100.0 / 360.0),
    "knob_speed": _knob("speed knob", 360.0, "display.set_speed", 500.0, 500.0 / 360.0),
    "oven_door": _oven_door,
    "hx_lid": _hx_lid,
    "shaker_hood": _shaker_hood,
}


def oracle_main(env: str) -> None:
    task = TASKS[env]
    rb = _Robot()
    try:
        PLANS[task.plan](rb, task)
        rb.req({"op": "done", "text": "reference solution finished"})
    except _Finished:
        return
