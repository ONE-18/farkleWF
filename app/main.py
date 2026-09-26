from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATABASE_PATH = Path(os.getenv("FARKLE_DB_PATH", "data/farkle.db"))


def get_connection() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                device_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_players_name_unique "
            "ON players (name COLLATE NOCASE)"
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Farkle World", version="0.1.0", lifespan=lifespan)


class PlayerRegistration(BaseModel):
    name: str = Field(..., min_length=2, max_length=40)
    device_id: str = Field(..., min_length=10, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres")
        return cleaned


class PlayerResponse(BaseModel):
    id: int
    name: str
    device_id: str
    created_at: str
    updated_at: str


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/players", response_model=PlayerResponse)
def register_player(player: PlayerRegistration) -> PlayerResponse:
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO players (name, device_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (player.name, player.device_id, now, now),
            )
            row = connection.execute(
                "SELECT id, name, device_id, created_at, updated_at FROM players WHERE device_id = ?",
                (player.device_id,),
            ).fetchone()
    except sqlite3.IntegrityError as error:
        if "players.name" in str(error) or "idx_players_name_unique" in str(error):
            raise HTTPException(
                status_code=409,
                detail="Ese nombre ya está siendo usado por otro cliente",
            ) from error
        raise

    if row is None:
        raise HTTPException(status_code=500, detail="No se pudo guardar el jugador")
    return PlayerResponse(**dict(row))


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/app.js", include_in_schema=False)
def serve_script() -> FileResponse:
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")


@app.get("/styles.css", include_in_schema=False)
def serve_styles() -> FileResponse:
    return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")