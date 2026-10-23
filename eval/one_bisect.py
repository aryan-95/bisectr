"""Run ONE synthetic bisect trial and print every probe next to the ground truth.
usage: python eval/one_bisect.py --image SHA --scenario payload_bloat --culprit 10 [--commits 12]"""
import argparse, yaml
from bisectr import probe, report
from bisectr.bisect import run_bisect
from bisectr.config import load

ap = argparse.ArgumentParser()
ap.add_argument("--image", required=True)
ap.add_argument("--scenario", required=True)
ap.add_argument("--culprit", type=int, required=True)
ap.add_argument("--commits", type=int, default=12)
ap.add_argument("--config", default="bisectr.yaml")
a = ap.parse_args()

cfg = load(a.config)
scen = {s["name"]: s for s in yaml.safe_load(open("eval/scenarios.yaml"))["scenarios"]}[a.scenario]
image = a.image if ":" in a.image else f"{cfg.infra.image_repo}:{a.image}"
tag = image.split(":", 1)[1]
if not probe.image_exists(cfg, tag):
    raise SystemExit(f"No image tagged {tag} in ECR. Commit your changes, then run ./scripts/push_images.sh")
targets = [(image, {} if i < a.culprit else scen["env"]) for i in range(a.commits)]

res, ev = run_bisect(cfg, targets)
print(report.bisect_markdown(res, [f"commit{i}" for i in range(a.commits)], ev))
print(f"\nresult: {res.kind}  culprit={res.culprit}  window={res.window}  | expected culprit: commit{a.culprit}")
print("\nevery probe vs ground truth:")
for e in ev:
    kind = "pair" if "pair_vs" in e else ("retry" if e.get("retry") else ("confirm" if e.get("confirm") else "probe"))
    truth = "BAD" if e["index"] >= a.culprit else "clean"
    flag = "   <-- MISJUDGED" if (truth == "BAD") != (e["verdict"] == "bad") and e["verdict"] in ("bad", "good") else ""
    print(f"commit{e['index']:>2} truth={truth:5} {kind:7} -> {e['verdict']:12} "
          f"ratio={e['ratio']:.2f} delta={e.get('delta_ms', float('nan')):.1f}ms agree={e['agree']}{flag}")
print(f"\ntasks launched: {probe.TASKS_LAUNCHED}")
