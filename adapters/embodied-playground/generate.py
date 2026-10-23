"""Embodied Playground's Launcher tasks (EP-100's Launch suite, on its own MuJoCo package) -> Robo Use tasks.

Embodied Playground (github.com/Winniechen2002/Embodied-Playground) scores agents on 410 environments; its EP-100
benchmark has 100 of them in five suites. Launch, 34 of the 100, is the suite that runs on MuJoCo, so on a CPU; the
others need Isaac Sim (an NVIDIA RTX GPU) or ManiSkill's Vulkan renderer. Each Launcher task is scored over four
conditions (the benchmark's four-trial protocol: spring stiffness 22, 24, 26 and 28 N/m, with small launcher and
projectile offsets and four backgrounds). This writes one task folder per task and condition, at Embodied Playground's
Level 0 (the agent sees RGB images and the robots' joints; no skills).

Every folder gets a reference solution. For each condition the generator searches, in the simulator's virtualenv, the
draw of a scripted pull-and-release (planner.py) that clears the targets, over draws of 4 to 11 cm (above that the
weak gripper slips), keeps the middle of the widest band of successful draws (a band of at least two, so the shot does
not hang on one value), and stores that shot's plan in oracle/plan.json after replaying the stored plan from a fresh
reset. A task is written only when all four of its conditions have such a shot.

Usage: python adapters/embodied-playground/generate.py [--out tasks/embodied-playground] [--tasks A007,A008]

Needs `robouse fetch-assets --embodied-playground` and the simulator's virtualenv (docs/suites/embodied-playground.md).
Downloads Embodied Playground's task catalog (docs/evaluation/tasks.json, docs/ep_subsets/tasks.json) at the pinned
commit for the goals, budgets, robots and conditions.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.request
from pathlib import Path

from robouse import config
from robouse.backends.embodied import VERIFY_SH
from robouse.backends.embodied_playground import source
from robouse.backends.embodied_playground.backend import PUBLIC_FIELDS, WORKER
from robouse.tasks import write_task
from robouse.workers.client import StdioWorker

# the Launch tasks of EP-100 written by default: those a single scripted shot clears in all four conditions (the
# suite page lists the others and why they are left out)
DEFAULT_TASKS = ("A007", "A008", "A010", "A044", "A055", "A018")
DRAWS = tuple(round(0.04 + 0.01 * i, 2) for i in range(8))  # 4 to 11 cm
RAW = f"https://raw.githubusercontent.com/{source.REPO}/{source.REVISION}"
CATALOG = "docs/evaluation/tasks.json"
SUBSETS = "docs/ep_subsets/tasks.json"
CONDITION_TEXT = {
    1: "spring stiffness 22 N/m, dusk background",
    2: "spring stiffness 24 N/m, park background",
    3: "spring stiffness 26 N/m, desert background with drifting scenery",
    4: "spring stiffness 28 N/m, snow background with pulsing scenery",
}

USAGE = """\
## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the scoring, or other files to succeed; the episode server judges the physical state itself.

```
robo info                          # the robots, the camera's projection matrix, the action groups and the step budget
robo observe                       # the robots' joint state, and the camera image (saved under observations/)
robo act V1 V2 ... V16 [--repeat N]  # one action (16 numbers, see Controls), applied N times (N <= 50)
robo done "short summary"          # end the episode and ask for scoring
robo give-up "reason"              # end the episode without claiming success
```

- Positions are in metres in the world frame (+z up); joint angles in radians.
- The episode has a fixed step budget (see `robo info`); every simulated control step counts.
- The episode is scored solved the moment Embodied Playground's success check holds; after that `robo act` answers that the episode has finished. If the episode ends otherwise (`terminated` or `truncated` in `robo observe`), or when you stop, call `robo done` once.
"""

BODY = (
    """# Embodied Playground, Launcher: {name}

This is Embodied Playground's task `{task_id}` ({index} of its EP-100 benchmark, type {type}), condition {condition} of 4 ({condition_text}), at its Level 0. Two simulated Franka Panda arms stand by a scene in MuJoCo; you drive them with the `robo` command.

## Goal

Embodied Playground's goal for this task, verbatim:

> {goal}

The declared condition: the launcher's spring stiffness in this episode is {stiffness:g} N/m.

**Success** is Embodied Playground's own check, made at every physics step: every required target cleared, and the task's other conditions met (toppled structures, fractures, protected targets, order). The episode is scored solved the first time it holds. Any other ending scores 0.

