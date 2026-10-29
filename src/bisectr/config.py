from __future__ import annotations
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class Task(BaseModel):
    cpu: int = Field(default=1024, gt=0)
    memory: int = Field(default=2048, gt=0)
    app_cpu: int = Field(default=512, gt=0)

    @model_validator(mode="after")
    def app_cpu_fits_task(self):
        if self.app_cpu + 256 > self.cpu:
            raise ValueError("task.app_cpu plus the 256 CPU-unit runner reservation cannot exceed task.cpu")
        return self


class Endpoint(BaseModel):
    path: str
    weight: int = Field(gt=0)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    body: Optional[dict[str, Any]] = None
    max_p95_ratio: Optional[float] = Field(default=None, ge=1)
    max_error_delta: Optional[float] = Field(default=None, ge=0, le=1)

    @field_validator("path")
    @classmethod
    def path_is_absolute(cls, value):
        if not value.startswith("/"):
            raise ValueError("endpoint paths must start with '/'")
        return value


class Scenario(BaseModel):
    profile: str = "default"
    rps: int = Field(default=20, gt=0)
    seconds: int = Field(default=30, gt=0)
    warmup_seconds: int = Field(default=5, ge=0)
    endpoints: list[Endpoint] = Field(default_factory=lambda: [
        Endpoint(path="/users", weight=3), Endpoint(path="/orders", weight=2),
    ])

    @model_validator(mode="after")
    def has_endpoints(self):
        if not self.profile.strip():
            raise ValueError("scenario.profile must not be empty")
        if not self.endpoints:
            raise ValueError("scenario.endpoints must contain at least one endpoint")
        return self


class Thresholds(BaseModel):
    alpha: float = Field(default=0.01, gt=0, lt=1)
    min_ratio: float = Field(default=1.25, ge=1)
    min_agree: int = Field(default=2, gt=0)
    error_abs: float = Field(default=0.02, ge=0, le=1)
    cost_min_ratio: float = Field(default=1.15, ge=1)
    min_delta_ms: float = Field(default=2.0, ge=0)


class Cost(BaseModel):
    target_rps: int = Field(default=500, gt=0)
    target_utilization: float = Field(default=0.6, gt=0, le=1)
    on_cost_regression: Literal["warn", "fail"] = "warn"


class Pricing(BaseModel):
    vcpu_hour: float = Field(default=0.0, ge=0)
    gb_hour: float = Field(default=0.0, ge=0)


class Infra(BaseModel):
    region: str
    cluster: str
    log_group: str
    exec_role: str
    sg: str
    subnets: list[str]
    image_repo: str
    runner_image: str
    runs_table: Optional[str] = None
    baseline_table: Optional[str] = None
    reports_bucket: Optional[str] = None
    budget_name: Optional[str] = None

    @field_validator("image_repo")
    @classmethod
    def image_repo_has_repository_name(cls, value):
        if "/" not in value or value.endswith("/"):
            raise ValueError("infra.image_repo must include an ECR repository path")
        return value

    @model_validator(mode="after")
    def cloud_storage_is_complete(self):
        resources = (self.runs_table, self.baseline_table, self.reports_bucket)
        if any(resources) and not all(resources):
            raise ValueError(
                "Configure runs_table, baseline_table, and reports_bucket together."
            )
        if any(resources) and not self.budget_name:
            raise ValueError("Cloud storage configuration also requires infra.budget_name.")
        return self


class Config(BaseModel):
    service: str = "service"
    port: int = Field(default=8000, ge=1, le=65535)
    health_path: str = "/health"
    task: Task = Task()
    scenario: Scenario = Scenario()
    scenarios: list[Scenario] = Field(default_factory=list)
    thresholds: Thresholds = Thresholds()
    cost: Cost = Cost()
    pricing: Pricing = Pricing()
    replicas: int = Field(default=3, gt=0)
    max_probes: int = Field(default=24, gt=0)
    bisect_k: int = Field(default=3, gt=0)
    max_parallel_tasks: int = Field(default=6, gt=0)
    infra: Infra

    @field_validator("health_path")
    @classmethod
    def health_path_is_absolute(cls, value):
        if not value.startswith("/"):
            raise ValueError("health_path must start with '/'")
        return value

    @model_validator(mode="after")
    def scenarios_have_unique_profiles(self):
        names = [scenario.profile for scenario in self.scenarios]
        if len(names) != len(set(names)):
            raise ValueError("scenario profile names must be unique")
        return self

    def scaled(self, factor: float) -> "Config":
        c = self.model_copy(deep=True)
        c.scenario.seconds = int(c.scenario.seconds * factor)
        return c


def load(path: str = "bisectr.yaml") -> Config:
    with open(path) as f:
        return Config(**yaml.safe_load(f))
