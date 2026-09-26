from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from .games import GameError, create_game, get_game, join_game, start_game


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
# El volumen Docker define esta ruta; fuera de Docker se usa data/farkle.db.
DATABASE_PATH = Path(os.getenv("FARKLE_DB_PATH", "data/farkle.db"))


def get_connection() -> sqlite3.Connection:
    # Cada operación abre su propia conexión y sqlite3.Row permite respuestas tipo diccionario.
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    # El esquema se crea al arrancar para que un volumen nuevo sea utilizable sin migraciones manuales.
    with get_connection() as connection:
        # El índice evita que dos dispositivos usen el mismo nombre, ignorando mayúsculas.
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
        # La tabla games representa la sala y el turno actual, no las reglas de Farkle.
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_players_name_unique "
            "ON players (name COLLATE NOCASE)"
        )
        # La relación separada permite que cada jugador tenga asiento y puntuación dentro de una partida.
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS games (
                id TEXT PRIMARY KEY,
                host_player_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                current_player_id INTEGER,
                turn_number INTEGER NOT NULL DEFAULT 0,
                max_players INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (host_player_id) REFERENCES players (id),
                FOREIGN KEY (current_player_id) REFERENCES players (id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS game_players (
                game_id TEXT NOT NULL,
                player_id INTEGER NOT NULL,
                seat INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (game_id, player_id),
                UNIQUE (game_id, seat),
                FOREIGN KEY (game_id) REFERENCES games (id),
                FOREIGN KEY (player_id) REFERENCES players (id)
            )
            """
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    # FastAPI espera a que el esquema exista antes de aceptar peticiones.
    initialize_database()
    yield


# La aplicación sirve la API y los archivos estáticos desde el mismo proceso.
app = FastAPI(title="Farkle World", version="0.1.0", lifespan=lifespan)


class PlayerRegistration(BaseModel):
    # El device_id llega del localStorage y vincula futuras visitas con el mismo jugador.
    name: str = Field(..., min_length=2, max_length=40)
    device_id: str = Field(..., min_length=10, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        # Normalizar espacios antes de comprobar la unicidad evita nombres visualmente duplicados.
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


class CreateGameRequest(BaseModel):
    # La capacidad de la partida es dinámica; solo hace falta identificar al creador.
    player_id: int


class JoinGameRequest(BaseModel):
    player_id: int


class GameActionRequest(BaseModel):
    player_id: int


@app.get("/api/health")
def health_check() -> dict[str, str]:
    # Endpoint ligero para Docker, monitorización y comprobaciones locales.
    return {"status": "ok"}


@app.post("/api/players", response_model=PlayerResponse)
def register_player(player: PlayerRegistration) -> PlayerResponse:
    # El mismo device_id actualiza su jugador; otro dispositivo con el mismo nombre recibe 409.
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


def handle_game_error(error: GameError) -> None:
    # Traducir errores de dominio aquí mantiene games.py independiente de FastAPI.
    raise HTTPException(status_code=error.status_code, detail=error.detail) from error


@app.post("/api/games")
def create_game_endpoint(request: CreateGameRequest) -> dict:
    # Crear devuelve la sala con el anfitrión ya sentado en la posición 1.
    try:
        with get_connection() as connection:
            return create_game(connection, request.player_id)
    except GameError as error:
        handle_game_error(error)


@app.get("/api/games/{game_id}")
def get_game_endpoint(game_id: str) -> dict:
    # Los clientes consultan este recurso para refrescar el lobby y el turno actual.
    try:
        with get_connection() as connection:
            return get_game(connection, game_id)
    except GameError as error:
        handle_game_error(error)


@app.post("/api/games/{game_id}/join")
def join_game_endpoint(game_id: str, request: JoinGameRequest) -> dict:
    # Unirse asigna el siguiente asiento mientras la partida siga esperando.
    try:
        with get_connection() as connection:
            return join_game(connection, game_id, request.player_id)
    except GameError as error:
        handle_game_error(error)


@app.post("/api/games/{game_id}/start")
def start_game_endpoint(game_id: str, request: GameActionRequest) -> dict:
    # Este endpoint solo cambia el estado general; las acciones de Farkle vendrán después.
    try:
        with get_connection() as connection:
            return start_game(connection, game_id, request.player_id)
    except GameError as error:
        handle_game_error(error)


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    # La interfaz inicial se sirve desde el mismo origen que la API.
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/app.js", include_in_schema=False)
def serve_script() -> FileResponse:
    # Ruta explícita para que el frontend pueda cargar su módulo JavaScript.
    return FileResponse(STATIC_DIR / "app.js", media_type="application/javascript")


@app.get("/styles.css", include_in_schema=False)
def serve_styles() -> FileResponse:
    # Ruta explícita para los estilos sin necesidad de un servidor frontend separado.
    return FileResponse(STATIC_DIR / "styles.css", media_type="text/css")