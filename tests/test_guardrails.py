from types import SimpleNamespace

import pytest

from bisectr import guardrails
from bisectr.config import Config, Infra


def make_config(budget_name="bisectr-monthly"):
    return Config(
        infra=Infra(
            region="ap-south-1", cluster="cluster", log_group="logs", exec_role="role",
            sg="sg", subnets=["subnet"], image_repo="repo/image", runner_image="repo/runner",
            budget_name=budget_name,
        )
    )


def test_budget_guardrail_blocks_at_ninety_percent(monkeypatch):
    def fake_client(service, **kwargs):
        if service == "sts":
            return SimpleNamespace(get_caller_identity=lambda: {"Account": "123"})
        assert service == "budgets"
        return SimpleNamespace(describe_budget=lambda **_: {
            "Budget": {
                "BudgetLimit": {"Amount": "20"},
                "CalculatedSpend": {"ActualSpend": {"Amount": "18"}},
            }
        })

    monkeypatch.setattr(guardrails.boto3, "client", fake_client)

    with pytest.raises(guardrails.GuardrailBlocked, match="reached 90%"):
        guardrails.check_budget(make_config())


def test_budget_guardrail_allows_spend_below_ninety_percent(monkeypatch):
    def fake_client(service, **kwargs):
        if service == "sts":
            return SimpleNamespace(get_caller_identity=lambda: {"Account": "123"})
        return SimpleNamespace(describe_budget=lambda **_: {
            "Budget": {
                "BudgetLimit": {"Amount": "20"},
                "CalculatedSpend": {"ActualSpend": {"Amount": "17.99"}},
            }
        })

    monkeypatch.setattr(guardrails.boto3, "client", fake_client)

    guardrails.check_budget(make_config())


def test_budget_check_is_skipped_when_unconfigured(monkeypatch):
    monkeypatch.setattr(
        guardrails.boto3,
        "client",
        lambda *_args, **_kwargs: pytest.fail("AWS client should not be created"),
    )

    guardrails.check_budget(make_config(budget_name=None))


def test_missing_kill_switch_fails_closed(monkeypatch):
    class ParameterNotFound(Exception):
        pass

    class FakeSSM:
        exceptions = SimpleNamespace(ParameterNotFound=ParameterNotFound)

        def get_parameter(self, **_kwargs):
            raise ParameterNotFound

    monkeypatch.setattr(guardrails.boto3, "client", lambda *_args, **_kwargs: FakeSSM())

    with pytest.raises(guardrails.GuardrailBlocked, match="parameter.*missing"):
        guardrails.check_enabled(make_config(budget_name=None))
