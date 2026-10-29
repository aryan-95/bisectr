# Runbook

Replace bracketed placeholders such as `<arn>` with actual values, without typing the angle brackets.

- Stop everything: `aws ssm put-parameter --name /bisectr/enabled --value false --overwrite`
- Resume: same command with `--value true`
- Runs are also blocked when actual spend reaches 90% of `bisectr-monthly`. Budget notifications at
  50% and 90% publish to the `bisectr-budget-alerts` SNS topic; configure `alert_email` to subscribe.
- Find stray tasks: `aws ecs list-tasks --cluster bisectr`
- Stop one: `aws ecs stop-task --cluster bisectr --task <arn>`
- Read a probe's logs: CloudWatch log group `/bisectr/probe`, stream `runner/runner/<task-id>`
- Run records and baseline cache entries are in DynamoDB tables `bisectr-runs` and
  `bisectr-baselines`; both use TTL. HTML reports are private objects under `reports/` in the S3
  bucket named by the Terraform output `reports_bucket` and expire after 90 days. The bucket is not
  emptied automatically by `terraform destroy`: export any reports you need and empty the bucket
  before destroying the stack.
- Terraform state uses a separate, pre-created S3 bucket. Before first initialization, enable
  versioning, encryption, and Block Public Access on that bucket. Migrate existing local state with:

  ```bash
  terraform -chdir=infra/envs/dev init -migrate-state \
    -backend-config="bucket=YOUR_TERRAFORM_STATE_BUCKET" \
    -backend-config="key=bisectr/dev/terraform.tfstate" \
    -backend-config="region=ap-south-1" \
    -backend-config="encrypt=true" \
    -backend-config="use_lockfile=true"
  ```

  For a new environment with no local state, omit `-migrate-state`. Keep the same backend arguments
  for later `terraform init` runs. The backend requires Terraform 1.10 or later and uses S3 native
  lockfiles; choose a different key for every environment.
- `bisectr trends` reads recent runs. The `bisectr-runs` table has a `kind-created_at-index`; apply
  the Terraform change before using cloud-backed trends. Local history is read from JSON files in
  `runs/`.
- `bisectr validate --baseline IMAGE --candidate IMAGE --trials 5` repeats comparisons without
  reusing cached baselines. It writes the trial data to CSV and stores run records according to the
  configured local or cloud storage.
- Tear down: `cd infra/envs/dev && terraform destroy`
