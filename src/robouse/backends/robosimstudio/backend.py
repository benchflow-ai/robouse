"""RoboSimStudio's bag and band tasks, behind the episode server and its step budget.

The downloaded examples, scene builders, robot models and evaluators run unmodified in a separate Python environment.
Each action is two native absolute tool poses: left x/y/z, xyzw quaternion, grip (0 open, 1 closed), then right.
Agents see the cameras and the robot's own state. Only the reference solution sees the material's geometry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ... import config
from ...core.embodiment_spec import Budgets, Camera, Embodiment, Field, RewardSpec, Sensors
from ...workers.client import StdioWorker
from ..base import ActionSpec, Backend, G, StepInfo, groups_from_layout
from . import source

WORKER = Path(__file__).with_name("worker.py")
NATIVE_W, NATIVE_H = 480, 320
PUBLIC_FIELDS = tuple(
    f"{arm}_{field}"
    for arm in ("left", "right")
    for field in ("tcp_pos", "tcp_quat", "joint_pos", "joint_vel", "gripper_width")
) + (
    "previous_action",
    "step_index",
    "simulation_time_s",
)


class RoboSimStudioBackend(Backend):
    name = "robosimstudio"
    robot_kind = "bimanual"
    robot_name = "robosimstudio-yam"
    camera = "overview"
    proprioception = PUBLIC_FIELDS
    probe_success = False
    dense_reward = "shaped"

    def __init__(self, spec: dict):
        super().__init__(spec)
        self.case = str(spec.get("env", ""))
        if self.case not in source.CASES:
            raise ValueError(f"robosimstudio tasks: {', '.join(source.CASES)}; got {self.case!r}")
        self.max_steps = int(spec.get("max_steps", 1200))
        package = source.require()
        self.worker = StdioWorker(
            "robosimstudio",
            config.sim_python("robosimstudio"),
            WORKER,
            setup=config.SUITES_DOCS,
            env={
                "ROBOSIMSTUDIO_DEVICE": "cpu",
                "PYTHONPATH": str(package),
                "PYTHONPYCACHEPREFIX": str(config.cache_dir() / "robosimstudio-pycache"),
                "WARP_CACHE_PATH": str(config.cache_dir() / "robosimstudio-kernels"),
            },
        )
        try:
            self.meta = self.worker.call("make", package_root=str(package), case=self.case, max_steps=self.max_steps)
        except Exception:
            self.worker.close()
            raise
        self.last = list(self.meta["neutral_action"])
        self._state: dict | None = None
        self._fresh = True
        self.last_judge: dict | None = None
        names = [
            f"{arm}_{part}" for arm in ("left", "right") for part in ("x", "y", "z", "qx", "qy", "qz", "qw", "grip")
        ]
        self.action_spec = ActionSpec(
            names,
            [-0.1, -0.7, 0.60, -1, -1, -1, -1, 0] * 2,
            [1.3, 0.7, 1.6, 1, 1, 1, 1, 1] * 2,
            "Left then right: absolute tool x/y/z in world metres, xyzw quaternion, grip (0 open, 1 closed). "
            "Native RoboSimStudio Cartesian IK and physical joint servos; no object teleportation.",
        )

    def reset(self, seed: int) -> None:
        # These are fixed upstream example layouts; changing the seed does not create a new layout.
        if self._fresh:
            self._fresh = False
            return
        self.meta = self.worker.call("reset")
        self.last = list(self.meta["neutral_action"])
        self._state = None
        self.last_judge = None

    def step(self, action: Any) -> StepInfo:
        values = self.action_spec.clip(action)
        result = self.worker.call("step", action=values.tolist())
        self.last = result["action"]
        self._state = None
        return StepInfo(
            bool(result["success"]),
            float(result["reward"]),
            {k: result[k] for k in ("terminated", "truncated", "close_kind")},
        )

    def hold_action(self) -> list[float]:
        return list(self.last)

    def observe(self) -> dict:
        if self._state is None:
            self._state = self.worker.call("observe")
        return dict(self._state)

    def privileged_state(self) -> dict:
        return {"scene": self.worker.call("privileged")}

    def success(self) -> bool:
        result = self.worker.call("success")
        self.last_judge = result["detail"]
        return bool(result["success"])

    def render(self, width: int | None = None, height: int | None = None) -> np.ndarray:
        return self.worker.call("render", width=width or NATIVE_W, height=height or NATIVE_H)

    def camera_info(self, cameras: list[str]) -> list[dict]:
        return self.worker.call("camera_info") if self.camera in cameras else []

    def action_layout(self) -> list[G]:
        return [
            G(
                arm,
                8,
                "ee_pose_abs",
                "m, quaternion xyzw, grip",
                hold="last",
                doc="absolute tool pose in world coordinates; grip 0 open, 1 closed",
            )
            for arm in ("left", "right")
        ]

    def embodiment(self) -> Embodiment:
        return Embodiment(
            name=self.robot_name,
            kind=self.robot_kind,
            action_groups=groups_from_layout(self.action_spec, self.action_layout()),
            sensors=Sensors(
                cameras=[Camera(self.camera, "world", NATIVE_W, NATIVE_H)],
                proprioception=[Field(name) for name in self.proprioception],
            ),
            skills=[],
            budgets=Budgets(max_steps=self.max_steps),
            reward=RewardSpec(dense="shaped", success_mode="first"),
            step_s=1.0 / self.meta["control_hz"],
            doc=self.action_spec.doc,
        )

    def info_extra(self) -> dict:
        return {
            "robosimstudio_task": self.case,
            "arms": self.meta["arms"],
            "neutral_action": self.meta["neutral_action"],
            "control_hz": self.meta["control_hz"],
            "simulator": {
                "revision": source.REVISION,
                **{k: self.meta[k] for k in ("mujoco", "newton", "superdex", "platform")},
            },
        }

    def close(self) -> None:
        self.worker.close()
