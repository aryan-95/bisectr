terraform {
  required_version = ">= 1.10.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {}
}

variable "region" { default = "us-east-1" }
provider "aws" { region = var.region }

locals {
  region_suffix = replace(var.region, "-", "")
}

data "aws_vpc" "default" { default = true }
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_ecr_repository" "svc" {
  name         = "bisectr-demo"
  force_delete = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "runner" {
  name         = "bisectr-runner"
  force_delete = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_lifecycle_policy" "recent_images" {
  for_each = {
    service = aws_ecr_repository.svc.name
    runner  = aws_ecr_repository.runner.name
  }

  repository = each.value
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 100 most recently pushed images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 100
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecs_cluster" "c" { name = "bisectr" }

resource "aws_cloudwatch_log_group" "probe" {
  name              = "/bisectr/probe"
  retention_in_days = 7
}

# zero inbound, outbound 443 only (ECR pull + log shipping)
resource "aws_security_group" "probe" {
  name   = "bisectr-probe"
  vpc_id = data.aws_vpc.default.id
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# execution role only (pull image, write logs). Probe tasks get NO task role.
resource "aws_iam_role" "exec" {
  name = "bisectr-exec-${local.region_suffix}"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "exec" {
  role       = aws_iam_role.exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_ssm_parameter" "kill_switch" {
  name  = "/bisectr/enabled"
  type  = "String"
  value = "true"
}

output "region" { value = var.region }
output "svc_repo" { value = aws_ecr_repository.svc.repository_url }
output "runner_repo" { value = aws_ecr_repository.runner.repository_url }
output "cluster" { value = aws_ecs_cluster.c.name }
output "subnets" { value = data.aws_subnets.default.ids }
output "sg" { value = aws_security_group.probe.id }
output "exec_role" { value = aws_iam_role.exec.arn }
output "log_group" { value = aws_cloudwatch_log_group.probe.name }
