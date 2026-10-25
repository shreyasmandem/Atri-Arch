# One container: the FastAPI backend serves the API and the static studio.
# Free hosts: Hugging Face Spaces (Docker, 16 GB RAM) or Render (render.yaml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ENVIRONMENT=production DEBUG=false PUBLIC_DEMO=true PORT=7860 PYTHONPATH=/app/backend
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY README.md backend/README.md
COPY backend/pyproject.toml backend/
COPY backend/aip backend/aip
# setuptools will not read a readme outside the package directory.
RUN sed -i "s#../README.md#README.md#" backend/pyproject.toml && pip install "./backend[vision]"
COPY frontend frontend

# A writable place for the SQLite store and caches (Spaces run as a non-root user).
RUN mkdir -p backend/var backend/data && chmod -R 777 backend/var backend/data
WORKDIR /app/backend
EXPOSE 7860
CMD ["sh", "-c", "uvicorn aip.api.app:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers"]
