"""Local baseline cache + run records (swap for DynamoDB/S3 later)."""
import hashlib, json, pathlib, time

CACHE = pathlib.Path(".bisectr_cache")
RUNS = pathlib.Path("runs")


def _path(cfg, image, env):
    sig = json.dumps({"i": image, "e": env or {}, "s": cfg.scenario.model_dump(),
                      "r": cfg.replicas, "t": cfg.task.model_dump()}, sort_keys=True)
    return CACHE / (hashlib.sha1(sig.encode()).hexdigest() + ".json")


def load(cfg, image, env):
    p = _path(cfg, image, env)
    return json.loads(p.read_text()) if p.exists() else None


def save(cfg, image, env, raw):
    CACHE.mkdir(exist_ok=True)
    _path(cfg, image, env).write_text(json.dumps(raw))


def save_run(name, data):
    RUNS.mkdir(exist_ok=True)
    p = RUNS / f"{name}-{int(time.time())}.json"
    p.write_text(json.dumps(data, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    return p
