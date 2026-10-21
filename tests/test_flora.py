"""`robouse flora`: the input files of NVIDIA's Flora scripts, and the import of their results into trial folders. No
model runs here: tests/flora_stand_in.py writes results in the record formats of NVIDIA's scripts."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import flora_stand_in as stand_in
import pytest

from robouse.analysis import flora as F
from robouse.analysis.report import build
from robouse.cli import main

ROOT = Path(__file__).resolve().parents[1]
# What NVIDIA's scripts accept (Flora-Rewarder's batch_utils/engine.py read_jobs, the captioning pipeline's cli.py jobs)
REWARD_KEYS = {"id", "task", "videos"}
REWARD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
CAPTION_KEYS = {"id", "video", "profile", "left_wrist", "right_wrist", "yam32", "instruction"}
CAPTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")

STEPS = [
    {"index": 1, "action": "task", "t_video_start_s": 0.0, "t_video_end_s": 0.0},
    {"index": 2, "action": "robo observe", "t_video_start_s": 0.0, "t_video_end_s": 0.0},
    {"index": 3, "action": "robo move-to 0.1 0.2 0.3", "t_video_start_s": 0.0, "t_video_end_s": 1.5},
    {"index": 4, "action": "robo grip 1", "t_video_start_s": 1.5, "t_video_end_s": 2.0},
    {"index": 5, "action": "robo move-to 0.1 0.2 0.5", "t_video_start_s": 2.0, "t_video_end_s": 3.0},
    {"index": 6, "action": "robo done", "t_video_start_s": 3.0, "t_video_end_s": 3.0},
]


def trial(
    run: Path,
    name: str,
    *,
    reward: float = 1.0,
    frames: int = 90,
    task: str = "arc-gravity",
    metadata: dict | None = None,
    task_path: str = "",
    video: bool = True,
    exception: bool = False,
) -> Path:
    d = run / name
    (d / "artifacts").mkdir(parents=True)
    cfg = {"task": task, "task_path": task_path, "harness": "claude-code", "metadata": metadata or {"suite": "s"}}
    (d / "config.json").write_text(json.dumps(cfg))
    result: dict = {
        "verifier_result": {"rewards": {"reward": reward}},
        "episode": {"outcome": "done", "metrics": {"progress": reward}},
    }
    if exception:
        result["exception_info"] = {"exception_type": "HarnessError"}
    (d / "result.json").write_text(json.dumps(result))
    if video:
        (d / "artifacts" / "recording.mp4").write_bytes(b"not really an mp4: " + name.encode())
    index = {"fps": 30, "n_frames": frames, "duration_s": round(frames / 30, 3), "steps": STEPS}
    (d / "artifacts" / "recording_index.json").write_text(json.dumps(index))
    return d


def jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.read_text().splitlines()]


@pytest.fixture
def run(tmp_path: Path) -> Path:
    r = tmp_path / "runs" / "r1"
    trial(r, "arc-gravity__claude-code__aaaaaa", reward=1.0)
    trial(r, "arc-gravity__claude-code__bbbbbb", reward=0.0)
    trial(r, "arc-gravity__claude-code__cccccc", exception=True)
    trial(r, "arc-gravity__claude-code__dddddd", video=False)
    trial(r, "arc-gravity__claude-code__eeeeee", reward=0.0, frames=30 * 130)  # 130 s: too long to caption
    return r


def test_export_writes_the_formats_nvidia_reads(run: Path, tmp_path: Path) -> None:
    out = tmp_path / "jobs"
    rep = F.export(F.trial_folders([run, run / "arc-gravity__claude-code__aaaaaa"]), out)  # each trial once
    assert rep["jobs"] == 3 and rep["caption_jobs"] == 2 and rep["long"] == ["arc-gravity__claude-code__eeeeee"]
    assert {p.name.split("__")[-1]: why for p, why in rep["skipped"]} == {
        "cccccc": "failed on infrastructure, so it has no verdict",
        "dddddd": "no recording (no simulator step ran)",
    }
    manifest = json.loads((out / "trials.json").read_text())
    rewards = jsonl(out / "reward_jobs.jsonl")
    assert len(rewards) == 3
    for r in rewards:
        assert set(r) == REWARD_KEYS and REWARD_ID.fullmatch(r["id"]) and len(r["videos"]) == 1
        copy = out / r["videos"][0]
        job = manifest["jobs"][r["id"]]
        assert (
            not Path(r["videos"][0]).is_absolute()
            and copy.read_bytes() == (Path(job["trial"]) / job["video"]["recording"]).read_bytes()
        )
        assert job["video"]["sha256"] == hashlib.sha256(copy.read_bytes()).hexdigest()
        assert r["task"] == "Rule inference: falling" and job["instruction_from"] == "description"  # the bundled task
    caps = jsonl(out / "caption_jobs.jsonl")
    assert [c["id"] for c in caps] == [r["id"] for r in rewards[:2]]
    for c in caps:
        assert set(c) <= CAPTION_KEYS and CAPTION_ID.fullmatch(c["id"]) and c["profile"] in F.PROFILES
        assert (out / c["video"]).is_file()
    long = manifest["jobs"]["arc-gravity__claude-code__eeeeee"]
    assert long["caption_job"] is False and long["video"]["duration_s"] == 130.0
    assert manifest["jobs"]["arc-gravity__claude-code__bbbbbb"]["simulator"] == {
        "reward": 0.0,
        "success": False,
        "outcome": "done",
        "progress": 0.0,
    }
    assert manifest["rewarder"]["repo"] == "nvidia/Flora-Rewarder" and len(manifest["rewarder"]["revision"]) == 40
    with pytest.raises(FileExistsError, match="already holds Flora jobs"):
        F.export(F.trial_folders([run]), out)


def test_instruction_sources(tmp_path: Path) -> None:
    task = tmp_path / "t1"
    task.mkdir()
    (task / "task.md").write_text("---\ntask:\n  name: x/t1\nrobouse:\n  id: t1\n---\n\n# Stack the blocks\n\nBody.\n")
    described = tmp_path / "t2"
    described.mkdir()
    (described / "task.md").write_text("---\ntask:\n  description: 'Put the  cup\n    on the tray'\n---\n\n# Title\n")
    lib = {"language_instruction": "put the bowl on the plate", "suite": "libero"}
    assert F.task_instruction({"task": "x", "metadata": lib}) == ("put the bowl on the plate", "language_instruction")
    assert F.task_instruction({"task": "t2", "task_path": str(described)}) == ("Put the cup on the tray", "description")
    assert F.task_instruction({"task": "t1", "task_path": str(task)}) == ("Stack the blocks", "title")
    assert F.task_instruction({"task": "arc-gravity", "task_path": "/gone"}) == (
        "Rule inference: falling",
        "description",
    )
    assert F.task_instruction({"task": "no-such-task"}) == ("no such task", "task id")


def test_export_instruction_override(run: Path, tmp_path: Path) -> None:
    F.export(F.trial_folders([run]), tmp_path / "j", instruction="  stack the   blocks ", profile="dex")
    assert {r["task"] for r in jsonl(tmp_path / "j" / "reward_jobs.jsonl")} == {"stack the blocks"}
    assert {c["profile"] for c in jsonl(tmp_path / "j" / "caption_jobs.jsonl")} == {"dex"}
    with pytest.raises(ValueError, match="caption profile"):
        F.export([], tmp_path / "k", profile="robot")


def test_export_instructions_per_task(run: Path, tmp_path: Path, capsys) -> None:
    other = tmp_path / "runs" / "r2"
    trial(other, "one-demo-box-mirrored__claude-code__ffffff", task="one-demo-box-mirrored")
    given = tmp_path / "instructions.json"
    given.write_text(json.dumps({"one-demo-box-mirrored": " Open the  box ", "no-such-task": "x"}))
    assert (
        main(["flora", "export", str(run), str(other), "--out", str(tmp_path / "j"), "--instructions", str(given)]) == 0
    )
    assert "--instructions: no exported trial has task no-such-task" in capsys.readouterr().out
    manifest = json.loads((tmp_path / "j" / "trials.json").read_text())["jobs"]
    by = {r["id"]: r["task"] for r in jsonl(tmp_path / "j" / "reward_jobs.jsonl")}
    assert by["one-demo-box-mirrored__claude-code__ffffff"] == "Open the box"
    assert manifest["one-demo-box-mirrored__claude-code__ffffff"]["instruction_from"] == "--instructions"
    assert by["arc-gravity__claude-code__aaaaaa"] == "Rule inference: falling"  # not named: the task's own
    for bad in ("[1, 2]", '{"t": ""}', "not json"):
        given.write_text(bad)
        assert main(["flora", "export", str(run), "--out", str(tmp_path / "k"), "--instructions", str(given)]) == 2
        assert "--instructions" in capsys.readouterr().err and not (tmp_path / "k").exists()


def test_job_ids_are_valid_and_unique() -> None:
    taken: set[str] = set()
    long = "very-long-task-name-" * 10 + "__claude-code__abcdef"
    ids = [F.job_id(n, taken) for n in ["a__b__c", "a__b__c", "-odd name!", long, long]]
    assert ids[:3] == ["a__b__c", "a__b__c-2", "odd-name"]
    assert ids[3] != ids[4] and all(F.JOB_ID.fullmatch(i) and len(i) <= 96 for i in ids)


def test_import_writes_flora_json_with_the_agent_steps(run: Path, tmp_path: Path) -> None:
    out = tmp_path / "jobs"
    F.export(F.trial_folders([run]), out)
    stand_in.run(out)
    written, warnings = F.import_results(out)
    assert warnings == [] and len(written) == 3
    by = {t.name.split("__")[-1]: rec for t, rec in written}
    for key, sim in (("aaaaaa", True), ("bbbbbb", False), ("eeeeee", False)):
        rec = json.loads((run / f"arc-gravity__claude-code__{key}" / "grader" / "flora.json").read_text())
        assert rec == by[key] and rec["schema"] == "robouse-flora/1" and rec["simulator"]["success"] is sim
        o = rec["outcome"]
        assert o["success"] is (o["score"] == 5) and o["agrees"] is (o["success"] == sim)
        assert 0 <= o["progress"] <= 1 and sum(o["probabilities"].values()) == pytest.approx(1)
    # the 3 s video: suboptimal over 0.75-1.2 s, during step 3 only (steps without video time are left out)
    seg = [s for s in by["aaaaaa"]["dense"]["segments"] if s["label"] == "suboptimal"]
    assert [(s["start_s"], s["end_s"]) for s in seg] == [(0.733, 1.2)]
    assert seg[0]["steps"] == [{"index": 3, "action": "robo move-to 0.1 0.2 0.3"}]
    assert seg[0]["rationale"] == "stand-in suboptimal stretch" and by["aaaaaa"]["dense"]["seconds"]["suboptimal"] > 0
    # each clip's own labels: its span, its 32 scores and its stretches that are not normal, with its reasons
    (clip,) = by["aaaaaa"]["dense"]["clips"]
    assert clip["start_s"] == 0.0 and len(clip["quality"]) == 32 and "2" in clip["quality"] and clip["valid"] is True
    assert clip["stretches"] == [
        {"start_s": 0.733, "end_s": 1.2, "label": "suboptimal", "rationale": "stand-in suboptimal stretch"}
    ]
    caps = by["bbbbbb"]["captions"]["segments"]
    assert [c["caption"] for c in caps] == ["Stand-in caption 1.", "Stand-in caption 2."]
    assert [s["index"] for s in caps[1]["steps"]] == [4, 5]  # 1.5-3.0 s
    assert "captions" not in by["eeeeee"]  # 130 s: no caption job
    assert not (run / "arc-gravity__claude-code__cccccc" / "grader").exists()


def test_import_skips_results_for_other_videos(run: Path, tmp_path: Path) -> None:
    out = tmp_path / "jobs"
    F.export(F.trial_folders([run]), out)
    stand_in.run(out)
    rows = jsonl(out / "results" / "terminal.jsonl")
    rows[0]["duration_s"] += 1.0
    rows.append({**rows[1], "id": "not-a-job"})
    (out / "results" / "terminal.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "garbage\n")
    cap = out / "results" / "captions" / f"{rows[1]['id']}.json"
    cap.write_text(json.dumps({**json.loads(cap.read_text()), "input_sha256": {"main": "0" * 64}}))
    written, warnings = F.import_results(out)
    assert sorted(warnings) == sorted(
        [
            "terminal.jsonl:5: not a result line, skipped",
            "not-a-job: a result for no job in trials.json, skipped",
            f"{rows[0]['id']}: terminal.jsonl scored a video of another length, skipped",
            f"{rows[1]['id']}: captions/{rows[1]['id']}.json captioned another video, skipped",
        ]
    )
    by = {rec["job"]: rec for _, rec in written}
    assert "outcome" not in by[rows[0]["id"]] and "dense" in by[rows[0]["id"]]
    assert "captions" not in by[rows[1]["id"]] and "outcome" in by[rows[1]["id"]]


def test_success_score_and_partial_results(run: Path, tmp_path: Path) -> None:
    out = tmp_path / "jobs"
    F.export(F.trial_folders([run]), out)
    stand_in.run(out, only=("terminal",))
    written, _ = F.import_results(out, success_score=1)  # every score counts as solved
    assert all(rec["outcome"]["success"] and set(rec) & {"dense", "captions"} == set() for _, rec in written)
    assert [rec["outcome"]["agrees"] for _, rec in written] == [rec["simulator"]["success"] for _, rec in written]
    bare = tmp_path / "jobs-without-results"
    F.export(F.trial_folders([run]), bare)
    with pytest.raises(FileNotFoundError, match="no Flora results"):
        F.import_results(bare)
    with pytest.raises(FileNotFoundError, match="has no trials.json"):
        F.import_results(tmp_path)


def test_report_reads_flora(run: Path, tmp_path: Path) -> None:
    out = tmp_path / "jobs"
    F.export(F.trial_folders([run]), out)
    stand_in.run(out)
    written, _ = F.import_results(out)
    rep = build([run], ["harness"])
    g = rep["groups"][0]
    agree = sum(rec["outcome"]["agrees"] for _, rec in written)
    assert g["flora_agree"]["n"] == 3 and g["flora_agree"]["k"] == agree
    mean = sum(rec["outcome"]["progress"] for _, rec in written) / 3
    assert g["flora_progress"]["value"] == pytest.approx(mean, abs=1e-4)


def test_cli(run: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "jobs"
    assert main(["flora", "export", str(run), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "wrote 3 reward jobs and 2 caption jobs" in text and "skipped" in text
    assert "python -m batch_utils.terminal_reward --jobs $JOBS/reward_jobs.jsonl" in text
    assert f"robouse flora import {out}" in text
    assert main(["flora", "import", str(out)]) == 2 and "no Flora results" in capsys.readouterr().err
    stand_in.run(out)
    assert main(["flora", "import", str(out), "--success-score", "4"]) == 0
    text = capsys.readouterr().out
    assert "arc-gravity__claude-code__aaaaaa: outcome " in text and "; 2 captions" in text
    assert "trials (Flora's solved: scores 4 to 5)" in text and "wrote grader/flora.json in 3 trial folders" in text
    assert main(["flora", "export", str(tmp_path / "nothing-here"), "--out", str(tmp_path / "j2")]) == 2
    empty = tmp_path / "empty-run"
    trial(empty, "t__h__000000", video=False)
    assert main(["flora", "export", str(empty), "--out", str(tmp_path / "j3")]) == 1
    assert not (tmp_path / "j3" / "trials.json").exists()


def test_video_facts_without_a_recording_index(tmp_path: Path) -> None:
    imageio = pytest.importorskip("imageio.v2")
    pytest.importorskip("imageio_ffmpeg")
    import numpy as np

    d = tmp_path / "older-trial"
    (d / "episode").mkdir(parents=True)
    w = imageio.get_writer(d / "episode" / "recording.mp4", fps=30, codec="libx264", macro_block_size=16)
    for i in range(12):
        w.append_data(np.full((32, 32, 3), 20 * i, dtype=np.uint8))
    w.close()
    video = F.recording(d)
    assert video == d / "episode" / "recording.mp4"
    assert F.video_facts(d, video) == {"fps": 30.0, "frames": 12, "duration_s": 0.4}
    assert F.video_facts(d, d / "missing.mp4") == {}
