"""Generate the two validated RoboSimStudio CPU tasks, preserving the upstream examples and goal predicates.

Usage: python adapters/robosimstudio/generate.py [--out tasks/robosimstudio]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from robouse.backends.embodied import VERIFY_SH, oracle_sh
from robouse.backends.robosimstudio.backend import PUBLIC_FIELDS
from robouse.backends.robosimstudio.source import CASES, REVISION
from robouse.tasks import write_task

TASKS = {
    "open-bag": (
        "Open the bag",
        "Open the canvas bag's mouth to at least 30 mm, using the robot's grippers.",
        "the native `mouth_opening` predicate measures at least 0.03 m",
        "The table surface is at z = 0.728 m. The canvas bag stands on the table.",
    ),
    "hook-band": (
        "Hook the rubber band",
        "Hook the rubber band from the upper peg onto the lower one, keeping it around both pegs.",
        "the native `encircles` predicate holds for both the upper and lower peg spans",
        "The bench is at z = 0.75 m. A vertical pegboard holds two pegs; the band initially hangs around the upper one.",
    ),
}

BODY = """# RoboSimStudio: {title}

{instruction}

**Success:** the episode ends successfully at the first control step where {success}. This is the upstream scored example's physical success rule. A `done` call before the goal holds scores 0.

**Scene.** {scene} Two YAM arms with parallel grippers can manipulate the material. The layout is the upstream example's fixed layout; seeds do not randomize it. Use the camera to locate the material and fixtures.

**Controls.** `robo act` takes 16 numbers: the left tool's world x/y/z in metres, its quaternion qx/qy/qz/qw, its grip (0 open, 1 closed), then the same eight values for the right arm. A quaternion must be nonzero; the controller normalizes it. World +z is up. The simulator uses native Cartesian IK, joint servos and physical contacts. There are no skills. Start from `neutral_action` in `robo info` to hold the other arm. Interpolate tool poses in small increments and allow the joints time to follow.

**Observation.** `robo observe` gives each arm's tool position and xyzw orientation, joint positions and velocities, and measured gripper width, plus the previous action, step index and simulation time. `robo observe --image` saves the `overview` camera image. Its 3x4 projection in `robo info` maps homogeneous world points to image pixels. Material coordinates and goal metrics are hidden.

**Budget.** At most 1200 control steps, at 60 Hz (20 s simulated time). Every step counts, including repeats. The CPU solver is the pinned upstream example's implementation; its material coupling differs from the GPU path.

## How to control the robot

You are the robot's policy. Act through `robo` in your shell. The episode server judges the physical state.

```
robo info
robo observe --image
robo act V1 V2 ... V16 [--repeat N]
robo done "short summary"
robo give-up "reason"
```

A repeat executes at most 50 steps per call. The last tool targets are held between calls. The episode stops automatically on first success or at the step budget. Call `robo done` when finished if it has not already stopped.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[2] / "tasks" / "robosimstudio")
    out = parser.parse_args().out
    for case, (title, instruction, success, scene) in TASKS.items():
        tid = f"rss-{case}"
        meta = {
            "task": {"name": f"robouse/{tid}", "description": f"RoboSimStudio: {title}"},
            "metadata": {
                "source_benchmark": f"RoboSimStudio scored CPU example ({REVISION}, Apache-2.0)",
                "source_task": f"examples/06_tasks/{CASES[case]}",
                "language_instruction": instruction,
                "suite": "robosimstudio",
                "category": "deformable-manipulation",
                "difficulty": "hard",
                "tags": ["bimanual", "yam", "vision", "deformable", "cpu", "fixed-layout"],
            },
            "agent": {"timeout_sec": 1800},
            "verifier": {"timeout_sec": 60},
            "robouse": {
                "id": tid,
                "backend": "robosimstudio",
                "env": case,
                "seed": 0,
                "max_steps": 1200,
                "camera": "overview",
                "cameras": ["overview"],
                "obs_mode": "vision",
                "visible_fields": list(PUBLIC_FIELDS),
                "skills": False,
                "success_mode": "first",
                "frame_every": 10,
                "control_dt": 1 / 60,
            },
        }
        body = BODY.format(title=title, instruction=instruction, success=success, scene=scene)
        write_task(
            out / tid,
            meta,
            body,
            oracle_sh("robosimstudio", case, "native Cartesian poses; privileged grasp geometry."),
            VERIFY_SH,
        )
    print(f"{len(TASKS)} tasks -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
