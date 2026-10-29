data "archive_file" "reaper" {
  type        = "zip"
  source_file = "${path.module}/../../../lambdas/reaper/handler.py"
  output_path = "${path.module}/.reaper.zip"
}

resource "aws_iam_role" "reaper" {
  name = "bisectr-reaper"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "reaper_logs" {
  role       = aws_iam_role.reaper.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "reaper" {
  name = "bisectr-reaper"
  role = aws_iam_role.reaper.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "ecs:ListTasks"
        Resource  = "*"
        Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.c.arn } }
      },
      {
        Effect   = "Allow"
        Action   = "ecs:ListTaskDefinitions"
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:DescribeTasks", "ecs:StopTask"]
        Resource = "arn:aws:ecs:${local.reg}:${local.acct}:task/${aws_ecs_cluster.c.name}/*"
      },
      {
        Effect   = "Allow"
        Action   = "ecs:DeregisterTaskDefinition"
        Resource = "arn:aws:ecs:${local.reg}:${local.acct}:task-definition/bisectr-probe:*"
      }
    ]
  })
}

resource "aws_lambda_function" "reaper" {
  function_name    = "bisectr-reaper"
  role             = aws_iam_role.reaper.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.reaper.output_path
  source_code_hash = data.archive_file.reaper.output_base64sha256
  timeout          = 60
  environment {
    variables = {
      CLUSTER        = aws_ecs_cluster.c.name
      MAX_MINUTES    = "30"
      FAMILY         = "bisectr-probe"
      KEEP_REVISIONS = "50"
    }
  }
}

resource "aws_cloudwatch_event_rule" "reaper" {
  name                = "bisectr-reaper-schedule"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "reaper" {
  rule = aws_cloudwatch_event_rule.reaper.name
  arn  = aws_lambda_function.reaper.arn
}

resource "aws_lambda_permission" "reaper" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.reaper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.reaper.arn
}
