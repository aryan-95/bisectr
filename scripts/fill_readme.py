"""Replace the TODO(measure) results table in README.md with real numbers from eval/results.csv."""
import csv, collections, subprocess, sys, yaml

table = subprocess.check_output([sys.executable, "eval/report.py", "eval/results.csv"], text=True).strip()
rows = list(csv.DictReader(open("eval/results.csv")))
gate = collections.Counter(r["scenario"] for r in rows if r["kind"] == "gate")
bis = collections.Counter(r["scenario"] for r in rows if r["kind"] == "bisect")
mode = yaml.safe_load(open("bisectr.yaml"))["cost"]["on_cost_regression"]
note = (f"\n\n_Measured on AWS Fargate (ap-south-1): {max(gate.values())} gate trials per scenario "
        f"({len(gate)} scenarios incl. one noise-only control), {max(bis.values()) if bis else 0} bisect trial(s) per "
        f"regression scenario on a synthetic 12-commit history, `on_cost_regression: {mode}` for this run. "
        f"The cost figure is an upper bound (all tasks x full wall time) at US East list prices. "
        f"Raw rows: `eval/results.csv`._")

lines = open("README.md").read().split("\n")
start = next((i for i, l in enumerate(lines) if l.startswith("| Metric | Result |")), None)
if start is None:
    sys.exit("could not find the '| Metric | Result |' table in README.md")
end = start
while end < len(lines) and lines[end].startswith("|"):
    end += 1
lines[start:end] = (table + note).split("\n")
open("README.md", "w").write("\n".join(lines))
print("README.md table updated:\n")
print(table)
