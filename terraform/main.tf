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

# Archive the Lambda code directory into a zip file.
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/lambda.zip"
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
  description      = "Register for QuizPlease games and persist state in PostgreSQL"
  function_name    = var.resource_name
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "main.lambda_handler"
  runtime          = "python3.11"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 300

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
