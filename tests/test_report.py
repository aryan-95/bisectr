from bisectr import report
from types import SimpleNamespace


def test_github_auth_uses_bearer_token():
    assert report._h("abc123") == {
        "Authorization": "Bearer abc123",
        "Accept": "application/vnd.github+json",
    }


def test_gate_comment_explains_profile_and_failed_thresholds():
    cfg = SimpleNamespace(
        scenario=SimpleNamespace(profile="checkout-mix", rps=20, seconds=30, endpoints=[1, 2]),
        thresholds=SimpleNamespace(min_ratio=1.25, min_agree=2, cost_min_ratio=1.15),
        cost=SimpleNamespace(target_rps=500),
    )
    result = {
        "base": {"p95": 10, "err": 0.0, "cpu_per_1000": None, "mem_mb": 100},
        "cand": {"p95": 15, "err": 0.0, "cpu_per_1000": None, "mem_mb": 100},
        "detail": {"p": 0.001, "ratio": 1.5, "agree": 3},
        "cost": {"available": False},
        "reasons": ["latency"],
        "verdict": "FAIL",
        "replicas": 3,
        "reprobed": False,
    }

    markdown = report.comment_markdown(result, cfg)

    assert "checkout-mix" in markdown
    assert "Review the candidate's latency/error changes" in markdown


def test_history_dashboard_escapes_run_content():
    rendered = report.history_dashboard([{
        "kind": "gate",
        "created_at": 1_793_300_000,
        "data": {
            "inputs": {"candidate": "abcdef123456"},
            "result": {
                "verdict": "<script>alert(1)</script>",
                "cand": {"p95": 12.3},
                "cost": {"delta": 20.0},
            },
        },
    }])

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "12.30 ms" in rendered
    assert "20.00 USD/mo" in rendered
    assert "abcdef1234" in rendered
    assert "<svg" in rendered
