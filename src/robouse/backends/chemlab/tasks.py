"""The chemlab tasks: each operates one part of a ChemLab-Assets instrument to a target state from its contract.

A task names the instrument, the part's start state, the gripper's approach and workspace, what `robo observe` shows
of the instrument, and the checks the episode server applies after `robo done` (all must hold):
- {"joint": J, "min": a, "max": b, "scale": s}: joint J's position / s is within [a, b];
- {"runtime": SLOT, "equals": v}: the behaviour runtime's evaluator view has SLOT == v;
- {"runtime": SLOT, "min": a, "max": b}: the runtime's SLOT is within [a, b];
- {"released": [J, ...]}: the gripper touches none of these joints' parts.
`plan` names the reference solution in oracle.py. The text fields are what the generator writes into task.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .instruments import Part, Point

SASH_SCALE = 1.0038198375433474  # joint travel along the 5-degree rail per metre of opening (the contract's binding)
HX_SCALE = 1.6691  # joint travel along the lid's diagonal per metre of lift (the contract's binding)


@dataclass(frozen=True)
class Task:
    id: str
    instrument: str
    title: str
    parts: tuple[Part, ...]
    start: dict[str, float]
    approach: str  # "down" or "forward" (scene.APPROACH_QUAT)
    home: tuple[float, float, float]
    workspace: tuple[tuple[float, float, float], tuple[float, float, float]]
    checks: tuple[dict, ...]
    max_steps: int
    plan: str
    goal: str  # the goal, in the instrument's terms
    success: str  # the success rule, exactly as checked
    scene_text: str  # what the agent is told about the instrument and its part
    camera: str = "front"
    source: dict = field(default_factory=dict)  # where the target comes from in the contract


TASKS: dict[str, Task] = {}


def _add(t: Task) -> None:
    TASKS[t.id] = t


_add(
    Task(
        id="chemlab-fume-hood-sash",
        instrument="esco_efa5uduvw",
        title="Raise the fume hood's sash to the working stop",
        parts=(
            Part(
                "sash_joint",
                "sash",
                "opening_m",
                scale=SASH_SCALE,
                points={"handle_pos": Point("sash", (0.0, -0.0313, 0.0328))},
                sizes={"handle": "a 24 mm round bar along x across the sash's bottom edge", "travel_m": [0.0, 0.67]},
            ),
        ),
        start={"sash_joint": 0.15 * SASH_SCALE},
        approach="forward",
        home=(0.0, -0.75, 0.3),
        workspace=((-0.7, -0.95, 0.06), (0.7, -0.4, 0.95)),
        checks=(
            {"joint": "sash_joint", "scale": SASH_SCALE, "min": 0.447, "max": 0.467},
            {"runtime": "monitor.alarm", "equals": None},
            {"released": ["sash_joint"]},
        ),
        max_steps=900,
        plan="sash",
        goal="Raise the sash to its working stop, 457 mm (18 inches) above the work surface, and let go of it.",
        success=(
            "the sash's opening is 447 to 467 mm, the gripper does not touch the sash, and the hood's airflow monitor "
            "raises no alarm"
        ),
        scene_text=(
            "A bench-top chemical fume hood, the Esco Frontier Acela EFA-5UDUVW-9 (1.5 m wide) with a Sentinel XL "
            "airflow monitor, stands on a base cabinet; its front faces -y. Its sash, a glass window in an aluminium "
            "frame, slides up and down in front of the work chamber on rails tilted back 5 degrees from vertical; it is "
            "open 150 mm. The sash's handle is a 24 mm round bar along x across its bottom edge, and an airfoil sill "
            "runs along the work surface just below the handle when the sash is closed. Above the 457 mm stop the sash "
            "creeps back down to the stop when it is let go (the hood's Creep Down feature). The airflow monitor shows "
            "the face velocity through the opening and alarms when it is too low or too high."
        ),
        source={"sash_stop_m": "instrument_model.json documented.sash_stop_m (0.457)"},
    )
)

_RIGHT, _LEFT, _TOP = "door_right_joint", "door_left_joint", "door_top_joint"
_add(
    Task(
        id="chemlab-balance-draft-shield",
        instrument="mt_xpr204e",
        title="Close the analytical balance's draft shield",
        parts=(
            Part(_RIGHT, "right door", "opening_m", points={"handle_pos": Point("door_right", (0.007, -0.07, -0.062))}),
            Part(_LEFT, "left door", "opening_m", points={"handle_pos": Point("door_left", (-0.007, -0.07, -0.062))}),
            Part(_TOP, "top door", "opening_m", points={"handle_pos": Point("door_top", (0.0, -0.085, 0.003))}),
        ),
        start={_TOP: 0.08},
        approach="down",
        home=(0.0, -0.25, 0.42),
        workspace=((-0.3, -0.4, 0.03), (0.3, 0.35, 0.5)),
        checks=(
            {"joint": _RIGHT, "max": 0.0011},
            {"joint": _LEFT, "max": 0.0011},
            {"joint": _TOP, "max": 0.0011},
            {"runtime": "balance.status", "equals": "STABLE"},
            {"released": [_RIGHT, _LEFT, _TOP]},
        ),
        max_steps=600,
        plan="balance",
        goal=(
            "Close the draft shield so that the balance can settle: every door shut, and the balance reporting a "
            "stable reading."
        ),
        success=(
            "each of the three doors is open by no more than 1.1 mm (1 % of its 109 mm travel), the balance's status "
            "is STABLE, and the gripper touches none of the doors"
        ),
        scene_text=(
            "An analytical balance, the METTLER TOLEDO XPR204E (0.1 mg readability), stands on a bench; its front faces "
            "-y. Its glass draft shield has three sliding doors, on the left side, the right side and the top, each "
            "sliding toward the back (+y) by up to 109 mm to open. The top door is open 80 mm. Each side door has a "
            "small vertical grip on its outer face near its front edge, and the top door a low ridge across its top "
            "face near its front edge, 70 mm long, 8 mm deep and 5 mm tall. While any door is open the balance cannot "
            "settle: it shows UNSTABLE, and every movement of a door restarts its stability check, which needs the "
            "reading to hold still for 1.5 s with the doors shut before the balance shows STABLE."
        ),
        source={"door_fraction": "XPR204E runtime: environment valid only when the widest door is open <= 1 %"},
    )
)

_KNOB_T, _KNOB_S = "knob_temperature_joint", "knob_speed_joint"
_IKA_TEXT = (
    "A magnetic hotplate stirrer, the IKA Plate RCT digital, stands on a bench; its front faces -y. Two knobs stand on "
    "the glass panel in front of the heating plate: the temperature knob on the left and the stirring-speed knob on "
    "the right. Each is a cylinder 31 mm across and 17 mm tall that turns about a vertical axis (clockwise seen from "
    "above raises the setting, from a stop at the lowest setting). The display shows the set temperature and the set "
    "speed."
)
_add(
    Task(
        id="chemlab-hotplate-temperature",
        instrument="ika_plate_rctdigital",
        title="Set the hotplate to 100 degC",
        parts=(
            Part(
                _KNOB_T,
                "temperature knob",
                "angle_deg",
                points={"knob_pos": Point("knob_temperature", (0.0, 0.0, 0.0085))},
                sizes={"diameter_m": 0.031, "top_z": 0.0653},
            ),
        ),
        start={},
        approach="down",
        home=(0.0, -0.25, 0.2),
        workspace=((-0.3, -0.4, 0.055), (0.3, 0.25, 0.4)),
        checks=(
            {"runtime": "heating.set_k", "min": 370.65, "max": 375.65},
            {"released": [_KNOB_T]},
        ),
        max_steps=600,
        plan="knob_temperature",
        goal="Set the heating temperature to 100 degC with the temperature knob.",
        success="the hotplate's set temperature is 97.5 to 102.5 degC and the gripper does not touch the knob",
        scene_text=_IKA_TEXT + " The temperature is set to 0 degC (the knob is at its stop).",
        source={"mapping": "contract matterix.bindings knob_temperature_joint: scale 0.0628319 rad/K, offset -17.1625"},
    )
)
_add(
    Task(
        id="chemlab-hotplate-stirring",
        instrument="ika_plate_rctdigital",
        title="Set the stirrer to 500 rpm",
        parts=(
            Part(
                _KNOB_S,
                "speed knob",
                "angle_deg",
                points={"knob_pos": Point("knob_speed", (0.0, 0.0, 0.0085))},
                sizes={"diameter_m": 0.031, "top_z": 0.0653},
            ),
        ),
        start={},
        approach="down",
        home=(0.0, -0.25, 0.2),
        workspace=((-0.3, -0.4, 0.055), (0.3, 0.25, 0.4)),
        checks=(
            {"runtime": "stirring.set_rad_s", "min": 490 * math.pi / 30, "max": 510 * math.pi / 30},
            {"released": [_KNOB_S]},
        ),
        max_steps=600,
        plan="knob_speed",
        goal="Set the stirring speed to 500 rpm with the speed knob.",
        success="the stirrer's set speed is 490 to 510 rpm and the gripper does not touch the knob",
        scene_text=_IKA_TEXT + " The speed is set to 0 rpm (the knob is at its stop).",
        source={"mapping": "contract matterix.bindings knob_speed_joint: scale 0.12 rad per rad/s"},
    )
)

_add(
    Task(
        id="chemlab-drying-oven-door",
        instrument="binder_fd056",
        title="Close the drying oven's door",
        parts=(
            Part(
                "door_joint",
                "door",
                "angle_deg",
                points={
                    "handle_pos": Point("door", (-0.52, -0.0913, 0.31)),
                    "outer_top_corner": Point("door", (-0.56, -0.063, 0.62)),
                },
                sizes={"hinge_xy": [0.28, -0.2195], "width_m": 0.56, "top_z": 0.62, "thickness_m": 0.06},
            ),
        ),
        start={"door_joint": math.radians(100.0)},
        approach="down",
        home=(0.45, -0.75, 0.75),
        workspace=((-0.45, -1.0, 0.1), (0.8, -0.25, 0.95)),
        checks=(
            {"joint": "door_joint", "max": 0.05},
            {"runtime": "fan.running", "equals": True},
            {"released": ["door_joint"]},
        ),
        max_steps=900,
        plan="oven_door",
        goal="Close the oven's door so that it can heat again.",
        success=(
            "the door is shut to within 0.05 rad (2.9 degrees), so that the oven's door switch reads it closed and the "
            "oven's fan runs again, and the gripper does not touch the door"
        ),
        scene_text=(
            "A forced-convection drying oven, the BINDER FD 56, stands on a bench, set to 105 degC; its front faces -y. "
            "Its door is 0.56 m wide and 0.62 m tall, hinged on the right (seen from the front) about a vertical axis "
            "at x = 0.28, y = -0.2195; it is open 100 degrees, swung out toward the front right. A door switch stops "
            "the heater and the fan while the door is open more than 0.05 rad, and the display, the heating light "
            "and the fan show when the oven heats again. The door's handle is a block on its outer face near its free "
            "edge, and a control panel is mounted on the door's outer face above the handle."
        ),
        source={"door_switch_rad": "instrument_model.json engineering.door_switch_rad (0.05)"},
    )
)

_add(
    Task(
        id="chemlab-moisture-analyzer-lid",
        instrument="mt_hx204",
        title="Open the moisture analyzer's lid",
        parts=(
            Part(
                "lid_joint",
                "lid",
                "lift_m",
                scale=HX_SCALE,
                points={"front_face_pos": Point("lid", (0.055, -0.124, 0.045))},
                sizes={"travel": "145 mm back and 108.5 mm up, along a straight diagonal"},
            ),
        ),
        start={},
        approach="down",
        home=(0.05, -0.3, 0.25),
        workspace=((-0.25, -0.4, 0.065), (0.25, 0.35, 0.45)),
        checks=(
            {"joint": "lid_joint", "scale": HX_SCALE, "min": 0.1},
            {"released": ["lid_joint"]},
        ),
        max_steps=500,
        plan="hx_lid",
        goal="Open the sample chamber's lid far enough to load a sample: at least 100 mm.",
        success="the lid is lifted by at least 100 mm (of its 108.5 mm) and the gripper does not touch it",
        scene_text=(
            "A halogen moisture analyzer, the METTLER TOLEDO HX204, stands on a bench; its front faces -y, with its "
            "low display terminal in front of the heating module. The heating module's lid covers the sample chamber; "
            "it opens by sliding back and up along a straight diagonal, 145 mm back (+y) for 108.5 mm up, and stays "
            "where it is left. The instrument only lets a sample be loaded once the lid is lifted at least 100 mm. "
            "The lid is closed."
        ),
        source={"threshold": "HX204 runtime: sample.configure needs lid.position_m >= 0.1"},
    )
)

_add(
    Task(
        id="chemlab-shaker-hood",
        instrument="ika_ks4000",
        title="Open the incubated shaker's hood",
        parts=(
            Part(
                "hood_joint",
                "hood",
                "angle_deg",
                points={"handle_pos": Point("hood", (0.0, -0.435, -0.3185))},
                sizes={"hinge_yz": [0.1604, 0.5174], "handle": "a 12 mm round bar along x, 316 mm long"},
            ),
        ),
        start={},
        approach="forward",
        home=(0.0, -0.75, 0.3),
        workspace=((-0.5, -1.0, 0.1), (0.5, 0.0, 1.05)),
        checks=(
            {"joint": "hood_joint", "min": 1.4},
            {"released": ["hood_joint"]},
        ),
        max_steps=900,
        plan="shaker_hood",
        goal="Open the shaker's hood far enough to load the platform: at least 1.4 rad (80 degrees).",
        success="the hood is open at least 1.4 rad and the gripper does not touch it",
        scene_text=(
            "An incubated orbital shaker, the IKA KS 4000 i control, stands on a bench; its front faces -y. Its "
            "transparent hood covers the shaking platform and is hinged at the back about an axis along x at "
            "y = 0.1604, z = 0.5174; it opens by swinging up and back by up to 90 degrees, and gas springs hold it "
            "wherever it is let go. The shaker only lets the platform be loaded once the hood is open at least 1.4 "
            "rad. The hood's handle is a 12 mm round bar along x across its front, 316 mm long. The hood is closed."
        ),
        source={"threshold": "KS 4000 runtime: load.configure needs hood.angle_rad >= 1.4"},
    )
)