**The episode ends without success** at the first rule or physical violation (for example an arm pressing into an object, a joint moving too fast, a launcher part pushed past its limit, a protected target hit or targets cleared out of order), when the {seconds} s of simulated time are up, or once every projectile has been fired and has settled.

**Controls.** `robo act` takes 16 numbers: the left arm's seven joint targets (`left_0` to `left_6`, absolute, radians) and its gripper command (`left_gripper`: +1 open, -1 closed), then the same eight for the right arm. One step is 20 ms of simulated time (20 physics steps of 1 ms). Each joint moves toward its target no faster than its speed limit; a target held over several steps (`--repeat`) keeps the joint moving. There are no skills: at Level 0 you write your own perception, kinematics and planning, for example in Python with NumPy and Pillow. As Embodied Playground's rules say, do not search online or download anything for this task, and do not look for Embodied Playground's source, assets or task files: the episode, `robo` and your own code are all you use. `robo info` lists the robots (model, joint names, joint limits) and the neutral action, which is where both arms start.

**Observation.** `robo observe` reports per arm (`left`, `right`) the seven joint positions (`*_joint_pos`, rad), their velocities (`*_joint_vel`, rad/s) and the two finger positions (`*_finger_pos`, m), the previous action, the step index, the simulated time, and whether the episode has ended (`terminated`, `truncated`). It does not report where anything else is: find the scene in the `front_left` camera's images (640x400), which every `robo observe` saves. `robo info` gives that camera's 3x4 projection matrix, which maps a world point to its pixel.

The step budget is {max_steps} steps ({seconds} s of simulated time).

