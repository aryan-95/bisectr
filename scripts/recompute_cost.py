"""Recompute est_usd in eval/results.csv from the pricing currently in bisectr.yaml."""
import csv, shutil, yaml

cfg = yaml.safe_load(open("bisectr.yaml"))
p, t = cfg["pricing"], cfg["task"]
rate = t["cpu"] / 1024 * p["vcpu_hour"] + t["memory"] / 1024 * p["gb_hour"]
print("USD per task-hour:", round(rate, 5))
shutil.copy("eval/results.csv", "eval/results.csv.bak")
rows = list(csv.DictReader(open("eval/results.csv")))
for r in rows:
    r["est_usd"] = round(int(r["tasks"]) * float(r["wall_s"]) / 3600 * rate, 4)
with open("eval/results.csv", "w", newline="") as f:
    w = csv.DictWriter(f, rows[0].keys())
    w.writeheader()
    w.writerows(rows)
print(f"rewrote {len(rows)} rows (backup: eval/results.csv.bak); max est_usd now {max(r['est_usd'] for r in rows)}")
