"""API tests (SPEC 7, 10). Temp DB, FastAPI TestClient."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app import db

TODAY = "2026-03-16"


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = str(tmp_path / "api.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setenv("DEMO_TODAY", TODAY)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init(path)
    from app import main

    monkeypatch.setattr(main, "STATIC", main.STATIC)
    with TestClient(main.app) as c:
        c.db_path = path
        yield c


def add_notice(path, key, posted="2026-03-01", title="공지", source="hq"):
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO notice (key, source_id, source_name, url, title, posted_date,"
            " department, body_text, attachments, body_hash, crawled_at)"
            " VALUES (?, ?, ?, ?, ?, ?, NULL, '', '[]', ?, '2026-03-01')",
            (key, source, "게시판", "https://example/" + key, title, posted, db.body_hash(title, "")),
        )
    conn.close()


def test_index_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "UniQ" in res.text


def test_config(client):
    add_notice(client.db_path, "a:1", source="a")
    add_notice(client.db_path, "b:1", source="b")
    conn = db.connect(client.db_path)
    with conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('suggested_questions', ?)",
            (json.dumps(["학점 2.8이어도 돼?"], ensure_ascii=False),),
        )
    conn.close()
    body = client.get("/api/config").json()
    assert body == {"today": TODAY, "sources": 2, "suggested_questions": ["학점 2.8이어도 돼?"]}


def test_config_without_meta_gives_an_empty_list(client):
    body = client.get("/api/config").json()
    assert body["suggested_questions"] == []
    assert body["sources"] == 0
