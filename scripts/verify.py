"""One-shot verification. Usage: python scripts/verify.py [--local]   (--local skips AWS checks)"""
import csv, json, pathlib, subprocess, sys
import yaml

LOCAL = "--local" in sys.argv
tags = []


def check(name, ok, detail="", warn=False):
    tag = "PASS" if ok else ("WARN" if warn else "FAIL")
    tags.append(tag)
    print(f"[{tag}] {name}" + (f"  -> {detail}" if detail else ""))


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


print("== 1. Code ==")
rc, out = sh("python -m pytest -q 2>&1 | tail -3")
check("unit + property tests", rc == 0 and "passed" in out and "failed" not in out, out.splitlines()[-1] if out else "")
required = ["src/bisectr/cli.py", "src/bisectr/probe.py", "src/bisectr/judge.py", "src/bisectr/bisect.py",
            "src/bisectr/gate.py", "src/bisectr/report.py", "src/bisectr/cost.py", "runner/runner.py",
            "demo-app/main.py", "infra/envs/dev/main.tf", "infra/envs/dev/reaper.tf", "lambdas/reaper/handler.py",
            "eval/run_eval.py", "eval/results.csv", "docs/threat-model.md", "docs/runbook.md",
            "docs/adr/0001-no-task-role-probes.md", "action/action.yml", ".github/workflows/bisectr-gate.yml",
            ".github/workflows/bisectr-bisect.yml", ".github/workflows/build-main.yml", "README.md", "bisectr.yaml"]
missing = [p for p in required if not pathlib.Path(p).exists()]
check("required files present", not missing, f"missing: {missing}" if missing else f"{len(required)} files")

print("\n== 2. Config ==")
cfg = yaml.safe_load(open("bisectr.yaml")) if pathlib.Path("bisectr.yaml").exists() else {}
pr = cfg.get("pricing", {})
task = cfg.get("task", {"cpu": 1024, "memory": 2048})
hour = task["cpu"] / 1024 * pr.get("vcpu_hour", 0) + task["memory"] / 1024 * pr.get("gb_hour", 0)
check("pricing set and plausible (0.01-0.50 USD per task-hour)", 0.01 <= hour <= 0.5, f"{hour:.4f} USD/task-hour")
raw = open("bisectr.yaml").read() if cfg else ""
check("no unfilled placeholders in bisectr.yaml", "<" not in raw and "xxxx" not in raw)
wave = max(cfg.get("replicas", 3) * 2, cfg.get("replicas", 3) * cfg.get("bisect_k", 3))
check("one probe wave fits max_parallel_tasks", wave <= cfg.get("max_parallel_tasks", 6),
      f"wave={wave}, cap={cfg.get('max_parallel_tasks', 6)}")

print("\n== 3. Eval results ==")
rows = list(csv.DictReader(open("eval/results.csv"))) if pathlib.Path("eval/results.csv").exists() else []
rc, out = sh("pgrep -af 'run_eval.py' | grep -v pgrep")
check("eval finished (no run_eval.py process)", rc != 0, "still running, results incomplete" if rc == 0 else "")
if rows:
    g = [r for r in rows if r["kind"] == "gate"]
    b = [r for r in rows if r["kind"] == "bisect"]
    reg = [r for r in g if r["scenario"] != "control_noise_only"]
    ctl = [r for r in g if r["scenario"] == "control_noise_only"]
    sc = yaml.safe_load(open("eval/scenarios.yaml"))["scenarios"] if pathlib.Path("eval/scenarios.yaml").exists() else []
    seen = {r["scenario"] for r in g}
    check("every scenario has gate rows", all(s["name"] in seen for s in sc), f"seen: {sorted(seen)}")
    check("control rows exist", len(ctl) > 0, f"{len(ctl)} control trials")
    check("no false positives on control", all(r["outcome"] == "PASS" for r in ctl),
          f"{sum(r['outcome'] != 'PASS' for r in ctl)}/{len(ctl)} non-PASS")
    det = sum(r["outcome"] == "FAIL" for r in reg)
    check("regressions detected", det == len(reg), f"{det}/{len(reg)}", warn=True)
    check("no wrong culprit in bisect", all(r["outcome"] != "wrong_culprit" for r in b), f"{len(b)} bisect trials")
    found = sum(r["outcome"] == "found" for r in b)
    check("bisect found exact culprit", found == len(b), f"{found}/{len(b)} (ambiguous/flaky are safe but note them)", warn=True)
    mx = max(float(r["est_usd"]) for r in rows)
    check("est_usd column plausible (recompute after fixing pricing)", mx < 1.0, f"max row = {mx} USD")
