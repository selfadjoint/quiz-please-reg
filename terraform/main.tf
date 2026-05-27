terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.26"
    }
  }

  required_version = ">= 1.10.0"
  backend "s3" {}
}


provider "aws" {
  region                   = var.aws_region
  shared_credentials_files = var.aws_credentials_file
  profile                  = var.aws_profile
}

resource "aws_ecr_repository" "quiz_please_reg" {
  name                 = lower(var.resource_name)
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = false
  }

  tags = var.tags
}

resource "aws_ecr_repository_policy" "lambda_access" {
  repository = aws_ecr_repository.quiz_please_reg.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "LambdaECRAccess"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    }]
  })
}

resource "aws_iam_role" "lambda_execution_role" {
  name = var.resource_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Action = "sts:AssumeRole",
        Effect = "Allow",
        Sid    = "",
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_execution_role_policy_attachment" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "game_reg" {
  description   = "Register for QuizPlease games and persist state in PostgreSQL"
  function_name = var.resource_name
  role          = aws_iam_role.lambda_execution_role.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.quiz_please_reg.repository_url}:${var.image_tag}"
  timeout       = 300
  memory_size   = 2048

  environment {
    variables = {
      TEAM_NAME      = var.team_name
      CPT_EMAIL      = var.cpt_email
      CPT_NAME       = var.cpt_name
      CPT_PHONE      = var.cpt_phone
      TEAM_SIZE      = var.team_size
      PROMOTION_CODE = var.promotion_code
      DB_HOST        = var.db_host
      DB_PORT        = var.db_port
      DB_NAME        = var.db_name
      DB_USER        = var.db_user
      DB_PASSWORD    = var.db_password
      BOT_TOKEN      = var.bot_token
      GROUP_ID       = var.group_id
      ADMIN_CHAT_ID  = var.admin_chat_id != "" ? var.admin_chat_id : var.group_id
      PROXY_URL      = var.proxy_url
    }
  }

  tags = var.tags
}

resource "aws_lambda_permission" "allow_execution" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.game_reg.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule_rule.arn
}

resource "aws_cloudwatch_event_rule" "schedule_rule" {
  name                = var.resource_name
  description         = "Scheduled rule to trigger new game registrations every Monday and Friday"
  schedule_expression = "cron(15 11 ? * MON,FRI *)"
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.schedule_rule.name
  target_id = var.resource_name
  arn       = aws_lambda_function.game_reg.arn
}

output "ecr_repository_url" {
  value = aws_ecr_repository.quiz_please_reg.repository_url
}
