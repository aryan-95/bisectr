from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from scipy.stats import mannwhitneyu


@dataclass
class Rep:
    lat: np.ndarray
    errors: int
    n: int
    cpu: float | None
    mem: float
    endpoint_metrics: dict = field(default_factory=dict)

    @property
    def err_rate(self) -> float:
        return self.errors / self.n if self.n else 1.0

    @classmethod
    def from_dict(cls, d: dict) -> "Rep":
        return cls(np.asarray(d["latencies_ms"], dtype=float), d["errors"], d["n"],
                   d.get("cpu_s_per_req"), d.get("peak_mem_mb", 0.0),
                   {
                       key: {
                           "lat": np.asarray(value.get("latencies_ms", []), dtype=float),
                           "errors": int(value.get("errors", 0)),
                           "n": int(value.get("n", 0)),
                       }
                       for key, value in d.get("endpoint_metrics", {}).items()
                   })


def p95(a) -> float:
    return float(np.percentile(a, 95)) if len(a) else float("inf")


def judge(base: list[Rep], cand: list[Rep], th, endpoints=()) -> dict:
    """Decision rule: significant AND material AND replicas agree. Returns details."""
    b = np.concatenate([r.lat for r in base])
    c = np.concatenate([r.lat for r in cand])
    ratio = p95(c) / max(p95(b), 1e-6)
    p = float(mannwhitneyu(c, b, alternative="greater").pvalue)
    delta = p95(c) - p95(b)
    base_med = float(np.median([p95(r.lat) for r in base]))
    agree = int(sum(p95(r.lat) / max(base_med, 1e-6) >= th.min_ratio for r in cand))
    err_delta = float(np.mean([r.err_rate for r in cand]) - np.mean([r.err_rate for r in base]))

    if err_delta > th.error_abs:
        v = "bad"
    elif p < th.alpha and ratio >= th.min_ratio and agree >= th.min_agree and delta >= th.min_delta_ms:
        v = "bad"
    elif ratio < 1 + (th.min_ratio - 1) / 2 or delta < th.min_delta_ms:
        v = "good"
    else:
        v = "inconclusive"
    endpoint_results = []
    # Older runner result records contain only aggregate samples. Keep those
    # readable; new runner records include endpoint_metrics and enable budgets.
    if not any(rep.endpoint_metrics for rep in [*base, *cand]):
        endpoints = ()
    for endpoint in endpoints:
        key = f"{endpoint.method} {endpoint.path}"
        base_samples = [r.endpoint_metrics[key]["lat"] for r in base
                        if key in r.endpoint_metrics and len(r.endpoint_metrics[key]["lat"])]
        cand_samples = [r.endpoint_metrics[key]["lat"] for r in cand
                        if key in r.endpoint_metrics and len(r.endpoint_metrics[key]["lat"])]
        base_count = sum(len(samples) for samples in base_samples)
        cand_count = sum(len(samples) for samples in cand_samples)
        min_samples = max(10, th.min_agree * 2)
        if base_count < min_samples or cand_count < min_samples:
            endpoint_results.append({
                "endpoint": key,
                "verdict": "insufficient_samples",
                "base_samples": base_count,
                "cand_samples": cand_count,
                "required_samples": min_samples,
            })
            continue

        base_p95s = [p95(samples) for samples in base_samples]
        cand_p95s = [p95(samples) for samples in cand_samples]
        endpoint_base = np.concatenate(base_samples)
        endpoint_cand = np.concatenate(cand_samples)
        endpoint_ratio = p95(endpoint_cand) / max(p95(endpoint_base), 1e-6)
        endpoint_delta = p95(endpoint_cand) - p95(endpoint_base)
        endpoint_p = float(mannwhitneyu(
            endpoint_cand, endpoint_base, alternative="greater"
        ).pvalue)
        ratio_budget = endpoint.max_p95_ratio or th.min_ratio
        error_budget = endpoint.max_error_delta
        if error_budget is None:
            error_budget = th.error_abs
        base_endpoint_error = [
            r.endpoint_metrics[key]["errors"] / r.endpoint_metrics[key]["n"]
            for r in base if key in r.endpoint_metrics and r.endpoint_metrics[key]["n"]
        ]
        cand_endpoint_error = [
            r.endpoint_metrics[key]["errors"] / r.endpoint_metrics[key]["n"]
            for r in cand if key in r.endpoint_metrics and r.endpoint_metrics[key]["n"]
        ]
        endpoint_err_delta = (
            float(np.mean(cand_endpoint_error) - np.mean(base_endpoint_error))
            if base_endpoint_error and cand_endpoint_error else 0.0
        )
        endpoint_agree = sum(
            value >= np.median(base_p95s) * ratio_budget for value in cand_p95s
        )
        if endpoint_err_delta > error_budget:
            endpoint_verdict = "bad"
        elif (endpoint_p < th.alpha and endpoint_ratio >= ratio_budget
              and endpoint_agree >= th.min_agree and endpoint_delta >= th.min_delta_ms):
            endpoint_verdict = "bad"
        elif (endpoint_ratio < 1 + (ratio_budget - 1) / 2
              or endpoint_delta < th.min_delta_ms):
            endpoint_verdict = "good"
        else:
            endpoint_verdict = "inconclusive"
        endpoint_results.append({
            "endpoint": key,
            "verdict": endpoint_verdict,
            "base_p95_ms": float(p95(endpoint_base)),
            "cand_p95_ms": float(p95(endpoint_cand)),
            "p95_ratio": float(endpoint_ratio),
            "p95_delta_ms": float(endpoint_delta),
            "p": endpoint_p,
            "agree": endpoint_agree,
            "base_error_rate": float(np.mean(base_endpoint_error)) if base_endpoint_error else 0.0,
            "cand_error_rate": float(np.mean(cand_endpoint_error)) if cand_endpoint_error else 0.0,
            "error_delta": endpoint_err_delta,
            "max_p95_ratio": ratio_budget,
            "max_error_delta": error_budget,
        })

    if any(item["verdict"] == "bad" for item in endpoint_results):
        v = "bad"
    elif v == "good" and any(
        item["verdict"] in {"inconclusive", "insufficient_samples"}
        for item in endpoint_results
    ):
        v = "inconclusive"
    return {"verdict": v, "ratio": float(ratio), "p": p, "agree": agree, "err_delta": err_delta,
            "delta_ms": float(delta), "endpoints": endpoint_results}


def summarize(reps: list[Rep]) -> dict:
    allv = np.concatenate([r.lat for r in reps])
    cpus = [r.cpu for r in reps if r.cpu is not None]
    return {
        "p95": p95(allv),
        "latency_quantiles_ms": {
            f"p{quantile}": float(np.percentile(allv, quantile))
            for quantile in (50, 90, 95, 99)
        },
        "err": float(np.mean([r.err_rate for r in reps])),
        "cpu_per_1000": float(np.median(cpus) * 1000) if cpus else None,
        "mem_mb": float(max(r.mem for r in reps)),
    }
