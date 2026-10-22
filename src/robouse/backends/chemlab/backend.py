"""chemlab backend: a ChemLab-Assets laboratory instrument on a bench, operated by a floating two-finger gripper.

The instrument is its URDF converted to MuJoCo (scene.py), with the behaviour runtime from the same release driven
alongside (runtime.py). The robot is the Franka Hand (MuJoCo Menagerie's model of the Franka Emika Panda's hand) on a
free body welded to a mocap target, as the tabletop suites' gripper is, with one more degree of freedom: it turns about
its own tool axis ("twist"), so it can turn knobs. Its tool axis is fixed per task: pointing down, or pointing
horizontally into the instrument (+y).

Action: [dx, dy, dz, dtwist, grip] in [-1, 1]. dx/dy/dz move the tool point (between the fingertips) by about 1 cm per
unit per step; dtwist turns the gripper about its tool axis by 5 degrees per unit per step (positive: clockwise seen
from behind the gripper, looking along its tool axis); grip +1 closes the fingers, -1 opens them, values in between
give a partial opening (finger gap = 8 cm * (1 - grip) / 2). One step = 20 ms (10 physics steps of 2 ms). `robo
move-to` and `robo grip` send [dx, dy, dz, grip] (no twist).

Frame: the instrument's own frame (metres; +x right, +y toward the back, +z up; the front faces -y; the bench top is
z = 0 under the instrument's footprint, centred on the origin).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..base import ActionSpec, Backend, G, StepInfo
from . import assets
from .instruments import DEFAULT_JOINT, INSTRUMENTS, Instrument
from .runtime import Runtime
from .scene import FINGER_OPEN, GRIP_OPEN_CTRL, HAND, SETTLE_SUBSTEPS, SUBSTEPS, hand_quat, read_urdf, scene_model
from .tasks import TASKS, Task

STEP_M = 0.01  # metres per action unit per step
TWIST_STEP = math.radians(5.0)  # radians per action unit per step
TWIST_LIMIT = math.radians(720.0)
TWIST_LEAD = math.radians(20.0)  # the commanded twist stays this close to the gripper's actual twist
LEAD_M = 0.03  # the target stays this close to the tool point (no wind-up when the hand is blocked)
# A part the runtime moves on its own follows it under this PD force (N/m, N s/m, N): the one such part is the fume
# hood's sash (16 kg, 20 N of friction), which this tracks within about 5 mm while it creeps at 2 cm/s.
FOLLOW_KP, FOLLOW_KD, FOLLOW_MAX = 10000.0, 1200.0, 400.0
DT = SUBSTEPS * 0.002


def _r(v, n: int = 4) -> list[float]:
    return [round(float(x), n) for x in v]


def task_of(spec: dict) -> Task:
    key = str(spec.get("env") or spec.get("id"))
    if key not in TASKS:
        raise KeyError(f"unknown chemlab task {key!r}; tasks: {', '.join(sorted(TASKS))}")
    return TASKS[key]


def scene_config(inst: Instrument, task: Task) -> dict:
    return {
        "joints": inst.joints,
        "default_joint": DEFAULT_JOINT,
        "colliders": inst.colliders,
        "bench_half": inst.bench_half,
        "home": task.home,
        "approach": task.approach,
        "cameras": inst.cameras,
    }


class ChemLabBackend(Backend):
    name = "chemlab"
    robot_name = "floating-gripper-2f-twist"
    probe_success = False  # step() already evaluates success()
    proprioception = ("hand_pos", "hand_twist_deg", "gripper_open")

    def __init__(self, spec: dict):
        import mujoco

        self.spec = spec
        self.task = task_of(spec)
        self.inst = INSTRUMENTS[self.task.instrument]
        root = assets.require([self.inst.path, *self.inst.files()])
        self.max_steps = int(spec.get("max_steps", self.task.max_steps))
        self.camera = str(spec.get("camera", self.task.camera))
        self._mj = mujoco
        urdf = read_urdf(root / self.inst.urdf)
        self.model = scene_model(urdf, scene_config(self.inst, self.task))
        self.data = mujoco.MjData(self.model)
        self.action_spec = ActionSpec(
            names=["dx", "dy", "dz", "dtwist", "grip"],
            low=[-1, -1, -1, -1, -1],
            high=[1, 1, 1, 1, 1],
            doc="dx/dy/dz: tool point velocity, about 1 cm per unit per step; dtwist: turn about the tool axis, "
            "5 degrees per unit per step (positive: clockwise seen from behind the gripper); grip: +1 close, "
            "-1 open (intermediate values give a partial opening: finger gap = 8 cm * (1 - grip) / 2)",
        )
        m = self.model
        self._hand = m.body("hand").id
        self._lo = np.asarray(self.task.workspace[0], float)
        self._hi = np.asarray(self.task.workspace[1], float)
        self._fl = m.jnt_qposadr[m.joint(HAND + "finger_joint1").id]
        self._fr = m.jnt_qposadr[m.joint(HAND + "finger_joint2").id]
        self._grip_act = m.actuator(HAND + "actuator8").id
        # the operated joints, and which instrument geoms belong to each part (its joint's body and its children)
        self._joint = {}
        for j in {*(p.joint for p in self.task.parts), *self.task.start, *self._runtime_joints()}:
            jid = m.joint(j).id
            self._joint[j] = (jid, int(m.jnt_qposadr[jid]), int(m.jnt_dofadr[jid]), int(m.jnt_bodyid[jid]))
        self._part_of_geom: dict[int, str] = {}
        for g in range(m.ngeom):
            if m.geom_contype[g] != 2:
                continue
            b, owner = int(m.geom_bodyid[g]), "instrument"
            while b > 0:
                hit = [j for j, (_, _, _, jb) in self._joint.items() if jb == b]
                if hit:
                    owner = hit[0]
                    break
                b = int(m.body_parentid[b])
            self._part_of_geom[g] = owner
        # the hand's collision geoms: its mesh, and each finger's mesh and fingertip pads
        hand_bodies = {b for b in range(m.nbody) if m.body(b).name.startswith(HAND)}
        self._gripper_geoms = {g for g in range(m.ngeom) if m.geom_bodyid[g] in hand_bodies and m.geom_contype[g]}
        self._renderers: dict = {}
        self.runtime: Runtime | None = None
        self.steps = 0

    def _runtime_joints(self) -> list[str]:
        return list(self.inst.runtime.joints) if self.inst.runtime else []

    # ---- embodiment ------------------------------------------------------------------------------------------------
    def action_layout(self) -> list[G]:
        return [
            G("arm.ee_delta", 3, "ee_delta_pos", "tool point velocity, about 1 cm per unit per step", frame="world"),
            G("arm.ee_twist", 1, "ee_delta_rot", "5 degrees per unit per step, about the tool axis"),
            G("gripper", 1, "gripper", "normalized", hold="last", initial=-1.0, doc="+1 close, -1 open"),
        ]

    def skills(self) -> list[str]:
        return ["move_to", "grip"]

    # ---- lifecycle -------------------------------------------------------------------------------------------------
    def reset(self, seed: int) -> None:
        mj, m, d = self._mj, self.model, self.data
        mj.mj_resetData(m, d)
        for j, q in self.task.start.items():
            d.qpos[self._joint[j][1]] = q
        self._twist = 0.0
        d.mocap_pos[0] = self.task.home
        d.mocap_quat[0] = hand_quat(self.task.approach, 0.0)
        self._grip = -1.0
        d.ctrl[self._grip_act] = GRIP_OPEN_CTRL
        d.qpos[self._fl] = d.qpos[self._fr] = FINGER_OPEN
        mj.mj_forward(m, d)
        for _ in range(SETTLE_SUBSTEPS):
            mj.mj_step(m, d)
        self.steps = 0
        self.runtime = None
        if self.inst.runtime:
            self.runtime = Runtime(self.inst.runtime)
            self.runtime.sync(self._q(), set(), 0.0)
            self.runtime.warm_up()

    def close(self) -> None:
        for r in self._renderers.values():
            r.close()
        self._renderers = {}

    # ---- stepping --------------------------------------------------------------------------------------------------
    def step(self, action) -> StepInfo:
        mj, m, d = self._mj, self.model, self.data
        a = np.asarray(action, dtype=float)
        if a.shape == (4,):  # move_to / grip / the settle hold: [dx, dy, dz, grip]
            a = np.array([a[0], a[1], a[2], 0.0, a[3]])
        a = self.action_spec.clip(a)
        self._grip = float(a[4])
        hp = self.hand_pos()
        tgt = np.clip(d.mocap_pos[0] + a[:3] * STEP_M, self._lo, self._hi)
        d.mocap_pos[0] = hp + np.clip(tgt - hp, -LEAD_M, LEAD_M)
        actual = self.hand_twist()
        tw = float(np.clip(self._twist + a[3] * TWIST_STEP, -TWIST_LIMIT, TWIST_LIMIT))
        self._twist = float(np.clip(tw, actual - TWIST_LEAD, actual + TWIST_LEAD))
        d.mocap_quat[0] = hand_quat(self.task.approach, self._twist)
        d.ctrl[self._grip_act] = GRIP_OPEN_CTRL * (1.0 - self._grip) / 2.0
        held = self.touching()
        follow = self._follow_targets(held)
        for _ in range(SUBSTEPS):
            for dof, (target, qadr) in follow.items():
                f = FOLLOW_KP * (target - d.qpos[qadr]) - FOLLOW_KD * d.qvel[dof]
                d.qfrc_applied[dof] = float(np.clip(f, -FOLLOW_MAX, FOLLOW_MAX))
            mj.mj_step(m, d)
        for dof in follow:
            d.qfrc_applied[dof] = 0.0
        self.steps += 1
        if self.runtime:
            self.runtime.sync(self._q(), self.touching(), DT)
        return StepInfo(success=self.success())

    def _follow_targets(self, held: set[str]) -> dict[int, tuple[float, int]]:
        """Parts the runtime is moving on its own (and the gripper does not hold): dof -> (target, qpos address)."""
        out: dict[int, tuple[float, int]] = {}
        if not self.runtime:
            return out
        for j in self._runtime_joints():
            if j in held:
                continue
            target = self.runtime.joint_target(j)
            if target is not None:
                _, qadr, dof, _ = self._joint[j]
                out[dof] = (target, qadr)
        return out

    # ---- state -----------------------------------------------------------------------------------------------------
    def _q(self) -> dict[str, float]:
        return {j: float(self.data.qpos[qadr]) for j, (_, qadr, _, _) in self._joint.items()}

    def hand_pos(self) -> np.ndarray:
        return self.data.xpos[self._hand].copy()

    def hand_twist(self) -> float:
        """The gripper's actual twist about its tool axis (radians), continuous with the commanded one."""
        q0 = np.asarray(hand_quat(self.task.approach, 0.0))
        qh = self.data.xquat[self._hand]
        w0, x0, y0, z0 = q0
        conj = np.array([w0, -x0, -y0, -z0])
        mj = self._mj
        rel = np.zeros(4)
        mj.mju_mulQuat(rel, conj, qh)
        angle = -2.0 * math.atan2(rel[3], rel[0])
        cmd = getattr(self, "_twist", 0.0)
        return cmd + (angle - cmd + math.pi) % (2 * math.pi) - math.pi

    def touching(self) -> set[str]:
        """The joints of the parts the gripper touches ("instrument" for the rest of the instrument)."""
        out = set()
        d = self.data
        for i in range(d.ncon):
            c = d.contact[i]
            g1, g2 = int(c.geom1), int(c.geom2)
            if g1 in self._gripper_geoms and g2 in self._part_of_geom:
                out.add(self._part_of_geom[g2])
            elif g2 in self._gripper_geoms and g1 in self._part_of_geom:
                out.add(self._part_of_geom[g1])
        return out

    def _point(self, link: str, offset) -> np.ndarray:
        b = self.model.body(f"i_{link}").id
        return self.data.xpos[b] + self.data.xmat[b].reshape(3, 3) @ np.asarray(offset, float)

    def part_value(self, part) -> float:
        q = float(self.data.qpos[self._joint[part.joint][1]]) / part.scale
        return math.degrees(q) if part.quantity.endswith("_deg") else q

    def observe(self) -> dict[str, Any]:
        d = self.data
        ql, qr = d.qpos[self._fl], d.qpos[self._fr]
        labels = {p.joint: p.label for p in self.task.parts}
        touching = sorted(labels.get(j, "instrument") for j in self.touching())
        parts = {}
        for p in self.task.parts:
            v = self.part_value(p)
            e: dict[str, Any] = {p.quantity: round(v, 1) if p.quantity.endswith("_deg") else round(v, 4)}
            for name, pt in p.points.items():
                e[name] = _r(self._point(pt.link, pt.offset))
            e.update({k: v for k, v in p.sizes.items() if not isinstance(v, str)})
            parts[p.label] = e
        out: dict[str, Any] = {
            "hand_pos": _r(self.hand_pos()),
            "hand_twist_deg": round(math.degrees(self.hand_twist()), 1),
            "gripper_open": round(float((ql + qr) / (2 * FINGER_OPEN)), 3),
            "touching": touching,
            "parts": parts,
        }
        if self.runtime and self.runtime.spec.readouts:
            out["readouts"] = self.runtime.readouts()
        return out

    # ---- scoring ---------------------------------------------------------------------------------------------------
    def _evaluate(self) -> tuple[dict[str, bool], dict[str, Any]]:
        """Each of the task's checks, and the values it read (joints, runtime slots, what the gripper touches)."""
        q = self._q()
        held = self.touching()
        truth = self.runtime.read("host") if self.runtime else {}
        checks: dict[str, bool] = {}
        seen: dict[str, Any] = {}
        for c in self.task.checks:
            if "joint" in c:
                v = q[c["joint"]] / c.get("scale", 1.0)
                seen[c["joint"]] = round(v, 5)
                checks[f"{c['joint']} in [{c.get('min', '')}, {c.get('max', '')}]"] = bool(
                    c.get("min", -math.inf) <= v <= c.get("max", math.inf)
                )
            elif "runtime" in c:
                v = truth.get(c["runtime"])
                seen[c["runtime"]] = round(v, 5) if isinstance(v, float) else v
                if "equals" in c:
                    ok = v == c["equals"]
                else:
                    ok = isinstance(v, (int, float)) and c.get("min", -math.inf) <= v <= c.get("max", math.inf)
                checks[f"runtime {c['runtime']}"] = bool(ok)
            elif "released" in c:
                seen["touching"] = sorted(held)
                checks["released"] = not (held & set(c["released"]))
        return checks, seen

    def checks(self) -> dict[str, bool]:
        return self._evaluate()[0]

    def success(self) -> bool:
        return all(self.checks().values())

    def judge(self, outcome: str, text: str = "") -> bool:
        checks, seen = self._evaluate()
        self.last_judge: dict[str, Any] = {"checks": checks, "values": seen}  # recorded in the episode's result.json
        if self.runtime and self.runtime.log:
            self.last_judge["runtime_refused"] = self.runtime.log
        return outcome == "done" and all(checks.values())

    # ---- rendering -------------------------------------------------------------------------------------------------
    def mj_model_data(self):
        return self.model, self.data

    def render(self, width: int = 480, height: int = 480) -> np.ndarray:
        key = (width, height)
        r = self._renderers.get(key)
        if r is None:
            r = self._renderers[key] = self._mj.Renderer(self.model, height, width)
        r.update_scene(self.data, camera=self.camera)
        return r.render().copy()
