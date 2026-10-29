import json, pathlib, subprocess, yaml

pricing = {"vcpu_hour": 0.0, "gb_hour": 0.0}
config_path = pathlib.Path("bisectr.yaml")
existing_config = {}
if config_path.exists():
    loaded = yaml.safe_load(config_path.read_text()) or {}
    if isinstance(loaded, dict):
        existing_config = loaded
        if isinstance(existing_config.get("pricing"), dict):
            pricing.update(existing_config["pricing"])

out = json.loads(subprocess.check_output(
    ["terraform", "-chdir=infra/envs/dev", "output", "-json"]))
v = lambda k: out[k]["value"]

cfg = {
    "service": "bisectr-demo",
    "port": 8000,
    "health_path": "/health",
    "task": {"cpu": 1024, "memory": 2048, "app_cpu": 512},
    "scenario": {
        "rps": 20, "seconds": 30, "warmup_seconds": 5,
        "endpoints": [{"path": "/users", "weight": 3}, {"path": "/orders", "weight": 2}],
    },
    "thresholds": {"alpha": 0.01, "min_ratio": 1.25, "min_agree": 2,
                   "error_abs": 0.02, "cost_min_ratio": 1.15},
    "cost": {"target_rps": 500, "target_utilization": 0.6, "on_cost_regression": "warn"},
    "pricing": pricing,
    "replicas": 3,
    "max_probes": 24,
    "bisect_k": 3,
    "infra": {
        "region": v("region"), "cluster": v("cluster"), "log_group": v("log_group"),
        "exec_role": v("exec_role"), "sg": v("sg"), "subnets": v("subnets"),
        "image_repo": v("svc_repo"), "runner_image": v("runner_repo") + ":latest",
        "runs_table": v("runs_table"), "baseline_table": v("baseline_table"),
        "reports_bucket": v("reports_bucket"),
        "budget_name": v("budget_name"),
    },
}
for key in (
    "service", "port", "health_path", "task", "scenario", "scenarios", "thresholds",
    "cost", "replicas", "max_probes", "bisect_k", "max_parallel_tasks",
):
    if key in existing_config:
        cfg[key] = existing_config[key]
config_path.write_text(yaml.safe_dump(cfg, sort_keys=False))
print("wrote bisectr.yaml. Existing workload, threshold, task, and pricing settings were preserved.")
