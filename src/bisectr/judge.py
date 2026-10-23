from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from scipy.stats import mannwhitneyu


@dataclass
class Rep:
    lat: np.ndarray
    errors: int
    n: int
    cpu: float | None
    mem: float

    @property
    def err_rate(self) -> float:
        return self.errors / self.n if self.n else 1.0

    @classmethod
    def from_dict(cls, d: dict) -> "Rep":
        return cls(np.asarray(d["latencies_ms"], dtype=float), d["errors"], d["n"],
                   d.get("cpu_s_per_req"), d.get("peak_mem_mb", 0.0))


def p95(a) -> float:
    return float(np.percentile(a, 95)) if len(a) else float("inf")


def judge(base: list[Rep], cand: list[Rep], th) -> dict:
    """Decision rule: significant AND material AND replicas agree. Returns details."""
    b = np.concatenate([r.lat for r in base])
    c = np.concatenate([r.lat for r in cand])
    ratio = p95(c) / max(p95(b), 1e-6)
    p = float(mannwhitneyu(c, b, alternative="greater").pvalue)
    base_med = float(np.median([p95(r.lat) for r in base]))
    agree = int(sum(p95(r.lat) / max(base_med, 1e-6) >= th.min_ratio for r in cand))
    err_delta = float(np.mean([r.err_rate for r in cand]) - np.mean([r.err_rate for r in base]))

    if err_delta > th.error_abs:
        v = "bad"
    elif p < th.alpha and ratio >= th.min_ratio and agree >= th.min_agree:
        v = "bad"
    elif ratio < 1 + (th.min_ratio - 1) / 2:
        v = "good"
    else:
        v = "inconclusive"
    return {"verdict": v, "ratio": float(ratio), "p": p, "agree": agree, "err_delta": err_delta}


def summarize(reps: list[Rep]) -> dict:
    allv = np.concatenate([r.lat for r in reps])
    cpus = [r.cpu for r in reps if r.cpu is not None]
    return {
        "p95": p95(allv),
        "err": float(np.mean([r.err_rate for r in reps])),
        "cpu_per_1000": float(np.median(cpus) * 1000) if cpus else None,
        "mem_mb": float(np.median([r.mem for r in reps])),
    }
