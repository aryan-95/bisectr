import pytest

from bisectr.config import Config, Infra
from bisectr.cost import cost_report, tasks_needed
from bisectr.judge import Rep
from bisectr.config import Scenario, Task


def make_config():
    return Config(
        pricing={"vcpu_hour": 0.0, "gb_hour": 0.01},
        infra=Infra(region="r", cluster="c", log_group="g", exec_role="e", sg="s",
                    subnets=["a"], image_repo="x/y", runner_image="x/r"),
    )


def test_tasks_needed_exact():
    assert tasks_needed(1000, 0.001, 1.0, 0.6) == 2      # 1.0 / 0.6 -> 1.67 -> 2


def test_more_cpu_never_fewer_tasks():
    assert tasks_needed(500, 0.002, 1.0, 0.6) >= tasks_needed(500, 0.001, 1.0, 0.6)


def test_minimum_one_task():
    assert tasks_needed(1, 0.0001, 1.0, 0.6) == 1


def test_cost_report_is_not_priced_when_only_one_resource_rate_is_configured():
    reps = [Rep([], 0, 1, 0.001, 100.0) for _ in range(3)]

    result = cost_report(make_config(), reps, reps)

    assert result["priced"] is False
    assert result["delta"] is None


def test_scenario_rejects_endpoint_without_leading_slash():
    with pytest.raises(ValueError, match="must start with"):
        Scenario(endpoints=[{"path": "users", "weight": 1}])

def test_scenario_supports_weighted_json_requests():
    scenario = Scenario(
        profile="checkout-mix",
        endpoints=[
            {"path": "/orders", "weight": 2, "method": "POST", "body": {"items": [1]}},
        ],
    )

    assert scenario.profile == "checkout-mix"
    assert scenario.endpoints[0].method == "POST"
    assert scenario.endpoints[0].body == {"items": [1]}


def test_scenario_rejects_unsupported_http_method():
    with pytest.raises(ValueError):
        Scenario(endpoints=[{"path": "/orders", "weight": 1, "method": "TRACE"}])


def test_endpoint_rejects_regression_budgets_out_of_range():
    with pytest.raises(ValueError):
        Scenario(endpoints=[{"path": "/users", "weight": 1, "max_p95_ratio": 0.9}])
    with pytest.raises(ValueError):
        Scenario(endpoints=[{"path": "/users", "weight": 1, "max_error_delta": 1.1}])


def test_config_rejects_duplicate_scenario_profile_names():
    infra = Infra(region="r", cluster="c", log_group="g", exec_role="e", sg="s",
                  subnets=["a"], image_repo="x/y", runner_image="x/r")
    with pytest.raises(ValueError, match="must be unique"):
        Config(infra=infra, scenarios=[
            Scenario(profile="normal"), Scenario(profile="normal", rps=80),
        ])


def test_task_rejects_app_cpu_above_task_cpu():
    with pytest.raises(ValueError, match="cannot exceed"):
        Task(cpu=512, app_cpu=1024)


def test_task_reserves_cpu_for_runner():
    with pytest.raises(ValueError, match="runner reservation"):
        Task(cpu=512, app_cpu=512)
