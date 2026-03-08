CREATE SCHEMA IF NOT EXISTS quizplease;

CREATE TABLE IF NOT EXISTS quizplease.games (
    id INTEGER PRIMARY KEY,
    game_date DATE NOT NULL,
    game_time VARCHAR(10),
    venue VARCHAR(255),
    category VARCHAR(100),
    game_name VARCHAR(255),
    game_number VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_games_date
    ON quizplease.games (game_date DESC);

CREATE INDEX IF NOT EXISTS idx_games_category
    ON quizplease.games (category);

CREATE TABLE IF NOT EXISTS quizplease.game_registration_tracking (
    game_id INTEGER PRIMARY KEY
        REFERENCES quizplease.games (id)
        ON DELETE CASCADE,
    is_classic BOOLEAN NOT NULL,
    registered_on DATE,
    poll_created BOOLEAN NOT NULL DEFAULT FALSE,
    poll_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT game_registration_tracking_registered_poll_check
        CHECK (registered_on IS NOT NULL OR poll_created = FALSE),
    CONSTRAINT game_registration_tracking_poll_date_check
        CHECK (poll_date IS NULL OR poll_created = TRUE)
);

ALTER TABLE quizplease.game_registration_tracking
    ADD COLUMN IF NOT EXISTS poll_date DATE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'game_registration_tracking_registered_poll_check'
    ) THEN
        ALTER TABLE quizplease.game_registration_tracking
            ADD CONSTRAINT game_registration_tracking_registered_poll_check
            CHECK (registered_on IS NOT NULL OR poll_created = FALSE);
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'game_registration_tracking_poll_date_check'
    ) THEN
        ALTER TABLE quizplease.game_registration_tracking
            ADD CONSTRAINT game_registration_tracking_poll_date_check
            CHECK (poll_date IS NULL OR poll_created = TRUE);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_game_registration_tracking_registered
    ON quizplease.game_registration_tracking (game_id)
    WHERE registered_on IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_game_registration_tracking_pending_poll
    ON quizplease.game_registration_tracking (game_id)
    WHERE registered_on IS NOT NULL AND poll_created = FALSE;

CREATE INDEX IF NOT EXISTS idx_game_registration_tracking_classic
    ON quizplease.game_registration_tracking (is_classic, game_id);

COMMENT ON TABLE quizplease.game_registration_tracking IS
    'Tracks registration and poll workflow state for Quiz Please games';

CREATE OR REPLACE VIEW quizplease.game_registration_overview AS
SELECT
    g.id AS game_id,
    g.game_date,
    g.game_time,
    g.venue AS game_venue,
    CASE
        WHEN t.is_classic THEN 'Классическая игра'
        ELSE COALESCE(NULLIF(g.game_name, ''), g.category)
    END AS game_type,
    t.is_classic,
    t.registered_on AS reg_date,
    t.poll_created AS is_poll_created,
    t.poll_date,
    g.category,
    g.game_name,
    g.game_number
FROM quizplease.games AS g
JOIN quizplease.game_registration_tracking AS t
    ON t.game_id = g.id;
