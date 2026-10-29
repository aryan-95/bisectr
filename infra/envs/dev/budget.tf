variable "alert_email" {
  type        = string
  default     = ""
  description = "Email subscriber for budget alerts. Empty leaves the SNS topic without an email subscription."
}
variable "monthly_budget_usd" {
  type    = string
  default = "20"
}

resource "aws_budgets_budget" "monthly" {
  name         = "bisectr-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 90]
    content {
      comparison_operator       = "GREATER_THAN"
      threshold                 = notification.value
      threshold_type            = "PERCENTAGE"
      notification_type         = "ACTUAL"
      subscriber_sns_topic_arns = [aws_sns_topic.budget_alerts.arn]
    }
  }

  depends_on = [aws_sns_topic_policy.budget_alerts]
}

resource "aws_sns_topic" "budget_alerts" {
  name = "bisectr-budget-alerts"
}

resource "aws_sns_topic_policy" "budget_alerts" {
  arn = aws_sns_topic.budget_alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowAWSBudgetsPublish"
      Effect    = "Allow"
      Principal = { Service = "budgets.amazonaws.com" }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.budget_alerts.arn
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.me.account_id
        }
      }
    }]
  })
}

resource "aws_sns_topic_subscription" "budget_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.budget_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

output "budget_name" {
  value = aws_budgets_budget.monthly.name
}

output "budget_alert_topic_arn" {
  value = aws_sns_topic.budget_alerts.arn
}
