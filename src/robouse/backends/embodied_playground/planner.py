"""Reference shots for the Launcher tasks: inverse kinematics and a scripted pull-and-release of the launcher.

numpy only at import (mujoco inside the functions that need the model), and no robouse imports: the worker and the
suite's generator load this file by path inside the simulator's virtualenv, and the reference solution imports it in
Robo Use's own environment to expand a plan.

A plan is a list of segments [action, steps, ramp]: `action` is a full 16-number action in the task's layout (per arm
seven absolute joint targets in rad and a gripper command, +1 open and -1 closed; the power arm `left`, model prefix "",
first, then the aiming arm `right`, prefix "aim_"); with ramp 1 the joint targets go linearly from the previous action
to `action` over `steps` steps, with ramp 0 `action` is held for `steps` steps. `expand` turns a plan into per-step
actions, and is the only way a plan is turned into motion, in the generator's check and in the reference solution.

The shot: the power arm rises above and behind the launcher's carriage, comes down onto the line of the slide, moves in
with its fingers open until the carriage's handle is between them, closes them, pulls the carriage back along the slide
by `draw` metres, holds, and opens them. The passive spring sends the carriage forward and the latch releases the
projectile. Embodied Playground's Panda gripper is weak (a few newtons), so the grip slips from about 0.12 m of draw on;
the generator searches draws below that. Which draw hits the target for a task and condition is found by simulation, in
the generator, from the privileged scene; the reference solution replays the plan through `robo act`.
"""

from __future__ import annotations

import numpy as np

OPEN, CLOSED = 1.0, -1.0
CONTROL_DT = 0.02  # one action: 20 physics steps of 1 ms
MAX_JOINT_SPEED = 0.6  # rad/s for the reference motion (the env fails a joint above 1.1x its 2.175 or 2.61 rad/s limit)
SLOW_JOINT_SPEED = 0.25  # rad/s for the last few centimetres onto the handle
PRE_GRASP = 0.09  # m behind the handle along the slide, before moving in
ABOVE = 0.12  # m above the pre-grasp point, the first waypoint
GRASP_DEPTH = 0.0  # m past the handle's centre along the slide at which the fingertip point stops
DIGITS = 5  # plans are stored with joint targets rounded to this many decimals


