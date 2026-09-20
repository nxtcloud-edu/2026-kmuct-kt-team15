"""T01: schema and load (SPEC 6.1, 4)."""

import json
import sqlite3

from app import db


def test_init_creates_every_table(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = sqlite3.connect(path)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(db.TABLES) <= names
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_init_keeps_existing_rows(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT INTO notice (key, source_id, source_name, url, title, posted_date,"
            " body_text, attachments, body_hash, crawled_at)"
            " VALUES ('a:1', 'a', 'A', 'u', 't', '2026-03-01', '', '[]', 'h', 'c')"
        )
    conn.close()
    db.init(path)
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM notice").fetchone()[0] == 1
    conn.close()


def test_columns_match_spec_order(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(card)")]
    assert cols == [
        "notice_key", "title", "sub", "dept", "category", "apply_start", "apply_end",
        "conditions", "fields", "trace", "linked_to", "check_ok", "hidden", "demo_new",
        "interpreted_by",
    ]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(notice)")]
    assert cols == [
        "key", "source_id", "source_name", "url", "title", "posted_date", "department",
        "body_text", "attachments", "body_hash", "crawled_at",
    ]
    conn.close()


def test_connect_returns_rows(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.connect(path)
    row = conn.execute("SELECT 1 AS one").fetchone()
    assert row["one"] == 1
    conn.close()


def _sample(tmp_path, n=3):
    notices = [
        {
            "source_id": "hq", "notice_id": str(i), "source_name": "본부",
            "url": "https://example/{}".format(i), "title": "공지 {}".format(i),
            "posted_date": "2026-03-01", "department": None,
            "body_text": "본문 {}".format(i),
            "attachments": [{"name": "a.pdf", "url": "https://example/a.pdf"}],
            "crawled_at": "2026-09-16T00:00:00",
        }
        for i in range(n)
    ]
    path = tmp_path / "_all.json"
    path.write_text(json.dumps({"total": n, "notices": notices}, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_load_is_idempotent(tmp_path):
    path = str(tmp_path / "t.db")
    db.init(path)
    src = _sample(tmp_path)
    assert db.load(src, path) == 3
    assert db.load(src, path) == 3
    conn = db.connect(path)
    row = conn.execute("SELECT * FROM notice WHERE key = 'hq:0'").fetchone()
    assert row["title"] == "공지 0"
    assert json.loads(row["attachments"])[0]["name"] == "a.pdf"
    assert row["body_hash"] == db.body_hash("공지 0", "본문 0")
    conn.close()


def test_body_hash_is_sha1_of_title_newline_body():
    import hashlib

    assert db.body_hash("t", "b") == hashlib.sha1(b"t\nb").hexdigest()
