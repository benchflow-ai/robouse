"""Flora annotations of finished trials.

NVIDIA's Flora (https://research.nvidia.com/labs/gear/flora/) is a suite of open video models that label robot
episodes. Flora-Rewarder says how an episode went: an outcome score from 1 (complete failure) to 5 (complete success),
and a failure, suboptimal or normal label for every half second, with a reason for each bad stretch. Flora-TempSeg and
Flora-Captioner cut the video into actions and describe each one. A Robo Use trial also has the simulator's verdict,
so Flora's can be checked against it.

Flora's weights and NVIDIA's inference scripts are under NVIDIA's non-commercial license and are not part of Robo Use.
They run unmodified on a GPU machine; this module writes their input files and reads their output files:

  robouse flora export RUNS... --out DIR   one job per trial with a recording: DIR/videos/<id>.mp4, DIR/reward_jobs.jsonl
                                           (the Rewarder scripts' --jobs format), DIR/caption_jobs.jsonl (the captioning
                                           pipeline's --input-jsonl format) and DIR/trials.json (the trial of each job)
  NVIDIA's scripts, on the GPU machine     write DIR/results/terminal.jsonl, DIR/results/dense.jsonl and
                                           DIR/results/captions/<id>.json
  robouse flora import DIR                 writes <trial>/grader/flora.json for every trial with results, with each
                                           labelled stretch's agent steps (artifacts/recording_index.json), and prints
                                           Flora's outcome against the simulator's verdict (in `robouse report`:
                                           flora_agree and flora_progress)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA = "robouse-flora/1"
JOBS_SCHEMA = "robouse-flora-jobs/1"
# The revisions of NVIDIA's repositories whose scripts (batch_utils/) were checked against these files; trials.json
# records them and the docs page downloads them
REWARDER = {"repo": "nvidia/Flora-Rewarder", "revision": "7de68d22c4a9decec5ddb7f86ddcaee8f82d3367"}
CAPTIONER = {"repo": "nvidia/Flora-Captioner", "revision": "f736ca36925ae55d2f7915993ed1bc9f87288bb3"}
PROFILES = ("human", "yam", "dex", "tianji")  # the captioning pipeline's profiles; yam is its robot-actions profile
CAPTION_MAX_S = 120.0  # the captioning pipeline refuses longer videos (the input length NVIDIA validated)
JOB_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")  # ids that both NVIDIA pipelines accept
DURATION_TOLERANCE_S = 0.1
REWARD_JOBS, CAPTION_JOBS, TRIALS, RESULTS = "reward_jobs.jsonl", "caption_jobs.jsonl", "trials.json", "results"
LABELS = {1: "failure", 2: "suboptimal", 3: "normal"}
DOCS = "https://robouse.ai/docs/flora/"


# ---- export --------------------------------------------------------------------------------------------------------


def trial_folders(paths: list[str] | list[Path]) -> list[Path]:
    """The trial folders in `paths`, each a trial folder (with config.json) or a run folder of them; each once."""
    out: dict[Path, Path] = {}
    for p in map(Path, paths):
        if (p / "config.json").is_file():
            found = [p]
        elif p.is_dir():
            found = [d for d in sorted(p.iterdir()) if (d / "config.json").is_file()]
        else:
            raise FileNotFoundError(f"no trial or run folder at {p}")
        for d in found:
            out.setdefault(d.resolve(), d)
    return list(out.values())


def recording(trial: Path) -> Path | None:
    for rel in ("artifacts/recording.mp4", "episode/recording.mp4"):
        if (trial / rel).is_file() and (trial / rel).stat().st_size > 0:
            return trial / rel
    return None


def video_facts(trial: Path, video: Path) -> dict:
    """fps, frames and duration of a trial's recording: from artifacts/recording_index.json, which every trial has, else
    read from the video with imageio when it is installed, else {} (unknown)."""
    try:
        d = json.loads((trial / "artifacts" / "recording_index.json").read_text())
        fps, n = float(d["fps"]), int(d["n_frames"])
        if fps > 0 and n > 0:
            return {"fps": fps, "frames": n, "duration_s": round(n / fps, 3)}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        import imageio.v2 as imageio

        r = imageio.get_reader(video)
        try:  # count_frames: the ffmpeg plugin's reader, which reads mp4
            fps, n = float(r.get_meta_data().get("fps") or 0), int(r.count_frames())  # type: ignore[attr-defined]
        finally:
            r.close()
        if fps > 0 and n > 0:
            return {"fps": fps, "frames": n, "duration_s": round(n / fps, 3)}
    except Exception:  # noqa: BLE001  (no imageio, or a video it cannot read: the length stays unknown)
        pass
    return {}


def _one_line(text: object) -> str:
    return " ".join(str(text).split())


def _load_task(cfg: dict) -> Any:
    """The trial's task: its folder (`task_path`), else the bundled task with its id; None when neither is here."""
    from ..tasks import load_task, resolve_task_path

    path = cfg.get("task_path")
    if path and Path(path, "task.md").is_file():
        try:
            return load_task(path)
        except (OSError, ValueError):
            pass
    if cfg.get("task"):
        try:
            return load_task(resolve_task_path(str(cfg["task"])))
        except (SystemExit, OSError, ValueError):  # not a bundled task id (resolve_task_path exits)
            pass
    return None