def _joint_ids(m, prefix: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    jid = np.array([m.joint(f"{prefix}joint{i}").id for i in range(1, 8)])
    return jid, m.jnt_qposadr[jid], m.jnt_dofadr[jid]


def ik(m, d_scratch, prefix: str, pos, rot, q0, iters: int = 300, tol: float = 1e-4) -> tuple[np.ndarray, float]:
    """Joint angles that put the arm's `grasp` site at `pos` with orientation `rot` (3x3, columns = the site's x, y, z
    axes in the world): damped least squares on the site Jacobian, joint limits enforced. Uses `d_scratch` (an MjData of
    the same model holding the scene's current state) and changes only this arm's joints in it. Returns (q, error),
    the error being position error (m) plus 0.1 m per radian of orientation error."""
    import mujoco as mj

    jid, qadr, dadr = _joint_ids(m, prefix)
    site = m.site(f"{prefix}grasp").id
    lo, hi = m.jnt_range[jid, 0], m.jnt_range[jid, 1]
    q = np.clip(np.asarray(q0, dtype=float).copy(), lo, hi)
    pos, rot = np.asarray(pos, dtype=float), np.asarray(rot, dtype=float)
    jacp, jacr = np.zeros((3, m.nv)), np.zeros((3, m.nv))
    err = np.inf
    for _ in range(iters):
        d_scratch.qpos[qadr] = q
        mj.mj_kinematics(m, d_scratch)
        mj.mj_comPos(m, d_scratch)
        cur_p = d_scratch.site_xpos[site].copy()
        cur_r = d_scratch.site_xmat[site].reshape(3, 3).copy()
        ep = pos - cur_p
        er = 0.5 * sum(np.cross(cur_r[:, i], rot[:, i]) for i in range(3))  # orientation error
        err = float(np.linalg.norm(ep) + 0.1 * np.linalg.norm(er))
        if np.linalg.norm(ep) < tol and np.linalg.norm(er) < 10 * tol:
            break
        mj.mj_jacSite(m, d_scratch, jacp, jacr, site)
        jac = np.vstack([jacp[:, dadr], 0.5 * jacr[:, dadr]])
        e = np.r_[ep, 0.5 * er]
        dq = jac.T @ np.linalg.solve(jac @ jac.T + 1e-3 * np.eye(6), e)
        step = np.max(np.abs(dq))
        if step > 0.2:
            dq *= 0.2 / step
        q = np.clip(q + dq, lo, hi)
    return q, err


def frame(approach, closing) -> np.ndarray:
    """Rotation whose z axis is `approach` (palm toward fingertips) and whose y axis is `closing` (the fingers' line),
    made orthogonal to the approach."""
    z = np.asarray(approach, dtype=float)
    z = z / np.linalg.norm(z)
    y = np.asarray(closing, dtype=float)
    y = y - z * float(y @ z)
    y = y / np.linalg.norm(y)
    return np.column_stack([np.cross(y, z), y, z])


def ramp_steps(q_from, q_to, max_speed: float = MAX_JOINT_SPEED) -> int:
    """Control steps for a linear joint move with no joint faster than `max_speed`."""
    q_from, q_to = np.asarray(q_from, dtype=float), np.asarray(q_to, dtype=float)
    return max(1, int(np.ceil(np.max(np.abs(q_to - q_from)) / (max_speed * CONTROL_DT))))


def expand(plan: list, start: list[float]) -> list[list[float]]:
    """Per-step actions of a plan (see the module docstring), from the action in force before it (`start`)."""
    out: list[list[float]] = []
    prev = np.asarray(start, dtype=float)
    for action, steps, ramp in plan:
        a = np.asarray(action, dtype=float)
        n = int(steps)
        if ramp:
            for k in range(1, n + 1):
                v = prev + (a - prev) * (k / n)
                v[7], v[15] = a[7], a[15]  # gripper commands switch at once
                out.append([float(x) for x in v])
        else:
            out.extend([float(x) for x in a] for _ in range(n))
        prev = a
    return out


class ShotPlanner:
    """Builds the power arm's pull-and-release for one environment (an `agentbench_mujoco` FrankaCampaignEnv right
    after reset). The aiming arm holds its pose with its fingers open."""

    def __init__(self, env):
        import mujoco as mj

        self.env = env
        self.m = env.model
        self.scratch = mj.MjData(self.m)
        self.scratch.qpos[:] = env.data.qpos
        mj.mj_forward(self.m, self.scratch)
        self.home = np.asarray(env.last_action, dtype=float).copy()  # 16: the env's neutral action
        d = env.data
        self.handle = d.site("handle_site").xpos.copy()
        # the slide's pull direction in the world (the carriage joint's axis at the current elevation)
        self.pull = d.xaxis[self.m.joint("draw").id].copy()
        self.pull /= np.linalg.norm(self.pull)

    def action(self, left_q, left_grip: float) -> list[float]:
        a = [*map(float, left_q), float(left_grip), *map(float, self.home[8:15]), OPEN]
        return [round(x, DIGITS) for x in a]

    def solve(self, pos, rot, q0) -> tuple[np.ndarray, float]:
        return ik(self.m, self.scratch, "", pos, rot, q0)

    def plan(self, draw: float, pull_s: float = 1.6, hold_s: float = 0.3, follow_s: float = 4.0, closing=(0, 1, 0)):
        """The segments of one shot: approach, grasp, pull by `draw` metres in `pull_s` seconds, hold, release, then
        hold still for `follow_s` seconds. Returns (plan, report)."""
        rot = frame(-self.pull, closing)
        pos_g = self.handle - self.pull * GRASP_DEPTH
        pos_pre = self.handle + self.pull * PRE_GRASP
        pos_up = pos_pre + np.array([0.0, 0.0, ABOVE])
        q_home = self.home[:7]
        q_up, e_up = self.solve(pos_up, rot, q_home)
        q_pre, e_pre = self.solve(pos_pre, rot, q_up)
        q_g, e_g = self.solve(pos_g, rot, q_pre)
        worst = max(e_up, e_pre, e_g)
        plan: list[list] = [
            [self.action(q_up, OPEN), ramp_steps(q_home, q_up), 1],
            [self.action(q_pre, OPEN), ramp_steps(q_up, q_pre), 1],
            [self.action(q_g, OPEN), ramp_steps(q_pre, q_g, SLOW_JOINT_SPEED), 1],
            [self.action(q_g, OPEN), 10, 0],
            [self.action(q_g, CLOSED), 25, 0],  # close and let the grip build
        ]
        n = max(1, int(round(pull_s / CONTROL_DT)))
        q = q_g.copy()
        for k in range(1, n + 1):
            s = draw * (1 - np.cos(np.pi * k / n)) / 2  # smooth start and stop
            q, e = self.solve(pos_g + self.pull * s, rot, q)
            worst = max(worst, e)
            plan.append([self.action(q, CLOSED), 1, 0])
        plan.append([self.action(q, CLOSED), int(round(hold_s / CONTROL_DT)), 0])
        plan.append([self.action(q, OPEN), int(round(follow_s / CONTROL_DT)), 0])
        return plan, {"ik_error": worst}
