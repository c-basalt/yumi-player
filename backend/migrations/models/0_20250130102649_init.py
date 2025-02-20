from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "banned_user_cache" (
    "user_id" VARCHAR(255) NOT NULL  PRIMARY KEY,
    "user_name" VARCHAR(255) NOT NULL,
    "modified_at" INT NOT NULL
);
CREATE TABLE IF NOT EXISTS "cache_entries" (
    "cache_id" VARCHAR(1024) NOT NULL  PRIMARY KEY,
    "file_size" INT NOT NULL,
    "last_accessed" INT NOT NULL,
    "song_id" VARCHAR(255) NOT NULL,
    "song_source" VARCHAR(255) NOT NULL,
    "song_file" VARCHAR(32768) NOT NULL,
    "song_title" VARCHAR(255) NOT NULL,
    "song_singer" VARCHAR(255) NOT NULL,
    "song_decibel" REAL,
    "song_duration" INT,
    "song_meta" JSON NOT NULL,
    "is_valid" INT NOT NULL  DEFAULT 1
);
CREATE TABLE IF NOT EXISTS "player_status" (
    "key" VARCHAR(255) NOT NULL  PRIMARY KEY,
    "paused" INT NOT NULL
);
CREATE TABLE IF NOT EXISTS "playlist_cache_entries" (
    "cache_id" VARCHAR(1024) NOT NULL  PRIMARY KEY,
    "playlist_title" VARCHAR(255) NOT NULL,
    "song_ids" JSON NOT NULL,
    "songs_meta" JSON NOT NULL
);
CREATE TABLE IF NOT EXISTS "playlist_entries" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "user_id" VARCHAR(255) NOT NULL,
    "uid_hash" VARCHAR(255) NOT NULL,
    "user_name" VARCHAR(255) NOT NULL,
    "user_privilege" VARCHAR(10) NOT NULL  DEFAULT 'user',
    "song_id" VARCHAR(255) NOT NULL,
    "song_title" VARCHAR(255) NOT NULL,
    "song_artist" VARCHAR(255) NOT NULL,
    "song_source" VARCHAR(255) NOT NULL,
    "song_file" VARCHAR(32768) NOT NULL,
    "song_decibel" REAL,
    "song_duration" INT,
    "song_meta" JSON NOT NULL,
    "progress" INT NOT NULL  DEFAULT 0,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "is_queued" INT NOT NULL  DEFAULT 1,
    "is_canceled" INT NOT NULL  DEFAULT 0,
    "is_auto_entry" INT NOT NULL  DEFAULT 0,
    "is_from_control" INT NOT NULL  DEFAULT 0,
    "is_fallback" INT NOT NULL  DEFAULT 0,
    "queue_position" INT NOT NULL  DEFAULT 0
);
CREATE INDEX IF NOT EXISTS "idx_playlist_en_is_queu_676739" ON "playlist_entries" ("is_queued", "id");
CREATE INDEX IF NOT EXISTS "idx_playlist_en_user_id_98bfbc" ON "playlist_entries" ("user_id", "user_name");
CREATE INDEX IF NOT EXISTS "idx_playlist_en_is_queu_846bbf" ON "playlist_entries" ("is_queued", "is_canceled", "id");
CREATE INDEX IF NOT EXISTS "idx_playlist_en_is_canc_f6c835" ON "playlist_entries" ("is_canceled", "is_from_control", "uid_hash", "id");
CREATE TABLE IF NOT EXISTS "query_entries" (
    "query_id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "query_text" VARCHAR(1024) NOT NULL,
    "created_at" TIMESTAMP NOT NULL  DEFAULT CURRENT_TIMESTAMP,
    "user_id" VARCHAR(255) NOT NULL,
    "uid_hash" VARCHAR(255) NOT NULL,
    "user_name" VARCHAR(255) NOT NULL,
    "user_privilege" VARCHAR(10) NOT NULL  DEFAULT 'user',
    "result" VARCHAR(1024),
    "match_count" INT NOT NULL,
    "song_id" VARCHAR(255),
    "song_title" VARCHAR(255),
    "song_singer" VARCHAR(255),
    "song_source" VARCHAR(255)
);
CREATE TABLE IF NOT EXISTS "recent_bvid" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "bvid" VARCHAR(255) NOT NULL,
    "user_id" VARCHAR(255) NOT NULL,
    "uid_hash" VARCHAR(255) NOT NULL,
    "user_name" VARCHAR(255) NOT NULL,
    "user_privilege" VARCHAR(10) NOT NULL  DEFAULT 'user'
);
CREATE TABLE IF NOT EXISTS "aerich" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    "version" VARCHAR(255) NOT NULL,
    "app" VARCHAR(100) NOT NULL,
    "content" JSON NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """
