# VLA policies (`vla` harness)

`--harness vla --model PRESET` drives an episode with a vision-language-action policy served elsewhere (usually on a GPU). The client (`src/robouse/harnesses/vla/client.py`, standard library + numpy) is copied into the trial workspace and reaches the robot only through `robo`, like every harness; it speaks each policy server's own wire protocol, so the servers run unmodified.

The client runs on the runner's Python, which already has numpy, in isolated mode (`-I`); `PYTHONPATH`, `PYTHONHOME` and the user site do not change its imports. `ROBOUSE_VLA_PYTHON` selects another interpreter with numpy. When running Robo Use with `uvx`, set that variable to an environment outside the package caches the sandbox denies; the runner's cached virtualenv stays hidden.

```bash
export ROBOUSE_VLA_URL=ws://gpu-box:8000          # the policy server
robouse run --task libero-10-0 --harness vla --model openpi/pi05_libero --out runs/pi05
robouse run --task real-so101-reach --harness vla --model gr00t/so101 --out runs/gr00t   # ROBOUSE_VLA_URL=tcp://gpu-box:5555
```

## Wire protocols

| Wire | Servers | Transport and messages |
|---|---|---|
| `openpi` | openpi `serve_policy.py` (pi0, pi0-FAST, pi0.5) | websocket; msgpack with openpi's numpy convention; server metadata first, then one observation dict per request, reply `{"actions": [H, D]}` |
| `xpolicylab` | XPolicyLab policy servers (pi0/pi0.5, GR00T, OpenVLA-OFT, RDT-1B, SmolVLA, ACT, Diffusion Policy, ...) | websocket; msgpack + msgpack-numpy envelope (`hello`, `reset`, `infer`, `trial_end`), Observation Data Format v1.0, reply a list of per-step action dicts |
| `openvla` | OpenVLA `vla-scripts/deploy.py` | HTTP POST `/act`, json-numpy `{"image", "instruction", "unnorm_key"}`, reply one action |
| `gr00t` | Isaac GR00T N1.6/N1.7 `run_gr00t_server.py` | ZeroMQ REQ/REP, msgpack + msgpack-numpy, `{"endpoint": "get_action", "data": {"observation": ...}}`, reply `[{key: [B, H, D]}, info]` |
| `http-json` | Robo Use's MolmoAct2 server and `src/robouse/harnesses/vla/lerobot_server.py` (any LeRobot policy: SmolVLA, pi0, pi0.5, ACT, diffusion, MolmoAct2; LIBERO pipeline or joint-state robots) | HTTP JSON: `/reset`, `/act` with base64 PNG images and state, reply `{"actions": [[...]]}` |

## Presets

`src/robouse/harnesses/vla/presets.json` fixes, per policy, the wire, the observation template (dotted keys filled from a camera, state fields, the instruction or a constant, with resizing, padding and flips), the action mapping onto the task's action vector (selection, sign, scale, gripper conventions such as OpenVLA's, relative-to-state) and the chunk controller. Shipped: `openpi/pi05_libero`, `openpi/pi0_libero`, `lerobot/pi0_libero`, `lerobot/pi0fast_libero`, `lerobot/groot_n1.7_libero`, `lerobot/evo1_libero`, `lerobot/vla_jepa_libero`, `openvla/openvla-7b-libero`, `molmoact2/libero`, `lerobot/smolvla_libero`, `lerobot/pi05_libero`, `gr00t/so101`, `xpolicylab/metal-joint`, `xpolicylab/so101-joint`, and `*/generic` presets to fill in. Override any field with `ROBOUSE_VLA_POLICY_CONFIG=overrides.json`. State sources are dotted field names, `{"const": [...]}`, or `{"field": name, "scale": s, "fn": "quat_to_axis_angle" | "width_to_fingers"}` for robots that report a quantity in another form. `per_backend: {backend: {...}}` in an override applies top-level keys only on that simulator, so one job can span suites.

## Chunk execution and checks

- Controllers: open loop (`replan: K` executes the first K actions of each chunk), ACT/ALOHA temporal ensembling (`mode: ensemble`, weights exp(-m * age)), exponential smoothing (`smooth: alpha`).
- Compatibility check before anything moves: the preset's backends, the policy's action dimension against the task's (unless mapped), and the policy's control mode against the embodiment's action groups. A mismatch ends the episode with `give_up` and the reason, at 0 steps.
- A VLA never says done: the client claims `done` when the budget is about to run out or, with `stop.still_steps`, when the commanded action has settled.
- Every inference is one JSON line in `agent/stdout.jsonl` (chunk shape, executed actions, round-trip and server timing), converted to the trial's ATIF trajectory.

