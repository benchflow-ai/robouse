---
schema_version: '1.3'
task:
  name: robouse/chemlab-balance-draft-shield
  description: Close the analytical balance's draft shield
metadata:
  source_benchmark: ChemLab-Assets 1.3.0 (MBZUAI); instrument models, contracts and data CC BY-NC 4.0, downloaded at run time
  source_task: 'CHEM-001 METTLER TOLEDO XPR204E: door_right_joint, door_left_joint, door_top_joint'
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
  id: chemlab-balance-draft-shield
  backend: chemlab
  env: chemlab-balance-draft-shield
  seed: 0
  max_steps: 600
  camera: front
  cameras:
  - front
  - side
  skills: true
  success_mode: final
---

# Close the analytical balance's draft shield

An analytical balance, the METTLER TOLEDO XPR204E (0.1 mg readability), stands on a bench; its front faces -y. Its glass draft shield has three sliding doors, on the left side, the right side and the top, each sliding toward the back (+y) by up to 109 mm to open. The top door is open 80 mm. Each side door has a small vertical grip on its outer face near its front edge, and the top door a low ridge across its top face near its front edge, 70 mm long, 8 mm deep and 5 mm tall. While any door is open the balance cannot settle: it shows UNSTABLE, and every movement of a door restarts its stability check, which needs the reading to hold still for 1.5 s with the doors shut before the balance shows STABLE.

A two-finger parallel gripper, the Franka Hand of a Franka Emika Panda (floating, no arm), works in front of the instrument. The gripper points straight down and its fingers close along y; turning it (DTWIST) turns it about the vertical, so the fingers can close along any horizontal direction. Its fingers open to an 8 cm gap. Each finger is 2.1 cm wide across the closing direction and 2.4 cm thick where it leaves the hand, reaches 4.6 cm out of the hand, and its tip reaches 0.9 cm beyond the tool point along the tool axis. The hand's body begins 3.7 cm behind the tool point: it is 20.4 cm long along the closing direction, and across it 3.8 cm wide where the fingers leave it and 6.3 cm at its widest, 9.5 to 11.5 cm behind the tool point, so it reaches past the fingers on both sides.

## Task

Close the draft shield so that the balance can settle: every door shut, and the balance reporting a stable reading.

**Success:** after you call `robo done` and the robot holds still for 10 steps, each of the three doors is open by no more than 1.1 mm (1 % of its 109 mm travel), the balance's status is STABLE, and the gripper touches none of the doors. Any other ending scores 0.

**Frame.** Metres, in the instrument's own frame: x to the right as seen from the front, y toward the back of the instrument, z up. The instrument's front faces -y, its footprint is centred on the origin and the bench top is at z = 0. The gripper's tool point (the point between the fingertips) can reach x in [-0.3, 0.3], y in [-0.4, 0.35] and z in [0.03, 0.5].

**Controls.** `robo act DX DY DZ DTWIST GRIP` takes five numbers in [-1, 1]. DX, DY and DZ move the tool point by about 1 cm per unit per step. DTWIST turns the gripper about its own tool axis by 5 degrees per unit per step; positive is clockwise as seen from behind the gripper, looking along its tool axis (from above when it points down). GRIP is the fingers' target: +1 closed, -1 fully open (an 8 cm gap), and values in between give a partial opening (gap = 8 cm * (1 - GRIP) / 2); keep sending +1 to keep holding. `robo move-to X Y Z [--grip G]` moves the tool point in a straight line toward a point without turning the gripper, and `robo grip G [--steps N]` holds the hand still while it sets the fingers. One step is 20 ms of simulated time.

**Observation.** `robo observe` reports `hand_pos` (the tool point), `hand_twist_deg` (how far the gripper is turned about its tool axis from where it started), `gripper_open` (0 closed to 1 fully open), `touching` (the parts the gripper touches), and under `parts` the instrument's `right door`: `opening_m` (how far it is open, in metres), `handle_pos` (the centre of its handle); `left door`: `opening_m` (how far it is open, in metres), `handle_pos` (the centre of its handle); `top door`: `opening_m` (how far it is open, in metres), `handle_pos` (the centre of its handle). Under `readouts` it shows what the instrument displays: `balance.status` (the balance's status: STABLE, UNSTABLE and so on), `balance.net_kg` (its reading in kg).

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
