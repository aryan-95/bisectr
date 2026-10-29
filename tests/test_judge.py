import numpy as np
from bisectr.config import Thresholds
from bisectr.config import Endpoint
from bisectr.judge import Rep, judge, summarize

TH = Thresholds()


def rep(rng, scale=1.0, err=0.0, n=600):
    lat = rng.lognormal(np.log(40 * scale), 0.25, n)
    return Rep(lat, int(n * err), n, 0.001 * scale, 100.0)


def reps(seed, **kw):
    rng = np.random.default_rng(seed)
    return [rep(rng, **kw) for _ in range(3)]


def test_identical_is_good():
    assert judge(reps(1), reps(2), TH)["verdict"] == "good"


def test_small_shift_is_good():
    assert judge(reps(1), reps(2, scale=1.05), TH)["verdict"] == "good"


def test_clearly_slower_is_bad():
    d = judge(reps(1), reps(2, scale=1.6), TH)
    assert d["verdict"] == "bad" and d["agree"] == 3


def test_error_spike_is_bad():
    assert judge(reps(1), reps(2, err=0.10), TH)["verdict"] == "bad"


def test_one_slow_replica_is_not_bad():
    rng = np.random.default_rng(3)
    cand = [rep(rng, scale=2.0), rep(rng), rep(rng)]
    assert judge(reps(1), cand, TH)["verdict"] != "bad"


def test_tiny_absolute_difference_is_good():
    rng = np.random.default_rng(7)
    mk = lambda ms: [Rep(rng.lognormal(np.log(ms), 0.25, 600), 0, 600, 0.001, 100.0) for _ in range(3)]
    assert judge(mk(5.0), mk(5.9), TH)["verdict"] == "good"      # ratio ~1.18 but only ~1.4 ms


def test_summary_reports_peak_memory_across_replicas():
    reps = [rep(np.random.default_rng(i)) for i in range(3)]
    reps[1].mem = 150.0

    summary = summarize(reps)

    assert summary["mem_mb"] == 150.0
    assert set(summary["latency_quantiles_ms"]) == {"p50", "p90", "p95", "p99"}


def test_endpoint_budget_detects_regression_hidden_by_other_routes():
    rng = np.random.default_rng(42)

    def endpoint_rep(scale):
        users = rng.lognormal(np.log(5), 0.1, 2000)
        orders = rng.lognormal(np.log(10 * scale), 0.1, 100)
        return Rep(
            np.concatenate([users, orders]),
            0,
            2100,
            0.001,
            100,
            {
                "GET /users": {"lat": users, "errors": 0, "n": 2000},
                "GET /orders": {"lat": orders, "errors": 0, "n": 100},
            },
        )

    baseline = [endpoint_rep(1.0) for _ in range(3)]
    candidate = [endpoint_rep(1.8) for _ in range(3)]
    endpoints = [
        Endpoint(path="/users", weight=1),
        Endpoint(path="/orders", weight=1, max_p95_ratio=1.5),
    ]

    result = judge(baseline, candidate, TH, endpoints)

    assert result["verdict"] == "bad"
    assert [endpoint["verdict"] for endpoint in result["endpoints"]] == ["good", "bad"]
    assert result["endpoints"][1]["p95_ratio"] >= 1.5


def test_missing_endpoint_samples_prevent_confident_pass():
    baseline = reps(1)
    candidate = reps(2)
    for replica in [*baseline, *candidate]:
        replica.endpoint_metrics = {
            "GET /users": {"lat": replica.lat[:100], "errors": 0, "n": 100}
        }
    endpoints = [Endpoint(path="/orders", weight=1)]

    result = judge(baseline, candidate, TH, endpoints)

    assert result["verdict"] == "inconclusive"
    assert result["endpoints"][0]["verdict"] == "insufficient_samples"
