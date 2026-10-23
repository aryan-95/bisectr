"""Parallel k-point bisect with skip handling and a verify step.
search() is pure (oracle injected) so it can be property-tested."""
from __future__ import annotations
from dataclasses import dataclass

from .guardrails import check_enabled
from .judge import Rep, judge
from .probe import measure_many


@dataclass
class Result:
    kind: str                         # found | ambiguous | flaky | not_reproducible
    culprit: int | None = None
    window: tuple[int, int] | None = None
    probes: int = 0


def pick_points(lo, hi, k, skipped):
    cand = [i for i in range(lo + 1, hi) if i not in skipped]
    if not cand:
        return []
    if len(cand) <= k:
        return cand
    return sorted({cand[len(cand) * j // (k + 1)] for j in range(1, k + 1)})


def search(n, oracle, k=3, max_probes=24, pair=None) -> Result:
    """oracle(indices, confirm) -> {index: good|bad|skip}. Index 0 is good, n-1 is bad."""
    if n < 2:
        return Result("not_reproducible")
    s = oracle([0, n - 1], False)
    if s.get(0) != "good" or s.get(n - 1) != "bad":
        return Result("not_reproducible", probes=1)
    lo, hi, skipped, probes = 0, n - 1, set(), 1
    while hi - lo > 1 and probes < max_probes:
        pts = pick_points(lo, hi, k, skipped)[: max_probes - probes]
        if not pts:
            break
        v = oracle(pts, False)
        probes += len(pts)
        bad = [i for i in pts if v[i] == "bad"]
        if bad:
            hi = min(bad)
        good = [i for i in pts if v[i] == "good" and i < hi]
        if good:
            lo = max(good)
        skipped |= {i for i in pts if v[i] not in ("good", "bad")}
    if hi - lo > 1:
        return Result("ambiguous", window=(lo, hi), probes=probes)
    c = oracle([lo, hi], True)                       # verify with 2x samples
    # culprit must be bad; parent must not be bad; and when a head-to-head is available the
    # culprit must be measurably slower than its parent in the SAME time window
    parent_ok = (pair(lo, hi) == "bad") if pair else (c.get(lo) == "good")
    if c.get(hi) == "bad" and c.get(lo) != "bad" and parent_ok:
        return Result("found", culprit=hi, window=(lo, hi), probes=probes)
    return Result("flaky", window=(lo, hi), probes=probes)


def run_bisect(cfg, targets):
    """targets: [(image, env)], index 0 = good, last = bad. Returns (Result, evidence)."""
    check_enabled(cfg)
    base = [Rep.from_dict(d) for d in measure_many(cfg, {0: targets[0]})[0]]
    evidence = []

    def _label(d):
        return "skip" if d["verdict"] == "inconclusive" else d["verdict"]

    def oracle(idxs, confirm=False):
        out = {i: "good" for i in idxs if i == 0}      # index 0 is the baseline by definition
        todo = [i for i in idxs if i != 0]
        if not todo:
            return out
        raw = measure_many(cfg.scaled(2.0) if confirm else cfg, {i: targets[i] for i in todo})
        retry = []
        for i in todo:
            d = judge(base, [Rep.from_dict(x) for x in raw[i]], cfg.thresholds)
            evidence.append({"index": i, "confirm": confirm, **d})
            if d["verdict"] == "inconclusive" and not confirm:
                retry.append(i)
            else:
                out[i] = _label(d)
        if retry:                                      # one longer re-probe, like the gate
            raw = measure_many(cfg.scaled(2.0), {i: targets[i] for i in retry})
            for i in retry:
                d = judge(base, [Rep.from_dict(x) for x in raw[i]], cfg.thresholds)
                evidence.append({"index": i, "retry": True, **d})
                out[i] = _label(d)
        return out

    def pair(lo, hi):
        raw = measure_many(cfg.scaled(2.0), {lo: targets[lo], hi: targets[hi]})
        d = judge([Rep.from_dict(x) for x in raw[lo]], [Rep.from_dict(x) for x in raw[hi]], cfg.thresholds)
        evidence.append({"index": hi, "pair_vs": lo, **d})
        return d["verdict"]

    res = search(len(targets), oracle, k=cfg.bisect_k, max_probes=cfg.max_probes, pair=pair)
    return res, evidence
