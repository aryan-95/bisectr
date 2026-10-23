# Runbook

- Stop everything: `aws ssm put-parameter --name /bisectr/enabled --value false --overwrite`
- Resume: same command with `--value true`
- Find stray tasks: `aws ecs list-tasks --cluster bisectr`
- Stop one: `aws ecs stop-task --cluster bisectr --task <arn>`
- Read a probe's logs: CloudWatch log group `/bisectr/probe`, stream `runner/runner/<task-id>`
- Tear down: `cd infra/envs/dev && terraform destroy`
