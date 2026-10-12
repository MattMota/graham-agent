"""Chaves de acesso ao servidor MCP: o usuário cria, vê e revoga as suas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from src.mcp_server import server as mcp_server
from src.server.auth import require_user
from src.storage import tokens
from src.tools.catalog import READ, WRITE

router = APIRouter(prefix="/api/keys")

# Um limite que nenhum uso normal alcança, só para conter um laço que crie chaves.
MAX_KEYS = 20


class NewKey(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="Para quem é a chave, como 'Claude Code'.")
    can_write: bool = Field(default=False, description="Se a chave pode gravar na carteira e na watchlist.")

    @field_validator("name")
    @classmethod
    def _clean(cls, value: str) -> str:
        name = " ".join(value.split())
        if not name:
            raise ValueError("Dê um nome à chave.")
        return name


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _key(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "can_write": WRITE in row["scopes"],
        "created_at": _iso(row["created_at"]),
        "last_used_at": _iso(row["last_used_at"]),
    }


@router.get("")
async def list_keys(request: Request) -> dict[str, Any]:
    rows = await tokens.list_keys(request.app.state.pool, await require_user(request))
    return {"mcp_url": f"{mcp_server.public_url()}{mcp_server.PATH}", "keys": [_key(row) for row in rows]}


@router.post("", status_code=201)
async def create_key(body: NewKey, request: Request) -> dict[str, Any]:
    pool, user_id = request.app.state.pool, await require_user(request)
    if len(await tokens.list_keys(pool, user_id)) >= MAX_KEYS:
        raise HTTPException(status_code=409, detail=f"Limite de {MAX_KEYS} chaves; revogue alguma antes.")
    scopes = [READ, WRITE] if body.can_write else [READ]
    token, row = await tokens.issue(pool, user_id, "chave", scopes, name=body.name)
    # A única vez em que a chave aparece: só o hash dela fica guardado.
    return {**_key(row), "token": token}


@router.delete("/{key_id}", status_code=204)
async def revoke_key(key_id: UUID, request: Request) -> None:
    if not await tokens.revoke_key(request.app.state.pool, await require_user(request), key_id):
        raise HTTPException(status_code=404, detail="Chave não encontrada.")
