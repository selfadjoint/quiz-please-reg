terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.26"
    }
  }

  required_version = ">= 1.2.0"
}


provider "aws" {
  region                   = var.aws_region
  shared_credentials_files = var.aws_credentials_file
  profile                  = var.aws_profile
}

data "aws_iam_policy_document" "lambda_assume_role_policy" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_execution_role" {
  name               = "lambda_execution_role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role_policy.json
}

resource "aws_iam_role_policy_attachment" "lambda_execution_role_policy_attachment" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_dynamodb_access" {
  name = "lambda_dynamodb_access"
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
  name         = var.dynamodb_table_name
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

resource "aws_lambda_function" "lambda_function" {
  description   = "Register for QuizPlease games"
  filename      = "lambda.zip"
  function_name = "QuizPleaseReg"
  role          = aws_iam_role.lambda_execution_role.arn
  handler       = "main.lambda_handler"

  source_code_hash = filebase64sha256("lambda.zip")

  runtime = "python3.11"
  timeout = 300

  environment {
    variables = {
      TEAM_NAME           = var.team_name
      CPT_EMAIL           = var.cpt_email
      CPT_NAME            = var.cpt_name
      CPT_PHONE           = var.cpt_phone
      TEAM_SIZE           = var.team_size
      DYNAMODB_TABLE_NAME = var.dynamodb_table_name
      BOT_TOKEN           = var.bot_token
      GROUP_ID            = var.group_id
    }
  }

  tags = var.tags
}

resource "aws_cloudwatch_event_rule" "every_monday_rule" {
  name                = "every_monday_rule"
  schedule_expression = "cron(15 11 ? * MON *)"
}

resource "aws_cloudwatch_event_target" "every_monday_target" {
  rule      = aws_cloudwatch_event_rule.every_monday_rule.name
  target_id = "lambda_function_target"
  arn       = aws_lambda_function.lambda_function.arn
}

resource "aws_lambda_permission" "allow_cloudwatch_to_call_lambda" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.lambda_function.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_monday_rule.arn
}