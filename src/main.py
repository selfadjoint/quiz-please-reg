import logging
import os
from time import sleep
import re

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
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', GROUP_ID)  # Fallback to GROUP_ID if not set

# Headers to mimic a real browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
    'Referer': 'https://yerevan.quizplease.ru/schedule',
}

# Create a session to maintain cookies
session = req.Session()
session.headers.update(HEADERS)

# Flag to track if we've visited the schedule page (for session establishment)
_schedule_visited = False

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
    global _schedule_visited
    try:
        page = session.get(_url)
        page.raise_for_status()
        _schedule_visited = True  # Mark as visited since we just fetched the schedule
        sleep(2)  # Small delay to appear more human-like
    except req.exceptions.RequestException as e:
        logging.error('Failed to get game IDs from the registration page: %s', e)
        return [], []

    soup = BeautifulSoup(page.content, 'html.parser')

    game_ids = []
    other_game_ids = []

    for game in soup.find_all(class_='schedule-block-head w-inline-block'):
        try:
            game_id = re.search(r'id=(\d+)', game['href'])
            if game_id:
                game_title_elem = game.find(class_='h2 h2-game-card h2-left')
                if game_title_elem and game_title_elem.text == 'Квиз, плиз! YEREVAN':
                    game_ids.append(game_id.group(1))
                elif game_title_elem:
                    other_game_ids.append(game_id.group(1))
        except (KeyError, AttributeError) as e:
            logging.warning(f'Failed to parse game element: {e}')
            continue

    total_games = len(game_ids) + len(other_game_ids)
    logging.info(f'Parsed {total_games} game IDs from the registration page ({len(game_ids)} classic, {len(other_game_ids)} other)')
    return game_ids, other_game_ids


def get_game_attrs(_game_id):
    """
    Fetches and processing data for a single game.
    Returns tuple of (date, time, venue, type) or None if parsing fails.
    """
    # Ensure we've visited the schedule page first to avoid CAPTCHA
    ensure_schedule_visited()

    game_url = GAME_PAGE_URL_TEMPLATE.format(_game_id)
    try:
        page = session.get(game_url)
        page.raise_for_status()
        sleep(2)  # Small delay after request to avoid rate limiting
        soup = BeautifulSoup(page.content, 'html.parser')

        info_columns = soup.find_all('div', class_='game-info-column')
        if len(info_columns) < 2:
            raise ValueError(f'Expected at least 2 game-info-column elements, found {len(info_columns)}')

        # Find the column with date (contains a month name)
        date_column = None
        for col in info_columns:
            text_elem = col.find('div', class_='text')
            if text_elem:
                text_content = text_elem.text.strip()
                # Check if this contains a month name
                if any(month in text_content for month in month_translation.keys()):
                    date_column = col
                    break
        
        if date_column is None:
            raise ValueError('Could not find column with date information')
        
        # Extract date and time from the date column
        _date_raw = date_column.find('div', class_='text').text.split()
        time_elem = date_column.find('div', class_='text text-grey')
        if time_elem:
            # Format: "Суббота, 16:00" - extract just the time
            _time = time_elem.text.split()[-1]
        else:
            # Fallback: date and time might be in same element like "29 ноября 16:00"
            if len(_date_raw) > 2 and ':' in _date_raw[-1]:
                _time = _date_raw[-1]
                _date_raw = _date_raw[:-1]  # Remove time from date
            else:
                raise ValueError('Could not find time information')
        
        # Find venue column (contains address with "ул" or "Ереван")
        _venue = None
        for col in info_columns:
            grey_elem = col.find('div', class_='text text-grey')
            if grey_elem and ('ул' in grey_elem.text or 'Ереван' in grey_elem.text):
                # Get the main venue name (non-grey text)
                venue_elem = col.find('div', class_='text')
                if venue_elem:
                    _venue = venue_elem.text.strip().replace(' Yerevan', '')
                break
        
        if _venue is None:
            raise ValueError('Could not find venue information')

        heading_info = soup.find_all('div', class_='game-heading-info')
        if not heading_info:
            raise ValueError('No game-heading-info element found')

        _type = heading_info[0].find('h1').text
        _type = 'Классическая игра' if _type == 'Квиз, плиз! YEREVAN' else _type
        _type = _type.replace(' YEREVAN', '').replace('Квиз, плиз! ', '')

        # Pad day with leading zero if needed
        _date_raw[0] = '0' + _date_raw[0] if len(_date_raw[0]) == 1 else _date_raw[0]

        # Translate month
        if _date_raw[1] not in month_translation:
            raise ValueError(f'Unknown month: {_date_raw[1]}')
        _date_raw[1] = month_translation[_date_raw[1]]

        # Determine year based on game ID (needs updating yearly)
        if int(_game_id) < 49999:
            _date_raw.append('2022')
        elif int(_game_id) < 69919:
            _date_raw.append('2023')
        elif int(_game_id) < 93630:
            _date_raw.append('2024')
        else:
            _date_raw.append('2025')

        _date = '-'.join(_date_raw[::-1])
        return _date, _time, _venue, _type

    except Exception as e:
        logging.error(f'Failed to get game attributes for game ID {_game_id}: {e}')
        return None


