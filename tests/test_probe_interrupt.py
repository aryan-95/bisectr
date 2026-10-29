import json
import time
import pytest
from bisectr import probe
from bisectr.config import Config, Infra


def test_ctrl_c_stops_running_tasks(monkeypatch):
    cfg = Config(infra=Infra(region="r", cluster="c", log_group="g", exec_role="e", sg="s", subnets=["a"],
                             image_repo="x/y", runner_image="x/r"))
    launched, stopped = [], []
    monkeypatch.setattr(probe, "register", lambda c, img, env: "td")

    def fake_launch(c, td):
        arn = f"arn:task/{len(launched)}"
        launched.append(arn)
        probe._ACTIVE.add(arn)
        return arn

    monkeypatch.setattr(probe, "launch", fake_launch)
    monkeypatch.setattr(probe, "wait_and_read", lambda c, arn: (time.sleep(0.5), {})[1])
    monkeypatch.setattr(probe, "stop", lambda c, arn: stopped.append(arn))

    def interrupted(futs):
        time.sleep(0.2)                    # let the tasks start, then simulate Ctrl+C
        raise KeyboardInterrupt

    monkeypatch.setattr(probe, "as_completed", interrupted)
    with pytest.raises(KeyboardInterrupt):
        probe.measure_many(cfg, {"a": ("img", {}), "b": ("img", {})})
    assert len(launched) == 6 and set(launched) <= set(stopped)
    time.sleep(0.8)
    assert not probe._ACTIVE


def test_register_passes_health_path_and_endpoint_models_to_runner(monkeypatch):
    cfg = Config(
        health_path="/ready",
        scenario={"endpoints": [{"path": "/search?q=x", "weight": 2}]},
        infra=Infra(region="r", cluster="c", log_group="g", exec_role="e", sg="s",
                    subnets=["a"], image_repo="x/y", runner_image="x/r"),
    )
    captured = {}

    class FakeEcs:
        def register_task_definition(self, **kwargs):
            captured.update(kwargs)
            return {"taskDefinition": {"taskDefinitionArn": "task-definition"}}

    monkeypatch.setattr(probe, "_ecs", lambda _: FakeEcs())

    assert probe.register(cfg, "image:sha") == "task-definition"
    runner_env = {entry["name"]: entry["value"] for entry in captured["containerDefinitions"][1]["environment"]}
    assert runner_env["HEALTH_PATH"] == "/ready"
    assert json.loads(runner_env["ENDPOINTS"]) == [{"path": "/search?q=x", "weight": 2}]
    assert "taskRoleArn" not in captured