"""
    + USAGE
)


def _get_json(rel: str, cache: Path) -> dict:
    """A JSON file of Embodied Playground at the pinned commit (kept in `cache` between runs)."""
    p = cache / rel
    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{RAW}/{rel}", timeout=300) as r:
            p.write_bytes(r.read())
    return json.loads(p.read_text())


def best_draw(results: dict[float, dict]) -> float | None:
    """The middle of the widest band of consecutive successful draws (at least two wide), else None."""
    best: list[float] = []
    run: list[float] = []
    for d in sorted(results):
        if results[d]["success"]:
            run.append(d)
            if len(run) > len(best):
                best = list(run)
        else:
            run = []
    if len(best) < 2:
        return None
    return best[(len(best) - 1) // 2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tasks" / "embodied-playground"))
    ap.add_argument("--tasks", default=",".join(DEFAULT_TASKS), help="Launcher case ids, e.g. A007,A008")
    ap.add_argument("--cache", default=str(config.cache_dir() / "embodied-playground-catalog" / source.REVISION[:12]))
    a = ap.parse_args()
    out, cache = Path(a.out), Path(a.cache)
    catalog = {t["task_id"]: t for t in _get_json(CATALOG, cache)["tasks"]}
    subsets = {t["task_id"]: t for t in _get_json(SUBSETS, cache)["tasks"]}
    source.require()
    worker = StdioWorker(
        "embodied_playground", config.sim_python("embodied_playground", "embodied-playground"), WORKER, timeout=3600
    )
    pp = str(source.package_parent())
    written, skipped = [], {}
    staged: list[tuple[Path, dict, str, str, dict]] = []
    try:
        scenarios = None
        for case in a.tasks.split(","):
            task_id = f"marble/dual-panda/{case}"
            ep, member = catalog[task_id], subsets.get(task_id)
            if member is None:
                skipped[case] = "not in EP-100"
                continue
            group = next(g for g in ep["groups"] if g["variant"] == "loaded")
            trials = {t["trial_index"]: t for t in group["trials"]}
            folders = []
            for cond in (1, 2, 3, 4):
                trial = trials[cond]
                params = trial["environment_parameters"]
                if scenarios is None:
                    worker.call("make", package_parent=pp, task={"scenario": "warmup"}, seed=0)
                    scenarios = worker.call("scenarios")
                scenario = scenarios[int(case[1:]) - 1]
                spec = {"scenario": scenario, "initial_mode": "loaded", "environment_parameters": params}
                worker.call("make", package_parent=pp, task=spec, seed=int(trial["reset_seed"]))
                results = {d: worker.call("try_shot", draw=d, seed=int(trial["reset_seed"])) for d in DRAWS}
                draw = best_draw(results)
                line = " ".join(f"{d:.2f}:{'ok' if r['success'] else '--'}" for d, r in sorted(results.items()))
                print(f"{case} c{cond} {scenario}: {line} -> {draw}", flush=True)
                if draw is None:
                    skipped[case] = f"condition {cond}: no band of two or more successful draws in 4-11 cm"
                    break
                plan = results[draw]["plan"]
                check = worker.call("replay", plan=plan, seed=int(trial["reset_seed"]))
                if not check["success"]:
                    skipped[case] = f"condition {cond}: the stored plan did not succeed on replay"
                    break
                folders.append((cond, trial, scenario, draw, plan, check))
            if len(folders) != 4:
                continue
            for cond, trial, scenario, draw, plan, check in folders:
                tid = f"ep-launch-{case.lower()}-c{cond}"
                params = trial["environment_parameters"]
                meta = {
                    "task": {
                        "name": f"robouse/{tid}",
                        "description": f"Embodied Playground {member['index']} ({task_id}), condition {cond} of 4: "
                        f"{member['name']}",
                    },
                    "metadata": {
                        "source_benchmark": f"Embodied Playground (EP-100), {source.REPO} at {source.REVISION[:7]}",
                        "source_task": task_id,
                        "ep_index": member["index"],
                        "ep_type": member["type"],
                        "ep_name": member["name"],
                        "ep_split": member["split"],
                        "ep20": bool(member["ep20"]),
                        "ep_condition": cond,
                        "ep_protocol": ep["version"],
                        "ep_level": 0,
                        "suite": "embodied-playground",
                        "category": "manipulation",
                        "difficulty": "hard" if member["split"] == "Hard" else "medium",
                        "tags": ["bimanual", "franka", "mujoco", "vision", "long-horizon", "embodied-playground"],
                        "reference_solution": (
                            f"scripted pull-and-release with a {draw * 100:.0f} cm draw, found by simulation "
                            f"(robouse.backends.embodied_playground.planner); {check['steps']} steps"
                        ),
                    },
                    "agent": {"timeout_sec": int(ep["budgets"]["wall_seconds"])},
                    "verifier": {"timeout_sec": 120},
                    "robouse": {
                        "id": tid,
                        "backend": "embodied_playground",
                        "family": "marble",
                        "env": task_id,
                        "ep_scenario": scenario,
                        "condition": cond,
                        "initial_mode": "loaded",
                        "environment_parameters": params,
                        "goal": ep["goal"],
                        "seed": int(trial["reset_seed"]),
                        "max_steps": int(ep["budgets"]["max_steps"]),
                        "camera": "front_left",
                        "cameras": ["front_left"],
                        "obs_mode": "vision",
                        "visible_fields": list(PUBLIC_FIELDS),
                        "skills": False,
                        "success_mode": "first",
                        "frame_every": 5,
                    },
                }
                body = BODY.format(
                    name=member["name"],
                    task_id=task_id,
                    index=member["index"],
                    type=member["type"],
                    condition=cond,
                    condition_text=CONDITION_TEXT[cond],
                    goal=ep["goal"],
                    stiffness=params["spring_stiffness"],
                    max_steps=ep["budgets"]["max_steps"],
                    seconds=ep["budgets"]["simulation_seconds"],
                )
                oracle = (
                    "#!/bin/bash\n# Reference solution: replay this condition's reference shot (plan.json) through "
                    "robo act; the generator found it in simulation (a scripted pull-and-release of the launcher).\n"
                    "set -euo pipefail\n"
                    'python -m robouse.oracle --backend embodied_playground --env "$(dirname "$0")/plan.json"\n'
                )
                plans = {
                    "embodied_playground": f"{source.REPO}@{source.REVISION}",
                    "task": task_id,
                    "note": "Robo Use's reference shot for this condition; see robouse.backends.embodied_playground.planner",
                    "conditions": {str(cond): {"draw_m": draw, "steps": check["steps"], "plan": plan}},
                }
                staged.append((out / tid, meta, body, oracle, plans))
            written.append(case)
    finally:
        worker.close()
    if out.exists():
        shutil.rmtree(out)
    for d, meta, body, oracle, plans in staged:
        write_task(d, meta, body, oracle, VERIFY_SH)
        (d / "oracle" / "plan.json").write_text(json.dumps(plans, separators=(",", ":")) + "\n")
    print(f"{len(staged)} task folders for {', '.join(written) or 'no task'} -> {out}")
    for case, why in skipped.items():
        print(f"  skipped {case}: {why}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
