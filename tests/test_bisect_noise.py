import numpy as np
from bisectr import bisect
from bisectr.config import Config, Infra


def make_cfg():
    return Config(infra=Infra(region="r", cluster="c", log_group="g", exec_role="e", sg="s", subnets=["a"],
                              image_repo="x/y", runner_image="x/r"), bisect_k=2)


def test_one_noisy_probe_does_not_cause_flaky(monkeypatch):
    """Reproduces the real failure: a clean commit (4) measures 1.7x slower once, due to host noise."""
    rng = np.random.default_rng(1)
    state = {"used": False}

    def fake(c, specs):
        out = {}
        for name, (img, env) in specs.items():
            real_bad = bool(env)
            noisy = (not real_bad) and name == 4 and "base" not in specs and not state["used"]
            if noisy:
                state["used"] = True
            scale = 2.4 if real_bad else (1.7 if noisy else 1.0)
            out[name] = [{"n": 600, "errors": 0, "cpu_s_per_req": 0.003, "peak_mem_mb": 34.0,
                          "latencies_ms": list(rng.lognormal(np.log(5 * scale), 0.2, 600))}
                         for _ in range(c.replicas)]
        return out

    monkeypatch.setattr(bisect, "measure_many", fake)
    monkeypatch.setattr(bisect, "check_enabled", lambda c: None)
    targets = [("img", {"REGRESSION": "payload_bloat"} if i >= 10 else {}) for i in range(12)]
    res, ev = bisect.run_bisect(make_cfg(), targets)
    assert res.kind == "found" and res.culprit == 10, (res.kind, res.culprit, res.window)
