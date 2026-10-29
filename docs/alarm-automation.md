# Alarm-triggered investigation and verified revert PR

This optional automation is disabled unless `enable_alarm_bisect=true`. It is designed for this
repository's main-branch image builds:

1. `build-main` tests and publishes the commit-tagged app image and runner image.
2. After image publication succeeds, CI writes the previous and current successful main build SHAs
   together to `/bisectr/main-build-range` in SSM Parameter Store.
3. An EventBridge rule listens for CloudWatch alarm state transitions to `ALARM` whose alarm name
   begins with `alarm_name_prefix`.
4. A Lambda validates the stored SHA range, deduplicates EventBridge retries, and dispatches
   `.github/workflows/bisectr-alarm.yml`.
5. The workflow bisects the range. If a culprit is verified, it creates a revert on a separate
   branch, builds the reverted demo app image, and compares that image against the previous main
   build.
6. Only a PASS results in a revert pull request. The PR is never merged automatically. If bisect
   cannot verify one culprit, or the revert does not pass, the workflow opens an issue and does not
   open a revert PR.

## Important scope limitation

The current project builds and probes the demo app; it does not deploy an application to production.
The tracked SHA range is therefore the two latest successful **main image builds**, not confirmed
production releases. A CloudWatch alarm from a real production service may refer to a different
version. Do not treat this feature as automatic production rollback. For production use, first modify
the deployment pipeline to publish the actual deployed and last-known-good SHAs only after deploy
health checks pass, and review the alarm-to-service mapping.

This workflow also assumes the GitHub repository's service image is built from `demo-app/`, as the
existing image-publishing workflow does. Adapt and review the build context before using it for another
service.

## Configure

1. Create a **fine-grained GitHub token** for this one repository with Actions: write permission.
   Store it in AWS Secrets Manager as a secret string; a plain token string or JSON such as
   `{"token":"..."}` is accepted. Do not place the token in Terraform variables, YAML, or shell
   history.
2. Apply the Terraform integration, using the existing remote state:

   ```bash
   terraform -chdir=infra/envs/dev apply \
     -var="github_repo=OWNER/REPO" \
     -var="enable_alarm_bisect=true" \
     -var="alarm_name_prefix=bisectr-" \
     -var="github_dispatch_token_secret_arn=SECRET_ARN"
   ```

   If other Terraform variables are required by your existing state, include them as usual.
   Terraform creates the EventBridge rule, dispatch Lambda, narrowly scoped IAM permissions, and a
   DynamoDB idempotency table. The image-range SSM parameter is created by the successful CI build
   workflow once it has published an image.
3. Ensure the repository Actions setting permits GitHub Actions to create pull requests. The
   workflow token is granted `contents: write`, `pull-requests: write`, and `issues: write`; it
   creates a branch and PR but never merges.
4. Create or configure a CloudWatch alarm with a name beginning with the prefix. Keep the alarm
   specific to a service and metric that should trigger investigation, and test it in a non-production
   environment first.
5. Confirm two successful main image builds have populated `/bisectr/main-build-range`. The first
   build only seeds the range; it cannot start a bisect because there is no previous image.
6. Test with a controlled alarm transition. Confirm EventBridge invokes the Lambda, a workflow run
   appears, duplicate events do not dispatch duplicate runs, and the outcome is either a verified
   revert PR or a no-culprit/unverified issue.

Use the SSM kill switch and AWS budget guardrails in the [runbook](runbook.md). Disable the feature
with `enable_alarm_bisect=false` and re-apply Terraform.

## Safety boundaries

- The alarm Lambda can only read the main image range, read the configured GitHub token secret,
  deduplicate event IDs, and invoke the configured workflow.
- The alarm workflow runs only on `main`; the bisect result must be `found` before attempting a
  revert.
- Reverts with conflicts, unverified results, or a non-PASS performance check must not be merged.
- The PR is advisory for human review. Review data migrations, dependent changes, alarm correctness,
  and production health before merging.
- A PASS in a synthetic Fargate workload is not proof that production has recovered. Verify the
  actual service after a human merges and deploys the PR.
