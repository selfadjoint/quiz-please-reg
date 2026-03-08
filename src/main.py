import logging
import os
import re
from functools import wraps
from time import sleep

import pendulum as pdl
import requests as req
from bs4 import BeautifulSoup

from game_details import parse_game_page_html
from postgres_store import get_db_connection, select_tracked_game_ids, upsert_game_and_tracking


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger()
logger.setLevel(logging.INFO)


SCHEDULE_URL = "https://yerevan.quizplease.ru/schedule"
GAME_PAGE_URL_TEMPLATE = "https://yerevan.quizplease.ru/game-page?id={}"
REG_URL = "https://yerevan.quizplease.am/ajax/save-record"
BOT_TOKEN = os.environ["BOT_TOKEN"]
GROUP_ID = os.environ["GROUP_ID"]
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", GROUP_ID)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Referer": "https://yerevan.quizplease.ru/schedule",
}

session = req.Session()
session.headers.update(HEADERS)
_schedule_visited = False


def retry_on_failure(max_attempts=3, delay_seconds=20):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if attempt < max_attempts:
                        logger.warning(
                            "%s failed on attempt %s/%s: %s. Retrying in %ss...",
                            func.__name__,
                            attempt,
                            max_attempts,
                            exc,
                            delay_seconds,
                        )
                        sleep(delay_seconds)
                    else:
                        logger.error("%s failed after %s attempts: %s", func.__name__, max_attempts, exc)
            raise last_exception

        return wrapper

    return decorator


def ensure_schedule_visited():
    global _schedule_visited
    if _schedule_visited:
        return

    try:
        logger.debug("Visiting schedule page to establish session...")
        session.get(SCHEDULE_URL)
        _schedule_visited = True
        sleep(2)
    except Exception as exc:
        logger.warning("Failed to pre-visit schedule page: %s", exc)


def get_game_ids(url):
    global _schedule_visited
    try:
        page = session.get(url)
        page.raise_for_status()
        _schedule_visited = True
        sleep(2)
    except req.exceptions.RequestException as exc:
        logger.error("Failed to get game IDs from the registration page: %s", exc)
        return [], []

    soup = BeautifulSoup(page.content, "html.parser")
    classic_game_ids = []
    other_game_ids = []

    for game in soup.find_all(class_="schedule-block-head w-inline-block"):
        try:
            game_id = re.search(r"id=(\d+)", game["href"])
            if not game_id:
                continue

            game_title_elem = game.find(class_="h2 h2-game-card h2-left")
            if game_title_elem and game_title_elem.text == "Квиз, плиз! YEREVAN":
                classic_game_ids.append(game_id.group(1))
            elif game_title_elem:
                other_game_ids.append(game_id.group(1))
        except (KeyError, AttributeError) as exc:
            logger.warning("Failed to parse game element: %s", exc)

    logger.info(
        "Parsed %s game IDs from the registration page (%s classic, %s other)",
        len(classic_game_ids) + len(other_game_ids),
        len(classic_game_ids),
        len(other_game_ids),
    )
    return classic_game_ids, other_game_ids


@retry_on_failure(max_attempts=5, delay_seconds=60)
def get_game_details(game_id):
    ensure_schedule_visited()

    page = session.get(GAME_PAGE_URL_TEMPLATE.format(game_id))
    page.raise_for_status()
    sleep(2)

    game = parse_game_page_html(page.content, int(game_id))
    if not game.get("game_type"):
        raise ValueError(f"Could not derive game_type for game {game_id}")
    return game


@retry_on_failure(max_attempts=5, delay_seconds=60)
def register(game_id):
    logger.info("Registering at game %s", game_id)
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}
    body = {
        "QpRecord[teamName]": os.environ["TEAM_NAME"],
        "QpRecord[phone]": os.environ["CPT_PHONE"],
        "QpRecord[email]": os.environ["CPT_EMAIL"],
        "QpRecord[captainName]": os.environ["CPT_NAME"],
        "QpRecord[count]": os.environ["TEAM_SIZE"],
        "QpRecord[custom_fields_values]": [],
        "QpRecord[comment]": "",
        "have_cert": 1,
        "promo_code": os.environ["PROMOTION_CODE"],
        "QpRecord[game_id]": game_id,
        "QpRecord[payment_type]": 2,
    }
    response = session.post(REG_URL, data=body, headers=headers)
    response.raise_for_status()
    logger.info("Registration result: %s", response.text)


