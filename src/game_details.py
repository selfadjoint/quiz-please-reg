from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup


MONTH_TRANSLATION = {
    "января": "01",
    "февраля": "02",
    "марта": "03",
    "апреля": "04",
    "мая": "05",
    "июня": "06",
    "июля": "07",
    "августа": "08",
    "сентября": "09",
    "октября": "10",
    "ноября": "11",
    "декабря": "12",
}


def infer_year_from_game_id(game_id: int) -> str:
    if game_id < 49999:
        return "2022"
    if game_id < 69919:
        return "2023"
    if game_id < 93630:
        return "2024"
    if game_id < 119884:
        return "2025"
    return "2026"


def normalize_category(category: str | None, is_classic: bool) -> str | None:
    if is_classic:
        return "Классические игры"
    if category is None:
        return None
    normalized = category.strip()
    return normalized or None


def normalize_heading(title: str | None) -> str | None:
    if title is None:
        return None

    normalized = title.strip()
    if not normalized:
        return None

    match = re.findall(r".+(?=\sY)", normalized)
    if match:
        return match[0].strip()

    return normalized.replace(" YEREVAN", "").replace(" Yerevan", "").strip()


def parse_game_date_time(soup: BeautifulSoup, game_id: int) -> tuple[str, str | None]:
    info_columns = soup.find_all("div", class_="game-info-column")
    date_parts = None
    game_time = None

    for col in info_columns:
        text_elem = col.find("div", class_="text")
        if not text_elem:
            continue

        text_content = text_elem.get_text(strip=True)
        if not any(month in text_content for month in MONTH_TRANSLATION):
            continue

        date_parts = text_content.split()
        time_elem = col.find("div", class_="text text-grey")
        if time_elem:
            time_parts = time_elem.get_text(strip=True).split()
            if time_parts and ":" in time_parts[-1]:
                game_time = time_parts[-1]
        elif len(date_parts) > 2 and ":" in date_parts[-1]:
            game_time = date_parts[-1]
            date_parts = date_parts[:-1]
        break

    if not date_parts:
        raise ValueError(f"Could not parse date for game {game_id}")

    day = date_parts[0].zfill(2)
    month = MONTH_TRANSLATION.get(date_parts[1])
    if month is None:
        raise ValueError(f"Unknown month for game {game_id}: {date_parts[1]}")

    game_date = f"{infer_year_from_game_id(game_id)}-{month}-{day}"
    return game_date, game_time


def parse_game_venue(soup: BeautifulSoup) -> str | None:
    for col in soup.find_all("div", class_="game-info-column"):
        grey_elem = col.find("div", class_="text text-grey")
        if grey_elem and ("ул" in grey_elem.text or "Ереван" in grey_elem.text):
            venue_elem = col.find("div", class_="text")
            if venue_elem:
                venue = venue_elem.get_text(strip=True).replace(" Yerevan", "").strip()
                return venue or None
    return None


def parse_game_identity(soup: BeautifulSoup) -> dict[str, Any]:
    heading = soup.find("div", class_="game-heading-info")
    headings = heading.find_all("h1") if heading else []

    raw_title = headings[0].get_text(strip=True) if headings else None
    game_name = normalize_heading(raw_title)
    is_classic = game_name == "Квиз, плиз!"

    game_number = None
    if len(headings) > 1:
        game_number = headings[1].get_text(strip=True).lstrip("#№").strip() or None

    category_elem = soup.find("div", class_="game-tag")
    raw_category = category_elem.get_text(strip=True) if category_elem else None
    category = normalize_category(raw_category, is_classic)

    game_type = "Классическая игра" if is_classic else (game_name or category)

    return {
        "game_name": game_name,
        "game_number": game_number,
        "category": category,
        "game_type": game_type,
        "is_classic": is_classic,
    }


def parse_game_page_html(page_content: bytes | str, game_id: int) -> dict[str, Any]:
    soup = BeautifulSoup(page_content, "html.parser")
    game_date, game_time = parse_game_date_time(soup, game_id)
    details = parse_game_identity(soup)
    details.update(
        {
            "game_id": game_id,
            "game_date": game_date,
            "game_time": game_time,
            "game_venue": parse_game_venue(soup),
        }
    )
    return details
