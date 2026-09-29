"""Aplica as migrations de `db/migrations/` em ordem, cada uma uma única vez.

Uso, a partir da raiz do projeto:

    uv run db/migrate.py
"""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def main() -> None:
    load_dotenv()

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.schema_migrations (
                name       text        PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = {name for (name,) in conn.execute("SELECT name FROM public.schema_migrations")}

        pending = [path for path in sorted(MIGRATIONS_DIR.glob("*.sql")) if path.name not in applied]
        if not pending:
            print("Nenhuma migration pendente.")
            return

        for path in pending:
            # Cada arquivo roda numa transação: se falhar no meio, nada dele fica
            # aplicado e ele continua pendente para a próxima execução.
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO public.schema_migrations (name) VALUES (%s)", (path.name,))
            print(f"Aplicada: {path.name}")


if __name__ == "__main__":
    main()
