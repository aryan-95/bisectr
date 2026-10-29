import subprocess

import pytest
import typer
from types import SimpleNamespace

from bisectr import cli
from bisectr.config import Config, Infra, Scenario


def test_resolve_commit_returns_full_sha(monkeypatch):
    def fake_check_output(command, **kwargs):
        assert command == ["git", "rev-parse", "--verify", "HEAD^{commit}"]
        assert kwargs["stderr"] == subprocess.PIPE
        return "abcdef123456\n"

    monkeypatch.setattr(cli.subprocess, "check_output", fake_check_output)

    assert cli._resolve_commit("HEAD", "good") == "abcdef123456"


def test_resolve_commit_reports_invalid_ref(monkeypatch, capsys):
    def fake_check_output(command, **kwargs):
        raise subprocess.CalledProcessError(128, command)

    monkeypatch.setattr(cli.subprocess, "check_output", fake_check_output)

    with pytest.raises(typer.Exit) as exc:
        cli._resolve_commit("GOOD_COMMIT_SHA", "good")

    assert exc.value.exit_code == 2
    assert "Invalid good commit 'GOOD_COMMIT_SHA'" in capsys.readouterr().err


def test_bisect_result_payload_resolves_sha_and_suspect_window():
    result = SimpleNamespace(
        kind="found",
        culprit=2,
        window=(1, 2),
        probes=5,
    )
    evidence = [{"index": 2, "verdict": "bad"}]

    payload = cli._bisect_result_payload(
        result, ["a" * 40, "b" * 40, "c" * 40], evidence
    )

    assert payload == {
        "kind": "found",
        "culprit": "c" * 40,
        "window": ["b" * 40, "c" * 40],
        "probes": 5,
        "evidence": evidence,
    }


def test_bisect_rejects_good_commit_that_is_not_an_ancestor(monkeypatch, capsys):
    monkeypatch.setattr(cli, "load", lambda _: object())
    monkeypatch.setattr(cli, "_resolve_commit", lambda ref, _: ref)
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    with pytest.raises(typer.Exit) as exc:
        cli.bisect_cmd(config="unused", good="good-sha", bad="bad-sha")

    assert exc.value.exit_code == 2
    assert "good commit must be an ancestor of bad commit" in capsys.readouterr().err


def test_trends_prints_recent_gate_result(monkeypatch, capsys):
    cfg = SimpleNamespace()
    monkeypatch.setattr(cli, "load", lambda _: cfg)
    monkeypatch.setattr(
        cli.store,
        "list_runs",
        lambda _cfg, **_kwargs: [{
            "kind": "gate",
            "created_at": 1793300000,
            "data": {
                "inputs": {"scenario": {"profile": "checkout"}},
                "result": {"verdict": "FAIL", "detail": {"ratio": 1.4}},
            },
        }],
    )

    cli.trends(config="unused", kind="all", limit=20)

    output = capsys.readouterr().out
    assert "checkout" in output
    assert "FAIL" in output
    assert "1.40x" in output


def test_validate_repeats_gate_without_cache_and_writes_csv(monkeypatch, tmp_path, capsys):
    class ConfigStub:
        scenario = SimpleNamespace(
            profile="checkout",
            model_dump=lambda: {"profile": "checkout"},
        )
        thresholds = SimpleNamespace(model_dump=lambda: {"min_ratio": 1.25})

    cfg = ConfigStub()
    calls = []
    saved = []
    monkeypatch.setattr(cli, "load", lambda _: cfg)
    monkeypatch.setattr(cli.probe, "image_exists", lambda _cfg, _image: True)
    monkeypatch.setattr(cli, "_image", lambda _cfg, image: f"repo:{image}")
    monkeypatch.setattr(cli, "run_gate", lambda *args, **kwargs: (
        calls.append((args, kwargs)) or {
            "detail": {"ratio": 1.2, "p": 0.3, "agree": 1},
            "cost": {"regression": False},
            "verdict": "PASS",
        }
    ))
    monkeypatch.setattr(cli.store, "save_run", lambda *args: saved.append(args))
    out = tmp_path / "nested" / "results.csv"

    cli.validate_cmd(
        config="unused",
        baseline="good",
        candidate="new",
        trials=2,
        out=str(out),
    )

    assert len(calls) == 2
    assert all(call[1]["use_cache"] is False for call in calls)
    assert len(saved) == 2
    assert "p95_ratio" in out.read_text()
    assert "2/2" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("verdict", "exit_code", "message"),
    [
        ("PASS", 0, "Regression resolved"),
        ("WARN", 1, "not confirmed as resolved"),
        ("FAIL", 1, "not confirmed as resolved"),
    ],
)
def test_verify_fix_reports_resolution_and_saves_run(
    monkeypatch, capsys, verdict, exit_code, message
):
    class ConfigStub:
        scenario = SimpleNamespace(model_dump=lambda: {"profile": "default"})
        thresholds = SimpleNamespace(model_dump=lambda: {"min_ratio": 1.25})

    cfg = ConfigStub()
    saved = []
    reports = []
    monkeypatch.setattr(cli, "load", lambda _: cfg)
    monkeypatch.setattr(cli.probe, "image_exists", lambda *_args: True)
    monkeypatch.setattr(cli, "_image", lambda _cfg, image: f"repo:{image}")
    monkeypatch.setattr(
        cli,
        "run_gate",
        lambda *_args, **kwargs: (
            {"verdict": verdict, "reasons": [], "detail": {}}
            if kwargs["use_cache"] is False
            else pytest.fail("fix verification must not reuse cached results")
        ),
    )
    monkeypatch.setattr(cli.store, "save_run", lambda *args: saved.append(args))
    monkeypatch.setattr(cli.report, "comment_markdown", lambda *_args: "PASS")
    monkeypatch.setattr(cli.report, "html_report", lambda *args: "html")
    monkeypatch.setattr(cli.store, "save_report", lambda *args: reports.append(args) or "runs/report.html")

    with pytest.raises(typer.Exit) as exc:
        cli.verify_fix(
            config="unused", baseline="known-good", candidate="fixed"
        )

    assert exc.value.exit_code == exit_code
    assert saved[0][0] == "verify-fix"
    assert reports
    assert message in capsys.readouterr().out


