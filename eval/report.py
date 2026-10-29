import csv, statistics as st, sys

rows = list(csv.DictReader(open(sys.argv[1] if len(sys.argv) > 1 else "eval/results.csv")))
g = [r for r in rows if r["kind"] == "gate"]
b = [r for r in rows if r["kind"] == "bisect"]
reg = [r for r in g if r["scenario"] != "control_noise_only"]
ctl = [r for r in g if r["scenario"] == "control_noise_only"]
cost = [r for r in reg if r["scenario"] in ("cpu_hot_loop", "payload_bloat")]
med = lambda xs: round(st.median(xs), 2) if xs else "n/a"
cnt = lambda rs, k: sum(r["outcome"] == k for r in rs)
rate = lambda numerator, denominator: (
    f"{numerator}/{denominator} ({numerator / denominator:.1%})"
    if denominator else "n/a"
)

print("| Metric | Result |\n|---|---|")
print(f"| Gate: regressions detected (excluding control) | {rate(cnt(reg,'FAIL'),len(reg))} |")
print(f"| Gate: false-positive rate on noise-only control | {rate(cnt(ctl,'FAIL'),len(ctl))} |")
print(f"| Gate: cost regressions detected (cpu_hot_loop, payload_bloat) | {sum(r['cost_flag']=='True' for r in cost)}/{len(cost)} |")
print(f"| Bisect: exact culprit found | {rate(cnt(b,'found'),len(b))} |")
print(f"| Bisect: wrong-culprit rate | {rate(cnt(b,'wrong_culprit'),len(b))} |")
print(f"| Bisect: ambiguous or flaky reported | {cnt(b,'ambiguous')+cnt(b,'flaky')}/{len(b)} |")
print(f"| Median wall time per gate run (s) | {med([float(r['wall_s']) for r in g])} |")
print(f"| Median tasks per bisect | {med([int(r['tasks']) for r in b])} |")
costs = [float(r["est_usd"]) for r in g]
priced = bool(costs) and any(value > 0 for value in costs)
print(f"| Median estimated Fargate cost per gate run (USD) | {med(costs) if priced else 'not priced'} |")
print(f"| Estimated Fargate cost across gate runs (USD) | {round(sum(costs), 2) if priced else 'not priced'} |")
