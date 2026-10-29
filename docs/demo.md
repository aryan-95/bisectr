# Feature validation and judge demo

Use this guide to validate Bisectr from unit tests through live CI. Local checks do not incur AWS
charges. Fargate-backed commands do; use a staging account, check the budget and kill switch first,
and do not run the suite and evaluation at the same time.

## 1. Local checks

Run from the Bisectr repository root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src/bisectr runner eval
git diff --check
.venv/bin/bisectr --help
.venv/bin/bisectr gate --help
.venv/bin/bisectr suite --help
.venv/bin/bisectr bisect --help
.venv/bin/bisectr validate --help
.venv/bin/bisectr verify-fix --help
.venv/bin/bisectr trends --help
.venv/bin/bisectr dashboard --help
```

These verify local logic and command parsing, not AWS behavior. `pytest` includes judge, runner,
bisect, configuration, reporting, storage, and CLI tests.

Run the deterministic noise simulation separately; it does not call AWS:

```bash
.venv/bin/python eval/noise_sensitivity.py --trials 1000 --out /tmp/bisectr-noise.csv
```

Treat its output as simulation data, not measured AWS accuracy.

## 2. AWS readiness and safety

Before any live probe:

1. Confirm the AWS account and region: `aws sts get-caller-identity`.
2. Confirm `bisectr.yaml` points to the intended ECR repo, cluster, subnets, security group,
   log group, and runner image.
3. Check that the kill switch is enabled and the configured AWS budget has headroom.
4. Ensure the baseline and candidate images are already pushed to ECR.
5. Remember a normal gate uses three replicas per side (six Fargate tasks) and takes around a few
   minutes. Bisect and evaluation can launch many more tasks and run much longer.

Do not regenerate configuration over custom workload/pricing settings without first backing it up.
Use the [runbook](runbook.md) for the kill switch and cleanup steps.

## 3. Validate gate, workload, endpoints, and cost

First run the A/A control; it should PASS:

```bash
make gate-ok
```

Then run the controlled regression separately; expect FAIL (the command can exit nonzero because the
gate is meant to fail):

```bash
make gate-bad
```

Inspect the HTML report and confirm the candidate p95/error data, route table, reasons, and sizing
estimate. A dollar estimate only appears when both Fargate prices are configured. It is an estimate,
not the AWS bill.

For configured multiple workload profiles:

```bash
bisectr suite --config bisectr.yaml --candidate CANDIDATE_SHA --baseline BASELINE_SHA
```

Confirm each profile appears in the report and that any failing profile makes the suite fail. Endpoint
budgets must be set on the configured endpoints; verify the route-level result table shows the
appropriate PASS/FAIL or insufficient-samples evidence. Do not treat an unmeasured endpoint as
passing.

To repeat a no-cache comparison and save each trial to CSV:

```bash
bisectr validate --config bisectr.yaml \
  --baseline BASELINE_IMAGE_TAG --candidate CANDIDATE_IMAGE_TAG \
  --trials 5 --out eval/validation.csv
bisectr trends --config bisectr.yaml --kind validate
bisectr dashboard --config bisectr.yaml --out runs/dashboard.html
```

Open the generated dashboard locally and confirm the recorded runs, latency trend, cost trend, and
verdicts. `trends` and dashboard read stored history; they do not launch probes.

## 4. Validate bisect and fix verification

Generate a separate, disposable image history with one known slow commit:

```bash
DEST=../bisectr-demo-history-demo \
LOG=../bisectr-shas-demo.txt \
./scripts/make_demo_history.sh 10 6
```

The script refuses to overwrite either output path. Read the first and last SHAs:

```bash
GOOD=$(awk 'NR==1 {print $2}' ../bisectr-shas-demo.txt)
BAD=$(tail -n 1 ../bisectr-shas-demo.txt | awk '{print $2}')
cd ../bisectr-demo-history-demo
bisectr bisect --config ../bisectr/bisectr.yaml --good "$GOOD" --bad "$BAD"
```

The injected regression is at commit 6. Bisect should locate it or report an uncertain result; inspect
the evidence and do not claim certainty if it reports ambiguous/flaky.

After fixing or reverting the culprit, build and push the fixed image, then compare the known-good
image with the fixed candidate:

```bash
bisectr verify-fix --config ../bisectr/bisectr.yaml \
  --baseline "$GOOD_BASELINE" --candidate "$FIXED_SHA"
