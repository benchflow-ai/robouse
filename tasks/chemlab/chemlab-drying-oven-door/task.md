---
schema_version: '1.3'
task:
  name: robouse/chemlab-drying-oven-door
  description: Close the drying oven's door
metadata:
  source_benchmark: ChemLab-Assets 1.3.0 (MBZUAI); instrument models, contracts and data CC BY-NC 4.0, downloaded at run time
  source_task: 'CHEM-011 BINDER FD 56: door_joint'
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
  id: chemlab-drying-oven-door
  backend: chemlab
  env: chemlab-drying-oven-door
  seed: 0
  max_steps: 900
  camera: front
  cameras:
  - front
  - side
  skills: true
  success_mode: final
---

# Close the drying oven's door

A forced-convection drying oven, the BINDER FD 56, stands on a bench, set to 105 degC; its front faces -y. Its door is 0.56 m wide and 0.62 m tall, hinged on the right (seen from the front) about a vertical axis at x = 0.28, y = -0.2195; it is open 100 degrees, swung out toward the front right. A door switch stops the heater and the fan while the door is open more than 0.05 rad, and the display, the heating light and the fan show when the oven heats again. The door's handle is a block on its outer face near its free edge, and a control panel is mounted on the door's outer face above the handle.

A two-finger parallel gripper, the Franka Hand of a Franka Emika Panda (floating, no arm), works in front of the instrument. The gripper points straight down and its fingers close along y; turning it (DTWIST) turns it about the vertical, so the fingers can close along any horizontal direction. Its fingers open to an 8 cm gap. Each finger is 2.1 cm wide across the closing direction and 2.4 cm thick where it leaves the hand, reaches 4.6 cm out of the hand, and its tip reaches 0.9 cm beyond the tool point along the tool axis. The hand's body begins 3.7 cm behind the tool point: it is 20.4 cm long along the closing direction, and across it 3.8 cm wide where the fingers leave it and 6.3 cm at its widest, 9.5 to 11.5 cm behind the tool point, so it reaches past the fingers on both sides.

## Task

Close the oven's door so that it can heat again.

**Success:** after you call `robo done` and the robot holds still for 10 steps, the door is shut to within 0.05 rad (2.9 degrees), so that the oven's door switch reads it closed and the oven's fan runs again, and the gripper does not touch the door. Any other ending scores 0.

**Frame.** Metres, in the instrument's own frame: x to the right as seen from the front, y toward the back of the instrument, z up. The instrument's front faces -y, its footprint is centred on the origin and the bench top is at z = 0. The gripper's tool point (the point between the fingertips) can reach x in [-0.45, 0.8], y in [-1, -0.25] and z in [0.1, 0.95].

**Controls.** `robo act DX DY DZ DTWIST GRIP` takes five numbers in [-1, 1]. DX, DY and DZ move the tool point by about 1 cm per unit per step. DTWIST turns the gripper about its own tool axis by 5 degrees per unit per step; positive is clockwise as seen from behind the gripper, looking along its tool axis (from above when it points down). GRIP is the fingers' target: +1 closed, -1 fully open (an 8 cm gap), and values in between give a partial opening (gap = 8 cm * (1 - GRIP) / 2); keep sending +1 to keep holding. `robo move-to X Y Z [--grip G]` moves the tool point in a straight line toward a point without turning the gripper, and `robo grip G [--steps N]` holds the hand still while it sets the fingers. One step is 20 ms of simulated time.

**Observation.** `robo observe` reports `hand_pos` (the tool point), `hand_twist_deg` (how far the gripper is turned about its tool axis from where it started), `gripper_open` (0 closed to 1 fully open), `touching` (the parts the gripper touches), and under `parts` the instrument's `door`: `angle_deg` (its angle in degrees from its closed position or its stop), `handle_pos` (the centre of its handle), `outer_top_corner` (the top corner of its outer face at the free edge), `hinge_xy` (where its vertical hinge axis is (x, y)), `width_m` (its width), `top_z` (the height of its top), `thickness_m` (its thickness). Under `readouts` it shows what the instrument displays: `display.text` (the text on its display), `display.temperature` (the measured temperature in degC), `indicator.heating` (the heating light), `fan.running` (whether the fan runs).

The step budget is 900 steps (18 s of simulated time).

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
