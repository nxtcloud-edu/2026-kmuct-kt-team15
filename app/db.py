"""SQLite schema, connection and the init/load CLI (SPEC 6.1, 4)."""

import hashlib
import json
import os
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "data/kmu.db")

# SPEC 6.1 verbatim. `init` runs these with CREATE TABLE IF NOT EXISTS so that a
# prepared kmu.db already sitting at DB_PATH is never dropped or rebuilt.
SCHEMA = r"""
CREATE TABLE notice (             -- 수집한 공지 원본. _all.json 한 항목 = 한 행
  key          TEXT PRIMARY KEY,  -- "{source_id}:{notice_id}"
  source_id    TEXT NOT NULL,
  source_name  TEXT NOT NULL,
  url          TEXT NOT NULL,
  title        TEXT NOT NULL,
  posted_date  TEXT NOT NULL,     -- YYYY-MM-DD
  department   TEXT,
  body_text    TEXT NOT NULL DEFAULT '',
  attachments  TEXT NOT NULL DEFAULT '[]',  -- JSON [{"name", "url"}]
  body_hash    TEXT NOT NULL,     -- sha1(title + "\n" + body_text)
  crawled_at   TEXT NOT NULL
);

CREATE TABLE card (
  notice_key     TEXT PRIMARY KEY REFERENCES notice(key),
  title          TEXT NOT NULL,
  sub            TEXT NOT NULL DEFAULT '',
  dept           TEXT NOT NULL,
  category       TEXT NOT NULL,
  apply_start    TEXT,
  apply_end      TEXT,
  conditions     TEXT NOT NULL DEFAULT '[]',
  fields         TEXT NOT NULL DEFAULT '[]',
  trace          TEXT NOT NULL DEFAULT '[]',
  linked_to      TEXT REFERENCES card(notice_key),
  check_ok       INTEGER,
  hidden         INTEGER NOT NULL DEFAULT 0,
  demo_new       INTEGER NOT NULL DEFAULT 0,
  interpreted_by TEXT NOT NULL
);

CREATE TABLE raw_source (
  id          INTEGER PRIMARY KEY,
  notice_key  TEXT NOT NULL REFERENCES notice(key),
  ord         INTEGER NOT NULL,
  kind        TEXT NOT NULL,
  label       TEXT NOT NULL,
  url         TEXT NOT NULL,
  text        TEXT NOT NULL,
  confidence  TEXT
);

CREATE TABLE task_template (
  id          INTEGER PRIMARY KEY,
  notice_key  TEXT NOT NULL REFERENCES card(notice_key),
  ord         INTEGER NOT NULL,
  title       TEXT NOT NULL,
  due         TEXT NOT NULL
);

CREATE TABLE review (
  id           INTEGER PRIMARY KEY,
  notice_key   TEXT NOT NULL REFERENCES notice(key),
  condition_id TEXT,
  reason       TEXT NOT NULL,
  note         TEXT NOT NULL DEFAULT '',
  resolved     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE student (
  id           TEXT PRIMARY KEY,
  profile      TEXT NOT NULL DEFAULT '{}',
  revealed_new INTEGER NOT NULL DEFAULT 0,
  is_seed      INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL
);

CREATE TABLE plan (
  student_id  TEXT NOT NULL REFERENCES student(id),
  notice_key  TEXT NOT NULL REFERENCES card(notice_key),
  added_at    TEXT NOT NULL,
  PRIMARY KEY (student_id, notice_key)
);

CREATE TABLE task_done (
  student_id  TEXT NOT NULL REFERENCES student(id),
  task_id     INTEGER NOT NULL REFERENCES task_template(id),
  PRIMARY KEY (student_id, task_id)
);

CREATE TABLE chat_miss (
  id          INTEGER PRIMARY KEY,
  student_id  TEXT,
  question    TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

TABLES = [
    "notice", "card", "raw_source", "task_template", "review",
    "student", "plan", "task_done", "chat_miss", "meta",
]


def connect(path=None):
    """Open DB_PATH in WAL mode with sqlite3.Row rows."""
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def body_hash(title, body_text):
    return hashlib.sha1((title + "\n" + body_text).encode("utf-8")).hexdigest()


def init(path=None):
    """Create the missing tables. Never drops an existing table or file."""
    conn = connect(path)
    with conn:
        conn.executescript(SCHEMA.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS "))
    conn.close()


def load(json_path, path=None):
    """Load _all.json into notice. Keys that are already there are skipped."""
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    notices = data["notices"] if isinstance(data, dict) else data
    conn = connect(path)
    with conn:
        for n in notices:
            key = "{}:{}".format(n["source_id"], n["notice_id"])
            conn.execute(
                "INSERT OR IGNORE INTO notice (key, source_id, source_name, url, title,"
                " posted_date, department, body_text, attachments, body_hash, crawled_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    n["source_id"],
                    n.get("source_name", ""),
                    n.get("url", ""),
                    n.get("title", ""),
                    n.get("posted_date", ""),
                    n.get("department"),
                    n.get("body_text") or "",
                    json.dumps(n.get("attachments") or [], ensure_ascii=False),
                    body_hash(n.get("title", ""), n.get("body_text") or ""),
                    n.get("crawled_at", ""),
                ),
            )
        count = conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0]
    conn.close()
    return count


def main(argv):
    if len(argv) >= 1 and argv[0] == "init":
        init()
        print("init: {}".format(DB_PATH))
        return 0
    if len(argv) >= 2 and argv[0] == "load":
        count = load(argv[1])
        print("load: {} rows in notice".format(count))
        return 0
    print("usage: python -m app.db init | python -m app.db load <_all.json>")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