```

Only PASS reports “Regression resolved.” WARN/FAIL means it was not verified. The command stores a
report and run-history record; it does not create or merge a revert PR.

## 5. Evaluation harness

The evaluation scenarios use the demo app's injected regressions and noise-only control. This is
synthetic evaluation, not validation of an independent service. Start it only when no other Fargate
test is running:

```bash
bisectr eval --config bisectr.yaml \
  --image "$(git rev-parse HEAD)" --trials 20 --bisect-trials 3 \
  --seed 20261029 --out eval/results-20-trials.csv
python eval/report.py eval/results-20-trials.csv
```

Evaluation can take a long time and bisect trials cost much more than a gate. For a stopped run, use
the same image, config, scenarios, trial counts, seed, and CSV with `--resume`; do not launch a second
copy. Publish only after every requested scenario/trial is present. Keep the CSV, report, image SHA,
configuration, and cost assumptions together.

## 6. Public-service case study

An injected demo only proves that the workflow can find an intentional change; it is not an
independent case study. For a public service, pin its source commit and image digests, record the
license, use a harmless read-only route, and create a controlled regression in a separate test image.
Compare the unmodified and controlled images with `bisectr validate`, run repeated trials, and publish
the methodology, results, failures, and AWS cost estimate with a clear label that the injected change
was intentional. Do not call this natural-regression detection.

## 7. Validate CI and merge blocking

For GitHub, open an eligible same-repository PR and verify the image-build job, AWS gate, PR comment,
and **Bisectr performance gate** check. Test one A/A PR and one known-regression PR. Only after a
successful gate establishes the check context should an administrator require it in the branch
ruleset. The workflow intentionally skips fork PRs and limits who can trigger AWS; do not weaken that
trust boundary. Once enabled, verify GitHub blocks the failing PR and permits the passing one.

For GitLab, validate a pipeline on the protected default branch. The current pipeline compares the
branch commit with its parent; it is not a merge-request gate. Verify OIDC role assumption, Docker
build/push, and the final Bisectr verdict in the job log.

## 8. Validate alarm-triggered investigation

This optional feature is disabled by default and currently tracks the two latest successful main
image builds, **not actual production deployments**. Follow [alarm-automation.md](alarm-automation.md)
to configure the GitHub dispatch token secret, apply Terraform, and set an alarm-name prefix. Test
only in a non-production environment:

1. Wait until two successful main image builds have populated `/bisectr/main-build-range`.
2. Trigger a test alarm whose name starts with the configured prefix.
3. Confirm only one workflow dispatch occurs for the EventBridge event ID.
4. Confirm a verified culprit leads to a separate revert branch, image build, `verify-fix` PASS, and
   an unmerged PR. An ambiguous bisect or failed verification must not create that PR.
5. Confirm the GitHub issue contains enough alarm and commit context when a culprit/revert cannot be
   safely verified.

This only investigates the two latest successful main builds. It does not roll back a live service,
and a Fargate PASS does not prove a production recovery. Configure deployment SHA tracking and
post-deployment health checks before using production alarms. Review [alarm-automation.md](alarm-automation.md)
for details.

## 9. Required GitHub check

After an eligible same-repository pull request has completed a successful Bisectr gate and the check
is visible, protect the default branch:

1. Open **Settings → Rules → Rulesets** (or **Branches → branch protection rules**).
2. Create or edit a ruleset targeting `main` and enable required status checks.
3. Require **Bisectr performance gate**. Consider also requiring the `bisectr-gate / build-candidate`
   workflow job so a failed image build cannot be mistaken for a successful gate.
4. Save the ruleset and verify it with a passing PR and the injected-regression PR.

The workflow intentionally skips fork pull requests and only runs for eligible collaborators. A
required check may therefore remain pending for a PR that is not eligible to run the cloud gate.
Do not weaken the workflow's trust restrictions to make a fork check run.

## 10. Backup recording

Record the sequence after confirming it works in the target AWS account. Keep the report visible in
the recording and have a copy available offline in case AWS capacity or network access fails.

## 11. Evidence and reporting

The demo history is synthetic and proves the workflow, not real-world accuracy. Keep actual
evaluation counts separate from simulated noise results. Document the repository, immutable
commit/image references, workload, trial counts, results, limitations, and failures before claiming
a public-service case study.
