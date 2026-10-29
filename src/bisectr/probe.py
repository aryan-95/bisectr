"""Register task definitions, launch Fargate probes, read results from CloudWatch Logs."""
from __future__ import annotations
import json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

TASKS_LAUNCHED = 0
_lock = threading.Lock()
_ACTIVE = set()          # ARNs of probe tasks currently running (stopped on Ctrl+C)


@lru_cache(maxsize=None)
def _ecs(region): return boto3.client("ecs", region_name=region)
@lru_cache(maxsize=None)
def _logs(region): return boto3.client("logs", region_name=region)
@lru_cache(maxsize=None)
def _ecr(region): return boto3.client("ecr", region_name=region)


def image_exists(cfg, tag: str) -> bool:
    repo = cfg.infra.image_repo.split("/", 1)[1]
    try:
        _ecr(cfg.infra.region).describe_images(repositoryName=repo, imageIds=[{"imageTag": tag}])
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"ImageNotFoundException", "RepositoryNotFoundException"}:
            return False
        raise


def register(cfg, image: str, env: dict | None = None) -> str:
    i = cfg.infra

    def log(prefix):
        return {"logDriver": "awslogs", "options": {
            "awslogs-group": i.log_group, "awslogs-region": i.region,
            "awslogs-stream-prefix": prefix}}

    runner_env = [
        {"name": "PORT", "value": str(cfg.port)},
        {"name": "HEALTH_PATH", "value": cfg.health_path},
        {"name": "RPS", "value": str(cfg.scenario.rps)},
        {"name": "SECONDS", "value": str(cfg.scenario.seconds)},
        {"name": "WARMUP", "value": str(cfg.scenario.warmup_seconds)},
        {"name": "ENDPOINTS", "value": json.dumps(
            [endpoint.model_dump(exclude_defaults=True) for endpoint in cfg.scenario.endpoints])},
    ]
    app_env = [{"name": k, "value": v} for k, v in (env or {}).items()]
    resp = _ecs(i.region).register_task_definition(
        family="bisectr-probe",
        networkMode="awsvpc",
        requiresCompatibilities=["FARGATE"],
        runtimePlatform={"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
        cpu=str(cfg.task.cpu), memory=str(cfg.task.memory),
        executionRoleArn=i.exec_role,                 # deliberately NO taskRoleArn
        containerDefinitions=[
            {"name": "app", "image": image, "cpu": cfg.task.app_cpu, "essential": False,
             "portMappings": [{"containerPort": cfg.port}],
             "environment": app_env, "logConfiguration": log("app")},
            {"name": "runner", "image": i.runner_image, "cpu": 256, "essential": True,
             "dependsOn": [{"containerName": "app", "condition": "START"}],
             "environment": runner_env, "logConfiguration": log("runner")},
        ],
    )
    return resp["taskDefinition"]["taskDefinitionArn"]


def launch(cfg, task_def: str) -> str:
    global TASKS_LAUNCHED
    i = cfg.infra
    for _ in range(40):                  # quota/capacity: wait for other tasks to finish (max ~10 min)
        r = _ecs(i.region).run_task(
            cluster=i.cluster, taskDefinition=task_def, launchType="FARGATE", count=1,
            networkConfiguration={"awsvpcConfiguration": {
                "subnets": i.subnets, "securityGroups": [i.sg], "assignPublicIp": "ENABLED"}})
        if not r["failures"]:
            break
        reason = str(r["failures"])
        if "vCPUs" not in reason and "capacity" not in reason.lower():
            raise RuntimeError(f"run_task failed: {r['failures']}")
        time.sleep(15)
    else:
        raise RuntimeError(f"run_task still failing after retries: {r['failures']}")
    arn = r["tasks"][0]["taskArn"]
    with _lock:
        TASKS_LAUNCHED += 1
        _ACTIVE.add(arn)
    return arn


def wait_and_read(cfg, arn: str) -> dict:
    i = cfg.infra
    ecs, logs = _ecs(i.region), _logs(i.region)
    attempts = int((cfg.scenario.seconds + cfg.scenario.warmup_seconds + 420) / 10)
    ecs.get_waiter("tasks_stopped").wait(
        cluster=i.cluster, tasks=[arn], WaiterConfig={"Delay": 10, "MaxAttempts": attempts})
    stream = f"runner/runner/{arn.split('/')[-1]}"
    marker = "BISECTR_RESULT "
    for _ in range(12):                      # CloudWatch lags a few seconds
        try:
            events = logs.get_log_events(
                logGroupName=i.log_group, logStreamName=stream, startFromHead=True)["events"]
            # join: long lines can be split into several events by the log driver
            text = "".join(e["message"] for e in events)
            k = text.find(marker)
            if k >= 0:
                obj, _ = json.JSONDecoder().raw_decode(text[k + len(marker):])
                return obj
        except logs.exceptions.ResourceNotFoundException:
            pass
        time.sleep(3)
    t = ecs.describe_tasks(cluster=i.cluster, tasks=[arn])["tasks"][0]
    raise RuntimeError(f"no result line; stoppedReason={t.get('stoppedReason')}")


def stop(cfg, arn: str) -> None:
    try:
        _ecs(cfg.infra.region).stop_task(cluster=cfg.infra.cluster, task=arn, reason="bisectr cleanup")
    except ClientError as exc:
        print(f"[bisectr] failed to stop probe task {arn}: {exc}", file=sys.stderr, flush=True)


def run_one(cfg, task_def: str) -> dict:
    arn = launch(cfg, task_def)
    try:
        return wait_and_read(cfg, arn)
    finally:
        stop(cfg, arn)
        with _lock:
            _ACTIVE.discard(arn)


def measure_many(cfg, specs: dict) -> dict:
    """specs: {name: (image, env)}. Launches replicas for every spec at the same time.
    Returns {name: [raw_result_dict, ...]}."""
    tds = {n: register(cfg, img, env) for n, (img, env) in specs.items()}
    out = {n: [] for n in specs}
    workers = max(1, len(specs) * cfg.replicas)
    sem = threading.Semaphore(max(1, cfg.max_parallel_tasks))

    def guarded(td):
        with sem:                      # never exceed the Fargate vCPU quota
            return run_one(cfg, td)

    total = len(specs) * cfg.replicas
    print(f"[bisectr] launching {total} probe tasks (max {cfg.max_parallel_tasks} at once)...",
          file=sys.stderr, flush=True)
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        futs = {ex.submit(guarded, td): n for n, td in tds.items() for _ in range(cfg.replicas)}
        done = 0
        for f in as_completed(futs):
            out[futs[f]].append(f.result())
            done += 1
            print(f"[bisectr]   {done}/{total} probe tasks finished", file=sys.stderr, flush=True)
    except BaseException:
        for arn in list(_ACTIVE):          # Ctrl+C or an error: never leave Fargate tasks running
            stop(cfg, arn)
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    ex.shutdown(wait=True)
    return out
