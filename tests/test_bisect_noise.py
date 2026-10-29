import numpy as np
from bisectr import bisect
from bisectr.config import Config, Infra


def make_cfg():
    return Config(infra=Infra(region="r", cluster="c", log_group="g", exec_role="e", sg="s", subnets=["a"],
                              image_repo="x/y", runner_image="x/r"), bisect_k=2)


def reps(rng, scale, c):
    return [{"n": 600, "errors": 0, "cpu_s_per_req": 0.003, "peak_mem_mb": 34.0,
             "latencies_ms": list(rng.lognormal(np.log(5 * scale), 0.2, 600))} for _ in range(c.replicas)]


def run(monkeypatch, scale_for):
    rng = np.random.default_rng(1)

    def fake(c, specs):
        return {name: reps(rng, scale_for(name, env, specs), c) for name, (img, env) in specs.items()}

    monkeypatch.setattr(bisect, "measure_many", fake)
    monkeypatch.setattr(bisect, "check_enabled", lambda c: None)
    monkeypatch.setattr(bisect, "RECHECKS", 2)      # these tests exercise the optional recheck vote
    targets = [("img", {"REGRESSION": "payload_bloat"} if i >= 10 else {}) for i in range(12)]
    return bisect.run_bisect(make_cfg(), targets)


def test_clean_commit_looking_slow_once_does_not_cause_flaky(monkeypatch):
    """Real failure #1: clean commit 4 measures 1.7x slower in the first (non-simultaneous) probe."""
    used = {"n": 0}

    def scale(name, env, specs):
        if env:
            return 2.4
        if name == 4 and 0 not in specs and used["n"] == 0:
            used["n"] += 1
            return 1.7
        return 1.0

    res, ev = run(monkeypatch, scale)
    assert res.kind == "found" and res.culprit == 10, (res.kind, res.culprit, res.window)
    assert any(e.get("recheck") for e in ev)


def test_bad_commit_looking_normal_once_does_not_abort(monkeypatch):
    """Real failure #2: bad commit 11 measures normal in ONE fresh recheck; a single noisy run must not veto."""
    calls = {"n": 0}

    def scale(name, env, specs):
        if env and name == 11 and set(specs) == {0, 11}:
            calls["n"] += 1
            return 1.0 if calls["n"] == 1 else 2.4      # first recheck is an outlier, the second is fine
        return 2.4 if env else 1.0

    res, ev = run(monkeypatch, scale)
    assert res.kind == "found" and res.culprit == 10, (res.kind, res.culprit, res.window)


def test_default_runs_without_rechecks(monkeypatch):
    assert bisect.RECHECKS == 0
    rng = np.random.default_rng(2)
    monkeypatch.setattr(bisect, "measure_many",
                        lambda c, specs: {n: reps(rng, 2.4 if env else 1.0, c) for n, (img, env) in specs.items()})
    monkeypatch.setattr(bisect, "check_enabled", lambda c: None)
    targets = [("img", {"R": "x"} if i >= 6 else {}) for i in range(12)]
    res, ev = bisect.run_bisect(make_cfg(), targets)
    assert res.kind == "found" and res.culprit == 6 and not any(e.get("recheck") for e in ev)


def test_sanity_check_survives_one_outlier(monkeypatch):
    """Real failure #2 at the endpoint: the bad end point looks normal once; one retry must rescue the run."""
    rng = np.random.default_rng(3)
    seen = {"n": 0}

    def fake(c, specs):
        out = {}
        for n, (img, env) in specs.items():
            scale = 2.4 if env else 1.0
            if env and n == 11:
                seen["n"] += 1
                scale = 1.0 if seen["n"] == 1 else 2.4      # first measurement of the end point is an outlier
            out[n] = reps(rng, scale, c)
        return out

    monkeypatch.setattr(bisect, "measure_many", fake)
    monkeypatch.setattr(bisect, "check_enabled", lambda c: None)
    targets = [("img", {"R": "x"} if i >= 10 else {}) for i in range(12)]
    res, _ = bisect.run_bisect(make_cfg(), targets)
    assert res.kind == "found" and res.culprit == 10
