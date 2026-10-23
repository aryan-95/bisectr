#!/usr/bin/env bash
set -euo pipefail
REGION=${REGION:-ap-south-1}
ACCT=$(aws sts get-caller-identity --query Account --output text)
REG=$ACCT.dkr.ecr.$REGION.amazonaws.com
SHA=$(git rev-parse HEAD)
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REG"
docker build --platform linux/amd64 -t "$REG/bisectr-runner:latest" runner
docker push "$REG/bisectr-runner:latest"
docker build --platform linux/amd64 -t "$REG/bisectr-demo:$SHA" demo-app
docker push "$REG/bisectr-demo:$SHA"
echo "pushed bisectr-demo:$SHA"
