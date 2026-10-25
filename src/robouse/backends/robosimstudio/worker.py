"""RoboSimStudio worker. Runs in its Python 3.12 environment, without importing Robo Use.

The two upstream examples build their own task, scene and evaluator. Intercept only their call to open a studio:
there is no browser or HTTP server. Actions go through the simulator's native absolute Cartesian controller;
the arm's IK and joint servos move the hands, and contact moves the material. No object poses are assigned.
"""

from __future__ import annotations

import importlib.util
import sys
from importlib.metadata import version
from pathlib import Path

import numpy as np

CASES = {"open-bag": "06_bag_scored.py", "hook-band": "07_band_scored.py"}


class Worker:
    def __init__(self) -> None:
        self.env = None
        self.renderers = {}
        self.modules = {}

    def make(self, package_root: str, case: str, max_steps: int = 1200) -> dict:
        if case not in CASES:
            raise ValueError(f"unsupported RoboSimStudio task {case!r}")
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.root = Path(package_root).resolve()
        sys.path.insert(0, str(self.root))
        import robosimstudio as rss
        import robosimstudio_bench as bench

        if not Path(rss.__file__).resolve().is_relative_to(self.root):
            raise RuntimeError("RoboSimStudio was imported from outside the pinned source folder")
        self.close()
        filename = self.root / "examples" / "06_tasks" / CASES[case]
        if case not in self.modules:
            name = f"robouse_rss_{case.replace('-', '_')}"
            spec = importlib.util.spec_from_file_location(name, filename)
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {filename}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            self.modules[case] = module
        opened = []
        view = rss.view
        try:
            rss.view = lambda env, **kwargs: opened.append(env)
            self.modules[case].main()
        finally:
            rss.view = view
        if len(opened) != 1 or not isinstance(opened[0], bench.Env):
            raise RuntimeError("the scored example did not build exactly one task environment")
        self.env = opened[0]
        self.case = case
        self.env.max_steps = max_steps
        self.env.use_control("ee_pose_abs")
        self.arms = list(self.env.scene.embodiment.iks)
        if self.arms != ["left", "right"]:
            raise RuntimeError(f"the pinned example's action order changed: {self.arms}")
        self.last = self.env.idle_action().astype(float)
        self.last_info = self.env.evaluate()[2]
        return self.metadata()

    def metadata(self) -> dict:
        import mujoco
        import newton

        return {
            "arms": self.arms,
            "neutral_action": self.last.tolist(),
            "control_hz": float(self.env.request.physics.control_hz),
            "platform": str(self.env.platform),
            "mujoco": mujoco.__version__,
            "newton": getattr(newton, "__version__", "unknown"),
            "superdex": version("superdex-physics"),
        }

    def reset(self) -> dict:
        self.env.reset()
        self.env.use_control("ee_pose_abs")
        self.last = self.env.idle_action().astype(float)
        self.last_info = self.env.evaluate()[2]
        return self.metadata()

    def step(self, action: list[float]) -> dict:
        values = np.asarray(action, dtype=float)
        if values.shape != (16,) or not np.isfinite(values).all():
            raise ValueError("RoboSimStudio actions must contain 16 finite values")
        for i in range(2):
            q = values[i * 8 + 3 : i * 8 + 7]
            norm = float(np.linalg.norm(q))
            if norm < 1e-8:
                raise ValueError("a tool quaternion must have nonzero length")
            values[i * 8 + 3 : i * 8 + 7] = q / norm
            values[i * 8 + 7] = np.clip(values[i * 8 + 7], 0.0, 1.0)
        _, reward, terminated, truncated, info = self.env.step(values)
        self.last = values
        self.last_info = info
        return {
            "success": bool(info["success"]),
            "reward": float(reward),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "close_kind": info.get("close_kind"),
            "action": values.tolist(),
        }

    def observe(self) -> dict:
        out = {
            "previous_action": self.last.tolist(),
            "step_index": int(self.env.step_count),
            "simulation_time_s": float(self.env.sim_time),
        }
        q = self.env.state.joint_q.numpy()
        qd = self.env.state.joint_qd.numpy()
        for arm in self.arms:
            ik = self.env.arm(arm)
            pos, quat = ik.ee_pose(self.env.state)
            out[f"{arm}_tcp_pos"] = pos.tolist()
            out[f"{arm}_tcp_quat"] = quat.tolist()
            out[f"{arm}_joint_pos"] = q[ik.arm_coords].tolist()
            out[f"{arm}_joint_vel"] = qd[ik.arm_dofs].tolist()
            out[f"{arm}_gripper_width"] = float(self.env.gripper(arm).width(self.env.state))
        return out

    def privileged(self) -> dict:
        """Reference-solution geometry, served only through the episode server's oracle channel."""
        if self.case == "open-bag":
            bag = self.env["bag"]
            points = np.asarray(bag.particle_q)
            lip = points[bag.entity.top[int(bag.entity.spec.cells[0]) + 1 :].ravel()]
            order = np.argsort(lip[:, 2])
            return {"lip": [float(np.median(lip[:, 0])), float(np.interp(0.753, lip[order, 2], lip[order, 1])), 0.753]}
        points = np.asarray(self.env["band"].particle_q)
        return {"band_bottom": points[np.argmin(points[:, 2])].tolist()}

    def success(self) -> dict:
        _, _, self.last_info = self.env.evaluate()
        return {"success": bool(self.last_info["success"]), "detail": self.last_info.get("metrics", {})}

    def _camera(self, width: int, height: int):
        from robosimstudio.core.cameras import CameraSpec

        z = float(self.env.scene.handles.surface_z)
        return CameraSpec(
            name="overview",
            width=width,
            height=height,
            fov_y=45.0,
            eye=(-0.1, -0.85, z + 0.68),
            look_at=(0.60, -0.08, z + 0.12),
            up=(0.0, 0.0, 1.0),
            near=0.01,
            far=8.0,
        )

    def render(self, width: int = 480, height: int = 320) -> np.ndarray:
        size = (width, height)
        if size not in self.renderers:
            self.renderers[size] = self.env.make_renderer(
                "tiled", cameras=[self._camera(width, height)], channels=("rgb",)
            )
        frame = self.renderers[size].render(self.env.state)["overview"]["rgb"]
        return np.asarray(frame, dtype=np.uint8)

    def camera_info(self, width: int = 480, height: int = 320) -> list[dict]:
        camera = self._camera(width, height)
        k = camera.intrinsics
        extrinsic = np.linalg.inv(camera.world_matrix)[:3]
        return [
            {
                "name": "overview",
                "width": width,
                "height": height,
                "projection": (k @ extrinsic).tolist(),
                "intrinsics": k.tolist(),
                "extrinsics": extrinsic.tolist(),
            }
        ]

    def close(self) -> None:
        for renderer in self.renderers.values():
            renderer.close()
        self.renderers = {}
        if self.env is not None:
            self.env.close()
            self.env = None
