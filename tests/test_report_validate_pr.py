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
    )
    monkeypatch.setattr(report.httpx, "get", lambda *args, **kwargs: response)

    report.validate_pr("aryan-95/bisectr", 12, "token")
