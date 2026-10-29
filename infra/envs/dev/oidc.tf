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
variable "gitlab_project_path" {
  type        = string
  default     = ""
  description = "GitLab group/project path allowed to assume the protected-branch CI role."
}
variable "gitlab_ref" {
  type        = string
  default     = "main"
  description = "Protected GitLab branch allowed to assume the CI role."
}
variable "create_gitlab_oidc_provider" {
  type        = bool
  default     = true
  description = "Set false if the GitLab OIDC provider already exists in this account."
}

data "aws_caller_identity" "me" {}
data "aws_region" "current" {}

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.github_repo != "" && var.create_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_openid_connect_provider" "gitlab" {
  count          = var.gitlab_project_path != "" && var.create_gitlab_oidc_provider ? 1 : 0
  url            = "https://gitlab.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  acct = data.aws_caller_identity.me.account_id
  reg  = data.aws_region.current.name
  oidc_arn = try(aws_iam_openid_connect_provider.github[0].arn,
  "arn:aws:iam::${local.acct}:oidc-provider/token.actions.githubusercontent.com")
  gitlab_oidc_arn = try(aws_iam_openid_connect_provider.gitlab[0].arn,
  "arn:aws:iam::${local.acct}:oidc-provider/gitlab.com")
  ci_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = "ecr:GetAuthorizationToken", Resource = "*" },
      {
        Effect = "Allow"
        Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:DescribeImages"]
        Resource = [aws_ecr_repository.svc.arn, aws_ecr_repository.runner.arn]
      },
      {
        Effect   = "Allow"
        Action   = "ecs:RegisterTaskDefinition"
        Resource = "arn:aws:ecs:${local.reg}:${local.acct}:task-definition/bisectr-probe:*"
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
      {
        Effect = "Allow"
        Action = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
        Resource = [
          aws_dynamodb_table.runs.arn,
          "${aws_dynamodb_table.runs.arn}/index/kind-created_at-index",
          aws_dynamodb_table.baselines.arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.reports.arn}/reports/*"
      },
      { Effect = "Allow", Action = "budgets:ViewBudget", Resource = "*" },
      { Effect = "Allow", Action = "ssm:GetParameter", Resource = aws_ssm_parameter.kill_switch.arn }
    ]
  })
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
  count  = var.github_repo != "" ? 1 : 0
  name   = "bisectr-ci"
  role   = aws_iam_role.ci[0].id
  policy = local.ci_policy
}

resource "aws_iam_role" "gitlab_ci" {
  count = var.gitlab_project_path != "" ? 1 : 0
  name  = "bisectr-gitlab-ci"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = local.gitlab_oidc_arn }
      Condition = {
        StringEquals = {
          "gitlab.com:aud" = "sts.amazonaws.com"
          "gitlab.com:sub" = "project_path:${var.gitlab_project_path}:ref_type:branch:ref:${var.gitlab_ref}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "gitlab_ci" {
  count  = var.gitlab_project_path != "" ? 1 : 0
  name   = "bisectr-gitlab-ci"
  role   = aws_iam_role.gitlab_ci[0].id
  policy = local.ci_policy
}

output "ci_role_arn" { value = try(aws_iam_role.ci[0].arn, "") }
output "gitlab_ci_role_arn" { value = try(aws_iam_role.gitlab_ci[0].arn, "") }
