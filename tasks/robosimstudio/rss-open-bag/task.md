---
schema_version: '1.3'
task:
  name: robouse/rss-open-bag
  description: 'RoboSimStudio: Open the bag'
metadata:
  source_benchmark: RoboSimStudio scored CPU example (eb3d46a839bf8d9b8df6e9c3f0205e141f5b3f7f, Apache-2.0)
  source_task: examples/06_tasks/06_bag_scored.py
  language_instruction: Open the canvas bag's mouth to at least 30 mm, using the robot's grippers.
  suite: robosimstudio
  category: deformable-manipulation
  difficulty: hard
  tags:
  - bimanual
  - yam
  - vision
  - deformable
  - cpu
  - fixed-layout
agent:
  timeout_sec: 1800
verifier:
  timeout_sec: 60
robouse:
  id: rss-open-bag
  backend: robosimstudio
  env: open-bag
  seed: 0
  max_steps: 1200
  camera: overview
  cameras:
  - overview
  obs_mode: vision
  visible_fields:
  - left_tcp_pos
  - left_tcp_quat
  - left_joint_pos
  - left_joint_vel
  - left_gripper_width
  - right_tcp_pos
  - right_tcp_quat
  - right_joint_pos
  - right_joint_vel
  - right_gripper_width
  - previous_action
  - step_index
  - simulation_time_s
  skills: false
  success_mode: first
  frame_every: 10
  control_dt: 0.016666666666666666
---

# RoboSimStudio: Open the bag

Open the canvas bag's mouth to at least 30 mm, using the robot's grippers.

**Success:** the episode ends successfully at the first control step where the native `mouth_opening` predicate measures at least 0.03 m. This is the upstream scored example's physical success rule. A `done` call before the goal holds scores 0.

**Scene.** The table surface is at z = 0.728 m. The canvas bag stands on the table. Two YAM arms with parallel grippers can manipulate the material. The layout is the upstream example's fixed layout; seeds do not randomize it. Use the camera to locate the material and fixtures.

**Controls.** `robo act` takes 16 numbers: the left tool's world x/y/z in metres, its quaternion qx/qy/qz/qw, its grip (0 open, 1 closed), then the same eight values for the right arm. A quaternion must be nonzero; the controller normalizes it. World +z is up. The simulator uses native Cartesian IK, joint servos and physical contacts. There are no skills. Start from `neutral_action` in `robo info` to hold the other arm. Interpolate tool poses in small increments and allow the joints time to follow.

**Observation.** `robo observe` gives each arm's tool position and xyzw orientation, joint positions and velocities, and measured gripper width, plus the previous action, step index and simulation time. `robo observe --image` saves the `overview` camera image. Its 3x4 projection in `robo info` maps homogeneous world points to image pixels. Material coordinates and goal metrics are hidden.

**Budget.** At most 1200 control steps, at 60 Hz (20 s simulated time). Every step counts, including repeats. The CPU solver is the pinned upstream example's implementation; its material coupling differs from the GPU path.

## How to control the robot

You are the robot's policy. Act through `robo` in your shell. The episode server judges the physical state.

```
robo info
robo observe --image
robo act V1 V2 ... V16 [--repeat N]
robo done "short summary"
robo give-up "reason"
```

A repeat executes at most 50 steps per call. The last tool targets are held between calls. The episode stops automatically on first success or at the step budget. Call `robo done` when finished if it has not already stopped.
