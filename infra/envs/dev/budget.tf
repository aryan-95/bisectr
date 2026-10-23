variable "alert_email" {
  type        = string
  default     = ""
  description = "Email for budget alerts. Empty = no budget created."
}
variable "monthly_budget_usd" {
  type    = string
  default = "20"
}

resource "aws_budgets_budget" "monthly" {
  count        = var.alert_email != "" ? 1 : 0
  name         = "bisectr-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 90
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
