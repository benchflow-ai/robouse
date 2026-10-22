"""A stand-in for NVIDIA's Flora inference scripts, for the `robouse flora` tests and for checking the plumbing without a
GPU. Standard library only. It is not Flora and looks at no picture: it reads the files `robouse flora export` wrote and
writes made-up labels, derived from each job's id, in the record formats of NVIDIA's scripts (Flora-Rewarder's
batch_utils/terminal_reward.py and dense_reward.py, the captioning pipeline's infer.py). A run through it checks the
files and the import, and says nothing about Flora.

    python tests/flora_stand_in.py JOBS     # writes JOBS/results/terminal.jsonl, dense.jsonl and captions/<id>.json

The real scripts decode each video; the stand-in takes its length from JOBS/trials.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

LABELS = {1: "failure", 2: "suboptimal", 3: "normal"}
CANONICAL = {"human": "Human", "yam": "YAM", "dex": "Dex", "tianji": "Tianji"}


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()] if p.is_file() else []


def _h(jid: str) -> int:
    return int(hashlib.sha256(jid.encode()).hexdigest()[:8], 16)


def terminal(job: dict, video: dict) -> dict:
    """A terminal_reward.py record: score 1 + (hash of the id) mod 5, with 0.7 of the probability on it."""
    score = 1 + _h(job["id"]) % 5
    probabilities = {str(k): 0.7 if k == score else 0.075 for k in range(1, 6)}
    expected = sum(k * probabilities[str(k)] for k in range(1, 6))
    return {
        "id": job["id"],
        "task": job["task"],
        "score": score,
        "expected_score": round(expected, 4),
        "progress": round((expected - 1) / 4, 4),
        "probabilities": probabilities,
        "rationale": None,
        "duration_s": video["duration_s"],
        "sampled_frames": min(64, max(2, int(video["duration_s"] * 10) // 2 * 2)),
        "output": f"Score: {score}",
    }


def frame_scores(jid: str, n: int) -> list[int]:
    """Normal, except a suboptimal stretch over 25-40% of the video and, for scores 1 and 2, a failure over 60-75%."""
    scores = [3] * n
    for i in range(int(n * 0.25), int(n * 0.40)):
        scores[i] = 2
    if 1 + _h(jid) % 5 <= 2:
        for i in range(int(n * 0.60), int(n * 0.75)):
            scores[i] = 1
    return scores


def dense(job: dict, video: dict) -> dict:
    """A dense_reward.py record: runs of equal frame scores as segments, with rationales for the bad ones."""
    fps, n = float(video["fps"]), int(video["frames"])
    scores = frame_scores(job["id"], n)
    segments, start = [], 0
    for i in range(1, n + 1):
        if i == n or scores[i] != scores[start]:
            s = scores[start]
            segments.append(
                {
                    "start_frame": start,
                    "end_frame": i,
                    "start_s": round(start / fps, 3),
                    "end_s": round(i / fps, 3),
                    "score": s,
                    "label": LABELS[s],
                    "rationale": None if s == 3 else f"stand-in {LABELS[s]} stretch",
                }
            )
            start = i
    seconds = int(-(-n // fps))
    # one clip over the whole video; its regions (window_regions in NVIDIA's core.py) are the segments
    regions = [
        {
            "first_group": k + 1,
            "last_group": k + 1,
            "score": s["score"],
            "label": s["label"],
            "start_s": s["start_s"],
            "end_s": s["end_s"],
            "rationale": s["rationale"],
        }
        for k, s in enumerate(segments)
    ]
    quality = "".join(str(scores[min(n - 1, n * g // 32)]) for g in range(32))
    return {
        "id": job["id"],
        "task": job["task"],
        "fps": fps,
        "num_frames": n,
        "duration_s": round(n / fps, 3),
        "worst_score": min(scores),
        "mean_score": round(sum(scores) / n, 4),
        "fraction": {LABELS[s]: round(scores.count(s) / n, 4) for s in (1, 2, 3)},
        "segments": segments,
        "per_second": [scores[min(n - 1, int((t + 0.5) * fps))] for t in range(seconds)],
        "clips": [{"start_s": 0.0, "end_s": round(n / fps, 3), "quality": quality, "regions": regions, "valid": True}],
        "invalid_clips": 0,
    }


def captions(job: dict, video: dict, sha256: str) -> dict:
    """An infer.py result: one caption per 4 s of video (at least two)."""
    duration = float(video["duration_s"])
    k = max(2, int(duration // 4))
    cuts = [round(duration * i / k, 3) for i in range(k + 1)]
    return {
        "schema_version": "flora_demo_annotation_v1",
        "duration_s": duration,
        "segments": [
            {
                "start_s": cuts[i],
                "end_s": cuts[i + 1],
                "caption": f"Stand-in caption {i + 1}.",
                "status": "complete",
                "segmentation_provenance": "fine",
            }
            for i in range(k)
        ],
        "elapsed_s": 0.0,
        "source_clock": "seconds relative to the first native source presentation timestamp",
        "camera_roles": ["main"],
        "profile": CANONICAL[job.get("profile", "human")],
        "model_revisions": {"stand-in": "not Flora"},
        "input_sha256": {"main": sha256},
    }


def run(jobs_dir: Path, only: tuple[str, ...] = ("terminal", "dense", "captions")) -> None:
    manifest = json.loads((jobs_dir / "trials.json").read_text())["jobs"]
    out = jobs_dir / "results"
    out.mkdir(parents=True, exist_ok=True)
    reward_jobs = _jsonl(jobs_dir / "reward_jobs.jsonl")
    if "terminal" in only:
        lines = [terminal(j, manifest[j["id"]]["video"]) for j in reward_jobs]
        (out / "terminal.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines))
    if "dense" in only:
        lines = [dense(j, manifest[j["id"]]["video"]) for j in reward_jobs]
        (out / "dense.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines))
    if "captions" in only:
        (out / "captions").mkdir(exist_ok=True)
        for j in _jsonl(jobs_dir / "caption_jobs.jsonl"):
            sha = hashlib.sha256((jobs_dir / j["video"]).read_bytes()).hexdigest()
            r = captions(j, manifest[j["id"]]["video"], sha)
            (out / "captions" / f"{j['id']}.json").write_text(json.dumps(r, indent=2) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("jobs", type=Path, help="the folder `robouse flora export` wrote")
    a = ap.parse_args()
    run(a.jobs)
    print(f"wrote stand-in results to {a.jobs / 'results'}")
