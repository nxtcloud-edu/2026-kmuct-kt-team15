"""FastAPI app: static files and the /api routes (SPEC 5, 7, 8.2)."""

import json
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app import db

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "static")

app = FastAPI(title="UniQ")


def today():
    return os.environ.get("DEMO_TODAY", "2026-03-16")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))


@app.get("/api/config")
def config():
    conn = db.connect()
    try:
        sources = conn.execute("SELECT COUNT(DISTINCT source_id) FROM notice").fetchone()[0]
        row = conn.execute("SELECT value FROM meta WHERE key = 'suggested_questions'").fetchone()
    finally:
        conn.close()
    questions = []
    if row:
        try:
            questions = json.loads(row["value"])
        except ValueError:
            questions = []
    return {"today": today(), "sources": sources, "suggested_questions": questions}