def task_instruction(cfg: dict) -> tuple[str, str]:
    """(instruction, its source) for Flora's prompts: the source benchmark's language instruction
    (`metadata.language_instruction`), else the task's one-line description, else its title, else its id."""
    md = cfg.get("metadata") or {}
    if _one_line(md.get("language_instruction") or ""):
        return _one_line(md["language_instruction"]), "language_instruction"
    task = _load_task(cfg)
    if task is not None:
        desc = _one_line((task.meta.get("task") or {}).get("description") or "")
        if desc:
            return desc, "description"
        m = re.search(r"^# (.+)$", task.body, re.M)
        if m:
            return _one_line(m.group(1)), "title"
    return str(cfg.get("task") or "the task").replace("-", " "), "task id"


def simulator_verdict(result: dict) -> dict:
    reward = float(((result.get("verifier_result") or {}).get("rewards") or {}).get("reward") or 0)
    ep = result.get("episode") or {}
    out: dict[str, Any] = {"reward": reward, "success": reward >= 1, "outcome": ep.get("outcome")}
    progress = (ep.get("metrics") or {}).get("progress")
    if isinstance(progress, int | float):
        out["progress"] = float(progress)
    return out


def job_id(name: str, taken: set[str]) -> str:
    """A job id for trial `name` that NVIDIA's scripts accept (JOB_ID) and that is not in `taken` (which it joins)."""
    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-_.") or "trial"
    if len(base) > 90:
        base = base[:81] + "-" + hashlib.sha256(name.encode()).hexdigest()[:8]
    cand, n = base, 2
    while cand in taken:
        cand, n = f"{base}-{n}", n + 1
    taken.add(cand)
    return cand


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:  # another file system, or no hard links
        shutil.copyfile(src, dst)


def read_instructions(path: str | Path) -> dict[str, str]:
    """An --instructions file: a JSON object from task ids to the instruction Flora is given for that task."""
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"--instructions {path}: not a readable JSON file ({e})") from None
    if not isinstance(d, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and _one_line(v) for k, v in d.items()
    ):
        raise ValueError(f"--instructions {path}: expected a JSON object of task ids to non-empty instructions")
    return {k: _one_line(v) for k, v in d.items()}


