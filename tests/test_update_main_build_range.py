import json

import pytest

from scripts import update_main_build_range


SHA_ONE = "1" * 40
SHA_TWO = "2" * 40


class FakeSSM:
    class exceptions:
        class ParameterNotFound(Exception):
            pass

    def __init__(self, value=None):
        self.value = value
        self.writes = []

    def get_parameter(self, *, Name):
        assert Name == update_main_build_range.PARAMETER_NAME
        if self.value is None:
            raise self.exceptions.ParameterNotFound()
        return {"Parameter": {"Value": self.value}}

    def put_parameter(self, **kwargs):
        self.writes.append(kwargs)


def _configure(monkeypatch, ssm, sha):
    monkeypatch.setenv("GITHUB_SHA", sha)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(update_main_build_range.boto3, "client", lambda *_a, **_kw: ssm)
    monkeypatch.setattr(update_main_build_range.subprocess, "run", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        update_main_build_range.subprocess,
        "check_output",
        lambda *_a, **_kw: sha + "\n",
    )


def test_first_successful_main_build_has_no_previous_baseline(monkeypatch):
    ssm = FakeSSM()
    _configure(monkeypatch, ssm, SHA_ONE)

    update_main_build_range.main()

    state = json.loads(ssm.writes[0]["Value"])
    assert state == {
        "good_sha": None,
        "bad_sha": SHA_ONE,
        "updated_by": "build-main",
    }
    assert ssm.writes[0]["Overwrite"] is True


def test_next_build_records_the_previous_successful_image(monkeypatch):
    ssm = FakeSSM(json.dumps({"good_sha": None, "bad_sha": SHA_ONE}))
    _configure(monkeypatch, ssm, SHA_TWO)

    update_main_build_range.main()

    state = json.loads(ssm.writes[0]["Value"])
    assert state["good_sha"] == SHA_ONE
    assert state["bad_sha"] == SHA_TWO


def test_main_build_range_rejects_short_sha(monkeypatch):
    ssm = FakeSSM()
    _configure(monkeypatch, ssm, "abc")

    with pytest.raises(ValueError, match="40-character commit SHA"):
        update_main_build_range.main()

    assert ssm.writes == []


def test_stale_main_build_does_not_overwrite_newer_range(monkeypatch):
    ssm = FakeSSM()
    _configure(monkeypatch, ssm, SHA_ONE)
    monkeypatch.setattr(
        update_main_build_range.subprocess,
        "check_output",
        lambda *_a, **_kw: SHA_TWO + "\n",
    )

    update_main_build_range.main()

    assert ssm.writes == []
