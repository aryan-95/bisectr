from __future__ import annotations
import yaml
from pydantic import BaseModel


class Task(BaseModel):
    cpu: int = 1024
    memory: int = 2048
    app_cpu: int = 512


class Scenario(BaseModel):
    rps: int = 20
    seconds: int = 30
    warmup_seconds: int = 5
    endpoints: list[dict] = [{"path": "/users", "weight": 3}, {"path": "/orders", "weight": 2}]


class Thresholds(BaseModel):
    alpha: float = 0.01
    min_ratio: float = 1.25
    min_agree: int = 2
    error_abs: float = 0.02
    cost_min_ratio: float = 1.15
    min_delta_ms: float = 2.0     # p95 must also differ by this many ms (noise floor)


class Cost(BaseModel):
    target_rps: int = 500
    target_utilization: float = 0.6
    on_cost_regression: str = "warn"   # warn | fail


class Pricing(BaseModel):
    vcpu_hour: float = 0.0
    gb_hour: float = 0.0


class Infra(BaseModel):
    region: str
    cluster: str
    log_group: str
    exec_role: str
    sg: str
    subnets: list[str]
    image_repo: str
    runner_image: str


class Config(BaseModel):
    service: str = "service"
    port: int = 8000
    task: Task = Task()
    scenario: Scenario = Scenario()
    thresholds: Thresholds = Thresholds()
    cost: Cost = Cost()
    pricing: Pricing = Pricing()
    replicas: int = 3
    max_probes: int = 24
    bisect_k: int = 3
    infra: Infra

    def scaled(self, factor: float) -> "Config":
        c = self.model_copy(deep=True)
        c.scenario.seconds = int(c.scenario.seconds * factor)
        return c


def load(path: str = "bisectr.yaml") -> Config:
    with open(path) as f:
        return Config(**yaml.safe_load(f))
