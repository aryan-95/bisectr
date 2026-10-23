import boto3


def check_enabled(cfg) -> None:
    """Kill switch: set SSM /bisectr/enabled to false to stop all runs."""
    ssm = boto3.client("ssm", region_name=cfg.infra.region)
    try:
        v = ssm.get_parameter(Name="/bisectr/enabled")["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return
    if v.strip().lower() != "true":
        raise SystemExit("Bisectr is disabled by the SSM kill switch (/bisectr/enabled).")
