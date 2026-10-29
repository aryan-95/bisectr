"""Replace the README results table with measurements from the selected CSV."""
import csv, collections, subprocess, sys, yaml

results_path = sys.argv[1] if len(sys.argv) > 1 else "eval/results.csv"
table = subprocess.check_output([sys.executable, "eval/report.py", results_path], text=True).strip()
rows = list(csv.DictReader(open(results_path)))
gate = collections.Counter(r["scenario"] for r in rows if r["kind"] == "gate")
bis = collections.Counter(r["scenario"] for r in rows if r["kind"] == "bisect")
cfg = yaml.safe_load(open("bisectr.yaml"))
mode = cfg["cost"]["on_cost_regression"]
region = cfg["infra"]["region"]
note = (f"\n\n_Measured on AWS Fargate ({region}): {max(gate.values())} gate trials per scenario "
        f"({len(gate)} scenarios incl. one noise-only control), {max(bis.values()) if bis else 0} bisect trial(s) per "
        f"regression scenario on a synthetic 12-commit history, `on_cost_regression: {mode}` for this run. "
        f"Costs are estimates from all launched tasks x wall time using configured Fargate vCPU/memory rates; "
        f"they exclude public IPv4, CloudWatch, transfer, and other charges. Raw rows: `{results_path}`._")

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
