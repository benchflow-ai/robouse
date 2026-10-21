# Annotate trials with Flora

[Flora](https://research.nvidia.com/labs/gear/flora/) is NVIDIA GEAR's suite of open video models for robotics data engines ("Flora: An Open Model Suite for Scaling Robotics Data Engines", Leng, Man, Li et al., 2026; the models are on [Hugging Face](https://huggingface.co/collections/nvidia/flora)). NVIDIA uses it to label the episodes GR00T models are trained on. Given a robot episode's video and its task instruction, its three models say how the episode went and what the robot did:

| Model | What it says about a recording | Size |
|---|---|---|
| [Flora-Rewarder](https://huggingface.co/nvidia/Flora-Rewarder) | Outcome: a score from 1 (complete failure) to 5 (complete success), with the probability of each score. Dense: for every 0.5 s, failure, suboptimal or normal, with a short reason for each stretch that is not normal. (A third prompt grades a rubric; Robo Use does not use it.) | 27.8B parameters, fine-tuned from Qwen3.5-27B; 55.6 GB of BF16 weights |
| [Flora-TempSeg](https://huggingface.co/nvidia/Flora-TempSeg) | The start and end of each action | a LoRA adapter on Qwen3.5-9B (19.3 GB) |
| [Flora-Captioner](https://huggingface.co/nvidia/Flora-Captioner) | One imperative instruction for each action TempSeg found: the intended action, its objects, and which hand or gripper does what | 27.4B parameters, fine-tuned from Qwen3.5-27B; 109 GB of FP32 weights |

A Robo Use trial also has the simulator's verdict, so Flora's can be checked against it. `robouse flora export` writes the input files of NVIDIA's inference scripts for a run's trials; the scripts run, unmodified, on a GPU machine; `robouse flora import` reads their results into the trial folders, with the agent's steps during each labelled stretch, and prints how often Flora's outcome agrees with the simulator. `robouse report` then has the agreement and Flora's progress estimate as metrics.

Flora's models have not run on a Robo Use trial yet (see [What was tested](#what-was-tested)), so nothing on this page says how well they judge simulated robots.

## Licence

Flora's weights, and the inference scripts in its Hugging Face repositories, are under the [NVIDIA License](https://developer.download.nvidia.com/licenses/NVIDIA-OneWay-Noncommercial-License-22Mar2022.pdf) (the model cards call it the NVIDIA OneWay Noncommercial License, 22 March 2022): they may be used only for research or evaluation, not commercially. NVIDIA's model cards add that Flora is not intended or supported for commercial or production use, and that its outputs are annotations, not meant to control a robot or to be a system's only safety monitor. The base models, Qwen3.5-27B and Qwen3.5-9B, are Apache 2.0.

Robo Use does not include or download any of it. `robouse flora` (Apache 2.0, like the rest of Robo Use) writes the scripts' input files and reads their output files; you download the models and scripts from Hugging Face on your own GPU machine and accept their licence there. The weights are public: no Hugging Face account is needed.

## What you need

- Robo Use: the base install; `robouse flora` needs no extra.
- Flora: a Linux machine with Python 3.12 and an NVIDIA GPU with 80 GB of memory, the configuration NVIDIA validated its scripts on (H100 80 GB). The Rewarder's outcome and dense scripts need one such GPU (vLLM 0.24.0, Transformers 5.8.1). The captioning pipeline runs TempSeg, then the Captioner, on one such GPU (PyTorch 2.11, Transformers 5.8.1), and NVIDIA recommends at least 150 GB of disk for the weights it downloads.

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

Flora's prompts take the task's instruction: the source benchmark's language instruction where the task has one (the LIBERO suites), else the task's one-line description, else its title. Some descriptions are not instructions (the rule-inference tasks' "Rule inference: falling", for example); `--instruction TEXT` gives every exported trial the same instruction instead. The captioning pipeline gets no instruction, its default. Its profile is `yam`, the pipeline's robot-actions profile; `--caption-profile dex` selects its dexterous-hand profile, and `human` its profile for videos of people.

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

`--with-rationale` makes `terminal_reward` give a one-line reason before each score. The captioning pipeline downloads its two models and the Qwen3.5-9B base itself, at the revisions it pins, so its repository needs only its code; give it a separate virtual environment, since its pins differ from the Rewarder's:

```sh
hf download nvidia/Flora-Captioner --revision f736ca36925ae55d2f7915993ed1bc9f87288bb3 --exclude '*.safetensors' --local-dir flora-captioner
cd flora-captioner
pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128
pip install -r batch_utils/requirements.txt
python infer.py --input-jsonl $JOBS/caption_jobs.jsonl --output-dir $JOBS/results/captions
```

These are the commands of NVIDIA's READMEs in the two repositories (`batch_utils/README.md`), which describe the options and outputs; Robo Use has not run them with the models yet ([What was tested](#what-was-tested)). Before you pay for a GPU, the same scripts check the job files on any Linux machine, without the weights: the Rewarder's `--dry-run` reads the videos and prints the first prompt (a copy of the repository without `*.safetensors` is enough, with Transformers 5.8.1 and CPU builds of PyTorch and torchvision), and the captioning pipeline's `--validate-only` checks every video. For the export above:

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
| `dense` | `segments`: each stretch's `start_s`, `end_s`, `label` (failure, suboptimal or normal), `rationale`, and `steps`, the agent's steps (`index` in the trajectory and the command) whose part of the recording overlaps it; `seconds` and `fraction` per label, `per_second`, `worst` |
| `captions` | `segments`: each action's `start_s`, `end_s`, `caption`, `status` and `steps`; the pipeline's `profile` and model revisions |

The steps come from the trial's `artifacts/recording_index.json`; steps that moved nothing have no part of the recording and appear in no stretch.

## What was tested

- `tests/test_flora.py`, with `tests/flora_stand_in.py`: a stand-in for NVIDIA's scripts that writes made-up labels in their output formats, without looking at the videos. The job files are checked against what NVIDIA's scripts accept (keys, ids, relative paths); the import against the stand-in's results, results of another length or video, unknown ids and malformed lines; and `robouse report`'s two metrics.
- NVIDIA's scripts, at the revisions above, read the job files `robouse flora export` wrote for 11 Claude Code trials of seven suites (`libero-pro`, `one-demo`, `kitchen`, `mobile-manip`, `quadruped`, `humanoid` and `dexhand`; recordings of 2.3 to 30 s at 1280x720) and for the example above, on a Linux machine without a GPU: `terminal_reward --dry-run` read every recording (frame count, rate and size), planned its frames and built its prompt, `dense_reward --dry-run` planned the first one's clips, and `--validate-only` decoded every caption job's video and accepted it (constant 30 fps). `robouse flora import` and `robouse report` then ran on the stand-in's results for those 11 trials.
- Not run: Flora's models. No GPU with 80 GB was available, so Robo Use has no Flora score, label or caption of a trial yet, and no measured agreement. Flora was trained on robot camera video and human egocentric video; Robo Use's recordings are simulator renders from the task's camera, often of robots and scenes unlike those, and how well Flora judges them is what the agreement would measure.

Other limits: Robo Use records one camera, the task's, though the Rewarder takes up to four synchronized views and the captioning pipeline one or three. The dense labels are retrospective (each 16-second clip sees 4 s past the moments it labels), for analysis after the trial, not a signal during it.
