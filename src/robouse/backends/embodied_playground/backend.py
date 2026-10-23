"""Embodied Playground's Launcher tasks: two Franka Pandas operate a passive spring launcher to clear targets.

Embodied Playground (github.com/Winniechen2002/Embodied-Playground; HKU, Sharpa, Tsinghua, Stanford, UNC and MIT) is a
long-horizon agentic robotics benchmark; its Launcher suite runs on its own MuJoCo package. That package is downloaded at
run time from a pinned commit (source.py, `robouse fetch-assets --embodied-playground`) and runs, unmodified, in its own
virtualenv (Python 3.11 with Embodied Playground's pins: MuJoCo 3.3.7, numpy 1.26.4, gymnasium 1.2.1), as a subprocess
(worker.py); this module is the bridge. Setup: the suites page of the docs (config.SUITES_DOCS).

The scene: a power arm (`left`, base at (0, -0.45, 0)) and an aiming arm (`right`, base at (0.15, 0.60, 0)) stand by a
launcher whose carriage slides on rails inclined 30 degrees, held by a spring; a handwheel sets its elevation. The
projectile sits in the carriage's cup (loaded start). Pull the carriage back by its handle and let go: the spring sends
it forward and the latch releases the projectile toward the targets down the lane. Spare projectiles lie on the floor
for reloading by hand. Frame: metres, +z up, the lane along +x.

Action (16 numbers, Embodied Playground's layout): per arm seven absolute joint targets (rad) and a binary gripper
command (+1 open, -1 closed; the gripper opens for values >= 0), the left arm first. One step is 20 ms (20 physics steps
of 1 ms); the environment moves each joint toward its target no faster than the joint's speed limit. Embodied Playground
ends the episode at the first rule or physical violation (an arm penetrating an object by more than 5 mm, a joint above
110% of its speed limit, the slide or the wheels past their limits, an unstable simulation, a protected target hit, the
wrong target order), when its 150 s of simulated time are up, and when every projectile has been fired and has settled.
Success is Embodied Playground's own rule (every required target cleared, plus any toppling, fracture or protection
rules of the task), checked at every physics step; the episode is scored solved the first time it holds.

Observation (Embodied Playground's Level 0): the robots' joint positions and velocities, the finger positions, the
previous action, the clock, the end flags, and the `front_left` camera (640x400) with its projection matrix. No object
positions: agents find the launcher, the projectiles and the targets in the image. No skills: at Level 0 agents write
their own kinematics and planning.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ... import config
from ...core.embodiment_spec import Budgets, Camera, Embodiment, Field, RewardSpec, Sensors
from ...workers.client import StdioWorker
from ..base import ActionSpec, Backend, G, StepInfo, groups_from_layout
from . import source

WORKER = Path(__file__).with_name("worker.py")
SETUP = config.SUITES_DOCS
SIDES = ("left", "right")
NATIVE_W, NATIVE_H = 640, 400
PUBLIC_FIELDS = (
    "left_joint_pos",
    "left_joint_vel",
    "left_finger_pos",
    "right_joint_pos",
    "right_joint_vel",
    "right_finger_pos",
    "previous_action",
    "step_index",
    "simulation_time_s",
    "terminated",
    "truncated",
)


class EmbodiedPlaygroundBackend(Backend):
    name = "embodied_playground"
    robot_kind = "bimanual"
    robot_name = "dual-panda-launcher"
    probe_success = False  # step() already returns the environment's verdict
    camera = "front_left"
    proprioception = PUBLIC_FIELDS

    def __init__(self, spec: dict):
        super().__init__(spec)
        family = str(spec.get("family", "marble"))
        if family != "marble":
            raise ValueError(f"embodied_playground: only the Launcher family (marble) runs on the CPU; got {family!r}")
        self.task_id = str(spec.get("env", ""))
        self.condition = int(spec.get("condition", 1))
        self.goal = str(spec.get("goal", ""))
        self.max_steps = int(spec.get("max_steps", 7500))
        task = {
            "scenario": str(spec["ep_scenario"]),
            "initial_mode": str(spec.get("initial_mode", "loaded")),
            "environment_parameters": dict(spec.get("environment_parameters") or {}),
            "max_seconds": round(self.max_steps * 0.02, 6),
        }
        source.require()
        self.worker = StdioWorker(
            "embodied_playground",
            config.sim_python("embodied_playground", "embodied-playground"),
            WORKER,
            setup=SETUP,
        )
        self._seed = int(spec.get("seed", 0))
        self.meta = self.worker.call("make", package_parent=str(source.package_parent()), task=task, seed=self._seed)
        self._fresh = True
        names = [f"{s}_{j}" for s in SIDES for j in [*range(7), "gripper"]]
        doc = (
            "Embodied Playground's layout: the left (power) arm's seven absolute joint targets (rad) and its gripper "
            "(+1 open, -1 closed), then the right (aiming) arm's eight. One step = 20 ms."
        )
        self.action_spec = ActionSpec(names=names, low=self.meta["low"], high=self.meta["high"], doc=doc)
        self.last = list(self.meta["neutral_action"])
        self._state: dict | None = None
        self.last_judge: dict | None = None

    # ---- simulator -------------------------------------------------------------------------------------------------
    def reset(self, seed: int) -> None:
        if self._fresh and int(seed) == self._seed:  # built with this seed a moment ago, nothing has stepped
            self._fresh = False
            return
        self.meta = self.worker.call("reset", seed=int(seed))
        self._fresh = False
        self.last = list(self.meta["neutral_action"])
        self._state = None

    def step(self, action: Any) -> StepInfo:
        a = [float(x) for x in self.action_spec.clip(action)]
        self.last = a
        self._fresh = False
        r = self.worker.call("step", action=a)
        self._state = None
        return StepInfo(success=bool(r["success"]), extra={k: r[k] for k in ("terminated", "truncated", "failure")})

    def observe(self) -> dict:
        if self._state is None:
            self._state = self.worker.call("observe")
        return dict(self._state)

    def privileged_state(self) -> dict:
        """The launcher, the projectiles and the targets: only for the reference solution."""
        return {"scene": self.worker.call("privileged")}

    def hold_action(self) -> list[float]:
        """Hold still: keep commanding the last joint targets and gripper commands."""
        return list(self.last)

    def render(self, width: int | None = None, height: int | None = None) -> np.ndarray:
        return self.worker.call("render", width=width, height=height)

    def camera_info(self, cameras: list[str]) -> list[dict]:
        if self.camera not in cameras:
            return []
        return self.worker.call("camera_info", width=NATIVE_W, height=NATIVE_H)

    def success(self) -> bool:
        r = self.worker.call("success")
        self.last_judge = r.get("detail")
        return bool(r["success"])

    def close(self) -> None:
        self.worker.close()

    # ---- embodiment ------------------------------------------------------------------------------------------------
    def skills(self) -> list[str]:
        return []

    def action_layout(self) -> list[G]:
        lay = []
        for s, role in zip(SIDES, ("power", "aiming"), strict=True):
            lay += [
                G(f"{s}_arm.joints", 7, "joint_pos", "rad", hold="last", doc=f"{s} ({role}) arm joints 1-7"),
                G(f"{s}_gripper", 1, "gripper", "binary", hold="last", initial=1.0, doc="+1 open, -1 closed"),
            ]
        return lay

    def embodiment(self) -> Embodiment:
        s = self.action_spec
        return Embodiment(
            name=self.robot_name,
            kind=self.robot_kind,
            action_groups=groups_from_layout(s, self.action_layout()),
            sensors=Sensors(
                cameras=[Camera(self.camera, "world", NATIVE_W, NATIVE_H, doc="overview of both arms and the lane")],
                proprioception=[Field(n) for n in self.proprioception],
            ),
            skills=[],
            budgets=Budgets(max_steps=int(self.max_steps)),
            reward=RewardSpec(dense="sparse"),
            step_s=0.02,
            doc=s.doc,
        )

    def info_extra(self) -> dict:
        return {
            "goal": self.goal,
            "embodied_playground_task": self.task_id,
            "condition": self.condition,
            "spring_stiffness_n_per_m": self.meta.get("spring_stiffness"),
            "control_period_s": self.meta.get("control_period_s"),
            "robots": self.meta.get("robots"),
            "neutral_action": self.meta.get("neutral_action"),
            "simulator": {"mujoco": self.meta.get("mujoco"), "embodied_playground": source.REVISION[:12]},
        }


# ---- reference solution -------------------------------------------------------------------------------------------
def oracle_main(env: str) -> None:
    """Replay the task's reference shot (oracle/plan.json, one plan per condition) through `robo act`. The plans were
    found by the suite's generator in simulation: a scripted pull-and-release of the launcher (planner.py), checked by
    expanding them exactly as here."""
    from ...agent_cli import _send
    from .planner import expand

    plans = json.loads(Path(env).read_text())
    info = _send({"op": "info"})
    if not info.get("ok"):
        raise SystemExit(f"oracle: {info.get('error')}")
    res = info["result"]
    plan = plans["conditions"][str(res.get("condition", 1))]["plan"]
    cap = int(res.get("max_repeat", 50))
    runs: list[list] = []  # [action, repeat], equal consecutive actions merged
    for a in expand(plan, res["neutral_action"]):
        if runs and runs[-1][0] == a:
            runs[-1][1] += 1
        else:
            runs.append([a, 1])
    for action, repeat in runs:
        left = repeat
        while left > 0:
            n = min(cap, left)
            r = _send({"op": "act", "action": action, "repeat": n})
            if not r.get("ok"):
                if "finished" in str(r.get("error", "")):
                    return  # solved: the episode ended at the first success
                raise SystemExit(f"oracle: {r.get('error')}")
            if str((r.get("result") or {}).get("episode", "")).startswith("finished"):
                return
            left -= n
    _send({"op": "done", "text": "oracle: reference shot replayed"})