def export(
    trials: list[Path],
    out: Path,
    *,
    profile: str = "yam",
    instruction: str | None = None,
    instructions: dict[str, str] | None = None,
) -> dict:
    """Write Flora's job files for `trials` into `out` (which must not hold jobs yet). `instruction` replaces every
    task's instruction, `instructions` (task id: instruction) those of the tasks it names. Returns {"jobs",
    "caption_jobs", "long", "skipped": [(trial, reason)], "unused": [task ids in `instructions` no trial has]}; with no
    job, nothing is written."""
    if profile not in PROFILES:
        raise ValueError(f"caption profile must be one of {', '.join(PROFILES)}")
    instructions = instructions or {}
    used: set[str] = set()
    if (out / TRIALS).exists():
        raise FileExistsError(f"{out} already holds Flora jobs ({TRIALS}); export into a new folder")
    taken: set[str] = set()
    jobs: dict[str, dict] = {}
    rewards: list[dict] = []
    captions: list[dict] = []
    skipped: list[tuple[Path, str]] = []
    long: list[str] = []
    for trial in trials:
        try:
            cfg = json.loads((trial / "config.json").read_text())
            result = json.loads((trial / "result.json").read_text())
        except (OSError, ValueError):
            skipped.append((trial, "no result yet"))
            continue
        if result.get("exception_info"):
            skipped.append((trial, "failed on infrastructure, so it has no verdict"))
            continue
        video = recording(trial)
        if video is None:
            skipped.append((trial, "no recording (no simulator step ran)"))
            continue
        jid = job_id(trial.name, taken)
        rel = f"videos/{jid}.mp4"
        (out / "videos").mkdir(parents=True, exist_ok=True)
        _link_or_copy(video, out / rel)
        facts = video_facts(trial, video)
        if instruction:
            text, source = _one_line(instruction), "--instruction"
        elif str(cfg.get("task")) in instructions:
            text, source = instructions[str(cfg["task"])], "--instructions"
            used.add(str(cfg["task"]))
        else:
            text, source = task_instruction(cfg)
        rewards.append({"id": jid, "task": text, "videos": [rel]})
        captioned = float(facts.get("duration_s", 0)) <= CAPTION_MAX_S
        if captioned:
            captions.append({"id": jid, "video": rel, "profile": profile})
        else:
            long.append(jid)
        jobs[jid] = {
            "trial": str(trial.resolve()),
            "task": cfg.get("task"),
            "instruction": text,
            "instruction_from": source,
            "video": {"recording": str(video.relative_to(trial)), "path": rel, "sha256": _sha256(out / rel), **facts},
            "simulator": simulator_verdict(result),
            "caption_job": captioned,
        }
    if jobs:
        _write_jsonl(out / REWARD_JOBS, rewards)
        if captions:
            _write_jsonl(out / CAPTION_JOBS, captions)
        manifest = {
            "schema": JOBS_SCHEMA,
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "caption_profile": profile,
            "rewarder": REWARDER,
            "captioner": CAPTIONER,
            "jobs": jobs,
        }
        (out / TRIALS).write_text(json.dumps(manifest, indent=2) + "\n")
    unused = sorted(set(instructions) - used)
    return {"jobs": len(jobs), "caption_jobs": len(captions), "long": long, "skipped": skipped, "unused": unused}


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


# ---- import --------------------------------------------------------------------------------------------------------


