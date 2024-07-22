
# QuizPlease Game Registration

This project contains an AWS Lambda function and Terraform configuration to register for QuizPlease games. The Lambda function scrapes the game schedule, processes game details, registers for new games, and stores game data in DynamoDB. It also send the list of non-classic games to the Telegram group.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
- [Important Note](#important-note)

## Prerequisites

Before you begin, ensure you have the following installed:

- [AWS CLI](https://aws.amazon.com/cli/)
- [Terraform](https://www.terraform.io/)
- [Python 3.8+](https://www.python.org/)
- [pip](https://pip.pypa.io/en/stable/)
- [Telegram bot and a group to send info to](https://core.telegram.org/bots)

## Project Structure

```plaintext
quiz-please-reg/
├── src/
│   ├── main.py
│   ├── requirements.txt
│   ├── dependencies
├── terraform/
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── lambda.zip
├── README.md
```

## Setup

1. **Clone the repository**:

   ```bash
   git clone https://github.com/your-repo/quiz-plese-reg.git
   cd quiz-please-reg

2. **Navigate to the Terraform directory**:

   ```bash
   cd ../terraform
   ```

3. **Initialize Terraform**:

   ```bash
   terraform init
   ```

4. **Create a `terraform.tfvars` file with the necessary variables. Example**:

   ```hcl
   aws_region                 = "us-east-1"
   team_name                  = "YourTeamName"
   cpt_email                  = "your-email@example.com"
   cpt_name                   = "YourCaptainName"
   cpt_phone                  = "1234567890"
   team_size                  = "5"
   dynamodb_table_name        = "QuizPleaseGames"
   aws_credentials_file       = "~/.aws/credentials"
   aws_profile                = "default"
   bot_token                  = "1234567890:ABCDEF"
   group_id                   = "-1234567890"
   ```

4. **Apply the Terraform configuration**:

   ```bash
   terraform apply
   ```

   Review the changes and type `yes` to confirm.

## Environment Variables

The Lambda function uses the following environment variables:

- `TEAM_NAME`: Name of the quiz team.
- `CPT_EMAIL`: Email of the team captain.
- `CPT_NAME`: Name of the team captain.
- `CPT_PHONE`: Phone number of the team captain.
- `TEAM_SIZE`: Number of team members.
- `DYNAMODB_TABLE_NAME`: Name of the DynamoDB table to store game data.
- `BOT_TOKEN`: Telegram bot token.
- `GROUP_ID`: Telegram group ID.

These variables are set in the Terraform configuration and passed to the Lambda function during deployment.

## Usage

Once deployed, the Lambda function will run every Monday at 11:15 UTC. It will:

1. Scrape the game schedule from the QuizPlease website.
2. Process and store new classic game details in DynamoDB.
3. Register the team for that games.
4. Send the list of non-classic games to the Telegram group.

Logs for the Lambda function can be viewed in AWS CloudWatch.

## License

This project is licensed under the MIT License.
