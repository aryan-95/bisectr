"""Stops probe tasks older than MAX_MINUTES and deregisters old task definition revisions."""
import datetime
import os

import boto3

ecs = boto3.client("ecs")
CLUSTER = os.environ["CLUSTER"]
MAX_MINUTES = int(os.environ.get("MAX_MINUTES", "30"))
FAMILY = os.environ.get("FAMILY", "bisectr-probe")
KEEP = int(os.environ.get("KEEP_REVISIONS", "50"))


def handler(event, context):
    now = datetime.datetime.now(datetime.timezone.utc)
    stopped, deregistered = [], []

    arns = []
    for page in ecs.get_paginator("list_tasks").paginate(cluster=CLUSTER, desiredStatus="RUNNING"):
        arns += page["taskArns"]
    for i in range(0, len(arns), 100):
        for t in ecs.describe_tasks(cluster=CLUSTER, tasks=arns[i:i + 100])["tasks"]:
            started = t.get("startedAt") or t.get("createdAt")
            if started and (now - started).total_seconds() > MAX_MINUTES * 60:
                ecs.stop_task(cluster=CLUSTER, task=t["taskArn"], reason="bisectr reaper: too old")
                stopped.append(t["taskArn"])

    revs = []
    for page in ecs.get_paginator("list_task_definitions").paginate(
            familyPrefix=FAMILY, status="ACTIVE", sort="DESC"):
        revs += page["taskDefinitionArns"]
    for arn in revs[KEEP:]:
        ecs.deregister_task_definition(taskDefinition=arn)
        deregistered.append(arn)

    print({"stopped": len(stopped), "deregistered": len(deregistered)})
    return {"stopped": stopped, "deregistered": deregistered}
