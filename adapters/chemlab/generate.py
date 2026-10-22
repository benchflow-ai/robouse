"""ChemLab-Assets laboratory instruments -> Robo Use tasks (the chemlab suite).

Each task operates one part of a ChemLab-Assets instrument (MBZUAI, release 1.3.0) to a target state from its contract,
with a floating Franka Hand: raise a fume hood's sash to its stop, close a balance's draft shield, set a
hotplate's temperature or stirring speed with its knob, close a drying oven's door, open a moisture analyzer's lid and
an incubated shaker's hood. The instrument is its URDF converted to MuJoCo, and its behaviour runtime runs alongside;
the episode server scores the final joint state and, where the task says so, the runtime's state. The task
definitions are src/robouse/backends/chemlab/tasks.py; this script writes their folders.

The task folders hold only Robo Use's own text and the facts the tasks need (positions, travel, target values). The
instrument files are CC BY-NC 4.0 and never enter the repository: `robouse fetch-assets --chemlab` downloads them.

Usage: python adapters/chemlab/generate.py [--out tasks/chemlab]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.chemlab.instruments import INSTRUMENTS, RELEASE
from robouse.backends.chemlab.scene import HAND_SIZE
from robouse.backends.chemlab.tasks import TASKS, Task
from robouse.backends.embodied import VERIFY_SH, oracle_sh
from robouse.tasks import write_task

APPROACH = {
    "down": (
        "The gripper points straight down and its fingers close along y; turning it (DTWIST) turns it about the "
        "vertical, so the fingers can close along any horizontal direction."
    ),
    "forward": (
        "The gripper points horizontally into the instrument (+y) and its fingers close along z, one finger above the "
        "other; turning it (DTWIST) turns it about the y axis."
    ),
}


def _cm(key: str) -> str:
    return f"{HAND_SIZE[key] * 100:.1f}".removesuffix(".0")


GRIPPER = (
    f"Its fingers open to an {_cm('gap')} cm gap. Each finger is {_cm('finger_width')} cm wide across the closing "
    f"direction and {_cm('finger_thickness')} cm thick where it leaves the hand, reaches {_cm('finger_out')} cm out of "
    f"the hand, and its tip reaches {_cm('tip')} cm beyond the tool point along the tool axis. The hand's body begins "
    f"{_cm('palm')} cm behind the tool point: it is {_cm('hand_length')} cm long along the closing direction, and "
    f"across it {_cm('hand_width')} cm wide where the fingers leave it and {_cm('hand_width_max')} cm at its widest, "
    "9.5 to 11.5 cm behind the tool point, so it reaches past the fingers on both sides."
)
QUANTITY = {
    "opening_m": "how far it is open, in metres",
    "angle_deg": "its angle in degrees from its closed position or its stop",
    "lift_m": "how far it is lifted, in metres",
}
FIELDS = {
    "handle_pos": "the centre of its handle",
    "knob_pos": "the centre of the knob, on its axis halfway up",
    "front_face_pos": "a point on its flat front face",
    "outer_top_corner": "the top corner of its outer face at the free edge",
    "hinge_xy": "where its vertical hinge axis is (x, y)",
    "hinge_yz": "where its hinge axis along x is (y, z)",
    "diameter_m": "the knob's diameter",
    "top_z": "the height of its top",
    "width_m": "its width",
    "thickness_m": "its thickness",
    "travel_m": "its range of travel",
}
READOUTS = {
    "display.text": "the text on its display",
    "monitor.reading_m_s": "the face velocity the airflow monitor shows, in m/s",
    "indicator.safe": "the monitor's green SAFE light",
    "indicator.unsafe": "the monitor's red alarm light",
    "balance.status": "the balance's status: STABLE, UNSTABLE and so on",
    "balance.net_kg": "its reading in kg",
    "display.set_temperature": "the set temperature in degC",
    "display.temperature": "the measured temperature in degC",
    "display.set_speed": "the set speed in rpm",
    "indicator.heating": "the heating light",
    "fan.running": "whether the fan runs",
}

USAGE = """\
## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the instrument's behaviour model, the scoring, or other files to succeed; the episode server judges the final physical state itself.

```
robo info                               # action space, available skills, step budget
robo observe                            # robot and instrument state as numbers
robo observe --image [--camera C]       # also saves a camera image and prints its path (open it to look)
robo act DX DY DZ DTWIST GRIP [--repeat N]   # low-level action, applied N times (N <= 50)
robo move-to X Y Z [--grip G]           # skill: move the tool point toward a point (no turning)
robo grip G [--steps N]                 # skill: hold position and set the gripper (+1 close, -1 open)
robo done "short summary"               # end the episode and ask for scoring
robo give-up "reason"                   # end the episode without claiming success
```

