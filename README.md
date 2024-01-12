
# QuizPlease Registration Automation

## Overview
This project contains a Python script for automating the registration process for QuizPlease classical games in Yerevan. Additionally, there's a Terraform script provided to deploy this automation as an AWS Lambda function, which will interact with DynamoDB and AWS CloudWatch. All the AWS resources usage is within the Free Tier.

## Prerequisites
- Python 3.x
- AWS account with appropriate permissions
- Terraform version >= 1.2.0
- AWS CLI, configured with access to your AWS account

## Configuration
Create a `config.py` file within the project directory, with a dictionary named `team` containing the necessary team information for the game registration:

```python
team = {
    'team_name': '<Team Name>',
    'cpt_phone': '<Captain Phone>',
    'cpt_email': '<Captain Email>',
    'cpt_name': '<Captain Name>',
    'team_size': <Number of Team Members>
}
```

Replace the placeholders with your team's actual information.

Replace Terraform parameters, such as the AWS profile or region, in the `main.tf` file if necessary.

## Python Script
The Python script `lambda_function.py` includes several functions:
- `get_game_ids()`: Scrapes the game IDs from the registration page.
- `save_game_ids()`: Stores the game IDs into a DynamoDB table.
- `load_game_ids()`: Retrieves the game IDs that have already been registered.
- `register()`: Registers for a game given a game ID.
- `lambda_handler()`: The AWS Lambda handler that runs the registration functions.

## Terraform Script
The Terraform script `main.tf` will set up:
- An IAM role for the Lambda function.
- A DynamoDB table to store game IDs.
- The Lambda function with the necessary permissions and environment variables.
- A CloudWatch Event Rule to trigger the Lambda function on a schedule.
- Permissions for CloudWatch to invoke the Lambda function.

## Deployment
To deploy the automation:
1. Navigate to the directory with the Terraform script.
2. Run `terraform init`.
3. Run `terraform apply`.

## Usage
Once deployed, the Lambda function will be triggered by CloudWatch Events as per the defined schedule (every Monday) to register the team for new classical QuizPlease games.

## Notes
- Ensure the AWS CLI is properly set up with the necessary permissions.
- You may need to adjust the CloudWatch Event Rule in the Terraform script for your scheduling needs.
- The `config.py` file is crucial for the script to run; it must be present with valid configurations.

## License
This project is open-sourced under the MIT License.