def put_item(_table, _game_id, _game_date, _game_type, _game_time, _game_venue, _is_classic=True, _reg_date=None):
    """
    Puts an item to a DynamoDB table.
    If _reg_date is provided, it means we've registered for this game.
    """
    try:
        item = {
            'game_id': {'N': _game_id},
            'game_date': {'S': _game_date},
            'game_time': {'S': _game_time},
            'game_venue': {'S': _game_venue},
            'game_type': {'S': _game_type},
            'is_classic': {'N': '1' if _is_classic else '0'},
        }

        # Add registration-specific fields if we're registering
        if _reg_date is not None:
            item['reg_date'] = {'S': _reg_date}
            item['is_poll_created'] = {'N': '0'}

        response = dynamodb.put_item(
            TableName=_table,
            Item=item,
        )
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            logging.info(f'Game {_game_id} put successfully to table {_table}')

        return None

    except Exception as e:
        logging.error(f'Failed to put item {_game_id} to table {_table}: {e}')


def get_all_game_ids(_table, _only_registered=False):
    """
    Gets all game IDs from a DynamoDB table.
    If _only_registered is True, returns only games where reg_date exists (games we registered for).
    """
    # Initialize variables to store results
    game_ids = []
    last_evaluated_key = None

    # Use a loop to handle pagination
    while True:
        scan_kwargs = {
            'TableName': _table,
            'ProjectionExpression': 'game_id, reg_date'
        }

        if last_evaluated_key:
            scan_kwargs['ExclusiveStartKey'] = last_evaluated_key

        response = dynamodb.scan(**scan_kwargs)

        for item in response['Items']:
            game_id = item['game_id']['N']
            has_reg_date = 'reg_date' in item

            if not _only_registered or has_reg_date:
                game_ids.append(game_id)

        last_evaluated_key = response.get('LastEvaluatedKey')

        if not last_evaluated_key:
            break

    return game_ids


