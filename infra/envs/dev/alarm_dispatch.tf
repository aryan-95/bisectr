variable "enable_alarm_bisect" {
  type        = bool
  default     = false
  description = "Enable CloudWatch alarm-triggered main-image bisect and verified revert PR automation."
}

variable "alarm_name_prefix" {
  type        = string
  default     = "bisectr-"
  description = "Only ALARM transitions for alarms beginning with this name prefix dispatch investigations."
}

variable "github_dispatch_token_secret_arn" {
  type        = string
  default     = ""
  description = "ARN of a Secrets Manager secret containing a fine-grained GitHub token with Actions:write."
}

check "alarm_bisect_configuration" {
  assert {
    condition = !var.enable_alarm_bisect || (
      var.github_repo != "" &&
      var.github_dispatch_token_secret_arn != "" &&
      var.alarm_name_prefix != ""
    )
    error_message = "Alarm bisect requires github_repo, github_dispatch_token_secret_arn, and a non-empty alarm_name_prefix."
  }
}

locals {
  main_build_range_parameter_arn = "arn:aws:ssm:${local.reg}:${local.acct}:parameter/bisectr/main-build-range"
}

data "archive_file" "alarm_dispatch" {
  type        = "zip"
  source_file = "${path.module}/../../../lambdas/alarm_dispatch/handler.py"
  output_path = "${path.module}/.alarm-dispatch.zip"
}

resource "aws_dynamodb_table" "alarm_dispatches" {
  count        = var.enable_alarm_bisect ? 1 : 0
  name         = "bisectr-alarm-dispatches"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "event_id"

  attribute {
    name = "event_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

resource "aws_iam_role" "alarm_dispatch" {
  count = var.enable_alarm_bisect ? 1 : 0
  name  = "bisectr-alarm-dispatch"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "alarm_dispatch_logs" {
  count      = var.enable_alarm_bisect ? 1 : 0
  role       = aws_iam_role.alarm_dispatch[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "alarm_dispatch" {
  count             = var.enable_alarm_bisect ? 1 : 0
  name              = "/aws/lambda/bisectr-alarm-dispatch"
  retention_in_days = 14
}

resource "aws_iam_role_policy" "alarm_dispatch" {
  count = var.enable_alarm_bisect ? 1 : 0
  name  = "bisectr-alarm-dispatch"
  role  = aws_iam_role.alarm_dispatch[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = local.main_build_range_parameter_arn
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.github_dispatch_token_secret_arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:DeleteItem"]
        Resource = aws_dynamodb_table.alarm_dispatches[0].arn
      }
    ]
  })
}

resource "aws_lambda_function" "alarm_dispatch" {
  count            = var.enable_alarm_bisect ? 1 : 0
  function_name    = "bisectr-alarm-dispatch"
  role             = aws_iam_role.alarm_dispatch[0].arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.alarm_dispatch.output_path
  source_code_hash = data.archive_file.alarm_dispatch.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      ALARM_NAME_PREFIX       = var.alarm_name_prefix
      DISPATCH_TABLE          = aws_dynamodb_table.alarm_dispatches[0].name
      GITHUB_REPOSITORY       = var.github_repo
      GITHUB_TOKEN_SECRET_ARN = var.github_dispatch_token_secret_arn
      GITHUB_WORKFLOW         = "bisectr-alarm.yml"
      GITHUB_REF              = "main"
      RANGE_PARAMETER         = "/bisectr/main-build-range"
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.alarm_dispatch_logs,
    aws_cloudwatch_log_group.alarm_dispatch,
  ]
}

resource "aws_cloudwatch_event_rule" "alarm_dispatch" {
  count       = var.enable_alarm_bisect ? 1 : 0
  name        = "bisectr-alarm-dispatch"
  description = "Dispatch a guarded Bisectr investigation for matching CloudWatch ALARM transitions."

  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = [{ prefix = var.alarm_name_prefix }]
      state     = { value = ["ALARM"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "alarm_dispatch" {
  count     = var.enable_alarm_bisect ? 1 : 0
  rule      = aws_cloudwatch_event_rule.alarm_dispatch[0].name
  target_id = "bisectr-alarm-dispatch"
  arn       = aws_lambda_function.alarm_dispatch[0].arn
  depends_on = [
    aws_lambda_permission.alarm_dispatch,
  ]
}

resource "aws_lambda_permission" "alarm_dispatch" {
  count         = var.enable_alarm_bisect ? 1 : 0
  statement_id  = "AllowCloudWatchAlarmEvents"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.alarm_dispatch[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.alarm_dispatch[0].arn
}

output "alarm_dispatch_lambda_arn" {
  value = try(aws_lambda_function.alarm_dispatch[0].arn, "")
}
