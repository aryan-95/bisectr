import subprocess

import pytest
import typer
from types import SimpleNamespace

from bisectr import cli


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
