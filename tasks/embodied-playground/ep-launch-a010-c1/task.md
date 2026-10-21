---
schema_version: '1.3'
task:
  name: robouse/ep-launch-a010-c1
  description: 'Embodied Playground Launch-05 (marble/dual-panda/A010), condition 1 of 4: Toppling timber gate'
metadata:
  source_benchmark: Embodied Playground (EP-100), Winniechen2002/Embodied-Playground at 45993d4
  source_task: marble/dual-panda/A010
  ep_index: Launch-05
  ep_type: Launch-Aim
  ep_name: Toppling timber gate
  ep_split: Easy
  ep20: false
  ep_condition: 1
  ep_protocol: environment-four-trial-v2
  ep_level: 0
  suite: embodied-playground
  category: manipulation
  difficulty: medium
  tags:
  - bimanual
  - franka
  - mujoco
  - vision
  - long-horizon
  - embodied-playground
  reference_solution: scripted pull-and-release with a 10 cm draw, found by simulation (robouse.backends.embodied_playground.planner); 482 steps
agent:
  timeout_sec: 600
verifier:
  timeout_sec: 120
robouse:
  id: ep-launch-a010-c1
  backend: embodied_playground
  family: marble
  env: marble/dual-panda/A010
  ep_scenario: wooden_gate
  condition: 1
  initial_mode: loaded
  environment_parameters:
    spring_stiffness: 22.0
    launcher_offset_m:
    - -0.012
    - 0.0
    - 0.0
    ammunition_offset_m:
    - -0.012
    - -0.008
    - 0.0
    background: dusk
    background_motion: static
  goal: 'Knock over the movable shield and reach the target behind it. Target indices are zero-based. Required targets: [0]; protected targets: []; required order: [] (empty means unrestricted); minimum toppled structures: 1.'
  seed: 0
  max_steps: 7500
  camera: front_left
  cameras:
  - front_left
  obs_mode: vision
  visible_fields:
  - left_joint_pos
  - left_joint_vel
  - left_finger_pos
  - right_joint_pos
  - right_joint_vel
  - right_finger_pos
  - previous_action
  - step_index
  - simulation_time_s
  - terminated
  - truncated
  skills: false
  success_mode: first
  frame_every: 5
---

# Embodied Playground, Launcher: Toppling timber gate

This is Embodied Playground's task `marble/dual-panda/A010` (Launch-05 of its EP-100 benchmark, type Launch-Aim), condition 1 of 4 (spring stiffness 22 N/m, dusk background), at its Level 0. Two simulated Franka Panda arms stand by a scene in MuJoCo; you drive them with the `robo` command.

## Goal

Embodied Playground's goal for this task, verbatim:

> Knock over the movable shield and reach the target behind it. Target indices are zero-based. Required targets: [0]; protected targets: []; required order: [] (empty means unrestricted); minimum toppled structures: 1.

The declared condition: the launcher's spring stiffness in this episode is 22 N/m.

**Success** is Embodied Playground's own check, made at every physics step: every required target cleared, and the task's other conditions met (toppled structures, fractures, protected targets, order). The episode is scored solved the first time it holds. Any other ending scores 0.

**The episode ends without success** at the first rule or physical violation (for example an arm pressing into an object, a joint moving too fast, a launcher part pushed past its limit, a protected target hit or targets cleared out of order), when the 150 s of simulated time are up, or once every projectile has been fired and has settled.

**Controls.** `robo act` takes 16 numbers: the left arm's seven joint targets (`left_0` to `left_6`, absolute, radians) and its gripper command (`left_gripper`: +1 open, -1 closed), then the same eight for the right arm. One step is 20 ms of simulated time (20 physics steps of 1 ms). Each joint moves toward its target no faster than its speed limit; a target held over several steps (`--repeat`) keeps the joint moving. There are no skills: at Level 0 you write your own perception, kinematics and planning, for example in Python with NumPy and Pillow. As Embodied Playground's rules say, do not search online or download anything for this task, and do not look for Embodied Playground's source, assets or task files: the episode, `robo` and your own code are all you use. `robo info` lists the robots (model, joint names, joint limits) and the neutral action, which is where both arms start.

**Observation.** `robo observe` reports per arm (`left`, `right`) the seven joint positions (`*_joint_pos`, rad), their velocities (`*_joint_vel`, rad/s) and the two finger positions (`*_finger_pos`, m), the previous action, the step index, the simulated time, and whether the episode has ended (`terminated`, `truncated`). It does not report where anything else is: find the scene in the `front_left` camera's images (640x400), which every `robo observe` saves. `robo info` gives that camera's 3x4 projection matrix, which maps a world point to its pixel.

The step budget is 7500 steps (150 s of simulated time).

## How to control the robot

You are the robot's policy. You act only through the `robo` command in your shell. There is no other way to move the robot, and you cannot read or change the simulator, the scoring, or other files to succeed; the episode server judges the physical state itself.

```
robo info                          # the robots, the camera's projection matrix, the action groups and the step budget
robo observe                       # the robots' joint state, and the camera image (saved under observations/)
robo act V1 V2 ... V16 [--repeat N]  # one action (16 numbers, see Controls), applied N times (N <= 50)
robo done "short summary"          # end the episode and ask for scoring
robo give-up "reason"              # end the episode without claiming success
```

- Positions are in metres in the world frame (+z up); joint angles in radians.
- The episode has a fixed step budget (see `robo info`); every simulated control step counts.
- The episode is scored solved the moment Embodied Playground's success check holds; after that `robo act` answers that the episode has finished. If the episode ends otherwise (`terminated` or `truncated` in `robo observe`), or when you stop, call `robo done` once.
