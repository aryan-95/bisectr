#!/usr/bin/env bash
# usage: scripts/make_demo_history.sh [N_COMMITS=10] [CULPRIT_INDEX=6]
# Builds a separate git repo with N commits, one of which adds a 30 ms delay, and pushes an image per commit.
set -euo pipefail
N=${1:-10}; CULPRIT=${2:-6}
SRC=$(cd "$(dirname "$0")/.." && pwd)
DEST=${DEST:-$SRC/../bisectr-demo-history}
LOG=${LOG:-$SRC/../bisectr-shas.txt}
REGION=${REGION:-us-east-1}
if [ -e "$DEST" ] || [ -e "$LOG" ]; then
  echo "Refusing to overwrite existing demo output." >&2
  echo "Choose fresh paths with DEST=/path/to/history LOG=/path/to/shas.txt." >&2
  exit 2
fi
ACCT=$(aws sts get-caller-identity --query Account --output text)
REG=$ACCT.dkr.ecr.$REGION.amazonaws.com
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REG" >/dev/null

mkdir -p "$DEST"; cd "$DEST"
git init -q -b main
git config user.email demo@bisectr.local; git config user.name bisectr-demo
cp "$SRC/demo-app/Dockerfile" .
cat > main.py << 'PY'
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/users")
def users():
    return {"users": [{"id": i, "name": f"user{i}"} for i in range(50)]}


@app.get("/orders")
def orders():
    return {"orders": [{"id": i, "total": i * 3} for i in range(30)]}
PY

for i in $(seq 1 "$N"); do
  [ "$i" -gt 1 ] && echo "# harmless change $i" >> main.py
  if [ "$i" -eq "$CULPRIT" ]; then
    sed -i 's/^def users():$/def users():\n    __import__("time").sleep(0.03)/' main.py
  fi
  git add -A
  git commit -q -m "commit $i"
  SHA=$(git rev-parse HEAD)
  docker build -q --platform linux/amd64 -t "$REG/bisectr-demo:$SHA" . >/dev/null
  docker push -q "$REG/bisectr-demo:$SHA" >/dev/null
  echo "$i $SHA" | tee -a "$LOG"
done
echo
echo "good   = $(sed -n 1p "$LOG" | cut -d' ' -f2)"
echo "bad    = $(tail -1 "$LOG" | cut -d' ' -f2)"
echo "answer = $(sed -n ${CULPRIT}p "$LOG" | cut -d' ' -f2)   (commit $CULPRIT)"