def register(_game_id):
    """
    Registers at a game with the given ID.
    """
    logging.info('Registering at game %s', _game_id)
    headers = {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}
    body = {
        'QpRecord[teamName]': os.environ['TEAM_NAME'],
        'QpRecord[phone]': os.environ['CPT_PHONE'],
        'QpRecord[email]': os.environ['CPT_EMAIL'],
        'QpRecord[captainName]': os.environ['CPT_NAME'],
        'QpRecord[count]': os.environ['TEAM_SIZE'],
        'QpRecord[custom_fields_values]': [],
        'QpRecord[comment]': '',
        'have_cert': 1,
        'promo_code': os.environ['PROMOTION_CODE'],
        'QpRecord[game_id]': _game_id,
        'QpRecord[payment_type]': 2,
    }
    try:
        reg = session.post(REG_URL, data=body, headers=headers)
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
    body = {'chat_id': _group_id, 'text': _message, 'parse_mode': 'HTML',
            'link_preview_options': {'is_disabled': True}}
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

    # Game ids may be added manually during Lambda invocation. Format: {"game_ids": []}
    if 'game_ids' not in event:
        event['game_ids'] = []

    manual_game_ids = [str(x) for x in event['game_ids']]
    is_manual_run = len(manual_game_ids) > 0

    if is_manual_run:
        # Manual run: register only for manually specified games
        logging.info(f'Manual run with {len(manual_game_ids)} game(s)')

        if manual_game_ids:
            # Only check against games we've registered for (those with reg_date)
            # This allows registering for non-classic games that were previously only tracked
            saved_game_ids = get_all_game_ids(DYNAMODB_TABLE_NAME, _only_registered=True)
            new_manual_game_ids = [x for x in manual_game_ids if x not in saved_game_ids]
            already_registered_ids = [x for x in manual_game_ids if x in saved_game_ids]

            if already_registered_ids:
                logging.warning(f'Skipping {len(already_registered_ids)} already registered game(s): {already_registered_ids}')

            if new_manual_game_ids:
                message = 'Мы зарегистрировались на игры:\n\n'
                failed_games = []
                for game_id in new_manual_game_ids:
                    try:
                        register(game_id)
                        game_attrs = get_game_attrs(game_id)
                        if game_attrs is None:
                            logging.error(f'Skipping game {game_id} due to parsing failure')
                            failed_games.append((game_id, 'Failed to parse game attributes'))
                            continue

                        game_date, game_time, game_venue, game_type = game_attrs

                        # Determine if it's a classic game based on the type
                        is_classic = game_type == 'Классическая игра'

                        put_item(DYNAMODB_TABLE_NAME,
                                 game_id,
                                 game_date,
                                 game_type,
                                 game_time,
                                 game_venue,
                                 _is_classic=is_classic,
                                 _reg_date=pdl.today().format('YYYY-MM-DD'))
                        message += f"{pdl.parse(game_date).format('dd, DD MMMM', locale='ru').capitalize()}, {game_type}\n"
                        sleep(2)
                    except Exception as e:
                        logging.error(f'Failed to process game {game_id}: {e}')
                        failed_games.append((game_id, str(e)))
                        continue

                # Only send message if we actually registered for at least one game
                if message != 'Мы зарегистрировались на игры:\n\n':
                    send_message(BOT_TOKEN, GROUP_ID, message.rstrip())

                # Send summary of failures if any
                if failed_games:
                    failure_msg = f"⚠️ <b>Failed to register for {len(failed_games)} game(s) (manual run)</b>\n\n"
                    for gid, error in failed_games:
                        game_link = GAME_PAGE_URL_TEMPLATE.format(gid)
                        failure_msg += f"<a href=\"{game_link}\">Game {gid}</a>\nError: {error}\n\n"
                    send_message(BOT_TOKEN, ADMIN_CHAT_ID, failure_msg.rstrip())
            else:
                logging.info('All manually specified games are already registered')

    else:
        # Scheduled run: parse site, register for classic games, notify about non-classic games
        logging.info('Scheduled run')

        all_game_ids = get_game_ids(SCHEDULE_URL)
        classic_game_ids = all_game_ids[0]
        other_game_ids = all_game_ids[1]

        saved_game_ids = get_all_game_ids(DYNAMODB_TABLE_NAME, _only_registered=True)

        # Handle classic games
        new_classic_game_ids = [x for x in classic_game_ids if x not in saved_game_ids]
        logging.info(f'Found {len(classic_game_ids)} classical game(s), {len(new_classic_game_ids)} of them are new')

        if new_classic_game_ids:
            message = 'Мы зарегистрировались на игры:\n\n'
            failed_games = []
            for game_id in new_classic_game_ids:
                try:
                    register(game_id)
                    game_attrs = get_game_attrs(game_id)
                    if game_attrs is None:
                        logging.error(f'Skipping game {game_id} due to parsing failure')
                        failed_games.append((game_id, 'Failed to parse game attributes'))
                        continue

                    game_date, game_time, game_venue, game_type = game_attrs
                    put_item(DYNAMODB_TABLE_NAME,
                             game_id,
                             game_date,
                             game_type,
                             game_time,
                             game_venue,
                             _is_classic=True,
                             _reg_date=pdl.today().format('YYYY-MM-DD'))
                    message += f"{pdl.parse(game_date).format('dd, DD MMMM', locale='ru').capitalize()}, {game_type}\n"
                    sleep(2)
                except Exception as e:
                    logging.error(f'Failed to process game {game_id}: {e}')
                    failed_games.append((game_id, str(e)))
                    continue

            # Only send message if we actually registered for at least one game
            if message != 'Мы зарегистрировались на игры:\n\n':
                send_message(BOT_TOKEN, GROUP_ID, message.rstrip())

            # Send summary of failures if any
            if failed_games:
                failure_msg = f"⚠️ <b>Failed to register for {len(failed_games)} classic game(s)</b>\n\n"
                for gid, error in failed_games:
                    game_link = GAME_PAGE_URL_TEMPLATE.format(gid)
                    failure_msg += f"<a href=\"{game_link}\">Game {gid}</a>\nError: {error}\n\n"
                send_message(BOT_TOKEN, ADMIN_CHAT_ID, failure_msg.rstrip())

        # Handle non-classic games
        if other_game_ids:
            logging.info(f'Found {len(other_game_ids)} other game(s)')
            # Get ALL game IDs to check if we've already seen this game
            all_saved_game_ids = get_all_game_ids(DYNAMODB_TABLE_NAME, _only_registered=False)
            new_other_game_ids = [x for x in other_game_ids if x not in all_saved_game_ids]

            if new_other_game_ids:
                logging.info(f'{len(new_other_game_ids)} of them are new')
                next_week_games = []
                failed_other_games = []
                for game_id in new_other_game_ids:
                    try:
                        game_attrs = get_game_attrs(game_id)
                        if game_attrs is None:
                            logging.error(f'Skipping non-classic game {game_id} due to parsing failure')
                            failed_other_games.append((game_id, 'Failed to parse game attributes'))
                            continue

                        game_date, game_time, game_venue, game_type = game_attrs

                        # Save to DynamoDB to track it (no reg_date since we're not registering)
                        put_item(DYNAMODB_TABLE_NAME,
                                 game_id,
                                 game_date,
                                 game_type,
                                 game_time,
                                 game_venue,
                                 _is_classic=False,
                                 _reg_date=None)

                        next_week_games.append(
                            f"{pdl.parse(game_date).format('dd, DD MMMM', locale='ru').capitalize()}, "
                            f"<a href=\"{GAME_PAGE_URL_TEMPLATE.format(game_id)}\">{game_type}</a>, ID <code>{game_id}</code>"
                        )
                    except Exception as e:
                        logging.error(f'Failed to process non-classic game {game_id}: {e}')
                        failed_other_games.append((game_id, str(e)))
                        continue

                if next_week_games:
                    message = 'Ближайшие тематические игры:\n\n' + '\n'.join(next_week_games)
                    send_message(BOT_TOKEN, GROUP_ID, message.rstrip())

                # Send summary of failures for non-classic games if any
                if failed_other_games:
                    failure_msg = f"⚠️ <b>Failed to parse {len(failed_other_games)} non-classic game(s)</b>\n\n"
                    for gid, error in failed_other_games:
                        game_link = GAME_PAGE_URL_TEMPLATE.format(gid)
                        failure_msg += f"<a href=\"{game_link}\">Game {gid}</a>\nError: {error}\n\n"
                    send_message(BOT_TOKEN, ADMIN_CHAT_ID, failure_msg.rstrip())

    logging.info('All done!')


if __name__ == '__main__':
    lambda_handler(event={'game_ids': []}, context=None)
