"""Simulator worker for the `embodied_playground` backend: Embodied Playground's Launcher tasks on its own MuJoCo package
(`agentbench_mujoco`, from the pinned download), in its own virtualenv (Python 3.11, MuJoCo 3.3.7, Embodied Playground's
pins).

This file runs inside that virtualenv, where robouse is not installed: standard library, numpy, mujoco, gymnasium,
Pillow and the downloaded package. The environment is Embodied Playground's own `FrankaCampaignEnv`, unmodified: its
scene builder, its spring launcher, its damage, fracture and toppling models, its rule checks and its success rule.
This worker only drives it: it builds the task's condition, steps it with the task's 16-number action, reports the
public observation Embodied Playground's Level 0 allows (the robots' joint positions and velocities and the previous
action), renders its `front_left` view, and reports the environment's own verdict.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import mujoco
import numpy as np

PLANNER = Path(__file__).with_name("planner.py")
CAMERA = "front_left"
NATIVE_W, NATIVE_H = 640, 400  # Embodied Playground's camera resolution
SIDES = (("left", ""), ("right", "aim_"))  # the action's arm order and the model's joint prefixes


def _r(v, n: int = 5) -> list[float]:
    return [round(float(x), n) for x in np.ravel(v)]


def _planner():
    spec = importlib.util.spec_from_file_location("robouse_ep_planner", PLANNER)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {PLANNER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Worker:
    def __init__(self) -> None:
        self.env = None
        self.task: dict = {}

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    def make(self, package_parent: str, task: dict, seed: int = 0) -> dict:
        """Import Embodied Playground's MuJoCo package from `package_parent` (the bridge has checked every module's
        hash) and build the task: {"scenario", "initial_mode", "environment_parameters", "max_seconds"}."""
        if package_parent not in sys.path:
            sys.path.insert(0, package_parent)
        from agentbench_mujoco.campaign_env import FrankaCampaignEnv
        from agentbench_mujoco.campaign_scene import SCENARIOS

        if task["scenario"] not in SCENARIOS:
            raise ValueError(f"unknown Launcher scenario {task['scenario']!r}")
        self.task = dict(task)
        self.cls = FrankaCampaignEnv
        return self.reset(seed)

    def reset(self, seed: int = 0) -> dict:
        """A fresh environment for the task's condition, reset with `seed` (the benchmark's reset seed is 0)."""
        if self.env is not None:
            self.env.close()
        params = dict(self.task.get("environment_parameters") or {})
        self.env = self.cls(
            scenario=self.task["scenario"],
            initial_mode=self.task.get("initial_mode", "loaded"),
            observation_mode="state",
            render_mode="rgb_array",
            width=NATIVE_W,
            height=NATIVE_H,
            **params,
        )
        if self.task.get("max_seconds"):
            self.env.max_seconds = min(self.env.max_seconds, float(self.task["max_seconds"]))
        self.env.reset(seed=int(seed))
        self.done = {"terminated": False, "truncated": False}
        return self.meta()

    def meta(self) -> dict:
        e = self.env
        m = e.model
        robots = {}
        for side, prefix in SIDES:
            jid = [m.joint(f"{prefix}joint{i}").id for i in range(1, 8)]
            robots[side] = {
                "model": "Franka Panda",
                "joint_names": [f"{prefix}joint{i}" for i in range(1, 8)],
                "joint_limits": [_r(x, 4) for x in m.jnt_range[jid]],
            }
        return {
            "low": _r(e.action_space.low, 4),
            "high": _r(e.action_space.high, 4),
            "neutral_action": _r(e.last_action, 4),
            "control_period_s": e.physics_dt * e.decimation,
            "max_steps": int(np.ceil(e.max_seconds / (e.physics_dt * e.decimation) - 1e-9)),
            "robots": robots,
            "spring_stiffness": float(e.spring_stiffness),
            "mujoco": mujoco.__version__,
        }

    # ---- control ---------------------------------------------------------------------------------------------------
    def step(self, action: list[float]) -> dict:
        """One control step (20 ms, 20 physics steps). Once the environment has ended (success, a rule or physical
        violation, its time limit, or every projectile spent), further steps change nothing."""
        e = self.env
        if not (self.done["terminated"] or self.done["truncated"]):
            a = np.clip(np.asarray(action, dtype=np.float64), e.action_space.low, e.action_space.high)
            _, _, terminated, truncated, _ = e.step(a)
            self.done = {"terminated": bool(terminated), "truncated": bool(truncated)}
        return {"success": bool(e.success), **self.done, "failure": e.failure}

    def step_result(self) -> dict:
        return {"success": bool(self.env.success), **self.done, "failure": self.env.failure}

    # ---- observation -----------------------------------------------------------------------------------------------
    def observe(self) -> dict:
        """The public state: what Embodied Playground's Level 0 allows (proprioception, the clock, the end flags)."""
        e, d = self.env, self.env.data
        out: dict = {}
        for i, (side, _) in enumerate(SIDES):
            out[f"{side}_joint_pos"] = _r(d.qpos[e.robot_q[7 * i : 7 * i + 7]])
            out[f"{side}_joint_vel"] = _r(d.qvel[e.robot_v[7 * i : 7 * i + 7]], 4)
            out[f"{side}_finger_pos"] = _r(d.qpos[e.finger_q[2 * i : 2 * i + 2]])
        out["previous_action"] = _r(e.last_action, 4)
        out["step_index"] = int(e.control_steps)
        out["simulation_time_s"] = round(float(d.time), 3)
        out["terminated"] = self.done["terminated"]
        out["truncated"] = self.done["truncated"]
        return out

    def privileged(self) -> dict:
        """What only the reference solution and the records see: the launcher, the projectiles, the targets."""
        e, d = self.env, self.env.data
        return {
            "phase": e.phase,
            "failure": e.failure,
            "draw_m": round(float(d.qpos[e.draw_q]), 4),
            "elevation_deg": round(float(np.rad2deg(d.qpos[e.elevation_q])) + 30.0, 2),
            "handle_pos": _r(d.site("handle_site").xpos, 4),
            "load_site_pos": _r(d.site("load_site").xpos, 4),
            "ammo": [
                {"name": a["name"], "kind": a["kind"], "pos": _r(d.xpos[b], 4), "status": int(s)}
                for a, b, s in zip(e.scene_spec["ammo"], e.ammo_ids, e.ammo_status, strict=True)
            ],
            "targets": [
                {"pos": _r(t["pos"], 4), "alive": bool(alive), "protected": i in e.protected_indices}
                for i, (t, alive) in enumerate(zip(e.scene_spec["targets"], e.target_alive, strict=True))
            ],
            "toppled": sorted(e.toppled),
        }

    def render(self, width: int | None = None, height: int | None = None) -> np.ndarray:
        img = self.env.render()
        if width and height and (int(width), int(height)) != (img.shape[1], img.shape[0]):
            from PIL import Image

            img = np.asarray(Image.fromarray(img).resize((int(width), int(height)), Image.BILINEAR))
        return np.ascontiguousarray(img, dtype=np.uint8)

    def camera_info(self, width: int = NATIVE_W, height: int = NATIVE_H) -> list[dict]:
        """The `front_left` view's 3x4 projection P with [u*w, v*w, w] = P @ [x, y, z, 1] in an image of width x height
        pixels, computed the way Embodied Playground calibrates it (the rendered scene's camera, MuJoCo's frustum)."""
        e = self.env
        self.env.render()  # the scene's camera is set when it renders
        cam = mujoco.mjv_averageCamera(e.renderer.scene.camera[0], e.renderer.scene.camera[1])
        forward, up, pos = np.asarray(cam.forward), np.asarray(cam.up), np.asarray(cam.pos)
        right = np.cross(forward, up)
        fy = NATIVE_H * cam.frustum_near / (cam.frustum_top - cam.frustum_bottom)
        k = np.array([[fy, 0.0, NATIVE_W / 2], [0.0, fy, NATIVE_H / 2], [0.0, 0.0, 1.0]])
        rot = np.column_stack((right, -up, forward))  # world from camera, OpenCV axes (x right, y down, z forward)
        ext = np.hstack([rot.T, (-rot.T @ pos)[:, None]])
        proj = np.diag([width / NATIVE_W, height / NATIVE_H, 1.0]) @ k @ ext
        return [
            {
                "name": CAMERA,
                "width": int(width),
                "height": int(height),
                "position": _r(pos, 4),
                "projection": [[round(float(x), 5) for x in row] for row in proj],
            }
        ]

    # ---- judging ---------------------------------------------------------------------------------------------------
    def success(self) -> dict:
        e = self.env
        detail = {
            "required_targets_cleared": int(np.count_nonzero(~e.target_alive[e.required_indices])),
            "required_targets": len(e.required_indices),
            "toppled": sorted(e.toppled),
            "fractured": sorted(e.fracture.broken),
            "shots_fired": len(e.shots),
            "failure": e.failure,
            "phase": e.phase,
            **self.done,
        }
        return {"success": bool(e.success), "detail": detail}

    # ---- reference shots (the suite's generator) ---------------------------------------------------------------------
    def scenarios(self) -> list[str]:
        """The Launcher scenarios in catalog order: task marble/dual-panda/A{i:03d} is scenario i (from 1)."""
        from agentbench_mujoco.campaign_scene import SCENARIOS

        return list(SCENARIOS)

    def try_shot(self, draw: float, seed: int = 0, follow_s: float = 4.0) -> dict:
        """From a fresh reset: the scripted pull-and-release with `draw` metres (planner.py), its plan expanded exactly
        as the reference solution expands it, run until the environment ends. Returns the outcome and the plan."""
        planner = _planner()
        self.reset(seed)
        plan, report = planner.ShotPlanner(self.env).plan(float(draw), follow_s=follow_s)
        return {**self.replay(plan, seed=seed, reset=False), "draw": float(draw), "plan": plan, **report}

    def replay(self, plan: list, seed: int = 0, reset: bool = True) -> dict:
        """Run a plan from a fresh reset (or from now), stopping when the environment ends."""
        planner = _planner()
        if reset:
            self.reset(seed)
        steps = 0
        r = self.step_result()
        for a in planner.expand(plan, list(self.env.last_action)):
            r = self.step(a)
            steps += 1
            if r["terminated"] or r["truncated"]:
                break
        launches = [ev for ev in self.env.events if ev["kind"] == "launched"]
        return {
            **r,
            "steps": steps,
            "launch_speed": round(launches[0]["speed"], 3) if launches else None,
            "launch_elevation_deg": round(launches[0]["elevation_deg"], 2) if launches else None,
            "targets_cleared": int(np.count_nonzero(~self.env.target_alive)),
            "toppled": len(self.env.toppled),
        }

    def close(self) -> None:
        if self.env is not None:
            self.env.close()
            self.env = None
