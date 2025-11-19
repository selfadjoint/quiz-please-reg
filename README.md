
# QuizPlease Game Registration

This project contains an AWS Lambda function and Terraform configuration to automatically register for QuizPlease games. The Lambda function scrapes the game schedule, processes game details, registers for new classic games, and stores game data in DynamoDB. It also notifies about non-classic games via Telegram and supports manual invocation for specific game registrations.

The architecture uses AWS Lambda and DynamoDB to stay within AWS Free Tier limits, making it cost-effective to run continuously.

## Table of Contents

- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
- [Clean Up](#clean-up)

## Project Structure

```plaintext
├── src
│   ├── main.py                # Lambda function code
│   ├── requirements.txt       # Python dependency definitions
│   └── (other source files or folders)
└── terraform
    ├── main.tf                # Terraform configuration
    ├── variables.tf           # Input variables
    ├── backend.hcl            # Backend configuration (not committed; see below)
    └── (other Terraform files)
├── README.md
```

- **src**: Contains the Lambda function source code and the dependency definition.
- **terraform**: Contains the Terraform configuration for deploying AWS resources.


## Prerequisites

Before you begin, ensure you have the following installed:

- [AWS CLI](https://aws.amazon.com/cli/)
- [Terraform](https://www.terraform.io/)
- [Python 3.11+](https://www.python.org/)
- [pip](https://pip.pypa.io/en/stable/)
- [Telegram bot and a group to send info to](https://core.telegram.org/bots)


## Setup

### 1. Clone the repository:

   ```bash
   git clone https://github.com/your-repo/quiz-plese-reg.git
   cd quiz-please-reg

### 2. Install Python Dependencies
The dependencies are not committed to the repository. To install them into the src folder, run:
```bash
pip install --upgrade --target ./src -r src/requirements.txt
```
This command installs all required Python packages into the src directory so that they are included in the Lambda deployment package.

### 3. Configure the Terraform Backend and Variables
Terraform uses an S3 backend for state storage. Since sensitive information should not be committed to the repository, create a separate backend configuration file.

Create a file named `backend.hcl` inside the `terraform` folder with content similar to:

```hcl
bucket       = "your-tf-state-bucket"                  # Replace with your S3 bucket name
key          = "your-resource-name/terraform.tfstate"  # Adjust as needed
region       = "us-east-1"                             # Your AWS region
profile      = "your_aws_profile"                      # The AWS CLI profile to use
encrypt      = true
use_lockfile = true
```
**Create a `terraform.tfvars` file with the necessary variables. Example**:

```hcl
aws_credentials_file       = "~/.aws/credentials"
aws_region                 = "us-east-1"
team_name                  = "YourTeamName"
cpt_email                  = "your-email@example.com"
cpt_name                   = "YourCaptainName"
cpt_phone                  = "1234567890"
team_size                  = "5"
promotion_code             = "YOUR_PROMO_CODE"
dynamodb_table_name        = "QuizPleaseGames"
aws_credentials_file       = "~/.aws/credentials"
aws_profile                = "default"
bot_token                  = "1234567890:ABCDEF"
group_id                   = "-1234567890"
admin_chat_id              = "-9876543210"  # Optional, for error notifications
```

### 4. Initialize Terraform
Change to the terraform directory and initialize Terraform using the backend configuration:
```bash
cd terraform
terraform init -backend-config=backend.hcl
```
This command sets up the backend and downloads required providers.

### 5. Review and Apply the Terraform Configuration
First, run a plan to see the changes that Terraform will apply:
```bash
terraform plan
```

If everything looks correct, deploy the resources with:
```bash
terraform apply
```
Confirm the apply action when prompted.

## DynamoDB Table Structure

The Lambda function uses a DynamoDB table to track game information and registration status. This serverless architecture (Lambda + DynamoDB) is designed to operate within AWS Free Tier limits:

- **Lambda Free Tier**: 1 million requests per month, 400,000 GB-seconds of compute time per month
- **DynamoDB Free Tier**: 25 GB of storage, 25 read capacity units, 25 write capacity units

With weekly scheduled runs and occasional manual invocations, this project stays well within these limits.

**Table Schema:**

| Field | Type | Description |
|-------|------|-------------|
| `game_id` | Number | Unique game identifier (Primary Key) |
| `game_date` | String | Date of the game (YYYY-MM-DD) |
| `game_time` | String | Time of the game (HH:MM) |
| `game_venue` | String | Venue name |
| `game_type` | String | Type of game (e.g., "Классическая игра" or themed game name) |
| `is_classic` | Number | 1 for classic games, 0 for non-classic |
| `reg_date` | String | Date when registration was completed (only set after successful registration) |
| `is_poll_created` | Number | Flag for poll creation (0 or 1) |

**Game States:**
- **Notified only**: Game exists in table with no `reg_date` (non-classic games we've been notified about)
- **Registered**: Game exists in table with `reg_date` populated (games we've successfully registered for)

This structure allows the system to:
- Track which games have been seen to avoid duplicate notifications
- Track which games have been registered for to avoid duplicate registrations
- Support manual registration for previously-notified non-classic games

## Environment Variables

The Lambda function uses the following environment variables:

- `TEAM_NAME`: Name of the quiz team.
- `CPT_EMAIL`: Email of the team captain.
- `CPT_NAME`: Name of the team captain.
- `CPT_PHONE`: Phone number of the team captain.
- `TEAM_SIZE`: Number of team members.
- `PROMOTION_CODE`: Promotion code for registration.
- `DYNAMODB_TABLE_NAME`: Name of the DynamoDB table to store game data.
- `BOT_TOKEN`: Telegram bot token.
- `GROUP_ID`: Telegram group ID for general notifications.
- `ADMIN_CHAT_ID`: Telegram chat ID for error notifications (optional, defaults to GROUP_ID).

These variables are set in the Terraform configuration and passed to the Lambda function during deployment.

## Usage

### Scheduled Runs

Once deployed, the Lambda function will run every Monday at 11:15 UTC. It will:

1. Scrape the game schedule from the QuizPlease website.
2. Identify classic games ("Квиз, плиз! YEREVAN") and non-classic games (themed games).
3. Register the team for new classic games automatically.
4. Store game details in DynamoDB with registration status.
5. Send notifications about newly registered classic games to the Telegram group.
6. Send notifications about newly found non-classic games to the Telegram group (with game links for manual registration).
7. Send error notifications to the admin chat if any operations fail.

### Manual Runs

You can manually invoke the Lambda function to register for specific games:

```bash
# Using AWS CLI 
aws lambda invoke \
  --function-name quiz-please-reg \
  --payload '{"game_ids": [123456, 123457]}' \
  --profile your-profile \
  response.json
```

Manual invocations:
- Register only for the specified game IDs
- Skip site scraping and non-classic game notifications
- Work for both classic and non-classic games
- Skip games that are already registered

### Features

- **CAPTCHA Avoidance**: The function visits the schedule page first to establish a proper session and avoid CAPTCHA triggers.
- **Retry Logic**: Failed operations (game attribute fetching, registration) are automatically retried up to 3 times with 20-second delays.
- **Error Notifications**: All errors are collected and sent as a summary to the admin chat for monitoring.
- **Smart Game Tracking**: Games are tracked in DynamoDB with separate flags for notification and registration status.
- **Rate Limiting Protection**: Built-in delays between requests to appear more human-like.

### Monitoring

Logs for the Lambda function can be viewed in AWS CloudWatch. Error notifications are automatically sent to the configured Telegram admin chat.

## Clean Up
To remove all resources created by Terraform, run:
```bash
terraform destroy
```
This will tear down the deployed AWS resources.
