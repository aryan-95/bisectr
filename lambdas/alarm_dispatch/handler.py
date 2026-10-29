"""Dispatch a guarded GitHub investigation for a matching CloudWatch alarm."""
import json
import os
import re
import time
import urllib.error
import urllib.request

import boto3
from botocore.exceptions import ClientError

ssm = boto3.client("ssm")
secrets = boto3.client("secretsmanager")
dynamodb = boto3.resource("dynamodb")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _dispatch_key(event):
    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("EventBridge event must contain a non-empty id")
    return event_id


def handler(event, _context):
    alarm_name = event.get("detail", {}).get("alarmName")
    state = event.get("detail", {}).get("state", {}).get("value")
    prefix = os.environ["ALARM_NAME_PREFIX"]
    if state != "ALARM" or not isinstance(alarm_name, str) or not alarm_name.startswith(prefix):
        return {"status": "ignored", "reason": "event is not a matching alarm transition"}

    try:
        range_value = ssm.get_parameter(Name=os.environ["RANGE_PARAMETER"])["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound as exc:
        raise RuntimeError("No main image range exists yet; wait for two successful main builds") from exc
    image_range = json.loads(range_value)
    good_sha, bad_sha = image_range.get("good_sha"), image_range.get("bad_sha")
    if not isinstance(good_sha, str) or not SHA_PATTERN.fullmatch(good_sha):
        raise ValueError("The main image range does not contain a valid previous good SHA")
    if not isinstance(bad_sha, str) or not SHA_PATTERN.fullmatch(bad_sha):
        raise ValueError("The main image range does not contain a valid current SHA")
    if good_sha == bad_sha:
        raise ValueError("The main image range must contain two distinct commits")

    dispatches = dynamodb.Table(os.environ["DISPATCH_TABLE"])
    event_id = _dispatch_key(event)
    try:
        dispatches.put_item(
            Item={"event_id": event_id, "expires_at": int(time.time()) + 30 * 24 * 60 * 60},
            ConditionExpression="attribute_not_exists(event_id)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return {"status": "duplicate", "event_id": event_id}
        raise

    try:
        secret_response = secrets.get_secret_value(SecretId=os.environ["GITHUB_TOKEN_SECRET_ARN"])
        secret_value = secret_response.get("SecretString")
        if not secret_value:
            raise ValueError("GitHub dispatch token secret has no SecretString")
        parsed_secret = json.loads(secret_value) if secret_value.startswith("{") else secret_value
        token = parsed_secret.get("token") if isinstance(parsed_secret, dict) else parsed_secret
        if not isinstance(token, str) or not token:
            raise ValueError(
                "GitHub dispatch token secret must be a token or a JSON object with token"
            )

        owner, repository = os.environ["GITHUB_REPOSITORY"].split("/", 1)
        workflow = os.environ["GITHUB_WORKFLOW"]
        url = (
            f"https://api.github.com/repos/{owner}/{repository}/actions/workflows/"
            f"{workflow}/dispatches"
        )
        payload = {
            "ref": os.environ["GITHUB_REF"],
            "inputs": {
                "good": good_sha,
                "bad": bad_sha,
                "alarm_name": alarm_name,
                "event_id": event_id,
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 204:
                raise RuntimeError(f"GitHub workflow dispatch returned HTTP {response.status}")
    except (ClientError, ValueError, json.JSONDecodeError, urllib.error.HTTPError,
            urllib.error.URLError, RuntimeError) as exc:
        dispatches.delete_item(Key={"event_id": event_id})
        raise
    return {"status": "dispatched", "event_id": event_id, "alarm_name": alarm_name}
