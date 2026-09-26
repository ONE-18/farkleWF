from datetime import datetime, timezone
import secrets
import sqlite3


WAITING = "waiting"
PLAYING = "playing"
FINISHED = "finished"


class GameError(Exception):
    # Los errores de dominio llevan directamente el estado HTTP que necesita la API.
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def _now() -> str:
    # Todas las fechas se guardan en UTC para que los clientes compartan la misma referencia.
    return datetime.now(timezone.utc).isoformat()


def _new_game_id(connection: sqlite3.Connection) -> str:
    # El código corto se comparte entre jugadores, por eso se regenera si ya existe.
    for _ in range(5):
        game_id = secrets.token_hex(4).upper()
        exists = connection.execute(
            "SELECT 1 FROM games WHERE id = ?", (game_id,)
        ).fetchone()
        if exists is None:
            return game_id
    raise GameError(500, "No se pudo generar el identificador de la partida")


def _require_player(connection: sqlite3.Connection, player_id: int) -> None:
    # Las operaciones de partida solo pueden ejecutarse para jugadores registrados.
    player = connection.execute(
        "SELECT 1 FROM players WHERE id = ?", (player_id,)
    ).fetchone()
    if player is None:
        raise GameError(404, "El jugador no existe")


def get_game(connection: sqlite3.Connection, game_id: str) -> dict:
    # La respuesta combina los datos de la partida con sus jugadores y asientos.
    game = connection.execute(
        """
         SELECT id, host_player_id, status, current_player_id, turn_number,
             created_at, updated_at
        FROM games
        WHERE id = ?
        """,
        (game_id.upper(),),
    ).fetchone()
    if game is None:
        raise GameError(404, "La partida no existe")

    # El orden por asiento mantiene estable el turno y la representación del lobby.
    players = connection.execute(
        """
        SELECT p.id, p.name, gp.seat, gp.score
        FROM game_players AS gp
        JOIN players AS p ON p.id = gp.player_id
        WHERE gp.game_id = ?
        ORDER BY gp.seat
        """,
        (game_id.upper(),),
    ).fetchall()
    return {
        **dict(game),
        "players": [dict(player) for player in players],
    }


def create_game(
    connection: sqlite3.Connection, player_id: int
) -> dict:
    # Una partida comienza abierta; el creador decide cuándo pasar a playing.
    _require_player(connection, player_id)
    game_id = _new_game_id(connection)
    now = _now()
    # max_players se conserva como columna histórica de SQLite, pero su valor 0 significa "sin límite".
    connection.execute(
        """
        INSERT INTO games (
            id, host_player_id, status, current_player_id, turn_number,
            max_players, created_at, updated_at
        ) VALUES (?, ?, ?, NULL, 0, ?, ?, ?)
        """,
        (game_id, player_id, WAITING, 0, now, now),
    )
    connection.execute(
        "INSERT INTO game_players (game_id, player_id, seat) VALUES (?, ?, 1)",
        (game_id, player_id),
    )
    return get_game(connection, game_id)


def join_game(connection: sqlite3.Connection, game_id: str, player_id: int) -> dict:
    # Un jugador puede repetir la petición sin obtener un segundo asiento.
    game = get_game(connection, game_id)
    _require_player(connection, player_id)
    if game["status"] != WAITING:
        raise GameError(409, "La partida ya ha comenzado")
    if any(player["id"] == player_id for player in game["players"]):
        return game
    # El siguiente asiento se calcula al final de la lista porque las partidas son dinámicas.
    seat = len(game["players"]) + 1
    connection.execute(
        "INSERT INTO game_players (game_id, player_id, seat) VALUES (?, ?, ?)",
        (game["id"], player_id, seat),
    )
    connection.execute(
        "UPDATE games SET updated_at = ? WHERE id = ?", (_now(), game["id"])
    )
    return get_game(connection, game["id"])


def start_game(connection: sqlite3.Connection, game_id: str, player_id: int) -> dict:
    # Solo el anfitrión inicia la partida; las reglas de dados aún no intervienen aquí.
    game = get_game(connection, game_id)
    if game["host_player_id"] != player_id:
        raise GameError(403, "Solo el creador puede iniciar la partida")
    if game["status"] != WAITING:
        raise GameError(409, "La partida ya ha comenzado")
    if len(game["players"]) < 2:
        raise GameError(409, "Se necesitan al menos 2 jugadores")

    # El primer asiento determina quién recibe el primer turno de la estructura actual.
    first_player_id = game["players"][0]["id"]
    connection.execute(
        """
        UPDATE games
        SET status = ?, current_player_id = ?, turn_number = 1, updated_at = ?
        WHERE id = ?
        """,
        (PLAYING, first_player_id, _now(), game["id"]),
    )
    return get_game(connection, game["id"])