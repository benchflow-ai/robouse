"""Dexhand suite -> Robo Use tasks (suite "dexhand"): a Shadow Dexterous Hand (Apache-2.0) or a LEAP Hand (MIT) from
MuJoCo Menagerie, or ROBOTIS's HX5-D20 (Apache-2.0, ROBOTIS's own MuJoCo model), hanging from a 6-axis positioner above a table, doing dexterous manipulation: reorienting a cube by
regrasp, pouring from a cup, turning a hand wheel, lifting a ball, moving a marker between holders, pressing buttons in
order and flipping a cube over in the palm with the fingers. Backend, scene, controllers, skills, judge and reference
solutions: src/robouse/backends/dexhand.py (+ dexhand_sim/scene.py).

Usage: python adapters/dexhand/generate.py [--out tasks/dexhand]
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from robouse.backends.dexhand.backend import ACTS, BUTTON_CLICK, CONTROL_DT, TASKS, DexHandBackend
from robouse.backends.dexhand.sim.scene import HANDS, TABLE_C, TABLE_HALF, TABLE_Z
from robouse.backends.embodied import write_embodied_task
from robouse.core.prompts import EMBODIED_USAGE

HAND_TEXT = {
    "shadow": (
        "a right Shadow Dexterous Hand (MuJoCo Menagerie model `shadow_hand`, Apache-2.0: 24 joints driven by 20 position "
        "actuators; the two distal joints of each finger are coupled by a tendon, as on the real hand, and are driven "
        "together by one actuator `..J0` whose target is their sum)"
    ),
    "leap": (
        "a right LEAP Hand (MuJoCo Menagerie model `leap_hand`, MIT: 16 joints, each driven by its own position actuator; "
        "index, middle and ring fingers have `mcp`, `rot` (side-to-side), `pip` and `dip` joints, the thumb has `cmc`, `axl`, "
        "`mcp` and `ipl`)"
    ),
    "hx5": (
        "a right ROBOTIS HX5-D20 hand (one of ROBOTIS's open-source HX Friends designs; ROBOTIS's own MuJoCo model from its "
        "`robotis_hand` repository, Apache-2.0: 20 joints, each a DYNAMIXEL XM335 position servo. `finger_r_joint1` to `4` "
        "are the thumb (a swing in the palm's plane, opposition, then two flexions), `5` to `8` the index finger, `9` to "
        "`12` the middle, `13` to `16` the ring and `17` to `20` the little finger (each: spread, then three flexions). The "
        "thumb sits beside the heel of the palm and, opposed, points down past it)"
    ),
}

SCENE = (
    "You control {hand}. Like a hand in a lab setup that is carried by a robot arm or gantry, it hangs from a 6-axis "
    "positioner above a table: three linear axes move the wrist in x, y and z and three rotary axes turn it in yaw, pitch "
    "and roll. The hand is not fixed to anything else and has no other support. World frame in metres: +x forward (away "
    "from the positioner's home), +y to the left, +z up; the floor is at z = 0 and the table top is at z = {tz:.2f}, "
    "spanning x from {x0:.2f} to {x1:.2f} and y from {y0:.2f} to {y1:.2f}. At roll = pitch = yaw = 0 the palm faces down "
    "and the fingers point along +x. PITCH tips the fingers down (+) or up (-); ROLL turns the hand about its own long "
    "axis (+90 makes the palm face +y, 180 makes it face up); YAW turns it about the vertical (counter-clockwise seen from "
    "above is +). `hand.palm_pos` is a point about 3.5 cm in front of the palm, roughly where a grasped object sits. "
    "Objects are real rigid bodies with rubber-like friction: a grasp holds only as long as the fingers' contact forces "
    "and friction hold it, and anything dropped falls. An object that falls to the floor fails the task."
)

TEXT = {
    "shadow-cube-face-up": dict(
        title="Cube: red face up (reorient by regrasp)",
        difficulty="hard",
        category="dexterous-manipulation",
        goal=(
            "A 5.6 cm cube (90 g) with six coloured faces (red, orange, green, blue, white, yellow) stands on the table at "
            "about (0.14, 0.0) with its white face up. Turn it so that its **red** face points up and leave it standing on the "
            "table. This is reorientation by regrasp: pick the cube up, turn it in the air with the hand, put it down and let "
            "go (or anything else that works physically); the red face's direction is in `objects.cube.face_normals`."
        ),
        success=(
            "the cube rests on the table, is not touched by the hand, and its red face's normal is within 20 degrees of "
            "straight up; the cube must never fall off the table"
        ),
    ),
    "shadow-pour-balls": dict(
        title="Pour balls into the bowl",
        difficulty="hard",
        category="dexterous-manipulation",
        goal=(
            "A blue cup (6.4 cm outer diameter, 11 cm tall) stands on the table at about (0.14, -0.10) with six small orange "
            "balls (1.8 cm) inside. A wide bowl (inner radius 9.5 cm, rim 4.5 cm above the table, 3 cm deep inside over a 1.5 cm solid bottom) is fixed to the table at (0.14, 0.14). "
            "Pick up the cup, pour at least four balls into the bowl, and put the cup back down upright on the table."
        ),
        success=(
            "at least 4 balls lie inside the bowl (centre within its inner radius and below its rim height), and the cup stands upright "
            "(axis within 20 degrees of vertical) on the table; dropping the cup to the floor fails; spilled balls do not "
            "count but do not fail the task. `progress.balls_in_bowl` counts the balls in the bowl"
        ),
    ),
    "shadow-turn-valve": dict(
        title="Open the hand-wheel valve",
        difficulty="medium",
        category="dexterous-manipulation",
        goal=(
            "A red hand wheel (radius 7.5 cm, three spokes, horizontal) sits on a vertical valve stem at (0.16, 0.0), 12 cm "
            "above the table (`landmarks.valve`). The stem turns with friction. Open the valve by turning the wheel at least "
            "180 degrees counter-clockwise (seen from above). The positioner's yaw range is about +-190 degrees, so a long "
            "turn may need more than one stroke."
        ),
        success=(
            "the wheel has turned at least 180 degrees counter-clockwise from its start angle (`progress.valve_turned_deg`); "
            "turning it back clockwise reduces the count"
        ),
    ),
    "leap-lift-ball": dict(
        title="Lift the ball",
        difficulty="easy",
        category="grasping",
        goal=(
            "A 6.6 cm ball (60 g) rests in a small ring stand on the table at about (0.12, 0.04). Pick it up and hold it at "
            "least 15 cm above the table top."
        ),
        success=(
            "the ball's centre is at least 0.15 m above the table top (z >= 0.55), the ball touches the hand and not the "
            "table, and it moves slower than 5 cm/s"
        ),
    ),
    "leap-pen-to-holder": dict(
        title="Marker into the pen cup",
        difficulty="hard",
        category="dexterous-manipulation",
        goal=(
            "A 16.6 cm marker (1.6 cm thick, red cap up) stands in a narrow blue stand at (0.14, -0.12) (hole radius 1.2 cm, "
            "rim 6 cm above the table, 4.5 cm deep inside). Take it out and put it into the green pen cup at (0.14, 0.14) (inner radius 3 cm, rim 8 cm above the table, 6.5 cm deep inside), then let "
            "go of it. Positions of both ends of the marker are in `objects.marker` (`cap_end`, `tip_end`)."
        ),
        success=(
            "the marker's lower end is inside the green pen cup (within its inner radius and below its rim), and the hand "
            "does not touch the marker; a marker dropped to the floor fails"
        ),
    ),
    "leap-press-buttons": dict(
        title="Press the buttons in order",
        difficulty="medium",
        category="dexterous-manipulation",
        goal=(
            "A panel on the table at (0.16, 0.0) carries three spring-loaded push buttons (radius 1.6 cm, 12 mm travel): red at "
            "y = -0.07, green at y = 0.0 and blue at y = 0.07 (`landmarks.buttons`). Press green, then blue, then green again. "
            "Never press red."
        ),
        success=(
            f"the recorded clicks are exactly green, blue, green in that order (a click is a button pushed down at least "
            f"{BUTTON_CLICK * 1000:.0f} mm; it must come back up past half of that before it can click again), with no "
            "other clicks; `progress.clicks` lists the clicks so far"
        ),
    ),
    "hx5-lift-ball": dict(
        title="Lift the ball (HX5-D20)",
        difficulty="easy",
        category="grasping",
        goal=(
            "A 6.6 cm ball (60 g) rests in a small ring stand on the table at about (0.12, 0.04). Pick it up and hold it at "
            "least 15 cm above the table top."
        ),
        success=(
            "the ball's centre is at least 0.15 m above the table top (z >= 0.55), the ball touches the hand and not the "
            "table, and it moves slower than 5 cm/s"
        ),
    ),
    "hx5-press-buttons": dict(
        title="Press the buttons in order (HX5-D20)",
        difficulty="medium",
        category="dexterous-manipulation",
        goal=(
            "A panel on the table at (0.16, 0.0) carries three spring-loaded push buttons (radius 1.6 cm, 12 mm travel): red at "
            "y = -0.07, green at y = 0.0 and blue at y = 0.07 (`landmarks.buttons`). Press green, then blue, then green again. "
            "Never press red."
        ),
        success=(
            f"the recorded clicks are exactly green, blue, green in that order (a click is a button pushed down at least "
            f"{BUTTON_CLICK * 1000:.0f} mm; it must come back up past half of that before it can click again), with no "
            "other clicks; `progress.clicks` lists the clicks so far"
        ),
    ),
    "leap-cube-in-hand": dict(
        title="Flip the cube in the palm (in-hand)",
        difficulty="medium",
        category="in-hand-manipulation",
        goal=(
            "The hand is held palm up (roll 180, pitch 0, yaw 0) about 20 cm above the table. A 6 cm cube (70 g) with six "
            "coloured faces lies on the palm near the finger roots, white face up and red face toward the fingertips (+x). "
            "Using the fingers, turn the cube over in the hand so that its **red** face points up, and leave it resting on the "
            "hand. This is in-hand manipulation: the positioner's roll, pitch and yaw must never deviate more than 15 degrees from "
            "their start values (so the wrist cannot simply tip the cube over), and the cube must never touch the table. "
            "Face directions are in `objects.cube.face_normals`."
        ),
        success=(
            "the cube's red face normal is within 25 degrees of straight up, the cube touches the hand and not the table, "
            "and no positioner angle (roll, pitch, yaw) ever deviated more than 15 degrees from its start, checked every 2 ms "
            "(`progress.wrist_rotation_since_start_deg` is the current largest change); the cube touching the table at any "
            "time, also checked every 2 ms, fails"
        ),
    ),
}


def controls(hand: str) -> str:
    acts = ACTS[hand]
    n = len(acts)
    return (
        "**Controls.** `robo act` takes {n6} numbers, each in [-1, 1], applied for one 40 ms step (`--repeat N` holds them for "
        "N steps): first the wrist group `wrist.pose_delta` = DX DY DZ DROLL DPITCH DYAW, which moves the positioner's "
        "target by x 1 cm along world x, y, z and by x 4 degrees on its roll, pitch and yaw joints (rotations about the "
        "wrist); then the "
        "hand group `hand.joints` = {names} ({n} values), each added to that actuator's position target as a fraction of its "
        "range (x 10 %; for the flexion joints + curls the finger). All zeros holds the current targets. The positioner is a stiff "
        "joint-space PD controller with force limits (200-300 N, 40 N m), so pushing into the table or an object stalls it "
        "instead of passing through; its target never runs more than 3 cm / 15 degrees ahead of the measured pose. The "
        "hand's actuators are the upstream position servos, so a finger stopped by an object keeps squeezing with a force "
        "that grows with the remaining target error. Skills (`robo info` lists arguments): `move_to X Y Z [SPEED]` and "
        "`move_by DX DY DZ [SPEED]` (straight line of the palm point, orientation kept, SPEED 0.01-0.25 m/s; reports "
        "`blocked` if stopped, `remaining_m` if it ran out of steps), "
        "`rotate ROLL PITCH YAW [SPEED]` (absolute positioner angles in degrees, turning about the palm point, SPEED 5-100 "
        "deg/s), "
        "`turn_about X Y DEG [SPEED]` (swing the hand about a vertical line, yawing with it, SPEED 5-90 deg/s; reports "
        "`remaining_deg` if it ran out of steps), `grasp power|pinch|tripod` "
        "(close those fingers until they stall or are fully closed; reports which fingers touch what), `open`, `pose NAME` "
        "(named postures: {poses}), `set_joint NAME DEG` and `wait [SECONDS]`. Skills are plain controllers: a grasp "
        "can slip or miss, and nothing is attached to the hand."
    ).format(
        n6=6 + n,
        names=" ".join(acts),
        n=n,
        poses=", ".join(
            f"`{p}`"
            for p in DexHandBackend({"env": next(k for k in TASKS if TASKS[k]["hand"] == hand)})
            .decl.skill("pose")
            .args[0]
            .choices
        ),
    )


OBS = (
    "**Observation.** `robo observe` reports `hand` (`wrist_pos` and `wrist_rpy_deg` of the positioner flange, their "
    "targets, `palm_pos`, `palm_normal`, `finger_dir`, `fingertips` positions, `joints` names with `joint_pos_norm` and "
    "`joint_target_norm` in [-1, 1] over each actuator's range, and `contacts` per finger), `objects` (position and what each "
    "touches, plus per-object details), `table`, `landmarks` (fixed things in the scene), `progress` and `safety_events`. "
    "Cameras: `front` (default), `side`, `top` and `back`."
)


def main() -> None:
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[2]
    ap.add_argument("--out", default=str(root / "tasks" / "dexhand"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    x0, x1 = TABLE_C[0] - TABLE_HALF[0], TABLE_C[0] + TABLE_HALF[0]
    y0, y1 = TABLE_C[1] - TABLE_HALF[1], TABLE_C[1] + TABLE_HALF[1]
    for tid, t in TASKS.items():
        x = TEXT[tid]
        hand = t["hand"]
        be = DexHandBackend({"env": tid})
        parts = [
            f"# {x['title']}",
            SCENE.format(hand=HAND_TEXT[hand], tz=TABLE_Z, x0=x0, x1=x1, y0=y0, y1=y1),
            "## Task\n\n" + x["goal"],
            f"**Success:** {x['success']}. Judged by the episode server from the simulated state after you call `robo done` "
            "and the hand has held still (zero action) for 10 steps.",
            controls(hand),
            OBS,
            f"The step budget is {t['max_steps']} steps ({t['max_steps'] * CONTROL_DT:.0f} s of simulated time).",
            EMBODIED_USAGE,
        ]
        write_embodied_task(
            out,
            task_id=tid,
            backend="dexhand",
            suite="dexhand",
            title=x["title"],
            instruction="\n\n".join(parts) + "\n",
            robot=HANDS[hand]["robot"],
            category=x["category"],
            difficulty=x["difficulty"],
            tags=["dexterous-hand", hand, "robotis" if hand == "hx5" else "menagerie", "mujoco"],
            max_steps=t["max_steps"],
            camera=be.camera,
            cameras=be.decl.cameras,
            oracle_note="scripted with the hand's skills (grasp, move, rotate), reading only the public observation.",
            extra_metadata=(
                {
                    "source_benchmark": "robouse original (dexhand suite; ROBOTIS HX5-D20 (right) from ROBOTIS's "
                    "robotis_hand repository)"
                }
                if hand == "hx5"
                else None
            ),
        )
    print(f"wrote {len(TASKS)} tasks to {out}")


if __name__ == "__main__":
    main()
