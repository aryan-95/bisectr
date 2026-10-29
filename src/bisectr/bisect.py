"""Parallel k-point bisect with skip handling, noise-robust voting, and a head-to-head verify step.
search() is pure (oracle injected) so it can be property-tested."""
from __future__ import annotations
from dataclasses import dataclass

from .guardrails import check_enabled
from .judge import Rep, judge
from .probe import measure_many

# Optional: confirm a "bad" probe with fresh head-to-head runs against a baseline measured at the same
# time (majority of RECHECKS + 1 votes; 2 means 2 of 3). OFF by default: in simulation with outliers
# in both directions it did not raise the exact-find rate (96 vs 93 of 150) and cost ~65% more tasks.
# Never turn it to 1: a single noisy recheck then vetoes a real regression.
RECHECKS = 0


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
    """oracle(indices, confirm) -> {index: good|bad|skip}. Index 0 is good, n-1 is bad.
    pair(lo, hi) -> 'bad' when hi is measurably slower than lo in a head-to-head run."""
    if n < 2:
        return Result("not_reproducible")
    s = oracle([0, n - 1], False)
    probes = 1
    if s.get(0) != "good" or s.get(n - 1) != "bad":
        s = oracle([0, n - 1], False)     # one fresh retry: a single outlier must not abort the whole run
        probes = 2
        if s.get(0) != "good" or s.get(n - 1) != "bad":
            return Result("not_reproducible", probes=probes)
    lo, hi, skipped = 0, n - 1, set()
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
    if pair is not None:
        # verify: the culprit must be measurably slower than its parent in a head-to-head run
        if pair(lo, hi) == "bad":
            return Result("found", culprit=hi, window=(lo, hi), probes=probes)
        return Result("flaky", window=(lo, hi), probes=probes)
    c = oracle([lo, hi], True)                       # verify with 2x samples
    if c.get(hi) == "bad" and c.get(lo) == "good":
        return Result("found", culprit=hi, window=(lo, hi), probes=probes)
    return Result("flaky", window=(lo, hi), probes=probes)


def run_bisect(cfg, targets):
    """targets: [(image, env)], index 0 = good, last = bad. Returns (Result, evidence)."""
    check_enabled(cfg)
    base = [Rep.from_dict(d) for d in measure_many(cfg, {0: targets[0]})[0]]
    evidence = []
    need = (RECHECKS + 1) // 2 + 1                    # bad votes required (the first probe counts as one)

    def _label(d):
        return "skip" if d["verdict"] == "inconclusive" else d["verdict"]

    def head_to_head(lo, hi):
        """Measure two commits at the same time (2x samples) and judge hi against lo."""
        raw = measure_many(cfg.scaled(2.0), {lo: targets[lo], hi: targets[hi]})
        return judge([Rep.from_dict(x) for x in raw[lo]], [Rep.from_dict(x) for x in raw[hi]],
                     cfg.thresholds, cfg.scenario.endpoints)

    def oracle(idxs, confirm=False):
        out = {i: "good" for i in idxs if i == 0}      # index 0 is the baseline by definition
        todo = [i for i in idxs if i != 0]
        if not todo:
            return out
        raw = measure_many(cfg.scaled(2.0) if confirm else cfg, {i: targets[i] for i in todo})
        retry, recheck = [], []
        for i in todo:
            d = judge(base, [Rep.from_dict(x) for x in raw[i]], cfg.thresholds,
                      cfg.scenario.endpoints)
            evidence.append({"index": i, "confirm": confirm, **d})
            if d["verdict"] == "inconclusive" and not confirm:
                retry.append(i)
            elif d["verdict"] == "bad" and not confirm:
                recheck.append(i)
            else:
                out[i] = _label(d)
        if retry:                                      # one longer re-probe, like the gate
            raw = measure_many(cfg.scaled(2.0), {i: targets[i] for i in retry})
            for i in retry:
                d = judge(base, [Rep.from_dict(x) for x in raw[i]], cfg.thresholds,
                          cfg.scenario.endpoints)
                evidence.append({"index": i, "retry": True, **d})
                if d["verdict"] == "bad":
                    recheck.append(i)
                else:
                    out[i] = _label(d)
        for i in recheck:                              # majority vote over fresh head-to-head runs
            bad_votes = 1
            for r in range(RECHECKS):
                if bad_votes >= need or bad_votes + (RECHECKS - r) < need:
                    break                              # already decided
                d = head_to_head(0, i)
                evidence.append({"index": i, "recheck": True, **d})
                bad_votes += d["verdict"] == "bad"
            out[i] = "bad" if bad_votes >= need else "skip"
        return out

    def pair(lo, hi):
        bad_votes = 0
        for r in range(3):                             # best of 3, stop as soon as two runs agree
            d = head_to_head(lo, hi)
            evidence.append({"index": hi, "pair_vs": lo, **d})
            bad_votes += d["verdict"] == "bad"
            if bad_votes >= 2 or (r + 1 - bad_votes) >= 2:
                break
        return "bad" if bad_votes >= 2 else "inconclusive"

    res = search(len(targets), oracle, k=cfg.bisect_k, max_probes=cfg.max_probes, pair=pair)
    return res, evidence
