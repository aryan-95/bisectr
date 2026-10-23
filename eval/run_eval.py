"""Runs gate and bisect trials on AWS and appends real rows to results.csv.
Bisect history is synthetic: commit i < culprit runs clean, commit i >= culprit has the
regression injected through the REGRESSION env var (same image, so no per-commit builds)."""
import argparse, csv, os, random, time
import yaml
from bisectr.bisect import run_bisect
from bisectr.config import load
from bisectr.gate import run_gate
from bisectr import probe

FIELDS = ["kind", "scenario", "trial", "expected", "outcome", "correct",
          "cost_flag", "wall_s", "tasks", "est_usd"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="bisectr.yaml")
    ap.add_argument("--scenarios", default="eval/scenarios.yaml")
    ap.add_argument("--image", required=True)
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--bisect-trials", type=int, default=3)
    ap.add_argument("--out", default="eval/results.csv")
    a = ap.parse_args()

    cfg = load(a.config)
    sc = yaml.safe_load(open(a.scenarios))
    image = a.image if ":" in a.image else f"{cfg.infra.image_repo}:{a.image}"
    rate = cfg.task.cpu / 1024 * cfg.pricing.vcpu_hour + cfg.task.memory / 1024 * cfg.pricing.gb_hour

    new = not os.path.exists(a.out)
    f = open(a.out, "a", newline="")
    w = csv.DictWriter(f, FIELDS)
    if new:
        w.writeheader()

    def emit(**row):
        row["est_usd"] = round(row["tasks"] * row["wall_s"] / 3600 * rate, 4)
        w.writerow(row); f.flush(); print(row)

    for s in sc["scenarios"]:
        control = not s["env"]
        for t in range(a.trials):                                   # gate trials
            t0, n0 = time.time(), probe.TASKS_LAUNCHED
            res = run_gate(cfg, (image, s["env"]), (image, {}), use_cache=False)
            exp = "PASS" if control else "FAIL"
            emit(kind="gate", scenario=s["name"], trial=t, expected=exp, outcome=res["verdict"],
                 correct=res["verdict"] == exp, cost_flag=res["cost"]["regression"],
                 wall_s=round(time.time() - t0, 1), tasks=probe.TASKS_LAUNCHED - n0)
        if control:
            continue
        for t in range(a.bisect_trials):                            # bisect trials
            n = sc["commits"]
            culprit = random.randint(1, n - 1)
            targets = [(image, {} if i < culprit else s["env"]) for i in range(n)]
            t0, n0 = time.time(), probe.TASKS_LAUNCHED
            r, _ = run_bisect(cfg, targets)
            outcome = "wrong_culprit" if r.kind == "found" and r.culprit != culprit else r.kind
            emit(kind="bisect", scenario=s["name"], trial=t, expected=f"found@{culprit}",
                 outcome=outcome, correct=outcome == "found", cost_flag="",
                 wall_s=round(time.time() - t0, 1), tasks=probe.TASKS_LAUNCHED - n0)
    f.close()


if __name__ == "__main__":
    main()