else:
    check("results.csv has rows", False, "run `bisectr eval` first")

print("\n== 4. Docs ==")
for f in ["README.md", "eval/real_world.md"]:
    n = open(f).read().count("TODO(measure)") if pathlib.Path(f).exists() else 0
    check(f"{f}: no TODO(measure) left", n == 0, f"{n} left" if n else "", warn=True)
rc, out = sh("git status --porcelain")
check("git working tree committed", not out, f"{len(out.splitlines())} uncommitted files" if out else "", warn=True)
for f in ["eval/results.csv", "bisectr.yaml"]:
    rc, _ = sh(f"git ls-files --error-unmatch {f}")
    check(f"{f} tracked in git", rc == 0, warn=True)

if LOCAL:
    print("\n(--local: AWS checks skipped)")
else:
    import boto3
    from botocore.exceptions import ClientError
    i = cfg["infra"]
    region = i["region"]
    ecs, ecr, ssm = (boto3.client(s, region_name=region) for s in ("ecs", "ecr", "ssm"))
    print("\n== 5. AWS resources ==")
    try:
        who = boto3.client("sts").get_caller_identity()["Account"]
        check("AWS credentials work", True, f"account ending {who[-4:]}")
    except Exception as e:
        check("AWS credentials work", False, str(e)[:80]); who = None
    if who:
        c = ecs.describe_clusters(clusters=[i["cluster"]])["clusters"]
        check("ECS cluster ACTIVE", bool(c) and c[0]["status"] == "ACTIVE")
        n = len(ecs.list_tasks(cluster=i["cluster"])["taskArns"])
        check("no stray probe tasks running", n == 0, f"{n} running")
        for repo in ("bisectr-demo", "bisectr-runner"):
            try:
                cnt = len(ecr.describe_images(repositoryName=repo)["imageDetails"])
                check(f"ECR {repo} has images", cnt > 0, f"{cnt} images")
            except ClientError as e:
                check(f"ECR {repo} has images", False, str(e)[:60])
        try:
            v = ssm.get_parameter(Name="/bisectr/enabled")["Parameter"]["Value"]
            check("kill switch present and ON", v == "true", f"value={v}")
        except ClientError:
            check("kill switch present and ON", False, "parameter missing")
        try:
            boto3.client("lambda", region_name=region).get_function(FunctionName="bisectr-reaper")
            check("reaper Lambda deployed", True)
        except ClientError:
            check("reaper Lambda deployed", False, warn=True)
        try:
            q = boto3.client("service-quotas", region_name=region).get_service_quota(
                ServiceCode="fargate", QuotaCode="L-3032A538")["Quota"]["Value"]
            check("max_parallel_tasks within Fargate vCPU quota",
                  cfg.get("max_parallel_tasks", 6) * task["cpu"] / 1024 <= q, f"quota={q} vCPU")
        except ClientError:
            check("quota readable", False, warn=True)

        print("\n== 6. Security claims (the ones in your README) ==")
        try:
            td = ecs.describe_task_definition(taskDefinition="bisectr-probe")["taskDefinition"]
            check("probe task definition has NO task role", "taskRoleArn" not in td, "none attached" if "taskRoleArn" not in td else td["taskRoleArn"])
        except ClientError:
            check("probe task definition exists", False)
        ec2 = boto3.client("ec2", region_name=region)
        sg = ec2.describe_security_groups(GroupIds=[i["sg"]])["SecurityGroups"][0]
        check("probe security group has zero inbound rules", not sg["IpPermissions"], f"{len(sg['IpPermissions'])} inbound")
        eg = sg["IpPermissionsEgress"]
        ok = len(eg) == 1 and eg[0].get("FromPort") == 443 and eg[0].get("ToPort") == 443
        check("probe security group egress is 443 only", ok, json.dumps([(e.get('FromPort'), e.get('ToPort')) for e in eg]))

print(f"\nSUMMARY: {tags.count('PASS')} pass, {tags.count('WARN')} warn, {tags.count('FAIL')} fail")
sys.exit(1 if "FAIL" in tags else 0)
