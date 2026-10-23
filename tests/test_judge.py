import numpy as np
from bisectr.config import Thresholds
from bisectr.judge import Rep, judge

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