def test_suite_runs_all_profiles_and_fails_if_any_profile_fails(monkeypatch, capsys):
    cfg = Config(
        infra=Infra(
            region="region", cluster="cluster", log_group="logs", exec_role="role",
            sg="sg", subnets=["subnet"], image_repo="repo/app",
            runner_image="repo/runner:latest",
        ),
        scenarios=[
            Scenario(profile="normal"),
            Scenario(profile="spike", rps=80),
        ],
    )
    ran_profiles = []
    saved = []
    results = iter(["PASS", "FAIL"])

    def fake_gate(profile_cfg, *_args, **_kwargs):
        ran_profiles.append(profile_cfg.scenario.profile)
        verdict = next(results)
        return {
            "verdict": verdict,
            "base": {"p95": 10, "err": 0.0, "cpu_per_1000": None, "mem_mb": 10},
            "cand": {"p95": 15, "err": 0.0, "cpu_per_1000": None, "mem_mb": 10},
            "detail": {"p": 0.01, "ratio": 1.5, "agree": 3, "err_delta": 0.0},
            "cost": {"available": False},
            "reasons": [],
            "replicas": 3,
            "reprobed": False,
        }

    monkeypatch.setattr(cli, "load", lambda _: cfg)
    monkeypatch.setattr(cli.probe, "image_exists", lambda *_args: True)
    monkeypatch.setattr(cli, "run_gate", fake_gate)
    monkeypatch.setattr(cli.report, "comment_markdown", lambda result, _cfg: result["verdict"])
    monkeypatch.setattr(cli.store, "save_run", lambda *args: saved.append(args))
    monkeypatch.setattr(cli.store, "save_report", lambda *_args: "local-report.html")

    with pytest.raises(typer.Exit) as exc:
        cli.suite(config="unused", candidate="abc", baseline="def", profiles=None)

    assert exc.value.exit_code == 1
    assert ran_profiles == ["normal", "spike"]
    assert len(saved) == 1
    assert "workload suite: FAIL" in capsys.readouterr().out


def test_dashboard_writes_history_html(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load", lambda _: object())
    monkeypatch.setattr(cli.store, "list_runs", lambda *_args, **_kwargs: [])
    output = tmp_path / "nested" / "dashboard.html"

    cli.dashboard(config="unused", out=str(output), limit=10)

    assert "No runs found." in output.read_text()
    assert "Dashboard written" in capsys.readouterr().out


def test_eval_passes_seed_and_trial_options_to_harness(monkeypatch):
    captured = []
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **kwargs: captured.append(command))

    cli.eval_cmd(image="image-sha", trials=20, seed=17, out="eval/selected.csv")

    assert "--trials" in captured[0]
    assert captured[0][captured[0].index("--trials") + 1] == "20"
    assert captured[0][captured[0].index("--seed") + 1] == "17"
    assert captured[0][captured[0].index("--out") + 1] == "eval/selected.csv"


def test_eval_passes_resume_flag_when_requested(monkeypatch):
    captured = []
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **kwargs: captured.append(command))

    cli.eval_cmd(image="image-sha", resume=True)

    assert captured[0][-1] == "--resume"
