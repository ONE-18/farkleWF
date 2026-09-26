# Imagen ligera para ejecutar FastAPI con la versión de Python del proyecto.
FROM python:3.14-slim

# Usar uv dentro de la imagen mantiene la instalación alineada con el desarrollo local.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FARKLE_DB_PATH=/data/farkle.db

# Copiar primero las dependencias permite reutilizar la capa si solo cambia el código.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

# El código se copia después de instalar dependencias para aprovechar la caché de Docker.
COPY app ./app
RUN mkdir -p /data

EXPOSE 8000
# Uvicorn escucha en todas las interfaces para que Compose pueda publicar el puerto.
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]