from __future__ import annotations
from . import store
from .cost import cost_report
from .guardrails import check_enabled
from .judge import Rep, judge, summarize
from .probe import measure_many
from .judge import p95


def _reps(raw):
    return [Rep.from_dict(d) for d in raw]


def _replica_summaries(reps):
    return [
        {
            "p95": p95(rep.lat),
            "error_rate": rep.err_rate,
            "cpu_s_per_req": rep.cpu,
            "peak_mem_mb": rep.mem,
        }
        for rep in reps
    ]


def run_gate(cfg, cand, base, use_cache=True) -> dict:
    """cand/base are (image, env) tuples. Baseline and candidate probes launch together."""
    check_enabled(cfg)
    cached = store.load(cfg, *base) if use_cache else None
    specs = {"cand": cand}
    if cached is None:
        specs["base"] = base
    raw = measure_many(cfg, specs)
    base_raw = cached if cached is not None else raw["base"]
    if cached is None and use_cache:
        store.save(cfg, *base, base_raw)
    cand_raw = raw["cand"]

    detail = judge(_reps(base_raw), _reps(cand_raw), cfg.thresholds)
    reprobed = False
    if detail["verdict"] == "inconclusive":            # one longer re-probe, both sides
        reprobed = True
        raw2 = measure_many(cfg.scaled(2.0), {"cand": cand, "base": base})
        base_raw, cand_raw = raw2["base"], raw2["cand"]
        detail = judge(_reps(base_raw), _reps(cand_raw), cfg.thresholds)

    base_reps, cand_reps = _reps(base_raw), _reps(cand_raw)
    cost = cost_report(cfg, base_reps, cand_reps)

    reasons = []
    if detail["verdict"] == "bad":
        reasons.append("errors" if detail["err_delta"] > cfg.thresholds.error_abs else "latency")
    verdict = {"bad": "FAIL", "good": "PASS", "inconclusive": "WARN"}[detail["verdict"]]
    if cost["regression"]:
        reasons.append("cost")
        if cfg.cost.on_cost_regression == "fail":
            verdict = "FAIL"
        elif verdict == "PASS":
            verdict = "WARN"

    return {"verdict": verdict, "reasons": reasons, "detail": detail, "cost": cost,
            "base": summarize(base_reps), "cand": summarize(cand_reps),
            "base_replicas": _replica_summaries(base_reps),
            "cand_replicas": _replica_summaries(cand_reps),
            "reprobed": reprobed, "replicas": cfg.replicas}