## Real checkpoints on a GPU

Each policy ran behind its own unmodified server on a Daytona H100 or RTX PRO 6000. The Robo Use runner, simulator and harness ran on the Mac and reached the server through an SSH tunnel (`ssh -N -L 18000:127.0.0.1:8000 <token>@ssh.app.daytona.io`); the preview proxy dropped long websocket sessions. One episode per task, initial states from the LIBERO demonstrations (see [LIBERO](suites/libero.md)).

| Preset | Checkpoint (licence) | Robo Use LIBERO, 40 tasks | Spatial / Object / Goal / Long | Published |
|---|---|---|---|---|
| `openpi/pi05_libero` | openpi `pi05_libero` (Gemma terms) | 38/40 | 10 / 9 / 9 / 10 | 96.85% (openpi) |
| `lerobot/groot_n1.7_libero` | `nvidia/gr00t17-lerobot-libero_*-640`, one per suite (Apache-2.0) | 38/40 | 10 / 10 / 9 / 9 | 96.5% (LeRobot) |
| `openpi/pi0_libero` | openpi `pi0_libero` (Gemma terms) | 36/40 | 9 / 9 / 9 / 9 | 94.15% (openpi) |
| `lerobot/evo1_libero` | `zuoxingdong/evo1_libero` (Qwen licence for the language part) | 40/40 | 10 / 10 / 10 / 10 | 96.65% (LeRobot) |
| `lerobot/vla_jepa_libero` | `lerobot/VLA-JEPA-LIBERO` (Apache-2.0) | 38/40 | 9 / 10 / 9 / 10 | 96.5% (LeRobot) |
| `lerobot/pi05_libero` | `lerobot/pi05_libero_finetuned_v044` (Gemma terms; gated PaliGemma tokenizer) | 37/40 | 10 / 10 / 8 / 9 | 97.5% (LeRobot) |
| `lerobot/pi0fast_libero` | `lerobot/pi0fast-libero` (Gemma terms; gated PaliGemma tokenizer) | 32/39 | 8 / 8 / 10 / 6 | 82.5% (LeRobot) |
| `lerobot/pi0_libero` | `lerobot/pi0_libero_finetuned_v044` (Gemma terms; gated PaliGemma tokenizer) | 30/40 | 6 / 10 / 7 / 7 | none for this checkpoint |
| `lerobot/smolvla_libero` | `HuggingFaceVLA/smolvla_libero` (Apache-2.0), `n_action_steps=10` | 26/40 | 5 / 10 / 8 / 3 | none for this checkpoint |

LeRobot's pi0-FAST has 39 scored trials: one ended when the Mac running the simulator ran out of disk, and was not rerun. The LeRobot ports ran with `--policy.n_action_steps=10` (pi0-FAST: `--policy.max_action_tokens=256 --policy.gradient_checkpointing=false`), with `HF_TOKEN` set on the server for the tokenizer. Published figures use LIBERO's held-out initial states and 50 episodes per task; the 95% interval on 38/40 is roughly 83-99%. Jobs: `runs/final-libero-vla-*`.

Cross-checks with the upstream evaluators, one episode per task on LIBERO's own initial states:
- GR00T N1.7, `lerobot-eval` with the same four checkpoints: 37/40 (9 / 10 / 9 / 9). The failed tasks differ from the Robo Use run's.
- pi0.5, openpi's `examples/libero/main.py` against the same server: libero_spatial 10/10.
- LeRobot's pi0.5 port, `lerobot-eval --policy.n_action_steps=10`: libero_spatial 10/10, libero_10 10/10 (Robo Use: 10/10 and 9/10).

Zero-shot probe (not trained on these tasks): 5 LIBERO-90 tasks, 4 robosuite Panda tasks and 3 Meta-World tasks (`runs/final-zeroshot-vla-*`, mapping in `per_backend` overrides: robosuite shares LIBERO's cameras, state from `hand_quat` and `gripper_open`; Meta-World fills both image slots with its one camera and maps LIBERO's (dx, dy) to (-dy, dx)). pi0.5 solved 1/12 (robosuite Lift, 73 steps); GR00T N1.7 (libero_10 checkpoint) 0/12. Every other trial ran out its step budget.

