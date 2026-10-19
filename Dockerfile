# O Graham num container, para subir tudo com `docker compose --profile app up`.
# Roda só na máquina do usuário (docs/adr/0001): a porta fica presa ao 127.0.0.1.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1

# As dependências antes do código: mudar um arquivo do projeto não reinstala tudo.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .

EXPOSE 8000
# As migrations pendentes antes de subir: o servidor se recusa a subir sem elas.
CMD ["sh", "-c", "uv run --no-sync db/migrate.py && exec uv run --no-sync uvicorn src.server.app:app --host 0.0.0.0 --port 8000"]
