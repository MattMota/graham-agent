"""Abre o MCP Inspector já conectado ao servidor MCP do Graham.

Cria uma chave de acesso temporária para a conta, passa ao Inspector no
cabeçalho e a revoga quando ele fecha. Uso, a partir da raiz do projeto, com o
servidor no ar:

    uv run scripts/mcp_inspector.py --email user@email.com
    uv run scripts/mcp_inspector.py --email user@email.com --escrita
    uv run scripts/mcp_inspector.py --email user@email.com -- --cli --method tools/list

Sem `--escrita`, a chave só lê: as ferramentas que gravam respondem com a
recusa. O que vier depois de `--` vai direto ao Inspector (por padrão, abre a
interface web). Precisa do Node (npx).
"""

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mcp_server.server import PATH, public_url  # noqa: E402
from src.storage import tokens  # noqa: E402
from src.tools.catalog import READ, WRITE  # noqa: E402

# A versão do Inspector com que o script foi testado; a maior fica fixa para
# uma mudança de linha de comando não quebrar o script sem aviso.
INSPECTOR = "@modelcontextprotocol/inspector@2"

# Se o script cair sem revogar, a chave vence sozinha.
KEY_TTL = timedelta(hours=12)
KEY_NAME = "MCP Inspector (temporária)"


def _pool() -> AsyncConnectionPool:
    return AsyncConnectionPool(
        os.environ["DATABASE_URL"], open=False, min_size=1, max_size=1,
        kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
    )


async def _issue(email: str, can_write: bool) -> tuple[str, str]:
    async with _pool() as pool:
        async with pool.connection() as conn:
            user = await (await conn.execute("SELECT id FROM core.users WHERE email = %s", (email.strip().lower(),))).fetchone()
        if user is None:
            raise SystemExit(f"Nenhuma conta com o e-mail {email}.")
        token, row = await tokens.issue(
            pool, user["id"], "chave", [READ, WRITE] if can_write else [READ], name=KEY_NAME, ttl=KEY_TTL
        )
        return token, str(row["id"])


async def _revoke(key_id: str) -> None:
    async with _pool() as pool:
        async with pool.connection() as conn:
            await conn.execute("UPDATE core.access_tokens SET revoked_at = now() WHERE id = %s", (key_id,))


def _run(coroutine):
    # O psycopg assíncrono não funciona com o ProactorEventLoop, o padrão do Windows.
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


def main() -> None:
    load_dotenv()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Abre o MCP Inspector conectado ao servidor MCP do Graham.")
    parser.add_argument("--email", required=True, help="Conta em nome da qual o Inspector chama as ferramentas.")
    parser.add_argument("--escrita", action="store_true", help="Permite as ferramentas que gravam na carteira e na watchlist.")
    args, extra = parser.parse_known_args()
    if extra and extra[0] == "--":
        extra = extra[1:]

    url = f"{public_url()}{PATH}"
    try:
        httpx.get(f"{public_url()}/api/health", timeout=5).raise_for_status()
    except httpx.HTTPError:
        raise SystemExit(f"O servidor não responde em {public_url()}. Suba-o antes (uv run uvicorn src.server.app:app --reload).")

    npx = shutil.which("npx")
    if npx is None:
        raise SystemExit("O MCP Inspector precisa do Node: instale-o e tente de novo.")

    token, key_id = _run(_issue(args.email, args.escrita))
    access = "leitura e escrita" if args.escrita else "só leitura"
    print(f"Chave temporária criada para {args.email} ({access}); será revogada ao fechar o Inspector.", flush=True)
    mode = [] if extra and extra[0] in ("--web", "--cli", "--tui") else ["--web"]
    # Sem a era, o Inspector conecta pela versão antiga do protocolo, que não
    # negocia extensões: as skills ficariam invisíveis. `auto` é o que o Graham usa.
    era = [] if "--protocol-era" in extra else ["--protocol-era", "auto"]
    command = [npx, "-y", INSPECTOR, *mode, *extra, *era, "--transport", "http", "--server-url", url,
               "--header", f"Authorization: Bearer {token}"]
    try:
        subprocess.run(command, check=False)
    except KeyboardInterrupt:
        pass
    finally:
        _run(_revoke(key_id))
        print("Chave temporária revogada.", flush=True)


if __name__ == "__main__":
    main()
