# Farkle World

Base dockerizada para una app multijugador de Farkle. La lógica de las partidas queda pendiente; esta primera versión identifica al jugador por nombre y por un UUID persistente del navegador.

## Desarrollo con uv

```powershell
uv sync
uv run uvicorn app.main:app --reload
```

Abre <http://localhost:8000>.

## Docker

```powershell
docker compose up --build
```

La base de datos SQLite se conserva en el volumen `farkle-data`. El endpoint `POST /api/players` recibe `{ "name": "Alex", "device_id": "..." }`; volver a registrarse desde el mismo navegador actualiza el nombre existente.