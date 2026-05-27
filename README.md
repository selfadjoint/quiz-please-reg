
# QuizPlease Game Registration

AWS Lambda function that automatically registers for QuizPlease Yerevan classic games. Scrapes the game schedule, registers for new classic games, stores tracking state in PostgreSQL, and sends Telegram notifications.

## Project Structure

```
├── src/
│   ├── main.py               # Lambda handler: scraping, registration, Telegram
│   ├── game_details.py       # HTML parser for game pages
│   ├── postgres_store.py     # PostgreSQL helpers
│   └── requirements.txt      # Python dependencies
├── sql/
│   └── schema.sql            # PostgreSQL schema (quizplease schema, 2 tables, 1 view)
├── terraform/
│   ├── main.tf               # Lambda + ECR + CloudWatch + IAM
│   ├── variables.tf          # Input variables
│   └── backend.hcl           # S3 backend config (not committed)
├── scripts/
│   └── deploy.sh             # Build Docker image, push to ECR, update Lambda
├── Dockerfile                # Python 3.12 + Playwright/Chromium + Xvfb
└── docs/
    └── postgres-migration.md # DynamoDB → Postgres migration notes
```

## Prerequisites

- [AWS CLI](https://aws.amazon.com/cli/) configured
- [Docker](https://www.docker.com/) (for building the Lambda container image)
- [Terraform](https://www.terraform.io/)
- PostgreSQL instance
- Telegram bot token and group

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-repo/quiz-please-reg.git
cd quiz-please-reg
```

### 2. Configure Terraform backend

Create `terraform/backend.hcl`:
```hcl
bucket       = "your-tf-state-bucket"
key          = "quiz-please-reg/terraform.tfstate"
region       = "eu-central-1"
profile      = "your-aws-profile"
encrypt      = true
```

### 3. Configure Terraform variables

Create `terraform/terraform.tfvars`:
```hcl
aws_credentials_file = ["~/.aws/credentials"]
aws_region           = "eu-central-1"
aws_profile          = "default"
resource_name        = "QuizPleaseReg"
image_tag            = "latest"

team_name       = "YourTeamName"
cpt_email       = "captain@example.com"
cpt_name        = "Captain Name"
cpt_phone       = "+1234567890"
team_size       = "5"
promotion_code  = ""

db_host     = "your-postgres-host"
db_port     = "5432"
db_name     = "quizplease"
db_user     = "quizplease_app"
db_password = "your-password"

bot_token     = "1234567890:ABCDEF"
group_id      = "-1234567890"
admin_chat_id = ""        # Optional; defaults to group_id
proxy_url     = ""        # Optional; routes browser traffic through proxy
```

### 4. Initialize Terraform and provision AWS resources

```bash
cd terraform
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

### 5. Apply the database schema

```bash
psql -h your-host -U your-user -d quizplease -f sql/schema.sql
```

### 6. Deploy the Lambda

```bash
./scripts/deploy.sh [--profile your-aws-profile]
```

This builds a `linux/amd64` Docker image, pushes it to ECR, and updates the Lambda function.

## How It Works

The Lambda runs every Monday and Friday at 11:15 UTC. It:

1. Launches a headed Chromium browser via Xvfb (required to bypass Cloudflare Bot Management — headless Chrome is blocked from AWS IPs).
2. Scrapes `yerevan.quizplease.com/schedule` to find upcoming games.
3. Classifies games: classic ("Квиз, плиз! YEREVAN") vs. themed.
4. Registers for new classic games via `fetch()` POST executed inside the browser (so the request uses Chrome's TLS fingerprint and session cookies).
5. Fetches full game metadata from each game page.
6. Stores metadata and registration state in PostgreSQL (`quizplease` schema).
7. Sends Telegram notifications: registered classic games + upcoming themed games.

## Manual Invocation

Register for specific game IDs without scraping:

```bash
aws lambda invoke \
  --function-name QuizPleaseReg \
  --payload '{"game_ids": [123456]}' \
  --region eu-central-1 \
  --profile your-profile \
  --cli-binary-format raw-in-base64-out \
  --log-type Tail \
  --cli-read-timeout 320 \
  response.json \
  --query 'LogResult' --output text | base64 -d
```

Manual mode skips scraping, works for both classic and themed games, and skips already-registered games.

## Environment Variables

| Variable | Description |
|---|---|
| `TEAM_NAME` | Quiz team name |
| `CPT_EMAIL` | Captain email |
| `CPT_NAME` | Captain name |
| `CPT_PHONE` | Captain phone |
| `TEAM_SIZE` | Number of team members |
| `PROMOTION_CODE` | Promo/certificate code (optional) |
| `DB_HOST` | PostgreSQL host |
| `DB_PORT` | PostgreSQL port |
| `DB_NAME` | PostgreSQL database name |
| `DB_USER` | PostgreSQL user |
| `DB_PASSWORD` | PostgreSQL password |
| `BOT_TOKEN` | Telegram bot token |
| `GROUP_ID` | Telegram group ID for notifications |
| `ADMIN_CHAT_ID` | Telegram chat ID for error alerts (defaults to `GROUP_ID`) |
| `PROXY_URL` | Optional proxy for browser traffic |

## Database Schema

Schema `quizplease`, not `public`:

- `quizplease.games` — game metadata (date, time, venue, category, game_name, game_number)
- `quizplease.game_registration_tracking` — bot state (registered_on, poll_created, poll_date)
- `quizplease.game_registration_overview` — view joining both tables

See `sql/schema.sql` for full definitions.

## Monitoring

CloudWatch logs at `/aws/lambda/QuizPleaseReg`. Error notifications sent automatically to `ADMIN_CHAT_ID`.

## Clean Up

```bash
cd terraform && terraform destroy
```
