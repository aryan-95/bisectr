import json

import pytest
from botocore.exceptions import ClientError

from lambdas.alarm_dispatch import handler as alarm_dispatch


GOOD_SHA = "1" * 40
BAD_SHA = "2" * 40


class FakeSSM:
    class exceptions:
        class ParameterNotFound(Exception):
            pass

    def get_parameter(self, *, Name):
        assert Name == "/bisectr/main-build-range"
        return {
            "Parameter": {
                "Value": json.dumps({"good_sha": GOOD_SHA, "bad_sha": BAD_SHA})
            }
        }


class FakeSecrets:
    def get_secret_value(self, *, SecretId):
        assert SecretId == "secret-arn"
        return {"SecretString": "token-value"}


class FakeDispatchTable:
    def __init__(self):
        self.items = {}

    def put_item(self, *, Item, ConditionExpression):
        assert ConditionExpression == "attribute_not_exists(event_id)"
        if Item["event_id"] in self.items:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}},
                "PutItem",
            )
        self.items[Item["event_id"]] = Item

    def delete_item(self, *, Key):
        self.items.pop(Key["event_id"], None)


class FakeDynamoDB:
    def __init__(self):
        self.table = FakeDispatchTable()

    def Table(self, name):
        assert name == "dispatches"
        return self.table


class FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _event(event_id="event-1", alarm="bisectr-prod-latency", state="ALARM"):
    return {
        "id": event_id,
        "detail": {"alarmName": alarm, "state": {"value": state}},
    }


def _configure(monkeypatch, table, requests):
    monkeypatch.setenv("ALARM_NAME_PREFIX", "bisectr-")
    monkeypatch.setenv("RANGE_PARAMETER", "/bisectr/main-build-range")
    monkeypatch.setenv("DISPATCH_TABLE", "dispatches")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN_SECRET_ARN", "secret-arn")
    monkeypatch.setenv("GITHUB_WORKFLOW", "bisectr-alarm.yml")
    monkeypatch.setenv("GITHUB_REF", "main")
    monkeypatch.setattr(alarm_dispatch, "ssm", FakeSSM())
    monkeypatch.setattr(alarm_dispatch, "secrets", FakeSecrets())
    dynamodb = FakeDynamoDB()
    dynamodb.table = table
    monkeypatch.setattr(alarm_dispatch, "dynamodb", dynamodb)
    monkeypatch.setattr(
        alarm_dispatch.urllib.request, "urlopen",
        lambda request, timeout: requests.append((request, timeout)) or FakeResponse(),
    )


def test_alarm_dispatch_ignores_nonmatching_and_non_alarm_events(monkeypatch):
    _configure(monkeypatch, FakeDispatchTable(), [])

    assert alarm_dispatch.handler(_event(alarm="other-service"), None)["status"] == "ignored"
    assert alarm_dispatch.handler(_event(state="OK"), None)["status"] == "ignored"


def test_alarm_dispatch_triggers_github_workflow_with_verified_range(monkeypatch):
    table, requests = FakeDispatchTable(), []
    _configure(monkeypatch, table, requests)

    result = alarm_dispatch.handler(_event(), None)

    assert result["status"] == "dispatched"
    request, timeout = requests[0]
    assert request.full_url.endswith("/actions/workflows/bisectr-alarm.yml/dispatches")
    assert request.get_header("Authorization") == "Bearer token-value"
    payload = json.loads(request.data)
    assert payload["ref"] == "main"
    assert payload["inputs"]["good"] == GOOD_SHA
    assert payload["inputs"]["bad"] == BAD_SHA
    assert payload["inputs"]["alarm_name"] == "bisectr-prod-latency"
    assert timeout == 15
    assert table.items["event-1"]["expires_at"] > 0


def test_alarm_dispatch_deduplicates_eventbridge_retries(monkeypatch):
    table, requests = FakeDispatchTable(), []
    _configure(monkeypatch, table, requests)
    alarm_dispatch.handler(_event(), None)

    result = alarm_dispatch.handler(_event(), None)

    assert result == {"status": "duplicate", "event_id": "event-1"}
    assert len(requests) == 1


def test_alarm_dispatch_rejects_missing_known_good_sha(monkeypatch):
    table = FakeDispatchTable()
    _configure(monkeypatch, table, [])

    class MissingGoodSSM(FakeSSM):
        def get_parameter(self, *, Name):
            return {"Parameter": {"Value": json.dumps({"bad_sha": BAD_SHA})}}

    monkeypatch.setattr(alarm_dispatch, "ssm", MissingGoodSSM())

    with pytest.raises(ValueError, match="previous good SHA"):
        alarm_dispatch.handler(_event(), None)

    assert table.items == {}
