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

resource "aws_iam_role_policy" "lambda_dynamodb_access" {
  name = var.resource_name
  role = aws_iam_role.lambda_execution_role.id

  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Scan",
        "dynamodb:Query"
      ],
      "Resource": "${aws_dynamodb_table.game_ids_table.arn}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:Scan",
        "dynamodb:Query"
      ],
      "Resource": "${aws_dynamodb_table.game_ids_table.arn}/index/*"
    }
  ]
}
EOF
}

resource "aws_dynamodb_table" "game_ids_table" {
  name         = var.resource_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "game_id"

  attribute {
    name = "game_id"
    type = "N"
  }

  attribute {
    name = "game_date"
    type = "S"
  }

  attribute {
    name = "is_poll_created"
    type = "N"
  }

  global_secondary_index {
    name            = "game_date_index"
    hash_key        = "game_date"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "poll_created_index"
    hash_key        = "is_poll_created"
    range_key       = "game_id"
    projection_type = "ALL"
  }

  tags = var.tags
}

resource "aws_lambda_function" "game_reg" {
  description      = "Register for QuizPlease games and send notifications to Telegram group"
  function_name    = var.resource_name
  role             = aws_iam_role.lambda_execution_role.arn
  handler          = "main.lambda_handler"
  runtime          = "python3.11"
  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  timeout          = 300

  environment {
    variables = {
      TEAM_NAME           = var.team_name
      CPT_EMAIL           = var.cpt_email
      CPT_NAME            = var.cpt_name
      CPT_PHONE           = var.cpt_phone
      TEAM_SIZE           = var.team_size
      PROMOTION_CODE      = var.promotion_code
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.game_ids_table.name
      BOT_TOKEN           = var.bot_token
      GROUP_ID            = var.group_id
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
  description         = "Scheduled rule to trigger new game registrations every Monday"
  schedule_expression = "cron(15 11 ? * MON *)"
}

resource "aws_cloudwatch_event_target" "lambda_target" {
  rule      = aws_cloudwatch_event_rule.schedule_rule.name
  target_id = var.resource_name
  arn       = aws_lambda_function.game_reg.arn
}