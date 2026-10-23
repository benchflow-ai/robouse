---
schema_version: '1.3'
task:
  name: robouse/chemlab-fume-hood-sash
  description: Raise the fume hood's sash to the working stop
metadata:
  source_benchmark: ChemLab-Assets 1.3.0 (MBZUAI); instrument models, contracts and data CC BY-NC 4.0, downloaded at run time
  source_task: 'CHEM-199 Esco Lifesciences Frontier Acela EFA-5UDUVW-9: sash_joint'
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
  id: chemlab-fume-hood-sash
  backend: chemlab
  env: chemlab-fume-hood-sash
  seed: 0
  max_steps: 900
  camera: front
  cameras:
  - front
  - side
  skills: true
  success_mode: final
---

# Raise the fume hood's sash to the working stop

A bench-top chemical fume hood, the Esco Frontier Acela EFA-5UDUVW-9 (1.5 m wide) with a Sentinel XL airflow monitor, stands on a base cabinet; its front faces -y. Its sash, a glass window in an aluminium frame, slides up and down in front of the work chamber on rails tilted back 5 degrees from vertical; it is open 150 mm. The sash's handle is a 24 mm round bar along x across its bottom edge, and an airfoil sill runs along the work surface just below the handle when the sash is closed. Above the 457 mm stop the sash creeps back down to the stop when it is let go (the hood's Creep Down feature). The airflow monitor shows the face velocity through the opening and alarms when it is too low or too high.

A two-finger parallel gripper, the Franka Hand of a Franka Emika Panda (floating, no arm), works in front of the instrument. The gripper points horizontally into the instrument (+y) and its fingers close along z, one finger above the other; turning it (DTWIST) turns it about the y axis. Its fingers open to an 8 cm gap. Each finger is 2.1 cm wide across the closing direction and 2.4 cm thick where it leaves the hand, reaches 4.6 cm out of the hand, and its tip reaches 0.9 cm beyond the tool point along the tool axis. The hand's body begins 3.7 cm behind the tool point: it is 20.4 cm long along the closing direction, and across it 3.8 cm wide where the fingers leave it and 6.3 cm at its widest, 9.5 to 11.5 cm behind the tool point, so it reaches past the fingers on both sides.

## Task

Raise the sash to its working stop, 457 mm (18 inches) above the work surface, and let go of it.

**Success:** after you call `robo done` and the robot holds still for 10 steps, the sash's opening is 447 to 467 mm, the gripper does not touch the sash, and the hood's airflow monitor raises no alarm. Any other ending scores 0.

**Frame.** Metres, in the instrument's own frame: x to the right as seen from the front, y toward the back of the instrument, z up. The instrument's front faces -y, its footprint is centred on the origin and the bench top is at z = 0. The gripper's tool point (the point between the fingertips) can reach x in [-0.7, 0.7], y in [-0.95, -0.4] and z in [0.06, 0.95].

**Controls.** `robo act DX DY DZ DTWIST GRIP` takes five numbers in [-1, 1]. DX, DY and DZ move the tool point by about 1 cm per unit per step. DTWIST turns the gripper about its own tool axis by 5 degrees per unit per step; positive is clockwise as seen from behind the gripper, looking along its tool axis (from above when it points down). GRIP is the fingers' target: +1 closed, -1 fully open (an 8 cm gap), and values in between give a partial opening (gap = 8 cm * (1 - GRIP) / 2); keep sending +1 to keep holding. `robo move-to X Y Z [--grip G]` moves the tool point in a straight line toward a point without turning the gripper, and `robo grip G [--steps N]` holds the hand still while it sets the fingers. One step is 20 ms of simulated time.

**Observation.** `robo observe` reports `hand_pos` (the tool point), `hand_twist_deg` (how far the gripper is turned about its tool axis from where it started), `gripper_open` (0 closed to 1 fully open), `touching` (the parts the gripper touches), and under `parts` the instrument's `sash`: `opening_m` (how far it is open, in metres), `handle_pos` (the centre of its handle), `travel_m` (its range of travel). Under `readouts` it shows what the instrument displays: `display.text` (the text on its display), `monitor.reading_m_s` (the face velocity the airflow monitor shows, in m/s), `indicator.safe` (the monitor's green SAFE light), `indicator.unsafe` (the monitor's red alarm light).

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
