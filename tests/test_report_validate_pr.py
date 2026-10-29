import json
from types import SimpleNamespace

import pytest

from bisectr import report


def test_validate_pr_reports_missing_pull_request(monkeypatch):
    monkeypatch.setattr(
        report.httpx, "get", lambda *args, **kwargs: SimpleNamespace(status_code=404)
    )

    with pytest.raises(RuntimeError, match="could not find pull request #1"):
        report.validate_pr("aryan-95/bisectr", 1, "token")


def test_validate_pr_accepts_existing_pull_request(monkeypatch):
    response = report.httpx.Response(
        200,
        request=report.httpx.Request(
            "GET", "https://api.github.com/repos/aryan-95/bisectr/pulls/12"
        ),
        content=json.dumps({"head": {"sha": "abcdef123456"}}),
    )
    monkeypatch.setattr(report.httpx, "get", lambda *args, **kwargs: response)

    assert report.validate_pr("aryan-95/bisectr", 12, "token")["head"]["sha"] == "abcdef123456"


def test_html_report_escapes_untrusted_text():
    data = {"result": {
        "base": {"latency_quantiles_ms": {"p50": 1, "p90": 2, "p95": 3, "p99": 4}},
        "cand": {"latency_quantiles_ms": {"p50": 2, "p90": 4, "p95": 6, "p99": 8}},
    }}
    rendered = report.html_report("<script>alert(1)</script>", "result", data)

    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<svg" in rendered


def test_post_check_run_uses_expected_sha_and_conclusion(monkeypatch):
    requests = []

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, **kwargs):
        requests.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(report.httpx, "post", fake_post)

    report.post_check_run(
        "owner/repo", "abcdef123456", "FAIL", "failure", "regression detected", "token")

    assert requests[0][0] == "https://api.github.com/repos/owner/repo/check-runs"
    assert requests[0][1]["json"]["head_sha"] == "abcdef123456"
    assert requests[0][1]["json"]["conclusion"] == "failure"
