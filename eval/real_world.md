# Real-world validation

**Scope:** demo service with a 10-commit history (`scripts/make_demo_history.sh 10 6`), one image per
commit on Fargate (ap-south-1), 3 replicas, k=2. The regression is a 30 ms sleep added to `/users` in
commit 6. This is a synthetic regression in a demo app, not a real open-source service.
Not yet validated on a real third-party service (future work).

## Run 1: FLAKY (before the fix)
The search converged on the correct window: commit 5 (`493ef372f8`, good) .. commit 6 (`6b0e3648e4`, bad).
Verification then re-measured the parent and got p95 ratio 1.19 (inconclusive), so Bisectr reported
FLAKY and refused to name a culprit. Baseline latency is about 5 ms, so 1 ms of jitter looks like a
20% regression, and the parent had measured 0.99 in the previous probe.

Fixes: (1) a noise floor (`min_delta_ms`, default 2 ms): a result is only "bad" if p95 is also at
least 2 ms worse, and under that it is "good"; (2) verification now runs the culprit and its parent at
the same time and requires the culprit to be significantly slower.

## Run 2: FOUND (after the fix)
Culprit `6b0e3648e4ded00d377b0f1d35c34d3a6d38bda5` = commit 6, correct. The head-to-head against the
parent gave p95 ratio 7.40, 3 of 3 replicas worse. Commit 4 measured ratio 1.25 (p = 2.8e-47, 2 replicas)
but only a few ms, and the noise floor correctly classified it as good.

## What this shows
Bisectr declined to give a confident answer when verification was borderline, instead of reporting a
possibly wrong commit. The two fixes made it resolve the same window correctly.
