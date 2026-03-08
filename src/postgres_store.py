from __future__ import annotations

import os
from typing import Any, Mapping


UPSERT_GAME_SQL = """
INSERT INTO quizplease.games (
    id,
    game_date,
    game_time,
    venue,
    category,
    game_name,
    game_number
)
VALUES (
    %(game_id)s,
    %(game_date)s,
    %(game_time)s,
    %(game_venue)s,
    %(category)s,
    %(game_name)s,
    %(game_number)s
)
ON CONFLICT (id) DO UPDATE
SET
    game_date = CASE
        WHEN EXISTS (
            SELECT 1
            FROM quizplease.team_game_participations AS p
            WHERE p.game_id = quizplease.games.id
        ) THEN quizplease.games.game_date
        ELSE EXCLUDED.game_date
    END,
    game_time = CASE
        WHEN EXISTS (
            SELECT 1
            FROM quizplease.team_game_participations AS p
            WHERE p.game_id = quizplease.games.id
        ) AND quizplease.games.game_time IS NOT NULL
          AND quizplease.games.game_time <> '' THEN quizplease.games.game_time
        WHEN EXCLUDED.game_time IS NULL OR EXCLUDED.game_time = '' THEN quizplease.games.game_time
        ELSE EXCLUDED.game_time
    END,
    venue = CASE
        WHEN EXISTS (
            SELECT 1
            FROM quizplease.team_game_participations AS p
            WHERE p.game_id = quizplease.games.id
        ) AND quizplease.games.venue IS NOT NULL
          AND quizplease.games.venue <> '' THEN quizplease.games.venue
        WHEN EXCLUDED.venue IS NULL OR EXCLUDED.venue = '' THEN quizplease.games.venue
        ELSE EXCLUDED.venue
    END,
    category = CASE
        WHEN EXISTS (
            SELECT 1
            FROM quizplease.team_game_participations AS p
            WHERE p.game_id = quizplease.games.id
        ) AND quizplease.games.category IS NOT NULL
          AND quizplease.games.category <> '' THEN quizplease.games.category
        WHEN EXCLUDED.category IS NULL OR EXCLUDED.category = '' THEN quizplease.games.category
        ELSE EXCLUDED.category
    END,
    game_name = CASE
        WHEN EXISTS (
            SELECT 1
            FROM quizplease.team_game_participations AS p
            WHERE p.game_id = quizplease.games.id
        ) AND quizplease.games.game_name IS NOT NULL
          AND quizplease.games.game_name <> '' THEN quizplease.games.game_name
        WHEN EXCLUDED.game_name IS NULL OR EXCLUDED.game_name = '' THEN quizplease.games.game_name
        ELSE EXCLUDED.game_name
    END,
    game_number = CASE
        WHEN EXISTS (
            SELECT 1
            FROM quizplease.team_game_participations AS p
            WHERE p.game_id = quizplease.games.id
        ) AND quizplease.games.game_number IS NOT NULL
          AND quizplease.games.game_number <> '' THEN quizplease.games.game_number
        WHEN EXCLUDED.game_number IS NULL OR EXCLUDED.game_number = '' THEN quizplease.games.game_number
        ELSE EXCLUDED.game_number
    END,
    updated_at = CURRENT_TIMESTAMP
"""


UPSERT_TRACKING_SQL = """
INSERT INTO quizplease.game_registration_tracking (
    game_id,
    is_classic,
    registered_on,
    poll_created,
    poll_date
)
VALUES (
    %(game_id)s,
    %(is_classic)s,
    %(registered_on)s,
    %(poll_created)s,
    %(poll_date)s
)
ON CONFLICT (game_id) DO UPDATE
SET
    is_classic = EXCLUDED.is_classic,
    registered_on = COALESCE(EXCLUDED.registered_on, quizplease.game_registration_tracking.registered_on),
    poll_created = CASE
        WHEN COALESCE(EXCLUDED.registered_on, quizplease.game_registration_tracking.registered_on) IS NULL THEN FALSE
        ELSE EXCLUDED.poll_created OR quizplease.game_registration_tracking.poll_created
    END,
    poll_date = COALESCE(EXCLUDED.poll_date, quizplease.game_registration_tracking.poll_date),
    updated_at = CURRENT_TIMESTAMP
"""


def get_db_connection():
    try:
        import psycopg2
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "psycopg2 is not installed. Install src/requirements.txt before running the Lambda locally."
        ) from exc

    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def select_tracked_game_ids(cur, only_registered: bool = False) -> list[str]:
    if only_registered:
        cur.execute(
            """
            SELECT game_id
            FROM quizplease.game_registration_tracking
            WHERE registered_on IS NOT NULL
            ORDER BY game_id
            """
        )
    else:
        cur.execute(
            """
            SELECT game_id
            FROM quizplease.game_registration_tracking
            ORDER BY game_id
            """
        )
    return [str(row[0]) for row in cur.fetchall()]


def upsert_game_and_tracking(
    cur,
    game: Mapping[str, Any],
    *,
    registered_on: str | None,
    poll_created: bool = False,
    poll_date: str | None = None,
) -> None:
    game_params = {
        "game_id": int(game["game_id"]),
        "game_date": game["game_date"],
        "game_time": game.get("game_time"),
        "game_venue": game.get("game_venue"),
        "category": game.get("category"),
        "game_name": game.get("game_name"),
        "game_number": game.get("game_number"),
    }
    cur.execute(UPSERT_GAME_SQL, game_params)
    cur.execute(
        UPSERT_TRACKING_SQL,
        {
            "game_id": int(game["game_id"]),
            "is_classic": bool(game["is_classic"]),
            "registered_on": registered_on,
            "poll_created": bool(poll_created and registered_on is not None),
            "poll_date": poll_date if registered_on is not None else None,
        },
    )