- Positions are in metres in the world frame (+z up); angles are in degrees.
- The episode has a fixed step budget (see `robo info`); every simulated step counts, including skills.
- Success is judged about 10 steps after you call `robo done`, with the robot holding still, so the goal must still be true when the robot stops.
- Work in small steps and re-observe after each motion. Call `robo done` exactly once when finished.
"""


def _range(lo: float, hi: float) -> str:
    return f"[{lo:g}, {hi:g}]"


def body(t: Task) -> str:
    inst = INSTRUMENTS[t.instrument]
    (x0, y0, z0), (x1, y1, z1) = t.workspace
    parts = []
    for p in t.parts:
        fields = [f"`{p.quantity}` ({QUANTITY[p.quantity]})"]
        fields += [f"`{k}` ({FIELDS[k]})" for k in p.points]
        fields += [f"`{k}` ({FIELDS[k]})" for k, v in p.sizes.items() if not isinstance(v, str)]
        parts.append(f"`{p.label}`: " + ", ".join(fields))
    readouts = inst.runtime.readouts if inst.runtime else ()
    obs = (
        "`robo observe` reports `hand_pos` (the tool point), `hand_twist_deg` (how far the gripper is turned about "
        "its tool axis from where it started), `gripper_open` (0 closed to 1 fully open), `touching` (the parts the "
        "gripper touches), and under `parts` the instrument's " + "; ".join(parts) + "."
    )
    if readouts:
        obs += (
            " Under `readouts` it shows what the instrument displays: "
            + ", ".join(f"`{r}` ({READOUTS[r]})" for r in readouts)
            + "."
        )
    seconds = round(t.max_steps * 0.02)
    return f"""# {t.title}

{t.scene_text}

A two-finger parallel gripper, the Franka Hand of a Franka Emika Panda (floating, no arm), works in front of the instrument. {APPROACH[t.approach]} {GRIPPER}

## Task

{t.goal}

**Success:** after you call `robo done` and the robot holds still for 10 steps, {t.success}. Any other ending scores 0.

**Frame.** Metres, in the instrument's own frame: x to the right as seen from the front, y toward the back of the instrument, z up. The instrument's front faces -y, its footprint is centred on the origin and the bench top is at z = 0. The gripper's tool point (the point between the fingertips) can reach x in {_range(x0, x1)}, y in {_range(y0, y1)} and z in {_range(z0, z1)}.

**Controls.** `robo act DX DY DZ DTWIST GRIP` takes five numbers in [-1, 1]. DX, DY and DZ move the tool point by about 1 cm per unit per step. DTWIST turns the gripper about its own tool axis by 5 degrees per unit per step; positive is clockwise as seen from behind the gripper, looking along its tool axis (from above when it points down). GRIP is the fingers' target: +1 closed, -1 fully open (an {_cm('gap')} cm gap), and values in between give a partial opening (gap = {_cm('gap')} cm * (1 - GRIP) / 2); keep sending +1 to keep holding. `robo move-to X Y Z [--grip G]` moves the tool point in a straight line toward a point without turning the gripper, and `robo grip G [--steps N]` holds the hand still while it sets the fingers. One step is 20 ms of simulated time.

**Observation.** {obs}

The step budget is {t.max_steps} steps ({seconds} s of simulated time).

{USAGE}"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "tasks" / "chemlab"))
    out = Path(ap.parse_args().out)
    if out.exists():
        shutil.rmtree(out)
    for t in TASKS.values():
        inst = INSTRUMENTS[t.instrument]
        meta = {
            "task": {"name": f"robouse/{t.id}", "description": t.title},
            "metadata": {
                "source_benchmark": f"ChemLab-Assets {RELEASE} (MBZUAI); instrument models, contracts and data CC BY-NC "
                "4.0, downloaded at run time",
                "source_task": f"{inst.chem_id} {inst.maker} {inst.model}: " + ", ".join(p.joint for p in t.parts),
                "suite": "chemlab",
                "category": "articulated-object",
                "difficulty": "medium",
                "tags": ["chemlab", "lab-instrument", "articulated", "behaviour-runtime"],
            },
            "agent": {"timeout_sec": 1800},
            "verifier": {"timeout_sec": 120},
            "robouse": {
                "id": t.id,
                "backend": "chemlab",
                "env": t.id,
                "seed": 0,
                "max_steps": t.max_steps,
                "camera": t.camera,
                "cameras": list(inst.cameras),
                "skills": True,
                "success_mode": "final",
            },
        }
        note = f"operate the {inst.name.lower()}'s {t.parts[0].label} from the observed part positions."
        write_task(out / t.id, meta, body(t), oracle_sh("chemlab", t.id, f"{note[0].upper()}{note[1:]}"), VERIFY_SH)
    print(f"{len(TASKS)} tasks -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
