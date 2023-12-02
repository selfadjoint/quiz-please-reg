import boto3
import json

# Initialize a DynamoDB client
session = boto3.Session(profile_name='personal')
dynamodb = session.resource('dynamodb', region_name='us-east-1')

# Specify the name of your DynamoDB table
table_name = 'QuizPleaseReg'
table = dynamodb.Table(table_name)

# Load the data from the JSON file
with open('game_ids.json', 'r') as file:
    data = json.load(file)

# Get the list of game IDs
game_ids = data['game_ids']

# Upload the list of game IDs as a single item to the DynamoDB table
item = {'game_id': 'game_ids', 'game_ids': game_ids}
table.put_item(Item=item)