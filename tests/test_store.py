import json

import pytest

from bisectr import store
from bisectr.config import Config, Infra


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, *, Item):
        key = Item.get("cache_key", Item.get("run_id"))
        self.items[key] = Item

    def get_item(self, *, Key):
        return {"Item": self.items[Key["cache_key"]]} if Key["cache_key"] in self.items else {}


class FakeDynamoDB:
    def __init__(self):
        self.table = FakeTable()

    def Table(self, _name):
        return self.table


def make_config(**infra_fields):
    infra = {
        "region": "region", "cluster": "cluster", "log_group": "logs",
        "exec_role": "role", "sg": "sg", "subnets": ["subnet"],
        "image_repo": "repo/image", "runner_image": "repo/runner:latest",
        **infra_fields,
    }
    return Config(infra=Infra(**infra))


def test_baseline_cache_uses_dynamodb_when_configured(monkeypatch):
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(store, "_dynamodb", lambda _: dynamodb)
    cfg = make_config(
        runs_table="runs",
        baseline_table="baselines",
        reports_bucket="reports",
        budget_name="budget",
    )
    result = [{"latencies_ms": [1.0, 2.0]}]

    store.save(cfg, "image:sha", {}, result)

    assert store.load(cfg, "image:sha", {}) == result


def test_run_records_use_cloud_table_when_configured(monkeypatch):
    dynamodb = FakeDynamoDB()
    monkeypatch.setattr(store, "_dynamodb", lambda _: dynamodb)
    cfg = make_config(
        runs_table="runs",
        baseline_table="baselines",
        reports_bucket="reports",
        budget_name="budget",
    )

    run_id = store.save_run("gate", {"verdict": "PASS"}, cfg, run_id="test-run")

    assert run_id == "test-run"
    assert json.loads(dynamodb.table.items["test-run"]["payload"]) == {"verdict": "PASS"}


def test_list_runs_returns_recent_local_records(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "RUNS", tmp_path)
    (tmp_path / "gate-old.json").write_text(json.dumps({"result": {"verdict": "PASS"}}))
    (tmp_path / "bisect-new.json").write_text(json.dumps({"result": {"kind": "found"}}))
    (tmp_path / "not-a-run.json").write_text("{}")
    cfg = make_config()

    runs = store.list_runs(cfg, kind="gate", limit=1)

    assert len(runs) == 1
    assert runs[0]["kind"] == "gate"
    assert runs[0]["data"]["result"]["verdict"] == "PASS"


def test_list_runs_rejects_nonpositive_limit():
    with pytest.raises(ValueError, match="limit must be greater than zero"):
        store.list_runs(make_config(), limit=0)


def test_list_runs_queries_recent_cloud_records(monkeypatch):
    class QueryTable:
        def query(self, **kwargs):
            assert kwargs["IndexName"] == "kind-created_at-index"
            assert kwargs["ScanIndexForward"] is False
            return {"Items": [{
                "run_id": "gate-1",
                "kind": "gate",
                "created_at": 123,
                "payload": json.dumps({"result": {"verdict": "PASS"}}),
            }]}

    class QueryDynamoDB:
        def Table(self, _name):
            return QueryTable()

    monkeypatch.setattr(store, "_dynamodb", lambda _: QueryDynamoDB())
    cfg = make_config(
        runs_table="runs",
        baseline_table="baselines",
        reports_bucket="reports",
        budget_name="budget",
    )

    runs = store.list_runs(cfg, kind="gate", limit=1)

    assert runs == [{
        "run_id": "gate-1",
        "kind": "gate",
        "created_at": 123,
        "data": {"result": {"verdict": "PASS"}},
    }]


def test_partial_cloud_storage_config_is_rejected():
    with pytest.raises(ValueError, match="Configure runs_table"):
        make_config(baseline_table="baselines")


def test_baseline_cache_key_changes_when_runner_image_changes():
    cfg = make_config()
    updated_cfg = make_config(runner_image="repo/runner:new")

    assert store._path(cfg, "image:sha", {}) != store._path(updated_cfg, "image:sha", {})


def test_report_is_uploaded_to_private_s3_bucket(monkeypatch):
    calls = []

    class FakeS3:
        def put_object(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(store.boto3, "client", lambda *_args, **_kwargs: FakeS3())
    cfg = make_config(
        runs_table="runs",
        baseline_table="baselines",
        reports_bucket="reports",
        budget_name="budget",
    )

    uri = store.save_report(cfg, "run-1", "<html>report</html>")

    assert uri == "s3://reports/reports/run-1.html"
    assert calls[0]["ContentType"] == "text/html; charset=utf-8"
    assert calls[0]["ServerSideEncryption"] == "AES256"
