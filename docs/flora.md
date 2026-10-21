# Annotate trials with Flora

[Flora](https://research.nvidia.com/labs/gear/flora/) is NVIDIA GEAR's suite of open video models for robotics data engines ("Flora: An Open Model Suite for Scaling Robotics Data Engines", Leng, Man, Li et al., 2026; the models are on [Hugging Face](https://huggingface.co/collections/nvidia/flora)). NVIDIA uses it to label the episodes GR00T models are trained on. Given a robot episode's video and its task instruction, its three models say how the episode went and what the robot did:

| Model | What it says about a recording | Size |
|---|---|---|
| [Flora-Rewarder](https://huggingface.co/nvidia/Flora-Rewarder) | Outcome: a score from 1 (complete failure) to 5 (complete success), with the probability of each score. Dense: for every 0.5 s, failure, suboptimal or normal, with a short reason for each stretch that is not normal. (A third prompt grades a rubric; Robo Use does not use it.) | 27.8B parameters, fine-tuned from Qwen3.5-27B; 55.6 GB of BF16 weights |
| [Flora-TempSeg](https://huggingface.co/nvidia/Flora-TempSeg) | The start and end of each action | a LoRA adapter on Qwen3.5-9B (19.3 GB) |
| [Flora-Captioner](https://huggingface.co/nvidia/Flora-Captioner) | One imperative instruction for each action TempSeg found: the intended action, its objects, and which hand or gripper does what | 27.4B parameters, fine-tuned from Qwen3.5-27B; 109 GB of FP32 weights |

A Robo Use trial also has the simulator's verdict, so Flora's can be checked against it. `robouse flora export` writes the input files of NVIDIA's inference scripts for a run's trials; the scripts run, unmodified, on a GPU machine; `robouse flora import` reads their results into the trial folders, with the agent's steps during each labelled stretch, and prints how often Flora's outcome agrees with the simulator. `robouse report` then has the agreement and Flora's progress estimate as metrics.

On 21 trials of claude-opus-5-5 (Claude Code, alone or in ASPIRE's workflow), Flora-Rewarder's outcome agreed with the simulator's verdict on 11: the simulator solved 19, Flora gave 9 of those its top score and gave neither of the other two a 5 ([What was tested](#what-was-tested)). It judges what the video shows, and where it disagreed, its reasons were about what the frames did or did not show (a lift seen from above, a bowl still in the gripper when the episode ended, a dial's setting). It is a second opinion on a recording, not a replacement for the simulator's check.

## Licence

Flora's weights, and the inference scripts in its Hugging Face repositories, are under the [NVIDIA License](https://developer.download.nvidia.com/licenses/NVIDIA-OneWay-Noncommercial-License-22Mar2022.pdf) (the model cards call it the NVIDIA OneWay Noncommercial License, 22 March 2022): they may be used only for research or evaluation, not commercially. NVIDIA's model cards add that Flora is not intended or supported for commercial or production use, and that its outputs are annotations, not meant to control a robot or to be a system's only safety monitor. The base models, Qwen3.5-27B and Qwen3.5-9B, are Apache 2.0.

Robo Use does not include or download any of it. `robouse flora` (Apache 2.0, like the rest of Robo Use) writes the scripts' input files and reads their output files; you download the models and scripts from Hugging Face on your own GPU machine and accept their licence there. The weights are public: no Hugging Face account is needed.

## What you need

- Robo Use: the base install; `robouse flora` needs no extra.
- Flora: a Linux machine with Python 3.12 and an NVIDIA GPU with 80 GB of memory, the configuration NVIDIA validated its scripts on (H100 80 GB). The Rewarder's outcome and dense scripts need one such GPU (vLLM 0.24.0, Transformers 5.8.1); vLLM 0.24.0 pins PyPI's PyTorch 2.11.0, which is built for CUDA 13 and so needs NVIDIA driver 580 or newer. The captioning pipeline runs TempSeg, then the Captioner, on one such GPU (PyTorch 2.11 for CUDA 12.8, Transformers 5.8.1), and NVIDIA recommends at least 150 GB of disk for the weights it downloads. The run below used 8 CPU cores, 80 GB of memory and 400 GB of disk beside the GPU.

## 1. Export the trials

Any finished trials will do. Here, the reference solution and the no-op control of one task:

```sh
robouse run --task libero-cube-on-plate --harness oracle --out runs/flora-demo
robouse run --task libero-cube-on-plate --harness noop --out runs/flora-demo
```

```console
$ robouse flora export runs/flora-demo --out flora-jobs
skipped runs/flora-demo/libero-cube-on-plate__noop__6c3d35: no recording (no simulator step ran)
wrote 1 reward job and 1 caption job to flora-jobs
next, with JOBS set to this folder on a Linux machine with an 80 GB NVIDIA GPU (https://robouse.ai/docs/flora/):
  in a copy of nvidia/Flora-Rewarder:
    python -m batch_utils.terminal_reward --jobs $JOBS/reward_jobs.jsonl --output $JOBS/results/terminal.jsonl
    python -m batch_utils.dense_reward --jobs $JOBS/reward_jobs.jsonl --output $JOBS/results/dense.jsonl
  in a copy of nvidia/Flora-Captioner:
    python infer.py --input-jsonl $JOBS/caption_jobs.jsonl --output-dir $JOBS/results/captions
then, here: robouse flora import flora-jobs
```

The folder holds:

| Path | Contents |
|---|---|
| `videos/<id>.mp4` | each trial's recording (a hard link where the file system allows, else a copy); the id is the trial folder's name, shortened if it is long |
| `reward_jobs.jsonl` | the Rewarder scripts' `--jobs` file: `{"id", "task", "videos"}`, with the task instruction as `task` |
| `caption_jobs.jsonl` | the captioning pipeline's `--input-jsonl` file: `{"id", "video", "profile"}` |
| `trials.json` | the trial folder of each job, its instruction and where it came from, the video's length, frame rate and SHA-256, and the simulator's verdict |

`export` takes trial folders or run folders. It leaves out trials that failed on infrastructure (they have no verdict) and trials without a recording; a recording longer than 120 s gets a reward job but no caption job, since the captioning pipeline refuses longer videos.

Flora's prompts take the task's instruction: the source benchmark's language instruction where the task has one (the LIBERO suites), else the task's one-line description, else its title. Some descriptions are not instructions (the rule-inference tasks' "Rule inference: falling", for example), and some say how the agent works as well as what the robot should do: the one-demo tasks' end in "after one demonstration", the CaP-X tasks' in "Code as policy with CaP-X's privileged API." Flora sees only the video, so give it the robot's task alone. `--instructions FILE` names the instruction of each task it lists, a JSON object of task ids and instructions; the tasks it does not list get their own:

```json
{
  "one-demo-box-mirrored": "Open the box",
  "capx-nut-assembly-s5": "Grasp the square nut by its handle and put it onto the square peg."
}
```

`--instruction TEXT` gives every exported trial the same instruction instead. `trials.json` records each job's instruction and where it came from. The captioning pipeline gets no instruction, its default. Its profile is `yam`, the pipeline's robot-actions profile; `--caption-profile dex` selects its dexterous-hand profile, and `human` its profile for videos of people.

A recording plays at 30 frames per second, but it advances only while the simulator steps: the agent's thinking time between `robo` requests is not in it. Flora's times are times in the recording.

## 2. Run Flora on a GPU machine

Copy the folder to the GPU machine and set `JOBS` to it there. The Rewarder's scripts load the weights stored next to them:

```sh
hf download nvidia/Flora-Rewarder --revision 7de68d22c4a9decec5ddb7f86ddcaee8f82d3367 --local-dir flora-rewarder
cd flora-rewarder
pip install -r batch_utils/requirements.txt
python -m batch_utils.terminal_reward --jobs $JOBS/reward_jobs.jsonl --output $JOBS/results/terminal.jsonl
python -m batch_utils.dense_reward --jobs $JOBS/reward_jobs.jsonl --output $JOBS/results/dense.jsonl
```

On a machine without the CUDA toolkit (a container with only the NVIDIA driver, for example), run the two scripts with `VLLM_USE_FLASHINFER_SAMPLER=0` in the environment. vLLM 0.24.0 compiles FlashInfer's top-k and top-p sampling kernels while its engine starts, which needs `nvcc`, and stops with "Could not find nvcc" without it. NVIDIA's scripts decode greedily (temperature 0), which never uses that sampler, so the setting does not change their scores, labels or probabilities.

`--with-rationale` makes `terminal_reward` give a one-line reason before each score. The captioning pipeline downloads its two models and the Qwen3.5-9B base itself, at the revisions it pins, so its repository needs only its code; give it a separate virtual environment, since its pins differ from the Rewarder's:

```sh
hf download nvidia/Flora-Captioner --revision f736ca36925ae55d2f7915993ed1bc9f87288bb3 --exclude '*.safetensors' --local-dir flora-captioner
cd flora-captioner
pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r batch_utils/requirements.txt
python infer.py --input-jsonl $JOBS/caption_jobs.jsonl --output-dir $JOBS/results/captions
```

These are the commands of NVIDIA's READMEs in the two repositories (`batch_utils/README.md`), which describe the options and outputs; the run in [What was tested](#what-was-tested) used them as they are. Before you pay for a GPU, the same scripts check the job files on any Linux machine, without the weights: the Rewarder's `--dry-run` reads the videos and prints the first prompt (a copy of the repository without `*.safetensors` is enough, with Transformers 5.8.1 and CPU builds of PyTorch and torchvision), and the captioning pipeline's `--validate-only` checks every video. For the export above:

```console
$ python -m batch_utils.terminal_reward --jobs $JOBS/reward_jobs.jsonl --output $JOBS/results/terminal.jsonl --dry-run 2>&1 | head -1
libero-cube-on-plate__oracle__7e6b12: 143 frames at 30 FPS, collage 320x320, 46 sampled frames
$ python -m batch_utils --input-jsonl $JOBS/caption_jobs.jsonl --validate-only | cut -d, -f1-4
{"status": "inputs_validated", "profile": "YAM", "yam32": false, "duration_s": 4.766667
```

## 3. Import the results

Copy `results/` back into the folder on the machine that has the trials, then:

```sh
robouse flora import flora-jobs
robouse report runs/flora-demo --metrics success,flora_agree,flora_progress
```

`import` reads whichever of `results/terminal.jsonl`, `results/dense.jsonl` and `results/captions/<id>.json` exist, writes `grader/flora.json` in each trial folder, prints one line per trial and the agreement over all of them. It skips, with a warning, a result for another video than the job's: an outcome or dense result of another length, or captions of a video with another SHA-256.

Flora counts a task as solved when its outcome score is 5 (complete success). `--success-score 4` counts 4 too; the results stay in `results/`, so importing again with another threshold takes a moment. In `robouse report`, `flora_agree` is the share of trials where Flora and the simulator agree, and `flora_progress` the mean of Flora's progress estimate, its expected score rescaled from 1-5 to 0-100% (NVIDIA calls it a value for ranking, not a calibrated probability of success).

`grader/flora.json` has:

| Key | Contents |
|---|---|
| `instruction`, `video`, `simulator` | the instruction Flora was given, the recording (length, frame rate, SHA-256) and the simulator's verdict (`reward`, `success`, `outcome`, `progress`) |
| `outcome` | `score` (1-5), `probabilities` of each score, `expected_score`, `progress` (0-1), `rationale` (with `--with-rationale`), `success` (score at or above the threshold) and `agrees` (with the simulator) |
| `dense` | `segments`: each stretch's `start_s`, `end_s`, `label` (failure, suboptimal or normal), `rationale`, and `steps`, the agent's steps (`index` in the trajectory and the command) whose part of the recording overlaps it; `seconds` and `fraction` per label, `per_second`, `worst`; `clips`: each 16 s clip's own labels (`start_s`, `end_s`, its 32 half-second scores as `quality`, and its `stretches` that are not normal, with their reasons) |
| `captions` | `segments`: each action's `start_s`, `end_s`, `caption`, `status` and `steps`; the pipeline's `profile` and model revisions |

The steps come from the trial's `artifacts/recording_index.json`; steps that moved nothing have no part of the recording and appear in no stretch.

## What was tested

### Flora's models on an H100

NVIDIA's scripts ran unmodified, at the revisions above, on one H100 80 GB (NVIDIA driver 595.71) with Python 3.12 and each repository's pinned requirements; the Rewarder's (vLLM 0.24.0, Transformers 5.8.1, PyTorch 2.11.0 for CUDA 13) ran with `VLLM_USE_FLASHINFER_SAMPLER=0`, as the machine had no CUDA toolkit ([2. Run Flora on a GPU machine](#2-run-flora-on-a-gpu-machine)). The weights downloaded without a Hugging Face account, and the Rewarder's matched its repository's `SHA256SUMS`. The trials were 14 runs of claude-opus-5-5: the 11 Claude Code trials of the dry run below and 3 trials of the `aspire` harness (Claude Code in ASPIRE's workflow) on CaP-X tasks. The simulator solved 12 of them. `--instructions` gave the one-demo and CaP-X tasks their description without the clause about the agent ([1. Export the trials](#1-export-the-trials)).

Flora's outcome (`terminal_reward`, its default prompt, without a rationale) against the simulator's verdict:

| Task | Suite | Recording | Simulator | Flora | P(Flora's score) | Agree |
|---|---|---|---|---|---|---|
| `one-demo-box-mirrored` | one-demo | 4.7 s | solved | 5 | 1.00 | yes |
| `one-demo-bottle-mirrored` | one-demo | 5.1 s | solved | 5 | 0.95 | yes |
| `one-demo-drawer-left` | one-demo | 2.3 s | solved | 5 | 0.92 | yes |
| `g1-drawer-stow` | humanoid | 5.5 s | solved | 5 | 1.00 | yes |
| `shadow-turn-valve` | dexhand | 10.8 s | solved | 5 | 0.98 | yes |
| `stretch-fetch-cup` | mobile-manip | 30.0 s | solved | 5 | 0.96 | yes |
| `spot-arm-reset` | quadruped | 5.9 s | solved | 5 | 0.36 | yes |
| `kitchen-complete` | kitchen | 19.1 s | solved | 3 | 0.77 | no |
| `libero-pro-spatial-swap-1` | libero-pro | 2.8 s | solved | 4 | 0.89 | no |
| `capx-cube-lifting-s5` | capx (`aspire`) | 1.1 s | solved | 2 | 0.99 | no |
| `capx-cube-stack-s5` | capx (`aspire`) | 1.5 s | solved | 4 | 0.76 | no |
| `capx-nut-assembly-s5` | capx (`aspire`) | 2.7 s | solved | 3 | 0.55 | no |
| `libero-pro-10-task-6` | libero-pro | 15.3 s | not solved | 3 | 0.40 | yes |
| `libero-pro-10-swap-4` | libero-pro | 16.1 s | not solved | 3 | 0.83 | yes |

`robouse flora import` counted 9 agreements in 14 (Flora's "solved" is a 5): Flora gave a 5 to 7 of the 12 trials the simulator solved, and a 3 to both it did not. With `--success-score 4`, 11 in 14. `robouse report` gave `flora_agree` 82% (9 of 11) for the Claude Code trials and 0% for the three ASPIRE trials, whose recordings are the shortest (1.1 to 2.7 s: CaP-X tasks record one frame every 8 control steps) and come from a camera looking down at the table.

Asked for a one-line rationale (`--with-rationale`), Flora gave the same scores except kitchen-complete's (4 instead of 3), and its reasons for marking solved trials down were about what the video shows:

- `capx-cube-lifting-s5` (2): "The robot approached and grasped the red cube, but the cube remained at or near the table surface and was not clearly lifted." CaP-X's check is that the cube is more than 4 cm above the table; the camera looks down on it.
- `libero-pro-spatial-swap-1` (4): "... but the bowl remained held by the gripper rather than being released onto the plate." The task ends the episode the moment LIBERO's check first passes (`success_mode: first`), so the recording stops with the bowl on the plate and still in the gripper.
- `capx-cube-stack-s5` (4): "... the gripper remained in contact with the red cube at the end instead of releasing it."
- `capx-nut-assembly-s5` (3): "... but the nut was not placed onto the peg."
- `kitchen-complete` (4): "... but it did not turn on the light switch." The simulator counted all four goals done.

For the two trials the simulator did not solve, the rationales named what went wrong: "the yellow-and-white mug was not placed on the right plate and was knocked over instead" (`libero-pro-10-swap-4`) and "the chocolate pudding ended up to the left of the plate rather than to its right" (`libero-pro-10-task-6`).

The dense labels (`dense_reward`) called 7 of the 14 recordings normal throughout: the three one-demo trials, `g1-drawer-stow` and `spot-arm-reset`, and two that Flora's outcome marked down, `kitchen-complete` and `capx-nut-assembly-s5`. They flagged the last 0.7 to 1.1 s of the cube-lifting recording (a failure: "the robot did not pick up the red cube from the white surface"), of the cube-stacking one (suboptimal: "the green cube is tilted while placing the red cube on it") and of `libero-pro-spatial-swap-1` (a failure: "the black bowl is not placed on the white plate"); in the unsolved LIBERO-PRO trials, they marked failures where the mugs went wrong ("the yellow and white mug is misaligned with the right plate", "the grasp is unstable"). They also flagged stretches of trials the simulator and Flora's outcome both called solved: in `stretch-fetch-cup`, 7.9 to 13.9 s as a failure ("the robot failed to pick up the cup due to misalignment of the arm on the cup") while the robot was still reaching (it grasped the cup at 15.7 s), and its drive back as suboptimal ("the robot is jittering while moving toward the table with the blue cup"). On a recording of about 10 to 20 s, the script's two 16-second clips nearly coincide (the second one ends at the recording's end), and where they disagree, its stitching, which gives each frame the label of the nearest half-second kept from either clip, alternates between them every few frames: `shadow-turn-valve`'s first clip called its 10.8 s normal, its second called 9.2 s of it a failure, and the stitched labels came out as 57 stretches. `grader/flora.json` keeps each clip's own labels (`dense.clips`) beside the stitched ones.

With each task's own description as the instruction (the export's default) instead of `--instructions`, every score was the same; Flora's probability of its score fell on the one-demo trials, from 0.95, 1.00 and 0.92 to 0.49, 0.82 and 0.44, and moved by at most 0.03 on the CaP-X ones. Between runs of the same jobs, scores were identical and probabilities moved by at most 0.03 (vLLM batches the requests differently).

On the H100, the Rewarder's 55.6 GB downloaded in about 40 s. The first script's vLLM engine loaded the weights in 24 s and took 130 s more to start (49 s of it compiling); the later ones, with the weights still in memory and the compiled graph cached, took 8 s and 18 s. Each script took 4.4 minutes for the 14 recordings the first time and 1.7 to 2.4 minutes after that.

A second session scored 7 more Claude Code trials, of the `chemlab` suite (lab instruments), which the simulator all solved. Flora gave a 5 to 2 of them (`chemlab-drying-oven-door` and `chemlab-shaker-hood`, P 1.00 and 0.98) and a 2 to the other 5 (P 0.50 to 0.68); its dense labels called all 7 recordings normal. Asked for a rationale, it scored those 5 at 1 to 4, saying the final frames did not show the result ("the final state did not show the stirrer set to 500 rpm"; "the draft shield remained open in the final frames"; for the moisture analyzer's lid, "the gripper remained engaged with the lid at the end"). Over all 21 trials, Flora's outcome agreed with the simulator on 11 (13 with `--success-score 4`); the simulator solved 19, and Flora gave a 5 to 9 of those and to neither of the 2 it did not solve.

The same session scored four recordings of exact replays of scored episodes from a second camera at 1920x1080 (each replay sent the episode's recorded requests again and got the same responses and the same verdict): ASPIRE's `capx-nut-assembly-s5` from the side instead of from above, and three of the chemlab trials. The camera changed no outcome score: the nut assembly got a 3 again (P 0.58), the oven door and the shaker hood a 5 (P 1.00), the fume hood's sash a 2. With a rationale, though, the nut assembly got a 5 ("The final state shows the nut correctly positioned on the peg") and the sash a 5, where the plain prompt gave a 3 and a 2: over the 25 recordings, the two prompts gave different scores for 7. The nut assembly's dense labels, in both of its clips, called 3.1 to 7.6 s a failure ("the square nut was not aligned with the square peg so the square nut slipped from the square peg") and the rest normal.

The captioning pipeline (TempSeg, then the Captioner, profile `yam`) wrote 30 captions for the first session's 14 recordings, taking 81 to 244 s per recording (it loads both models again for each one) and 28 minutes in all; `robouse flora import` read them without a warning. They follow what the robot did in order (`libero-pro-10-swap-4`'s eight: pick up the gray mug, put it on the right-side coaster, pick up the yellow mug, ...), but misname some objects (Franka Kitchen's kettle as "the toaster", the Stretch's cup as "the blue ball", the nut as "the black-and-brown cube") and give every gripper a hand ("with the right hand"), the `yam` profile being for a two-armed robot.

### Without a GPU

- `tests/test_flora.py`, with `tests/flora_stand_in.py`: a stand-in for NVIDIA's scripts that writes made-up labels in their output formats, without looking at the videos. The job files are checked against what NVIDIA's scripts accept (keys, ids, relative paths); the import against the stand-in's results, results of another length or video, unknown ids and malformed lines; and `robouse report`'s two metrics.
- NVIDIA's scripts, at the revisions above, read the job files `robouse flora export` wrote for 11 Claude Code trials of seven suites (`libero-pro`, `one-demo`, `kitchen`, `mobile-manip`, `quadruped`, `humanoid` and `dexhand`; recordings of 2.3 to 30 s at 1280x720) and for the example above, on a Linux machine without a GPU: `terminal_reward --dry-run` read every recording (frame count, rate and size), planned its frames and built its prompt, `dense_reward --dry-run` planned the first one's clips, and `--validate-only` decoded every caption job's video and accepted it (constant 30 fps).

Other limits: Robo Use records one camera, the task's, though the Rewarder takes up to four synchronized views and the captioning pipeline one or three. The dense labels are retrospective (each 16-second clip sees 4 s past the moments it labels), for analysis after the trial, not a signal during it.
