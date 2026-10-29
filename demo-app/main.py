import os, time, random, hashlib
from fastapi import FastAPI, Response

app = FastAPI()
MODE = os.getenv("REGRESSION", "none")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/users")
def users():
    if MODE == "slow_dependency":
        time.sleep(0.03)
    if MODE == "n_plus_one":
        for _ in range(50):           # 50 small "queries"
            time.sleep(0.0006)
    if MODE == "cpu_hot_loop":
        h = b"x"
        for _ in range(30000):        # tune so the effect is clearly >15% CPU
            h = hashlib.sha256(h).digest()
    if MODE == "error_rate" and random.random() < 0.10:
        return Response(status_code=500)
    n = 1000 if MODE == "payload_bloat" else 50   # 20x response size
    return {"users": [{"id": i, "name": f"user{i}"} for i in range(n)]}


@app.get("/orders")
def orders():
    return {"orders": [{"id": i, "total": i * 3} for i in range(30)]}


@app.post("/orders")
def create_order(order: dict):
    return {"accepted": True, "items": len(order.get("items", []))}