def send_message(bot_token, group_id, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = {
        "chat_id": group_id,
        "text": message,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    response = req.post(url, json=body)

    if response.status_code == 200:
        message_data = response.json()
        logger.info("Message sent successfully! Message: %s", message_data["result"]["text"])
        return message_data["result"]

    logger.error("Failed to send message. Status code: %s", response.status_code)
    logger.info("Response: %s", response.json())
    return None


def store_game(conn, game, *, registered_on=None, poll_created=False, poll_date=None):
    with conn.cursor() as cur:
        upsert_game_and_tracking(
            cur,
            game,
            registered_on=registered_on,
            poll_created=poll_created,
            poll_date=poll_date,
        )


def lambda_handler(event, context):
    logger.info("Starting")

    if "game_ids" not in event:
        event["game_ids"] = []

    manual_game_ids = [str(x) for x in event["game_ids"]]
    is_manual_run = bool(manual_game_ids)

    with get_db_connection() as conn:
        conn.autocommit = False

        if is_manual_run:
            logger.info("Manual run with %s game(s)", len(manual_game_ids))
            with conn.cursor() as cur:
                saved_game_ids = select_tracked_game_ids(cur, only_registered=True)
            new_manual_game_ids = [x for x in manual_game_ids if x not in saved_game_ids]
            already_registered_ids = [x for x in manual_game_ids if x in saved_game_ids]

            if already_registered_ids:
                logger.warning(
                    "Skipping %s already registered game(s): %s",
                    len(already_registered_ids),
                    already_registered_ids,
                )

            if new_manual_game_ids:
                message = "Мы зарегистрировались на игры:\n\n"
                failed_games = []

                for game_id in new_manual_game_ids:
                    try:
                        register(game_id)
                        game = get_game_details(game_id)
                        store_game(
                            conn,
                            game,
                            registered_on=pdl.today().format("YYYY-MM-DD"),
                            poll_created=False,
                        )
                        conn.commit()
                        message += (
                            f"{pdl.parse(game['game_date']).format('dd, DD MMMM', locale='ru').capitalize()}, "
                            f"{game['game_type']}\n"
                        )
                        sleep(2)
                    except Exception as exc:
                        conn.rollback()
                        logger.error("Failed to process game %s: %s", game_id, exc)
                        failed_games.append((game_id, str(exc)))

                if message != "Мы зарегистрировались на игры:\n\n":
                    send_message(BOT_TOKEN, GROUP_ID, message.rstrip())

                if failed_games:
                    failure_msg = f"⚠️ <b>Failed to register for {len(failed_games)} game(s) (manual run)</b>\n\n"
                    for gid, error in failed_games:
                        game_link = GAME_PAGE_URL_TEMPLATE.format(gid)
                        failure_msg += f"<a href=\"{game_link}\">Game {gid}</a>\nError: {error}\n\n"
                    send_message(BOT_TOKEN, ADMIN_CHAT_ID, failure_msg.rstrip())
            else:
                logger.info("All manually specified games are already registered")

        else:
            logger.info("Scheduled run")
            classic_game_ids, other_game_ids = get_game_ids(SCHEDULE_URL)

            with conn.cursor() as cur:
                saved_registered_ids = select_tracked_game_ids(cur, only_registered=True)
                saved_all_ids = select_tracked_game_ids(cur, only_registered=False)

            new_classic_game_ids = [x for x in classic_game_ids if x not in saved_registered_ids]
            logger.info(
                "Found %s classical game(s), %s of them are new",
                len(classic_game_ids),
                len(new_classic_game_ids),
            )

            if new_classic_game_ids:
                message = "Мы зарегистрировались на игры:\n\n"
                failed_games = []

                for game_id in new_classic_game_ids:
                    try:
                        register(game_id)
                        game = get_game_details(game_id)
                        store_game(
                            conn,
                            game,
                            registered_on=pdl.today().format("YYYY-MM-DD"),
                            poll_created=False,
                        )
                        conn.commit()
                        message += (
                            f"{pdl.parse(game['game_date']).format('dd, DD MMMM', locale='ru').capitalize()}, "
                            f"{game['game_type']}\n"
                        )
                        sleep(2)
                    except Exception as exc:
                        conn.rollback()
                        logger.error("Failed to process game %s: %s", game_id, exc)
                        failed_games.append((game_id, str(exc)))

                if message != "Мы зарегистрировались на игры:\n\n":
                    send_message(BOT_TOKEN, GROUP_ID, message.rstrip())

                if failed_games:
                    failure_msg = f"⚠️ <b>Failed to register for {len(failed_games)} classic game(s)</b>\n\n"
                    for gid, error in failed_games:
                        game_link = GAME_PAGE_URL_TEMPLATE.format(gid)
                        failure_msg += f"<a href=\"{game_link}\">Game {gid}</a>\nError: {error}\n\n"
                    send_message(BOT_TOKEN, ADMIN_CHAT_ID, failure_msg.rstrip())

            if other_game_ids:
                logger.info("Found %s other game(s)", len(other_game_ids))
                new_other_game_ids = [x for x in other_game_ids if x not in saved_all_ids]

                if new_other_game_ids:
                    logger.info("%s of them are new", len(new_other_game_ids))
                    next_week_games = []
                    failed_other_games = []

                    for game_id in new_other_game_ids:
                        try:
                            game = get_game_details(game_id)
                            store_game(conn, game, registered_on=None, poll_created=False)
                            conn.commit()
                            next_week_games.append(
                                f"{pdl.parse(game['game_date']).format('dd, DD MMMM', locale='ru').capitalize()}, "
                                f"<a href=\"{GAME_PAGE_URL_TEMPLATE.format(game_id)}\">{game['game_type']}</a>, "
                                f"ID <code>{game_id}</code>"
                            )
                        except Exception as exc:
                            conn.rollback()
                            logger.error("Failed to process non-classic game %s: %s", game_id, exc)
                            failed_other_games.append((game_id, str(exc)))

                    if next_week_games:
                        message = "Ближайшие тематические игры:\n\n" + "\n".join(next_week_games)
                        send_message(BOT_TOKEN, GROUP_ID, message.rstrip())

                    if failed_other_games:
                        failure_msg = f"⚠️ <b>Failed to parse {len(failed_other_games)} non-classic game(s)</b>\n\n"
                        for gid, error in failed_other_games:
                            game_link = GAME_PAGE_URL_TEMPLATE.format(gid)
                            failure_msg += f"<a href=\"{game_link}\">Game {gid}</a>\nError: {error}\n\n"
                        send_message(BOT_TOKEN, ADMIN_CHAT_ID, failure_msg.rstrip())

    logger.info("All done!")
    return {"statusCode": 200, "body": "OK"}
