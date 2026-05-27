import json as _json
import logging
import os
import re
import subprocess as _subprocess
import urllib.request
from functools import wraps
from time import sleep

import pendulum as pdl
from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, sync_playwright

from game_details import parse_game_page_html
from postgres_store import get_db_connection, select_tracked_game_ids, upsert_game_and_tracking


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger()
logger.setLevel(logging.INFO)


BASE_URL = "https://yerevan.quizplease.com"
SCHEDULE_URL = f"{BASE_URL}/schedule"
GAME_PAGE_URL_TEMPLATE = f"{BASE_URL}/game-page?id={{}}"
BOT_TOKEN = os.environ["BOT_TOKEN"]
GROUP_ID = os.environ["GROUP_ID"]
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", GROUP_ID)

# Reused across warm Lambda invocations
_pw = None
_browser = None
_context: BrowserContext | None = None
_page: Page | None = None
_xvfb_proc: _subprocess.Popen | None = None


def _ensure_xvfb() -> None:
    """Start Xvfb virtual display so Chrome runs headed (not headless).
    Headed mode inside Xvfb produces a normal desktop fingerprint — headless is
    trivially detected by Cloudflare's WAF."""
    global _xvfb_proc
    if _xvfb_proc is not None and _xvfb_proc.poll() is None:
        return
    # Clean stale lock from a previous Lambda container cold start
    try:
        os.unlink("/tmp/.X99-lock")
    except FileNotFoundError:
        pass
    _xvfb_proc = _subprocess.Popen(
        ["Xvfb", ":99", "-screen", "0", "1920x1080x24", "-ac", "+extension", "GLX", "+render", "-noreset"],
        stdout=_subprocess.DEVNULL,
        stderr=_subprocess.DEVNULL,
    )
    os.environ["DISPLAY"] = ":99"
    sleep(1)
    if _xvfb_proc.poll() is not None:
        raise RuntimeError("Xvfb failed to start")
    logger.info("Xvfb started on :99 (PID %s)", _xvfb_proc.pid)


def _is_cf_challenge(title: str) -> bool:
    return "Just a moment" in title or "момент" in title


def _navigate(page: Page, url: str, referer: str | None = None, timeout: int = 30000) -> None:
    """Navigate page to url, waiting up to timeout ms for CF challenge to clear."""
    page.goto(url, wait_until="load", timeout=timeout, referer=referer)
    if _is_cf_challenge(page.title()):
        # CF JS challenge: wait for redirect to complete
        page.wait_for_function(
            "() => !document.title.includes('Just a moment') && !document.title.includes('момент')",
            timeout=timeout,
        )


def _get_page() -> Page:
    global _pw, _browser, _context, _page

    # Check if existing page is still alive
    if _page is not None:
        try:
            _page.title()  # probe liveness
            return _page
        except Exception:
            logger.warning("Browser page is stale, re-creating...")
            _page = None
            _context = None
            _browser = None
            if _pw:
                try:
                    _pw.stop()
                except Exception:
                    pass
                _pw = None

    logger.info("Launching browser...")
    _ensure_xvfb()
    proxy_url = os.environ.get("PROXY_URL", "").strip()
    _pw = sync_playwright().start()
    try:
        _browser = _pw.chromium.launch(
            headless=False,
            proxy={"server": proxy_url} if proxy_url else None,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                # Lambda's seccomp blocks setgroups/setresuid used by Chrome's Zygote
                # when forking subprocesses → FATAL crash. --no-zygote disables the Zygote
                # so Chrome forks children directly without privilege manipulation.
                "--no-zygote",
                # --disable-gpu prevents in-process GPU from hanging while waiting for
                # hardware that doesn't exist in Lambda's environment.
                "--disable-gpu",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--lang=ru-RU",
                "--window-size=1920,1080",
            ],
            ignore_default_args=["--enable-automation"],
        )
    except Exception:
        try:
            _pw.stop()
        except Exception:
            pass
        _pw = None
        raise
    try:
        _context = _browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="ru-RU",
            timezone_id="Asia/Yerevan",
            extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"},
        )
        _context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        if proxy_url:
            logger.info("Proxy active: %s", proxy_url.split("@")[-1])
        _page = _context.new_page()
    except Exception:
        # Chrome crashed during setup — stop Playwright cleanly so retry can start fresh
        _context = None
        _browser = None
        try:
            _pw.stop()
        except Exception:
            pass
        _pw = None
        raise

    logger.info("Warming up on home page...")
    try:
        _navigate(_page, BASE_URL, timeout=30000)
        logger.info("Home page ready (title: %s)", _page.title())
    except Exception as exc:
        logger.warning("Home page warm-up issue: %s", exc)

    sleep(2)
    return _page


