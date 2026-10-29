import asyncio, json, os, random, time
import httpx

PORT = os.getenv("PORT", "8000")
BASE = f"http://localhost:{PORT}"
HEALTH_PATH = os.getenv("HEALTH_PATH", "/health")
RPS = int(os.getenv("RPS", "20"))
SECONDS = int(os.getenv("SECONDS", "30"))
WARMUP = int(os.getenv("WARMUP", "5"))
EPS = json.loads(os.getenv("ENDPOINTS", '[{"path":"/users","weight":3},{"path":"/orders","weight":2}]'))
META = os.getenv("ECS_CONTAINER_METADATA_URI_V4")

WEIGHTS = [e["weight"] for e in EPS]


async def wait_healthy(c):
    for _ in range(180):
        try:
            if (await c.get(BASE + HEALTH_PATH)).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    raise SystemExit("app never became healthy")


async def app_cpu_mem(c):
    """(cpu_seconds, mem_bytes) for the container named 'app'. None outside ECS."""
    if not META:
        return None, None
    task = (await c.get(META + "/task")).json()
    cid = next(x["DockerId"] for x in task["Containers"] if x["Name"] == "app")
    stats = (await c.get(META + "/task/stats")).json()[cid]
    cpu = stats["cpu_stats"]["cpu_usage"]["total_usage"] / 1e9
    mem = stats["memory_stats"].get("usage", 0)
    return cpu, mem


async def fire(c, endpoint, sched, out):
    if isinstance(endpoint, str):
        method, path, body = "GET", endpoint, None
    else:
        method = endpoint.get("method", "GET")
        path, body = endpoint["path"], endpoint.get("body")
    try:
        if method == "GET" and body is None:
            r = await c.get(BASE + path)
        else:
            r = await c.request(method, BASE + path, json=body)
        ok = r.status_code < 400
    except httpx.HTTPError:
        ok = False
    # latency from the SCHEDULED send time -> no coordinated omission
    out.append(((time.perf_counter() - sched) * 1000, ok))


async def phase(c, secs, out):
    start = time.perf_counter()
    tasks = []
    for i in range(int(RPS * secs)):
        sched = start + i / RPS
        delay = sched - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        endpoint = random.choices(EPS, WEIGHTS)[0]
        tasks.append(asyncio.create_task(fire(c, endpoint, sched, out)))
    await asyncio.gather(*tasks)


async def main():
    limits = httpx.Limits(max_connections=200)
    async with httpx.AsyncClient(limits=limits, timeout=10) as c:
        await wait_healthy(c)
        await phase(c, WARMUP, [])  # discarded warmup
        cpu0, _ = await app_cpu_mem(c)
        out = []
        state = {"peak": 0, "stop": False}

        async def sample_mem():
            while not state["stop"]:
                _, m = await app_cpu_mem(c)
                state["peak"] = max(state["peak"], m or 0)
                await asyncio.sleep(2)

        s = asyncio.create_task(sample_mem())
        await phase(c, SECONDS, out)
        state["stop"] = True
        await s
        cpu1, _ = await app_cpu_mem(c)

    n = len(out)
    errors = sum(1 for _, ok in out if not ok)
    cpu_per_req = ((cpu1 - cpu0) / n) if cpu0 is not None and n else None
    result = {
        "n": n,
        "errors": errors,
        "latencies_ms": [round(l, 2) for l, _ in out],
        "cpu_s_per_req": cpu_per_req,
        "peak_mem_mb": round(state["peak"] / 1e6, 1),
    }
    print("BISECTR_RESULT " + json.dumps(result), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