Serving, as run:

```bash
# openpi (checkpoints from the public gs://openpi-assets bucket; the tokenizer comes from Google's public big_vision bucket)
XLA_PYTHON_CLIENT_MEM_FRACTION=0.4 .venv/bin/python scripts/serve_policy.py --port 8000 \
  policy:checkpoint --policy.config=pi05_libero --policy.dir=/root/ckpt/pi05_libero
# any LeRobot policy (LeRobot e0d50211), e.g. GR00T N1.7 for one suite
MUJOCO_GL=egl .venv/bin/python lerobot_server.py --port 8000 -- --policy.path=/root/ckpt/gr00t17-libero_spatial \
  --policy.device=cuda --env.type=libero --env.task=libero_spatial \
  --env.camera_name_mapping='{"agentview_image":"image","robot0_eye_in_hand_image":"wrist_image"}' --seed=1000
# on the Mac, from the repo
ROBOUSE_VLA_URL=ws://127.0.0.1:18000 MUJOCO_GL=cgl PYTHONPATH=src .venv/bin/python -m robouse.cli run-many \
  --tasks tasks --task-list libero40.txt --harness vla --model openpi/pi05_libero --out runs/final-libero-vla-pi05 --concurrency 4
```

GR00T N1.7 loads its backbone weights from the checkpoint and its processor files from `nvidia/Cosmos-Reason2-2B` (gated; needs `HF_TOKEN`). The checkpoints' `base_model_path` names the trainer's cache, so it is pointed at a local copy of `nvidia/GR00T-N1.7-3B`. The 40-task run above used processor files copied from `Qwen/Qwen3-VL-2B-Instruct`, which are byte-identical to Cosmos-Reason2-2B's; 8 of its tasks (libero-spatial-0/3/6/9, libero-10-0/3/6/9) rerun with NVIDIA's official processor: 8/8, the same as before (`runs/_vla_evidence/groot-cosmos-*`).

Not run: openpi `pi0_fast_libero` (failed its first LIBERO task on Robo Use and 0 of 7 in openpi's own evaluator on the same server; the remaining trials hit server timeouts, so no result is published); X-VLA (`lerobot/xvla-libero` needs LIBERO's absolute-pose control mode, Robo Use's tasks use the standard delta controller); LaWAM (`jialei02/lawam-libero-sft-lerobot`: the server hung on `/act` with the GPU idle); ACT and Diffusion (their gym-aloha and PushT tasks are not hosted); WALL-OSS, EO-1, FLUX 3 Action, Multitask DiT (no public checkpoint for a hosted benchmark); LingBot-VA and FastWAM (LIBERO checkpoints, not run within the GPU budget).

## What was tested

- `tools/ops/vla_dogfood.sh`: mock policy servers built on the upstream libraries (msgpack, msgpack-numpy, websockets, pyzmq, json-numpy; `tests/vla_mock_servers.py`) on every wire, end to end through the sandboxed harness: openpi, OpenVLA and http-json replay a LIBERO demonstration through the wire and solve `libero-10-0`; XPolicyLab solves `real-metal-reach` and GR00T solves `real-so101-reach` on the hardware-in-the-loop mock. 5/5. The observations the servers received had the expected keys, shapes and dtypes (e.g. openpi `observation/image uint8[224, 224, 3]`, GR00T `video.front uint8[1, 1, 224, 224, 3]`).
- An incompatible pairing (`gr00t/so101` on the 7-joint Metal arm) is rejected at 0 steps.
- `tests/test_vla.py`: codecs, PNG round trip, resizing, gripper mapping, controllers, compatibility check, presets.
- A real model on CPU: SmolVLA-LIBERO (`HuggingFaceVLA/smolvla_libero`, Apache-2.0) behind `lerobot_server.py` in a LeRobot 0.6.1 virtualenv (`--policy.device=cpu --policy.n_action_steps=10`), preset `lerobot/smolvla_libero`: 2 of 5 LIBERO tasks solved (libero-spatial-0, libero-object-0; `runs/smolvla-cpu`).
- GPU-served checkpoints: above. Not tested: OpenVLA, MolmoAct2 through this client, XPolicyLab policies, GR00T on a real SO-101.