def _fetch_page_html(url: str) -> str:
    page = _get_page()
    _navigate(page, url, referer=BASE_URL, timeout=60000)
    title = page.title()
    if _is_cf_challenge(title):
        logger.error("CF challenge not resolved for %s. Title=%s, snippet=%s", url, title, page.content()[:500])
        raise RuntimeError(f"Cloudflare challenge not resolved for {url}")
    return page.content()


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


@retry_on_failure(max_attempts=3, delay_seconds=20)
def get_game_ids(url):
    html = _fetch_page_html(url)
    sleep(2)

    soup = BeautifulSoup(html, "html.parser")
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
        "Parsed %s game IDs from schedule (%s classic, %s other)",
        len(classic_game_ids) + len(other_game_ids),
        len(classic_game_ids),
        len(other_game_ids),
    )
    return classic_game_ids, other_game_ids


@retry_on_failure(max_attempts=5, delay_seconds=60)
def get_game_details(game_id):
    html = _fetch_page_html(GAME_PAGE_URL_TEMPLATE.format(game_id))
    sleep(2)

    game = parse_game_page_html(html, int(game_id))
    if not game.get("game_type"):
        raise ValueError(f"Could not derive game_type for game {game_id}")
    return game


@retry_on_failure(max_attempts=5, delay_seconds=60)
def register(game_id):
    logger.info("Registering at game %s", game_id)
    page = _get_page()

    # Visit the game page first so CF clears the session and any page-specific
    # tokens/cookies are set before we POST the registration form.
    game_url = GAME_PAGE_URL_TEMPLATE.format(game_id)
    _navigate(page, game_url, referer=SCHEDULE_URL, timeout=60000)
    sleep(1)

    # Use page.evaluate(fetch) so the POST goes through Chrome's network stack.
    # context.request.post() uses Playwright's internal HTTP client, which has a
    # different TLS fingerprint — CF blocks it even when cookies are correct.
    result = page.evaluate(
        """async (payload) => {
            const fd = new FormData();
            for (const [k, v] of Object.entries(payload.fields)) {
                fd.append(k, v);
            }
            const r = await fetch(payload.url, {
                method: 'POST',
                body: fd,
                credentials: 'include',
            });
            return { status: r.status, text: await r.text() };
        }""",
        {
            "url": GAME_PAGE_URL_TEMPLATE.format(game_id),
            "fields": {
                "record-from-form": "1",
                "QpRecord[teamName]": os.environ["TEAM_NAME"],
                "QpRecord[phone]": os.environ["CPT_PHONE"],
                "QpRecord[email]": os.environ["CPT_EMAIL"],
                "QpRecord[captainName]": os.environ["CPT_NAME"],
                "QpRecord[count]": str(os.environ["TEAM_SIZE"]),
                "QpRecord[custom_fields_values]": "",
                "QpRecord[comment]": "",
                "QpRecord[first_time]": "0",
                "QpRecord[max_people_active]": "",
                "QpRecord[site_content_id]": "",
                "reservation": "",
                "certificates[]": os.environ.get("PROMOTION_CODE", ""),
                "QpRecord[game_id]": str(game_id),
            },
        },
    )

    response_text = result["text"]
    status = result["status"]
    if "succes-reg" in response_text:
        logger.info("Registration successful for game %s", game_id)
    else:
        logger.error(
            "Registration failed for game %s (status %s). Response: %s",
            game_id,
            status,
            response_text[:500],
        )
        raise RuntimeError(
            f"Registration failed for game {game_id}: status {status}"
        )


def send_message(bot_token, group_id, message):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = _json.dumps({
        "chat_id": group_id,
        "text": message,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            result = _json.loads(resp.read())
            logger.info("Message sent successfully! Message: %s", result["result"]["text"])
            return result["result"]
    except Exception as exc:
        logger.error("Failed to send message: %s", exc)
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
            try:
                classic_game_ids, other_game_ids = get_game_ids(SCHEDULE_URL)
            except Exception as exc:
                error_msg = f"⚠️ <b>Failed to scrape schedule page</b>\n\nError: {exc}"
                send_message(BOT_TOKEN, ADMIN_CHAT_ID, error_msg)
                raise

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
