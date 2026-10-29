"""Persist the two latest successfully built main images for alarm investigations."""
import json
import os
import re
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError


PARAMETER_NAME = "/bisectr/main-build-range"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def main():
    current_sha = os.environ.get("GITHUB_SHA", "").lower()
    if not SHA_PATTERN.fullmatch(current_sha):
        raise ValueError("GITHUB_SHA must be a full 40-character commit SHA")
    subprocess.run(["git", "fetch", "origin", "main"], check=True)
    latest_main_sha = subprocess.check_output(
        ["git", "rev-parse", "FETCH_HEAD"], text=True
    ).strip()
    if latest_main_sha != current_sha:
        print(
            f"Skipping stale main build {current_sha}; current main is {latest_main_sha}."
        )
        return
    region = os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")
    ssm = boto3.client("ssm", region_name=region)
    previous_sha = None
    try:
        raw = ssm.get_parameter(Name=PARAMETER_NAME)["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        raw = None
    if raw is not None:
        state = json.loads(raw)
        if not isinstance(state, dict):
            raise ValueError(f"{PARAMETER_NAME} must contain a JSON object")
        previous_sha = state.get("bad_sha")
        if previous_sha is not None and not SHA_PATTERN.fullmatch(previous_sha):
            raise ValueError(f"{PARAMETER_NAME} contains an invalid bad_sha")

    if previous_sha == current_sha:
        print(f"{PARAMETER_NAME} already tracks {current_sha}; leaving it unchanged.")
        return
    if previous_sha is None:
        print("No prior main image is recorded; saving this image as the initial bad_sha.")
    value = json.dumps({
        "good_sha": previous_sha,
        "bad_sha": current_sha,
        "updated_by": "build-main",
    })
    ssm.put_parameter(
        Name=PARAMETER_NAME,
        Type="String",
        Value=value,
        Overwrite=True,
        Description="Latest two successfully built main image commits for Bisectr alarm analysis",
    )
    print(f"Recorded main image range: {previous_sha or 'none'} -> {current_sha}")


if __name__ == "__main__":
    try:
        main()
    except (ClientError, ValueError, json.JSONDecodeError) as exc:
        print(f"Failed to update main image range: {exc}", file=sys.stderr)
        raise
