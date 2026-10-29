"""Persist baseline results and run records locally or in configured AWS storage."""
from __future__ import annotations

import hashlib
import json
import pathlib
import time
import uuid

import boto3
from boto3.dynamodb.conditions import Key

CACHE = pathlib.Path(".bisectr_cache")
RUNS = pathlib.Path("runs")
CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
RUN_TTL_SECONDS = 90 * 24 * 60 * 60


def _path(cfg, image, env):
    sig = json.dumps({
        "image": image,
        "env": env or {},
        "scenario": cfg.scenario.model_dump(),
        "task": cfg.task.model_dump(),
        "port": cfg.port,
        "health_path": cfg.health_path,
        "replicas": cfg.replicas,
        "runner_image": cfg.infra.runner_image,
    }, sort_keys=True)
    return CACHE / (hashlib.sha256(sig.encode()).hexdigest() + ".json")


def _dynamodb(cfg):
    return boto3.resource("dynamodb", region_name=cfg.infra.region)


def _storage_configured(cfg):
    configured = (
        cfg.infra.runs_table,
        cfg.infra.baseline_table,
        cfg.infra.reports_bucket,
    )
    if any(configured) and not all(configured):
        raise ValueError(
            "Configure infra.runs_table, infra.baseline_table, and "
            "infra.reports_bucket together, or leave all three unset for local storage."
        )
    return all(configured)


def _local_or_cloud_table(cfg, name):
    _storage_configured(cfg)
    table_name = getattr(cfg.infra, name)
    if table_name:
        return _dynamodb(cfg).Table(table_name)
    return None


def load(cfg, image, env):
    table = _local_or_cloud_table(cfg, "baseline_table")
    if table:
        item = table.get_item(Key={"cache_key": _cache_key(cfg, image, env)}).get("Item")
        return json.loads(item["payload"]) if item else None
    path = _path(cfg, image, env)
    return json.loads(path.read_text()) if path.exists() else None


def save(cfg, image, env, raw):
    table = _local_or_cloud_table(cfg, "baseline_table")
    if table:
        table.put_item(Item={
            "cache_key": _cache_key(cfg, image, env),
            "payload": json.dumps(raw, default=_json_default),
            "expires_at": int(time.time()) + CACHE_TTL_SECONDS,
        })
        return
    CACHE.mkdir(exist_ok=True)
    _path(cfg, image, env).write_text(json.dumps(raw, default=_json_default))


def save_run(name, data, cfg=None, run_id=None):
    run_id = run_id or uuid.uuid4().hex
    table = _local_or_cloud_table(cfg, "runs_table") if cfg else None
    if table:
        table.put_item(Item={
            "run_id": run_id,
            "kind": name,
            "payload": json.dumps(data, indent=2, default=_json_default),
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + RUN_TTL_SECONDS,
        })
        return run_id

    RUNS.mkdir(exist_ok=True)
    path = RUNS / f"{name}-{run_id}.json"
    path.write_text(json.dumps(data, indent=2, default=_json_default))
    return path


def list_runs(cfg, kind=None, limit=20):
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    kinds = ("gate", "bisect", "validate") if kind is None else (kind,)
    if any(run_kind not in {"gate", "bisect", "validate"} for run_kind in kinds):
        raise ValueError("kind must be 'gate', 'bisect', 'validate', or None")

    table = _local_or_cloud_table(cfg, "runs_table")
    if table:
        runs = []
        for run_kind in kinds:
            response = table.query(
                IndexName="kind-created_at-index",
                KeyConditionExpression=Key("kind").eq(run_kind),
                Limit=limit,
                ScanIndexForward=False,
            )
            runs.extend(_cloud_run(item) for item in response.get("Items", []))
        return sorted(runs, key=lambda run: run["created_at"], reverse=True)[:limit]

    runs = []
    for path in RUNS.glob("*.json"):
        if not any(path.name.startswith(f"{run_kind}-") for run_kind in kinds):
            continue
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"Run record {path} must contain a JSON object")
        runs.append({
            "run_id": path.stem,
            "kind": path.name.split("-", 1)[0],
            "created_at": int(path.stat().st_mtime),
            "data": data,
        })
    return sorted(runs, key=lambda run: run["created_at"], reverse=True)[:limit]


def _cloud_run(item):
    payload = json.loads(item["payload"])
    if not isinstance(payload, dict):
        raise ValueError(f"Run record {item.get('run_id', '<unknown>')} must contain a JSON object")
    return {
        "run_id": item["run_id"],
        "kind": item["kind"],
        "created_at": int(item["created_at"]),
        "data": payload,
    }


def save_report(cfg, run_id, html):
    _storage_configured(cfg)
    bucket = cfg.infra.reports_bucket
    if not bucket:
        RUNS.mkdir(exist_ok=True)
        path = RUNS / f"{run_id}.html"
        path.write_text(html)
        return str(path)
    key = f"reports/{run_id}.html"
    boto3.client("s3", region_name=cfg.infra.region).put_object(
        Bucket=bucket,
        Key=key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        ServerSideEncryption="AES256",
    )
    return f"s3://{bucket}/{key}"


def _cache_key(cfg, image, env):
    return _path(cfg, image, env).stem


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
