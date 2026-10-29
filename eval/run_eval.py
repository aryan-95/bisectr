"""Runs gate and bisect trials on AWS and appends real rows to results.csv.
Bisect history is synthetic: commit i < culprit runs clean, commit i >= culprit has the
regression injected through the REGRESSION env var (same image, so no per-commit builds)."""
import argparse, csv, os, random, sys, time
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
    ap.add_argument("--seed", type=int, default=20261029)
    ap.add_argument("--out", default="eval/results.csv")
    ap.add_argument(
        "--resume", action="store_true",
        help="Skip trials already present in --out; use only with the same image, config, scenarios, and seed",
    )
    a = ap.parse_args()
    if a.trials <= 0 or a.bisect_trials <= 0:
        raise ValueError("--trials and --bisect-trials must be greater than zero")

    cfg = load(a.config)
    sc = yaml.safe_load(open(a.scenarios))
    if not sc.get("scenarios") or not isinstance(sc.get("commits"), int) or sc["commits"] < 2:
        raise ValueError("scenario file must define scenarios and commits >= 2")
    completed = set()
    if a.resume:
        if not os.path.exists(a.out):
            raise ValueError(f"Cannot resume: output file does not exist: {a.out}")
        scenario_names = {scenario["name"] for scenario in sc["scenarios"]}
        with open(a.out, newline="") as existing_file:
            reader = csv.DictReader(existing_file)
            if reader.fieldnames != FIELDS:
                raise ValueError(f"Cannot resume: {a.out} has an unexpected CSV header")
            for row in reader:
                kind, scenario, trial = row["kind"], row["scenario"], int(row["trial"])
                if scenario not in scenario_names:
                    raise ValueError(
                        f"Cannot resume: unknown scenario in existing results: {scenario}"
                    )
                if kind not in {"gate", "bisect"} or trial < 0:
                    raise ValueError(
                        f"Cannot resume: invalid evaluation trial in existing results: {row}"
                    )
                max_trial = a.trials if kind == "gate" else a.bisect_trials
                if trial >= max_trial:
                    raise ValueError(
                        f"Cannot resume: trial {trial} is outside the requested {kind} trial count"
                    )
                key = (kind, scenario, trial)
                if key in completed:
                    raise ValueError(f"Cannot resume: duplicate trial in existing results: {key}")
                completed.add(key)
        print(
            "Resuming existing results; confirm image, config, scenarios, and seed match the "
            "original run.",
            file=sys.stderr,
            flush=True,
        )
    image = a.image if ":" in a.image else f"{cfg.infra.image_repo}:{a.image}"
    rate = cfg.task.cpu / 1024 * cfg.pricing.vcpu_hour + cfg.task.memory / 1024 * cfg.pricing.gb_hour
    if rate <= 0:
        raise ValueError(
            "Set non-zero pricing.vcpu_hour and pricing.gb_hour in bisectr.yaml "
            "before collecting dollar cost estimates."
        )
    rng = random.Random(a.seed)

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    new = not os.path.exists(a.out)
    f = open(a.out, "a", newline="")
    w = csv.DictWriter(f, FIELDS)
    if new:
        w.writeheader()
    print(f"Evaluation seed: {a.seed}; output: {a.out}", flush=True)

    def emit(**row):
        row["est_usd"] = round(row["tasks"] * row["wall_s"] / 3600 * rate, 4)
        w.writerow(row); f.flush(); print(row)

    for s in sc["scenarios"]:
        control = not s["env"]
        for t in range(a.trials):
            if ("gate", s["name"], t) in completed:
                continue
            t0, n0 = time.time(), probe.TASKS_LAUNCHED
            res = run_gate(cfg, (image, s["env"]), (image, {}), use_cache=False)
            exp = "PASS" if control else "FAIL"
            emit(kind="gate", scenario=s["name"], trial=t, expected=exp, outcome=res["verdict"],
                 correct=res["verdict"] == exp, cost_flag=res["cost"]["regression"],
                 wall_s=round(time.time() - t0, 1), tasks=probe.TASKS_LAUNCHED - n0)
        if control:
            continue
        for t in range(a.bisect_trials):
            if ("bisect", s["name"], t) in completed:
                continue
            n = sc["commits"]
            culprit = rng.randint(1, n - 1)
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
