from __future__ import annotations
import math
import numpy as np


def tasks_needed(rps: float, cpu_s_per_req: float, vcpu_per_task: float, util: float) -> int:
    return max(1, math.ceil(rps * cpu_s_per_req / (vcpu_per_task * util)))


def monthly(cfg, tasks: int) -> float:
    vcpu, gb = cfg.task.cpu / 1024, cfg.task.memory / 1024
    hourly = vcpu * cfg.pricing.vcpu_hour + gb * cfg.pricing.gb_hour
    return tasks * hourly * 730


def _med(reps):
    v = [r.cpu for r in reps if r.cpu is not None]
    return float(np.median(v)) if v else None


def cost_report(cfg, base, cand) -> dict:
    cb, cc = _med(base), _med(cand)
    if not cb or not cc:
        return {"regression": False, "available": False}
    vcpu = cfg.task.cpu / 1024
    tb = tasks_needed(cfg.cost.target_rps, cb, vcpu, cfg.cost.target_utilization)
    tc = tasks_needed(cfg.cost.target_rps, cc, vcpu, cfg.cost.target_utilization)
    ratio = cc / cb
    agree = sum((r.cpu or 0) / cb >= cfg.thresholds.cost_min_ratio for r in cand)
    mem_peak = max(r.mem for r in cand)
    return {
        "available": True,
        "cpu_ratio": ratio,
        "regression": bool(ratio >= cfg.thresholds.cost_min_ratio and agree >= cfg.thresholds.min_agree),
        "tasks_base": tb, "tasks_cand": tc,
        "monthly_base": monthly(cfg, tb), "monthly_cand": monthly(cfg, tc),
        "delta": monthly(cfg, tc) - monthly(cfg, tb),
        "needs_bigger_task": bool(mem_peak > cfg.task.memory * 0.8),   # fit check, not scaling
        "priced": cfg.pricing.vcpu_hour > 0,
    }
