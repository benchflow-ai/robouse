"""The `robouse` command line: every command parses, and the planning paths work without a simulator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from robouse.cli import main, parser

ROOT = Path(__file__).resolve().parents[1]
VISIBLE = ["run", "run-many", "tasks", "components", "fetch-assets", "report", "flora", "summarize", "doctor"]
HIDDEN = ["serve", "grade", "estop", "operator", "hil-check", "robots", "export"]
COMMANDS = [c for c in VISIBLE + HIDDEN if c not in ("tasks", "components")]


@pytest.mark.parametrize("cmd", COMMANDS)
def test_help(cmd: str, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        main([cmd, "--help"])
    assert e.value.code == 0 and capsys.readouterr().out.startswith(f"usage: robouse {cmd}")


def test_top_level_help_lists_only_the_tested_commands(capsys) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    listed = {line.split()[0] for line in out.splitlines() if line.startswith("    ") and not line.startswith("     ")}
    assert out.count("Robo Use") == 1 and listed == set(VISIBLE)


def test_run_many_dry_run(capsys) -> None:
    rc = main(
        [
            "run-many",
            "--tasks",
            str(ROOT / "tasks" / "arc-style"),
            "--harness",
            "oracle",
            "--out",
            "/tmp/unused",
            "--sample",
            "2",
            "--seeds",
            "0-1",
            "--dry-run",
        ]
    )
    plan = json.loads(capsys.readouterr().out)
    assert rc == 0 and len(plan["tasks"]) == 2 and plan["trials"] == 4


def test_local_run_rejects_seeds(capsys) -> None:
    rc = main(["run", "--task", "arc-gravity", "--harness", "oracle", "--out", "/tmp/unused", "--seeds", "0-2"])
    assert rc == 2 and "run-many --seeds" in capsys.readouterr().err


def test_tasks_list_and_robots(capsys) -> None:
    assert main(["tasks", "list", str(ROOT / "tasks" / "arc-style")]) == 0
    assert "arc-gravity tabletop" in capsys.readouterr().out
    assert main(["robots"]) == 0
    out = capsys.readouterr().out
    assert "rosbridge" in out and "so100" in out


def test_record_size_is_validated(capsys) -> None:
    rc = main(["run", "--task", "arc-gravity", "--harness", "oracle", "--out", "/tmp/unused", "--record-size", "huge"])
    assert rc == 2 and "1280x720" in capsys.readouterr().err


def test_parser_builds() -> None:
    assert parser().prog == "robouse"


# what each help says about the folder `--out` writes: a run folder, as the site and docs call it (0.3.1; "job" before)
RUN_FOLDER = {
    None: "report metrics with 95% confidence intervals over run folders",
    "run": "--out OUT run folder; the trial is written to OUT/<task>__<harness>__<id>/",
    "run-many": "--out OUT run folder; one trial folder per task",
    "report": "runs run folders (run-many --out)",
    "grade": "trials trial folders or run folders",
}


@pytest.mark.parametrize("cmd", RUN_FOLDER, ids=lambda c: c or "robouse")
def test_help_says_run_folder(cmd, capsys) -> None:
    with pytest.raises(SystemExit):
        main([cmd, "--help"] if cmd else ["--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert RUN_FOLDER[cmd] in out and "job" not in out.lower(), out
    if cmd == "report":
        assert "runs [runs ...]" in out and "mode, run, regime" in out


def _trial(run: Path, name: str, reward: float) -> None:
    d = run / name
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"harness": "oracle", "task": name, "metadata": {"suite": "s"}}))
    (d / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": reward}}, "episode": {}}))


def test_report_groups_by_run_and_still_by_job(tmp_path, capsys) -> None:
    _trial(tmp_path / "run-a", "t1", 1.0)
    _trial(tmp_path / "run-b", "t1", 0.0)
    runs = [str(tmp_path / "run-a"), str(tmp_path / "run-b")]
    for key in ("run", "job"):  # job: the key's name before 0.3.1, still accepted
        out = tmp_path / f"{key}.json"
        assert main(["report", *runs, "--by", key, "--json", str(out)]) == 0
        groups = json.loads(out.read_text())["groups"]
        assert [g["group"][key] for g in groups] == ["run-a", "run-b"]
        assert [g["success"]["value"] for g in groups] == [1.0, 0.0]
    with pytest.raises(SystemExit) as e:
        main(["report", *runs, "--by", "nope"])
    assert "unknown group key" in str(e.value) and "'run'" in str(e.value) and "'job'" not in str(e.value)