def _read_jsonl(p: Path, warnings: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not p.is_file():
        return out
    for n, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            out[str(r["id"])] = r
        except (ValueError, KeyError, TypeError):
            warnings.append(f"{p.name}:{n}: not a result line, skipped")
    return out


def _video_steps(trial: Path) -> list[dict]:
    """The agent's steps with a span of video time (artifacts/recording_index.json); steps that moved nothing have
    none and are left out."""
    try:
        d = json.loads((trial / "artifacts" / "recording_index.json").read_text())
    except (OSError, ValueError):
        return []
    out = []
    for s in d.get("steps") or []:
        t0, t1 = s.get("t_video_start_s"), s.get("t_video_end_s")
        if isinstance(t0, int | float) and isinstance(t1, int | float) and t1 > t0:
            out.append({"index": s.get("index"), "action": str(s.get("action") or "")[:200], "t0": t0, "t1": t1})
    return out


def _steps_in(steps: list[dict], start: float, end: float) -> list[dict]:
    return [{"index": s["index"], "action": s["action"]} for s in steps if s["t0"] < end and s["t1"] > start]


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _same_length(r: dict, video: dict) -> bool:
    known, said = _num(video.get("duration_s")), _num(r.get("duration_s"))
    return known is None or said is None or abs(known - said) <= DURATION_TOLERANCE_S


def outcome(r: dict, simulator: dict, success_score: int = 5) -> dict:
    """Flora-Rewarder's outcome record (terminal_reward.py) for one trial, and whether it agrees with the simulator:
    Flora calls the task solved at `success_score` or above (5, complete success, by default)."""
    score = int(r["score"])
    if not 1 <= score <= 5:
        raise ValueError(f"outcome score {score} is not 1-5")
    expected = _num(r.get("expected_score"))
    progress = _num(r.get("progress"))
    if progress is None and expected is not None:
        progress = round((expected - 1) / 4, 4)
    success = score >= success_score
    return {
        "score": score,
        "expected_score": expected,
        "progress": progress,
        "probabilities": {str(k): float(v) for k, v in (r.get("probabilities") or {}).items()},
        "rationale": r.get("rationale"),
        "sampled_frames": r.get("sampled_frames"),
        "success_score": success_score,
        "success": success,
        "agrees": success == bool(simulator.get("success")),
    }


def _clip(c: dict) -> dict:
    """One 16 s clip as dense_reward.py scored it: its span, its 32 half-second scores (`quality`) and the stretches
    in it that are not normal, with the clip's own reasons."""
    return {
        "start_s": _num(c.get("start_s")),
        "end_s": _num(c.get("end_s")),
        "quality": c.get("quality"),
        "valid": c.get("valid"),
        "stretches": [
            {
                "start_s": _num(g.get("start_s")),
                "end_s": _num(g.get("end_s")),
                "label": g.get("label"),
                "rationale": g.get("rationale"),
            }
            for g in c.get("regions") or []
            if g.get("label") and g.get("label") != "normal"
        ],
    }


def dense(r: dict, steps: list[dict]) -> dict:
    """Flora-Rewarder's dense record (dense_reward.py): its labelled stretches, each with the agent's steps in it, and
    each clip's own labels (where two clips overlap and disagree, the stitched stretches alternate between them)."""
    segments = []
    for s in r.get("segments") or []:
        start, end, score = float(s["start_s"]), float(s["end_s"]), int(s["score"])
        segments.append(
            {
                "start_s": start,
                "end_s": end,
                "score": score,
                "label": s.get("label") or LABELS.get(score),
                "rationale": s.get("rationale"),
                "steps": _steps_in(steps, start, end),
            }
        )
    seconds = {
        label: round(sum(s["end_s"] - s["start_s"] for s in segments if s["label"] == label), 3)
        for label in LABELS.values()
    }
    worst = r.get("worst_score")
    return {
        "worst": LABELS.get(worst) if isinstance(worst, int) else None,
        "mean_score": _num(r.get("mean_score")),
        "seconds": seconds,
        "fraction": r.get("fraction"),
        "per_second": r.get("per_second"),
        "clips": [_clip(c) for c in r.get("clips") or [] if isinstance(c, dict)],
        "invalid_clips": int(r.get("invalid_clips") or 0),
        "segments": segments,
    }


def captions(r: dict, steps: list[dict]) -> dict:
    """The captioning pipeline's result (infer.py): one instruction per action, each with the agent's steps in it."""
    segments = []
    for s in r.get("segments") or []:
        start, end = float(s["start_s"]), float(s["end_s"])
        segments.append(
            {
                "start_s": start,
                "end_s": end,
                "caption": s.get("caption") or "",
                "status": s.get("status"),
                "steps": _steps_in(steps, start, end),
            }
        )
    return {"profile": r.get("profile"), "model_revisions": r.get("model_revisions"), "segments": segments}


def import_results(folder: Path, *, success_score: int = 5) -> tuple[list[tuple[Path, dict]], list[str]]:
    """Read NVIDIA's results in `folder`/results and write each trial's grader/flora.json. Returns ((trial folder,
    record) for each record written, warnings). Results for another video than the job's (another length, or another
    hash where the result names one) are left out with a warning."""
    try:
        manifest = json.loads((folder / TRIALS).read_text())
    except OSError:
        raise FileNotFoundError(f"{folder} has no {TRIALS}: export the trials with `robouse flora export`") from None
    jobs: dict[str, dict] = manifest.get("jobs") or {}
    res = folder / RESULTS
    warnings: list[str] = []
    terminal = _read_jsonl(res / "terminal.jsonl", warnings)
    dense_rows = _read_jsonl(res / "dense.jsonl", warnings)
    caption_rows: dict[str, dict] = {}
    for p in sorted((res / "captions").glob("*.json")):
        try:
            caption_rows[p.stem] = json.loads(p.read_text())
        except ValueError:
            warnings.append(f"captions/{p.name}: not JSON, skipped")
    if not (terminal or dense_rows or caption_rows):
        raise FileNotFoundError(
            f"no Flora results in {res}: expected terminal.jsonl, dense.jsonl or captions/<id>.json ({DOCS})"
        )
    for jid in sorted((set(terminal) | set(dense_rows) | set(caption_rows)) - set(jobs)):
        warnings.append(f"{jid}: a result for no job in {TRIALS}, skipped")
    written = []
    for jid, job in jobs.items():
        trial, video = Path(job["trial"]), job.get("video") or {}
        steps = _video_steps(trial)
        rec: dict[str, Any] = {
            "schema": SCHEMA,
            "job": jid,
            "task": job.get("task"),
            "instruction": job.get("instruction"),
            "video": video,
            "simulator": job.get("simulator") or {},
        }
        try:
            if jid in terminal:
                if _same_length(terminal[jid], video):
                    rec["outcome"] = outcome(terminal[jid], rec["simulator"], success_score)
                else:
                    warnings.append(f"{jid}: terminal.jsonl scored a video of another length, skipped")
            if jid in dense_rows:
                if _same_length(dense_rows[jid], video):
                    rec["dense"] = dense(dense_rows[jid], steps)
                else:
                    warnings.append(f"{jid}: dense.jsonl scored a video of another length, skipped")
            if jid in caption_rows:
                said = (caption_rows[jid].get("input_sha256") or {}).get("main")
                if (said is None or said == video.get("sha256")) and _same_length(caption_rows[jid], video):
                    rec["captions"] = captions(caption_rows[jid], steps)
                else:
                    warnings.append(f"{jid}: captions/{jid}.json captioned another video, skipped")
        except (ValueError, KeyError, TypeError) as e:
            warnings.append(f"{jid}: unreadable result ({type(e).__name__}: {e}), skipped")
            continue
        if not {"outcome", "dense", "captions"} & set(rec):
            continue
        if not trial.is_dir():
            warnings.append(f"{jid}: trial folder {trial} is gone, skipped")
            continue
        rec["imported_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (trial / "grader").mkdir(exist_ok=True)
        (trial / "grader" / "flora.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
        written.append((trial, rec))
    return written, warnings


# ---- command line ----------------------------------------------------------------------------------------------------


def export_main(
    paths: list[str], out: str, profile: str, instruction: str | None, instructions: str | None = None
) -> int:
    try:
        per_task = read_instructions(instructions) if instructions else None
        trials = trial_folders(paths)
        rep = export(trials, Path(out), profile=profile, instruction=instruction, instructions=per_task)
    except (FileNotFoundError, FileExistsError, ValueError) as e:
        print(f"robouse: {e}", file=sys.stderr)
        return 2
    for trial, reason in rep["skipped"]:
        print(f"skipped {trial}: {reason}")
    if rep["unused"]:
        print(f"--instructions: no exported trial has task {', '.join(rep['unused'])}")
    if not rep["jobs"]:
        print("robouse: no trial with a recording and a verdict; nothing written", file=sys.stderr)
        return 1
    print(f"wrote {_n(rep['jobs'], 'reward job')} and {_n(rep['caption_jobs'], 'caption job')} to {out}")
    if rep["long"]:
        print(f"no caption job for recordings longer than {CAPTION_MAX_S:g} s: {', '.join(rep['long'])}")
    print(
        f"next, with JOBS set to this folder on a Linux machine with an 80 GB NVIDIA GPU ({DOCS}):\n"
        f"  in a copy of {REWARDER['repo']}:\n"
        "    python -m batch_utils.terminal_reward --jobs $JOBS/reward_jobs.jsonl --output $JOBS/results/terminal.jsonl\n"
        "    python -m batch_utils.dense_reward --jobs $JOBS/reward_jobs.jsonl --output $JOBS/results/dense.jsonl\n"
        f"  in a copy of {CAPTIONER['repo']}:\n"
        "    python infer.py --input-jsonl $JOBS/caption_jobs.jsonl --output-dir $JOBS/results/captions\n"
        f"then, here: robouse flora import {out}"
    )
    return 0


def _n(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _seconds(rec: dict) -> str:
    d = rec["dense"]["seconds"]
    return f"failure {d['failure']:.1f} s, suboptimal {d['suboptimal']:.1f} s"


def import_main(folder: str, success_score: int) -> int:
    try:
        written, warnings = import_results(Path(folder), success_score=success_score)
    except (FileNotFoundError, ValueError) as e:
        print(f"robouse: {e}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    solved = lambda ok: "solved" if ok else "not solved"
    for trial, rec in written:
        parts = []
        if "outcome" in rec:
            o = rec["outcome"]
            parts.append(
                f"outcome {o['score']}/5 (Flora: {solved(o['success'])}, simulator: "
                f"{solved(rec['simulator'].get('success'))}, {'agree' if o['agrees'] else 'DISAGREE'})"
            )
        if "dense" in rec:
            parts.append(_seconds(rec))
        if "captions" in rec:
            parts.append(_n(len(rec["captions"]["segments"]), "caption"))
        print(f"{trial.name}: " + "; ".join(parts))
    scored = [rec for _, rec in written if "outcome" in rec]
    if scored:
        agree = sum(r["outcome"]["agrees"] for r in scored)
        flora = sum(r["outcome"]["success"] for r in scored)
        sim = sum(bool(r["simulator"].get("success")) for r in scored)
        both = sum(r["outcome"]["success"] and bool(r["simulator"].get("success")) for r in scored)
        rule = "score 5" if success_score == 5 else f"scores {success_score} to 5"
        print(
            f"Flora's outcome agrees with the simulator on {agree} of {len(scored)} trials (Flora's solved: {rule}): "
            f"Flora solved {flora}, the simulator {sim}, both {both}"
        )
    print(f"wrote grader/flora.json in {_n(len(written), 'trial folder')}")
    return 0 if written else 1
