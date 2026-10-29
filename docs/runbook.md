# Runbook

Replace bracketed placeholders such as `<arn>` with actual values, without typing the angle brackets.

- Stop new `us-east-1` probes: `aws ssm put-parameter --region us-east-1 --name /bisectr/enabled --value false --overwrite`
- Resume new `us-east-1` probes: same command with `--value true`
- Runs are also blocked when actual spend reaches 90% of `bisectr-monthly-useast1`. Budget notifications at
  50% and 90% publish to the `bisectr-budget-alerts` SNS topic; configure `alert_email` to subscribe.
- Find stray `us-east-1` tasks: `aws ecs list-tasks --region us-east-1 --cluster bisectr`
- Stop one: `aws ecs stop-task --region us-east-1 --cluster bisectr --task <arn>`
- Read a probe's logs: CloudWatch log group `/bisectr/probe`, stream `runner/runner/<task-id>`
- Run records and baseline cache entries are in DynamoDB tables `bisectr-runs` and
  `bisectr-baselines`; both use TTL. HTML reports are private objects under `reports/` in the S3
  bucket named by the Terraform output `reports_bucket` and expire after 90 days. The bucket is not
  emptied automatically by `terraform destroy`: export any reports you need and empty the bucket
  before destroying the stack.
- Terraform state uses a separate, pre-created S3 bucket. Before first initialization, enable
  versioning, encryption, and Block Public Access on that bucket. Initialize the new `us-east-1`
  stack with a separate state key:

  ```bash
  terraform -chdir=infra/envs/dev init -reconfigure \
    -backend-config="bucket=YOUR_TERRAFORM_STATE_BUCKET" \
    -backend-config="key=bisectr/dev/us-east-1/terraform.tfstate" \
    -backend-config="region=ap-south-1" \
    -backend-config="encrypt=true" \
    -backend-config="use_lockfile=true"
  ```

  The backend region above is the existing state bucket's region; it is independent of the AWS
  provider region (`us-east-1`). `-reconfigure` selects a separate state key and preserves the old
  `ap-south-1` stack. Do not use `-migrate-state` for this regional deployment. Keep the same backend
  arguments for later `terraform init` runs. The backend requires Terraform 1.10 or later and uses S3
  native lockfiles; choose a different key for every environment and region.
- `bisectr trends` reads recent runs. The `bisectr-runs` table has a `kind-created_at-index`; apply
  the Terraform change before using cloud-backed trends. Local history is read from JSON files in
  `runs/`.
- `bisectr validate --baseline IMAGE --candidate IMAGE --trials 5` repeats comparisons without
  reusing cached baselines. It writes the trial data to CSV and stores run records according to the
  configured local or cloud storage.
- The old `ap-south-1` stack is intentionally retained until the `us-east-1` stack has been verified.
  Review the selected Terraform backend/state before any teardown; destroying one region does not
  destroy the other.
- Tear down the currently selected stack only after review: `terraform -chdir=infra/envs/dev destroy -var=region=us-east-1`
