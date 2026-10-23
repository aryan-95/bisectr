import json, subprocess, yaml

out = json.loads(subprocess.check_output(
    ["terraform", "-chdir=infra/envs/dev", "output", "-json"]))
v = lambda k: out[k]["value"]

cfg = {
    "service": "bisectr-demo",
    "port": 8000,
    "task": {"cpu": 1024, "memory": 2048, "app_cpu": 512},
    "scenario": {
        "rps": 20, "seconds": 30, "warmup_seconds": 5,
        "endpoints": [{"path": "/users", "weight": 3}, {"path": "/orders", "weight": 2}],
    },
    "thresholds": {"alpha": 0.01, "min_ratio": 1.25, "min_agree": 2,
                   "error_abs": 0.02, "cost_min_ratio": 1.15},
    "cost": {"target_rps": 500, "target_utilization": 0.6, "on_cost_regression": "warn"},
    "pricing": {"vcpu_hour": 0.0, "gb_hour": 0.0},   # SET FROM AWS PRICING PAGE
    "replicas": 3,
    "max_probes": 24,
    "bisect_k": 3,
    "infra": {
        "region": v("region"), "cluster": v("cluster"), "log_group": v("log_group"),
        "exec_role": v("exec_role"), "sg": v("sg"), "subnets": v("subnets"),
        "image_repo": v("svc_repo"), "runner_image": v("runner_repo") + ":latest",
    },
}
yaml.safe_dump(cfg, open("bisectr.yaml", "w"), sort_keys=False)
print("wrote bisectr.yaml. Now set pricing.vcpu_hour and pricing.gb_hour from the AWS Fargate pricing page for your region.")
