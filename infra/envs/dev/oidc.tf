variable "github_repo" {
  type        = string
  default     = ""
  description = "OWNER/REPO allowed to assume the CI role. Empty = skip OIDC."
}
variable "create_oidc_provider" {
  type        = bool
  default     = true
  description = "Set false if the GitHub OIDC provider already exists in this account."
}

data "aws_caller_identity" "me" {}
data "aws_region" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.github_repo != "" && var.create_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

locals {
  acct = data.aws_caller_identity.me.account_id
  reg  = data.aws_region.current.name
  oidc_arn = try(aws_iam_openid_connect_provider.github[0].arn,
  "arn:aws:iam::${local.acct}:oidc-provider/token.actions.githubusercontent.com")
}

resource "aws_iam_role" "ci" {
  count = var.github_repo != "" ? 1 : 0
  name  = "bisectr-ci"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = local.oidc_arn }
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike   = { "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "ci" {
  count = var.github_repo != "" ? 1 : 0
  name  = "bisectr-ci"
  role  = aws_iam_role.ci[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      {
        Effect = "Allow"
        Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer", "ecr:DescribeImages"]
        Resource = [aws_ecr_repository.svc.arn, aws_ecr_repository.runner.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:RegisterTaskDefinition", "ecs:DescribeTaskDefinition", "ecs:DeregisterTaskDefinition"]
        Resource = "*"
      },
      {
        Effect    = "Allow"
        Action    = "ecs:RunTask"
        Resource  = "arn:aws:ecs:${local.reg}:${local.acct}:task-definition/bisectr-probe:*"
        Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.c.arn } }
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeTasks", "ecs:StopTask"]
        Resource = "arn:aws:ecs:${local.reg}:${local.acct}:task/${aws_ecs_cluster.c.name}/*"
      },
      {
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = aws_iam_role.exec.arn
        Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" } }
      },
      { Effect = "Allow", Action = "logs:GetLogEvents", Resource = "${aws_cloudwatch_log_group.probe.arn}:*" },
      { Effect = "Allow", Action = "ssm:GetParameter", Resource = aws_ssm_parameter.kill_switch.arn }
    ]
  })
}

output "ci_role_arn" { value = try(aws_iam_role.ci[0].arn, "") }
