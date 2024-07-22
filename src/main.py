import logging
import os
from time import sleep

import boto3
import pendulum as pdl
import requests as req
from bs4 import BeautifulSoup

# Set up logging
logging.basicConfig(
    level=logging.INFO, format='%(asctime)s.%(msecs)03d %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Set up constants
SCHEDULE_URL = 'https://yerevan.quizplease.ru/schedule'
GAME_PAGE_URL_TEMPLATE = 'https://yerevan.quizplease.ru/game-page?id={}'
DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']
REG_URL = 'https://yerevan.quizplease.am/ajax/save-record'
BOT_TOKEN = os.environ['BOT_TOKEN']
GROUP_ID = os.environ['GROUP_ID']

# Month translation dictionary
month_translation = {
    'января': '01',
    'февраля': '02',
    'марта': '03',
    'апреля': '04',
    'мая': '05',
    'июня': '06',
    'июля': '07',
    'августа': '08',
    'сентября': '09',
    'октября': '10',
    'ноября': '11',
    'декабря': '12',
}

# Initialize a DynamoDB client
dynamodb = boto3.client('dynamodb')


def get_game_ids(_url):
    """
    Gets the game IDs from the registration page.
    """
    try:
        reg_page = req.get(_url)
        reg_page.raise_for_status()
    except req.exceptions.RequestException as e:
        logging.error('Failed to get game IDs from the registration page: %s', e)
        return []

    reg_soup = BeautifulSoup(reg_page.content, 'html.parser')
    game_ids = []
    other_game_ids = []
    for game in reg_soup.find_all(class_='schedule-block-head w-inline-block'):
        if game.find(class_='h2 h2-game-card h2-left').text == 'Квиз, плиз! YEREVAN':
            game_ids.append(game['href'].split('=')[1])
        else:
            other_game_ids.append(game['href'].split('=')[1])
    logging.info(f'Parsed {len(game_ids)} game IDs from the registration page')
    return game_ids, other_game_ids


def get_game_attrs(_game_id):
    """
    Fetches and processes data for a single game.
    """
    game_url = GAME_PAGE_URL_TEMPLATE.format(_game_id)
    try:
        page = req.get(game_url)
        soup = BeautifulSoup(page.content, 'html.parser')
        _date_raw = soup.find_all('div', class_='game-info-column')[2].find('div', class_='text').text.split()
        _time = soup.find_all('div', class_='game-info-column')[2].find(
            'div', class_='text text-grey').text.split()[-1]
        _venue = soup.find_all('div', class_='game-info-column')[1].find(
            'div', class_='text').text.replace(' Yerevan', '')
        _type = soup.find_all('div', class_='game-heading-info')[0].find('h1').text.replace(' YEREVAN', '')
        _type = 'Классическая игра' if _type == 'Квиз, плиз!' else _type
    except Exception as e:
        logging.error(f'Failed to get game date for game ID {_game_id}: {e}')
        return None

    _date_raw[0] = '0' + _date_raw[0] if len(_date_raw[0]) == 1 else _date_raw[0]
    _date_raw[1] = month_translation[_date_raw[1]]

    # Some hardcode for the correct game year determination. Needs to be updated every year
    if int(_game_id) < 49999:
        _date_raw.append('2022')
    elif int(_game_id) < 69919:
        _date_raw.append('2023')
    else:
        _date_raw.append('2024')

    _date = '-'.join(_date_raw[::-1])
    return _date, _time, _venue, _type


def put_item(_table, _game_id, _game_date, _reg_date, _game_type, _game_time, _game_venue):
    """
    Puts an item to a DynamoDB table.
    """
    try:
        response = dynamodb.put_item(
            TableName=_table,
            Item={
                'game_id': {'N': _game_id},
                'game_date': {'S': _game_date},
                'game_time': {'S': _game_time},
                'is_poll_created': {'N': '0'},
                'reg_date': {'S': _reg_date},
                'game_venue': {'S': _game_venue},
                'game_type': {'S': _game_type},
            },
        )
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            logging.info(f'Game {_game_id} put successfully to table {_table}')

        return None

    except Exception as e:
        logging.error(f'Failed to put item {_game_id} to table {_table}: {e}')


def get_all_game_ids(_table):
    """
    Gets all game IDs from a DynamoDB table.
    """
    # Initialize variables to store results
    game_ids = []
    last_evaluated_key = None

    # Use a loop to handle pagination
    while True:
        if last_evaluated_key:
            response = dynamodb.scan(
                TableName=_table, ProjectionExpression='game_id', ExclusiveStartKey=last_evaluated_key
            )
        else:
            response = dynamodb.scan(TableName=_table, ProjectionExpression='game_id')

        game_ids.extend([item['game_id']['N'] for item in response['Items']])
        last_evaluated_key = response.get('LastEvaluatedKey')

        if not last_evaluated_key:
            break

    return game_ids


def register(_game_id):
    """
    Registers at a game with the given ID.
    """
    logging.info('Registering at game %s', _game_id)
    headers = {'Contect-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
    body = {
        'QpRecord[teamName]': os.environ['TEAM_NAME'],
        'QpRecord[phone]': os.environ['CPT_PHONE'],
        'QpRecord[email]': os.environ['CPT_EMAIL'],
        'QpRecord[captainName]': os.environ['CPT_NAME'],
        'QpRecord[count]': os.environ['TEAM_SIZE'],
        'QpRecord[custom_fields_values]': [],
        'QpRecord[comment]': '',
        'QpRecord[game_id]': _game_id,
        'QpRecord[payment_type]': 2,
    }
    try:
        reg = req.post(REG_URL, data=body, headers=headers)
        reg.raise_for_status()
        logging.info('Registration result: %s', reg.text)
    except Exception as e:
        logging.error('Registration failed: %s', e)
        raise


def send_message(_bot_token, _group_id, _message):
    """
    Sends a message to a channel.
    """
    url = f'https://api.telegram.org/bot{_bot_token}/sendMessage'
    body = {'chat_id': _group_id, 'text': _message}
    response = req.post(url, json=body)

    if response.status_code == 200:
        message_data = response.json()
        logger.info(f'Message sent successfully! Message: {message_data["result"]["text"]}')
        return message_data['result']
    else:
        logger.error(f'Failed to send message. Status code: {response.status_code}')
        logger.info(f'Response: {response.json()}')
        return None


def lambda_handler(event, context):
    """
    Main function.
    """
    logging.info('Starting')
    all_game_ids = get_game_ids(SCHEDULE_URL)
    game_ids = all_game_ids[0]  # classic games to register
    saved_game_ids = get_all_game_ids(DYNAMODB_TABLE_NAME)

    # Game ids may be added manually during Lambda invocation. Format: {"game_ids": []}
    if 'game_ids' not in event:
        event['game_ids'] = []
    logging.info(f'{len(event["game_ids"])} game(s) manually added')

    game_ids.extend(str(x) for x in event['game_ids'])
    new_game_ids = [x for x in game_ids if x not in saved_game_ids]
    logging.info(f'Found {len(game_ids)} classical game(s), {len(new_game_ids)} of them are new')

    # Register ащк new games
    for game_id in new_game_ids:
        register(game_id)
        game_date, game_time, game_venue, game_type = get_game_attrs(game_id)
        put_item(DYNAMODB_TABLE_NAME,
                 game_id,
                 game_date,
                 pdl.today().format('YYYY-MM-DD'),
                 game_type,
                 game_time,
                 game_venue)
        sleep(1)

    # Send non-classical games to the group if it's not a manual run
    if not event['game_ids']:
        other_game_ids = all_game_ids[1]
        logging.info(f'Found {len(other_game_ids)} other game(s)')
        message = 'Тематические игры на следующей неделе:\n\n'
        for game_id in other_game_ids:
            game_attrs = get_game_attrs(game_id)
            if pdl.parse(game_attrs[0]).week_of_year == pdl.today().add(weeks=1).week_of_year:
                message += f'{game_attrs[0]} {game_attrs[3]}, ID {game_id}\n'

        send_message(BOT_TOKEN, GROUP_ID, message.rstrip())

    logging.info('All done!')


if __name__ == '__main__':
    lambda_handler(event={'game_ids': []}, context=None)
