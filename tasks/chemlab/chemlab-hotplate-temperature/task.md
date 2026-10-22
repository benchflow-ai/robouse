---
schema_version: '1.3'
task:
  name: robouse/chemlab-hotplate-temperature
  description: Set the hotplate to 100 degC
metadata:
  source_benchmark: ChemLab-Assets 1.3.0 (MBZUAI); instrument models, contracts and data CC BY-NC 4.0, downloaded at run time
  source_task: 'CHEM-008 IKA Plate RCT digital: knob_temperature_joint'
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
  id: chemlab-hotplate-temperature
  backend: chemlab
  env: chemlab-hotplate-temperature
  seed: 0
  max_steps: 600
  camera: front
  cameras:
  - front
  - side
  skills: true
  success_mode: final
---

# Set the hotplate to 100 degC

A magnetic hotplate stirrer, the IKA Plate RCT digital, stands on a bench; its front faces -y. Two knobs stand on the glass panel in front of the heating plate: the temperature knob on the left and the stirring-speed knob on the right. Each is a cylinder 31 mm across and 17 mm tall that turns about a vertical axis (clockwise seen from above raises the setting, from a stop at the lowest setting). The display shows the set temperature and the set speed. The temperature is set to 0 degC (the knob is at its stop).

A two-finger parallel gripper, the Franka Hand of a Franka Emika Panda (floating, no arm), works in front of the instrument. The gripper points straight down and its fingers close along y; turning it (DTWIST) turns it about the vertical, so the fingers can close along any horizontal direction. Its fingers open to an 8 cm gap. Each finger is 2.1 cm wide across the closing direction and 2.4 cm thick where it leaves the hand, reaches 4.6 cm out of the hand, and its tip reaches 0.9 cm beyond the tool point along the tool axis. The hand's body begins 3.7 cm behind the tool point: it is 20.4 cm long along the closing direction, and across it 3.8 cm wide where the fingers leave it and 6.3 cm at its widest, 9.5 to 11.5 cm behind the tool point, so it reaches past the fingers on both sides.

## Task

Set the heating temperature to 100 degC with the temperature knob.

**Success:** after you call `robo done` and the robot holds still for 10 steps, the hotplate's set temperature is 97.5 to 102.5 degC and the gripper does not touch the knob. Any other ending scores 0.

**Frame.** Metres, in the instrument's own frame: x to the right as seen from the front, y toward the back of the instrument, z up. The instrument's front faces -y, its footprint is centred on the origin and the bench top is at z = 0. The gripper's tool point (the point between the fingertips) can reach x in [-0.3, 0.3], y in [-0.4, 0.25] and z in [0.055, 0.4].

**Controls.** `robo act DX DY DZ DTWIST GRIP` takes five numbers in [-1, 1]. DX, DY and DZ move the tool point by about 1 cm per unit per step. DTWIST turns the gripper about its own tool axis by 5 degrees per unit per step; positive is clockwise as seen from behind the gripper, looking along its tool axis (from above when it points down). GRIP is the fingers' target: +1 closed, -1 fully open (an 8 cm gap), and values in between give a partial opening (gap = 8 cm * (1 - GRIP) / 2); keep sending +1 to keep holding. `robo move-to X Y Z [--grip G]` moves the tool point in a straight line toward a point without turning the gripper, and `robo grip G [--steps N]` holds the hand still while it sets the fingers. One step is 20 ms of simulated time.

**Observation.** `robo observe` reports `hand_pos` (the tool point), `hand_twist_deg` (how far the gripper is turned about its tool axis from where it started), `gripper_open` (0 closed to 1 fully open), `touching` (the parts the gripper touches), and under `parts` the instrument's `temperature knob`: `angle_deg` (its angle in degrees from its closed position or its stop), `knob_pos` (the centre of the knob, on its axis halfway up), `diameter_m` (the knob's diameter), `top_z` (the height of its top). Under `readouts` it shows what the instrument displays: `display.set_temperature` (the set temperature in degC), `display.temperature` (the measured temperature in degC), `display.set_speed` (the set speed in rpm).

The step budget is 600 steps (12 s of simulated time).

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
