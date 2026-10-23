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
