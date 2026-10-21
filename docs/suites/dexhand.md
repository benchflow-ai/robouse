# Dexhand suite (Shadow Hand, LEAP Hand and ROBOTIS HX5-D20 on a positioner)

The dexhand suite has 9 tasks in `tasks/dexhand/`: three for the Shadow Dexterous Hand, four for the LEAP Hand and two for ROBOTIS's HX5-D20 (added 2026-10-21). The hand is the robot: it hangs from a 6-axis positioner above a table and does dexterous manipulation (regrasping, pouring, turning a wheel, pressing buttons, an in-hand flip). It is distinct from the DexJoCo suite, where Allegro hands sit on Panda arms.

- Backend: `src/robouse/backends/dexhand.py` (declaration, controllers, skills, monitor, judge, reference solutions) and `src/robouse/backends/dexhand_sim/scene.py` (scene builder and hand mounting).
- Generator: `python adapters/dexhand/generate.py`.
- Shared embodiment base: `src/robouse/backends/embodied.py`.

![Shadow Hand pouring balls from a cup into a bowl](../img/suites/dexhand.webp)

## Models and licences

The Shadow and LEAP hands come from MuJoCo Menagerie at commit `8161bba2...` (hashes in `assets/menagerie/embodiments.json`), each its upstream `right_hand.xml`. The HX5-D20 is one of ROBOTIS's open-source "HX Friends" hand designs ([docs](https://docs.robotis.com/docs/systems/hx_friends/)); its MuJoCo model is ROBOTIS's own, `robotis_hand_description/mujoco/hx5_d20_rev2/hx5_d20_right.xml` in [ROBOTIS-GIT/robotis_hand](https://github.com/ROBOTIS-GIT/robotis_hand) at commit `6f9e22a5...` (Apache-2.0; the model and its meshes, 14 files, about 7 MB, with hashes in `assets/robotis/hx5_d20.json`, downloaded by `robouse fetch-assets --all` or `--robot robotis_hx5_d20`). Each hand is attached unchanged: kinematics, position actuators, gains, force ranges, joint damping, contact exclusions, geom friction and solver parameters are as shipped.

| Hand | Menagerie folder | Licence | Joints / actuators |
|---|---|---|---|
| Shadow Dexterous Hand E3M5, right | `shadow_hand` | Apache-2.0 | 24 joints, 20 position actuators: 2 wrist, 5 thumb, 3 each for index/middle/ring (the two distal joints are tendon-coupled and share one `..J0` actuator whose target is their sum), 4 for the little finger |
| LEAP Hand, right | `leap_hand` | MIT | 16 joints, 16 position actuators: index/middle/ring `mcp`, `rot`, `pip`, `dip`; thumb `cmc`, `axl`, `mcp`, `ipl` |
| ROBOTIS HX5-D20 (rev2), right | `robotis_hx5_d20` (ROBOTIS's repository, not Menagerie) | Apache-2.0 | 20 joints, each a DYNAMIXEL XM335 position servo (kp 4, 0.387 N m): `finger_r_joint1`-`4` thumb (swing in the palm's plane, opposition, two flexions), `5`-`8` index, `9`-`12` middle, `13`-`16` ring, `17`-`20` little (spread, three flexions) |

## Scene and mounting

World frame: +x forward (away from the positioner's home), +y left, +z up. Floor at z = 0; the table top is at z = 0.40 and spans x -0.35..0.55, y -0.35..0.35.

The hand hangs from a positioner, as in lab setups where a hand is carried by an arm or gantry. The instructions say so. The positioner has three prismatic joints (x, y, z) and three revolute joints in yaw-pitch-roll order. At zero angles the palm faces down and the fingers point along +x. ROLL turns the hand about its long axis (+90: palm faces +y; 180: palm up), PITCH tips the fingers down (+), YAW turns about the vertical. The Shadow Hand is mounted at its wrist joint; the LEAP Hand and the HX5-D20 at the centre of the back of the palm (the HX5-D20's model has its fingers along +z and its palm facing +x, so it is turned 90 degrees about y). Only the hand has collision geometry; the grey link behind it is visual.

Objects are free rigid bodies. Their sliding friction is raised to 1.2 (rubber-coated; the small balls 0.8), because MuJoCo uses the larger coefficient of a pair; the hands keep their upstream friction (Shadow 1.0, LEAP 0.2 body / 0.5 fingertips). Grasps are friction grasps only: no welds, no teleports, no mocap.

Physics: 2 ms steps, `implicitfast` integrator, elliptic friction cones, each hand's upstream `impratio` (Shadow 10, LEAP 100, HX5-D20 10), no noslip iterations (grasps held without them). Container bottoms are 15 mm thick and the table is 8 cm thick, because thinner plates let fast small balls and the marker tunnel through.

## Action and controllers

One step is 40 ms (20 physics steps). The action is two groups, 26 values for Shadow and the HX5-D20 and 22 for LEAP, each in [-1, 1]. All zeros holds.

| Group | Mode | Components | Scale |
|---|---|---|---|
| `wrist.pose_delta` | `ee_delta_pose`; frame: xyz world, rpy positioner joints | DX DY DZ DROLL DPITCH DYAW | x 1 cm on the positioner's x, y, z target; x 4 degrees on its roll, pitch, yaw target |
| `hand.joints` | `joint_delta` | one per hand actuator (upstream order) | added to the actuator's position target, x 10 % of its control range per step |

Controllers:

- Positioner: joint-space PD with gravity feed-forward (`qfrc_bias`), recomputed every physics step. Gains come from the joint-space inertia at the start pose (40 rad/s, damping ratio 0.9). Motor limits are 200 N (x, y), 300 N (z) and 40 N m (rotations). The target never runs more than 3 cm or 15 degrees ahead of the measured pose, so pushing into the table stalls instead of building up force.
- Hand: the upstream position servos. A finger stopped by an object keeps squeezing with a force set by the remaining target error and the actuator's gain and force range.

## Observation, skills, events

`robo observe` returns:

- `hand`: wrist pose and targets, `palm_pos` (a point about 3.5 cm in front of the palm), `palm_normal`, `finger_dir`, fingertip positions, joint positions and targets normalised to [-1, 1], and per-finger contacts;
- `objects`: pose and what each object touches, cube face normals, and the marker's end points;
- `table`, `landmarks` (bowl and holders with rim height, `inside_bottom_z` and `inside_depth`; valve angle; buttons with depth), `progress`, `safety_events`.

Cameras: `front` (default), `side`, `top`, `back`.

Skills are generators that yield ordinary actions, so they share the budget and the video:

- `move_to X Y Z [SPEED]`, `move_by DX DY DZ [SPEED]`: straight line of the palm point with the orientation held; SPEED clamped to 0.01-0.25 m/s. Each reports `reached` or `blocked`, or `remaining_m` if it runs out of its 400 steps.
- `rotate ROLL PITCH YAW [SPEED]`: absolute positioner angles, turning about the palm point; SPEED clamped to 5-100 deg/s.
- `turn_about X Y DEG [SPEED]`: swing the hand about a vertical line, yawing with it; SPEED clamped to 5-90 deg/s. It reports `remaining_deg` if it runs out of its 580 steps.
- `grasp power|pinch|tripod`: close those fingers toward a fully closed posture until they stall. Reports which fingers touch what.
- `open` (gentle), `pose NAME` (`open`, `flat`, `relaxed`, `point`, `fist`, `power_ready`, `pinch_ready`, `tripod_ready`), `set_joint NAME DEG`, `wait [SECONDS]`.

None of the skills attaches anything or reads hidden state. They only read public observation fields and the controller's own targets.

Events: an object reaching the floor is recorded as "dropped" if the hand had lifted it, else "knocked off the table". In the in-hand task, the cube touching the table and any positioner angle deviating more than 15 degrees from its start are events, both checked every 2 ms physics step. Any event fails the task.

## Tasks

Success is judged from the physical state after `robo done` and a 10-step hold.

| Task | Hand | Goal | Success rule | Budget |
|---|---|---|---|---|
| shadow-cube-face-up | Shadow | Turn a 5.6 cm coloured cube so red is up (reorient by regrasp) | Red normal within 20 degrees of up; cube on the table, not touched by the hand; never fell off | 1200 |
| shadow-pour-balls | Shadow | Lift a cup holding six balls, pour into a bowl (rim 4.5 cm, 3 cm deep inside over a 1.5 cm bottom), set the cup down | At least 4 ball centres inside the bowl's inner radius and below its rim height; cup upright (within 20 degrees) on the table | 1200 |
| shadow-turn-valve | Shadow | Turn a three-spoke hand wheel (friction 0.15 N m) at least 180 degrees counter-clockwise | Wheel angle at least 180 degrees from its start (the yaw range means it may need more than one stroke; the oracle uses two) | 1000 |
| leap-lift-ball | LEAP | Lift a 6.6 cm ball out of a ring stand | Ball centre at least 0.15 m above the table, touching the hand, not the table, slower than 5 cm/s | 700 |
| leap-pen-to-holder | LEAP | Move a 16.6 cm marker from a narrow stand (4.5 cm deep inside) into a pen cup (6.5 cm deep inside) | Marker's lower end inside the cup (radius, below rim); hand not touching it | 1000 |
| leap-press-buttons | LEAP | Press spring buttons green, blue, green; never red | Click sequence exactly [green, blue, green] (a click is at least 8 mm of travel) | 800 |
| leap-cube-in-hand | LEAP | Palm up, flip a cube lying on the palm so red is up (in-hand, large tolerance) | Red normal within 25 degrees of up; cube on the hand, not the table; wrist angles never deviated more than 15 degrees from start and cube never touched the table (both checked every physics step) | 600 |
| hx5-lift-ball | HX5-D20 | Lift a 6.6 cm ball out of a ring stand (the LEAP task's scene) | As leap-lift-ball | 700 |
| hx5-press-buttons | HX5-D20 | Press spring buttons green, blue, green; never red (the LEAP task's scene) | As leap-press-buttons | 800 |

In-hand versus regrasp:

- `leap-cube-in-hand` is the in-hand task. The fingers roll the cube over its rear edge onto the palm while the wrist stays put, and the tolerance is large (25 degrees).
- `shadow-cube-face-up` is reorientation by regrasp: pick up, turn the forearm, put down, let go.

A scripted in-hand rotation about the vertical (finger gaits, pushes, couples) never exceeded about 10 degrees without the cube tumbling, so that version is not included.

## Validation

Real runner, 2026-09-28, on this Mac's CPU:

| Harness | Result | Runs |
|---|---|---|
| oracle | 7/7 | `runs/emb-oracle-dexhand-v2/`, `runs/emb-oracle-dexhand-v3/` |
| noop | 0/7 | `runs/emb-noop-dexhand-v2/`, `runs/emb-noop-dexhand-v3/` |

- Oracle episodes take 8-14 s wall time and 45-586 steps. The reference solutions use only the socket: skills plus raw `robo act` for the in-hand flip.
- MuJoCo's results differ slightly between platforms, and the pour is sensitive to them: in the linux/arm64 hub image (robohub runtime `embodied`) five of the six balls stayed caught behind the thumb after the first 45-degree pour, so the reference solution failed there. It now reads `progress.balls_in_bowl` after the pour and, while fewer than 5 are in the bowl, rolls the cup further (to -65 and -75 degrees) and back to shake them out. On the Mac the first pour already puts 5 in the bowl and nothing changes (586 steps, v3 run); in the Docker image the reference solution takes 675 steps and scores 1.
- Frames from every recording were checked. They show no interpenetration, no flying objects and no teleports.
- Plausible-but-wrong attempts all scored 0:
  - ball lifted only 8 cm;
  - cube held red-up in the hand instead of put down;
  - cup poured beside the bowl;
  - marker released beside the pen cup;
  - buttons pressed green, red, blue;
  - valve turned about 70 degrees.
- Sensitivity of the regrasp and in-hand solutions to the start pose:
  - cube face-up: 6/6 cube positions within 2 cm (tripod grasp; the power grasp failed 2/6 on release);
  - in-hand flip: 6/7 cube offsets within 1.5 cm.

HX5-D20 (2026-10-21, `robouse tasks check` on a Linux x86_64 CPU, MuJoCo 3.3.0): hx5-lift-ball reference solution 1 (146 steps), no-op 0; hx5-press-buttons reference solution 1 (245 steps), no-op 0. The same on macOS arm64 (in process). The press uses the LEAP task's solution unchanged (`point` posture, fingers down, index presses). The lift uses the same skills with the palm point 3.5 cm to the ball's right, 0.6 cm ahead and 2.5 cm higher than the LEAP's centred grasp (`grasp_dx`, `grasp_dy`, `grasp_dz` in the task): the HX5-D20's thumb sits beside the heel of the palm and, opposed, points straight down, so a centred grasp puts it on the table and the curling fingers squeeze the ball out; offset, the thumb comes down behind the ball and the fingers close it against the thumb. The lift also succeeds with the palm point moved 0.6 cm forward or back and 0.5 cm up or down (all four corners of that range).

## Model probe

One trial per task with Claude Code against Kimi K3 on Baseten (`claude-code-glm --model moonshotai/Kimi-K3`), 2026-09-28. Codex with GPT-6 Astra was not probed: every Codex account available for the run had hit its usage limit (until 2026-10-03). These are probes, not rates. Runs: `runs/emb-probe-dexhand-kimi/`.

| Task | Kimi K3 |
|---|---|
| shadow-turn-valve | 1 |
| leap-cube-in-hand | 1 (81 steps; wrist pitch stayed within 12 degrees) |
| shadow-pour-balls | 0 (agent timeout after 30 min) |

The probes ran before the review fixes; since then the in-hand wrist and table rules are checked at every physics step.

## Limitations

- The positioner is an idealised Cartesian-plus-Euler stage, not a real arm. It has no reach limits beyond its joint ranges and no link collisions.
- The Shadow Hand's upstream actuators are low-gain (kp 0.5-1, 1 N m force limit). Thin objects slip or are squeezed out of its grasps, so the marker task uses the LEAP Hand.
- The HX5-D20's thumb opposes from beside the heel of the palm, not across it, so its grasps of small objects need the object off the palm's centre line (see Validation). ROBOTIS's other HX Friends designs (HX4-D12, HX3-D11, the HX2-D01 gripper, the HX1-D03 finger) are not here: their CAD and URDF are Dropbox downloads with no licence stated, and the gripper has no files yet.
- The LEAP Hand's upstream contacts are very stiff (`solref` 1e-4, `impratio` 100). Fast finger motions can flick objects, which is why `open` ramps slowly.
- Contacts per finger are exact simulator contacts, a stand-in for tactile sensing. State is exact, with no sensor noise.
- The reference solutions are scripts tuned on the default scene; the simulation is deterministic, so they reproduce exactly.
