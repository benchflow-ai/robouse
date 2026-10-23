---
schema_version: '1.3'
task:
  name: robouse/chemlab-moisture-analyzer-lid
  description: Open the moisture analyzer's lid
metadata:
  source_benchmark: ChemLab-Assets 1.3.0 (MBZUAI); instrument models, contracts and data CC BY-NC 4.0, downloaded at run time
  source_task: 'CHEM-002 METTLER TOLEDO HX204: lid_joint'
  suite: chemlab
  category: articulated-object
  difficulty: medium
  tags:
  - chemlab
  - lab-instrument
  - articulated
  - behaviour-runtime
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 120
robouse:
  id: chemlab-moisture-analyzer-lid
  backend: chemlab
  env: chemlab-moisture-analyzer-lid
  seed: 0
  max_steps: 500
  camera: front
  cameras:
  - front
  - side
  skills: true
  success_mode: final
---

# Open the moisture analyzer's lid

A halogen moisture analyzer, the METTLER TOLEDO HX204, stands on a bench; its front faces -y, with its low display terminal in front of the heating module. The heating module's lid covers the sample chamber; it opens by sliding back and up along a straight diagonal, 145 mm back (+y) for 108.5 mm up, and stays where it is left. The instrument only lets a sample be loaded once the lid is lifted at least 100 mm. The lid is closed.

A two-finger parallel gripper, the Franka Hand of a Franka Emika Panda (floating, no arm), works in front of the instrument. The gripper points straight down and its fingers close along y; turning it (DTWIST) turns it about the vertical, so the fingers can close along any horizontal direction. Its fingers open to an 8 cm gap. Each finger is 2.1 cm wide across the closing direction and 2.4 cm thick where it leaves the hand, reaches 4.6 cm out of the hand, and its tip reaches 0.9 cm beyond the tool point along the tool axis. The hand's body begins 3.7 cm behind the tool point: it is 20.4 cm long along the closing direction, and across it 3.8 cm wide where the fingers leave it and 6.3 cm at its widest, 9.5 to 11.5 cm behind the tool point, so it reaches past the fingers on both sides.

## Task

Open the sample chamber's lid far enough to load a sample: at least 100 mm.

**Success:** after you call `robo done` and the robot holds still for 10 steps, the lid is lifted by at least 100 mm (of its 108.5 mm) and the gripper does not touch it. Any other ending scores 0.

**Frame.** Metres, in the instrument's own frame: x to the right as seen from the front, y toward the back of the instrument, z up. The instrument's front faces -y, its footprint is centred on the origin and the bench top is at z = 0. The gripper's tool point (the point between the fingertips) can reach x in [-0.25, 0.25], y in [-0.4, 0.35] and z in [0.065, 0.45].

**Controls.** `robo act DX DY DZ DTWIST GRIP` takes five numbers in [-1, 1]. DX, DY and DZ move the tool point by about 1 cm per unit per step. DTWIST turns the gripper about its own tool axis by 5 degrees per unit per step; positive is clockwise as seen from behind the gripper, looking along its tool axis (from above when it points down). GRIP is the fingers' target: +1 closed, -1 fully open (an 8 cm gap), and values in between give a partial opening (gap = 8 cm * (1 - GRIP) / 2); keep sending +1 to keep holding. `robo move-to X Y Z [--grip G]` moves the tool point in a straight line toward a point without turning the gripper, and `robo grip G [--steps N]` holds the hand still while it sets the fingers. One step is 20 ms of simulated time.

**Observation.** `robo observe` reports `hand_pos` (the tool point), `hand_twist_deg` (how far the gripper is turned about its tool axis from where it started), `gripper_open` (0 closed to 1 fully open), `touching` (the parts the gripper touches), and under `parts` the instrument's `lid`: `lift_m` (how far it is lifted, in metres), `front_face_pos` (a point on its flat front face).

The step budget is 500 steps (10 s of simulated time).

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
