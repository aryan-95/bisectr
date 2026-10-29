import boto3


class GuardrailBlocked(RuntimeError):
    pass


def check_budget(cfg) -> None:
    budget_name = cfg.infra.budget_name
    if not budget_name:
        return
    account_id = boto3.client("sts", region_name=cfg.infra.region).get_caller_identity()["Account"]
    budget = boto3.client("budgets", region_name="us-east-1").describe_budget(
        AccountId=account_id, BudgetName=budget_name
    )["Budget"]
    limit = float(budget["BudgetLimit"]["Amount"])
    actual = float(budget["CalculatedSpend"]["ActualSpend"]["Amount"])
    if limit <= 0:
        raise ValueError(f"AWS budget {budget_name!r} has a non-positive limit.")
    if actual >= limit * 0.9:
        raise GuardrailBlocked(
            f"AWS budget {budget_name!r} has reached 90% of its monthly limit "
            f"(${actual:.2f} of ${limit:.2f}); the run was stopped."
        )


def check_enabled(cfg) -> None:
    """Kill switch: set SSM /bisectr/enabled to false to stop all runs."""
    ssm = boto3.client("ssm", region_name=cfg.infra.region)
    try:
        v = ssm.get_parameter(Name="/bisectr/enabled")["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        raise GuardrailBlocked(
            "The SSM kill-switch parameter /bisectr/enabled is missing; refusing to start."
        )
    if v.strip().lower() != "true":
        raise GuardrailBlocked("Bisectr is disabled by the SSM kill switch (/bisectr/enabled).")
    check_budget(cfg)
