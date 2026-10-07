"""Autenticação por e-mail e senha, com sessão guardada no servidor.

O cookie leva um token aleatório; o banco guarda só o SHA-256 dele. Sair da
conta apaga a sessão, que deixa de valer na hora, ao contrário de um cookie
assinado, que valeria até expirar.
"""

import asyncio
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from src.storage import accounts, cache

SESSION_COOKIE = "graham_session"
SESSION_TTL = timedelta(days=30)

# Custo do bcrypt: cerca de 0,25 s por hash, fora do event loop.
BCRYPT_ROUNDS = 12
# O bcrypt só lê os primeiros 72 bytes; acima disso, a senha é recusada.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 8

# Tentativas de login erradas por e-mail antes do bloqueio, e por quanto tempo.
MAX_FAILURES = 10
FAILURE_WINDOW = timedelta(minutes=15)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Conferido quando o e-mail não existe, para a resposta levar o mesmo tempo
# de uma senha errada e não revelar quem tem conta.
_DUMMY_HASH = bcrypt.hashpw(b"graham", bcrypt.gensalt(BCRYPT_ROUNDS))

router = APIRouter(prefix="/api/auth")


# Senhas e tokens ───────────────────────────────────────────────────────────


async def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(BCRYPT_ROUNDS)
    return (await asyncio.to_thread(bcrypt.hashpw, password.encode(), salt)).decode()


async def check_password(password: str, password_hash: str | None) -> bool:
    expected = password_hash.encode() if password_hash else _DUMMY_HASH
    try:
        matches = await asyncio.to_thread(bcrypt.checkpw, password.encode(), expected)
    except ValueError:  # senha acima de 72 bytes ou hash corrompido
        return False
    return matches and password_hash is not None


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


# Sessão ────────────────────────────────────────────────────────────────────


async def _start_session(request: Request, response: Response, user_id: UUID) -> None:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    await accounts.create_session(request.app.state.pool, user_id, _token_hash(token), expires_at)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


async def current_user(request: Request) -> dict[str, Any] | None:
    """O usuário da sessão do cookie, ou `None`."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await accounts.session_user(request.app.state.pool, _token_hash(token))


async def require_user(request: Request) -> UUID:
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Entre na sua conta para continuar.")
    return user["id"]


# Rotas ─────────────────────────────────────────────────────────────────────


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_BYTES)

    @field_validator("email")
    @classmethod
    def _normalize(cls, value: str) -> str:
        email = value.strip().lower()
        if not EMAIL_PATTERN.match(email):
            raise ValueError("E-mail inválido.")
        return email

    @field_validator("password")
    @classmethod
    def _fits_bcrypt(cls, value: str) -> str:
        if len(value.encode()) > MAX_PASSWORD_BYTES:
            raise ValueError(f"A senha passa de {MAX_PASSWORD_BYTES} bytes.")
        return value


class NewAccount(Credentials):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_BYTES)


@router.post("/signup", status_code=201)
async def signup(body: NewAccount, request: Request, response: Response) -> dict[str, str]:
    user_id = await accounts.create_account(
        request.app.state.pool, body.email, await hash_password(body.password)
    )
    if user_id is None:
        raise HTTPException(status_code=409, detail="Este e-mail já tem conta. Entre com ele.")
    await _start_session(request, response, user_id)
    return {"email": body.email}


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response) -> dict[str, str]:
    redis = request.app.state.redis
    failures = cache.key("auth", "failures", body.email)
    if int(await redis.get(failures) or 0) >= MAX_FAILURES:
        raise HTTPException(
            status_code=429, detail="Muitas tentativas erradas. Tente de novo em alguns minutos."
        )

    account = await accounts.find_by_email(request.app.state.pool, body.email)
    if not await check_password(body.password, account and account["password_hash"]):
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(failures)
            pipe.expire(failures, int(FAILURE_WINDOW.total_seconds()))
            await pipe.execute()
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")

    await redis.delete(failures)
    await _start_session(request, response, account["id"])
    return {"email": account["email"]}


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await accounts.delete_session(request.app.state.pool, _token_hash(token))
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me")
async def me(request: Request) -> dict[str, str]:
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Sem sessão.")
    return {"email": user["email"]}
