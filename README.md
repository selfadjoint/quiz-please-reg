
# QuizPlease Game Registration

This project contains an AWS Lambda function and Terraform configuration to register for QuizPlease games. The Lambda function scrapes the game schedule, processes game details, registers for new games, and stores game data in DynamoDB. It also send the list of non-classic games to the Telegram group.

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
dynamodb_table_name        = "QuizPleaseGames"
aws_credentials_file       = "~/.aws/credentials"
aws_profile                = "default"
bot_token                  = "1234567890:ABCDEF"
group_id                   = "-1234567890"
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

## Clean Up
To remove all resources created by Terraform, run:
```bash
terraform destroy
```
This will tear down the deployed AWS resources.
