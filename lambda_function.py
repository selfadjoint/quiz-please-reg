from time import sleep
import requests as req
import logging
from bs4 import BeautifulSoup
import boto3
from config import team

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s.%(msecs)03d %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Set up constants
REG_LIST_URL = 'https://yerevan.quizplease.ru/schedule'
DYNAMODB_TABLE_NAME = 'QuizPleaseReg'
REG_URL = 'https://yerevan.quizplease.am/ajax/save-record'

# Initialize a DynamoDB client
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)


def get_game_ids(url):
    """
    Gets the game IDs from the registration page.
    """
    try:
        reg_page = req.get(url)
        reg_page.raise_for_status()
    except req.exceptions.RequestException as e:
        logging.error('Failed to get game IDs: %s', e)
        return set()

    reg_soup = BeautifulSoup(reg_page.content, 'html.parser')
    game_ids = set()
    for game in reg_soup.find_all(class_='schedule-block-head w-inline-block'):
        if game.find(class_='h2 h2-game-card h2-left').text == 'Квиз, плиз! YEREVAN':
            game_ids.add(game['href'].split('=')[1])
    return game_ids


def save_game_ids(_game_ids):
    """
    Saves the game IDs to a DynamoDB table.
    """
    try:
        table.put_item(Item={'game_id': 'game_ids', 'game_ids': list(_game_ids)})
    except Exception as e:
        logging.error('Failed to save game IDs: %s', e)


def load_game_ids():
    """
    Loads the games we have already registered at from a DynamoDB table.
    """
    try:
        response = table.get_item(Key={'game_id': 'game_ids'})
        if 'Item' in response:
            return set(response['Item']['game_ids'])
        else:
            return set()
    except Exception as e:
        logging.error('Failed to load game IDs: %s', e)
        return set()


def register(_game_id):
    """
    Registers at a game with the given ID.
    """
    logging.info('Registering at game %s', _game_id)
    headers = {'Contect-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
    body = {'QpRecord[teamName]': team['team_name'],
            'QpRecord[phone]': team['cpt_phone'],
            'QpRecord[email]': team['cpt_email'],
            'QpRecord[captainName]': team['cpt_name'],
            'QpRecord[count]': team['team_size'],
            'QpRecord[custom_fields_values]': [],
            'QpRecord[comment]': '',
            'QpRecord[game_id]': _game_id,
            'QpRecord[payment_type]': 2
            }
    try:
        reg = req.post(REG_URL, data=body, headers=headers)
        reg.raise_for_status()
        logging.info('Registration result: %s', reg.text)
    except Exception as e:
        logging.error('Registration failed: %s', e)
        raise


def lambda_handler(event, context):
    """
    Main function.
    """
    logging.info('Starting')
    game_ids = get_game_ids(REG_LIST_URL)
    saved_game_ids = load_game_ids()
    if 'game_ids' not in event:
        event['game_ids'] = set()
    new_game_ids = game_ids.union(set(x for x in event['game_ids'])).difference(saved_game_ids)
    logging.info('Found %d classical games, %d of them are new', len(game_ids), len(new_game_ids))
    for game_id in new_game_ids:
        register(game_id)
    save_game_ids(saved_game_ids.union(new_game_ids))
    logging.info('Done')
    sleep(1)


if __name__ == '__main__':
    lambda_handler()
