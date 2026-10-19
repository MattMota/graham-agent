"""Alocação: a classe de cada ativo, o enquadramento da carteira na alocação-alvo
e a sugestão de rebalanceamento (docs/adr/0004).

Os pesos são medidos em reais, pelo câmbio de agora: é a única conta do Graham
que soma moedas diferentes. Nada aqui grava operações; o rebalanceamento só
sugere, e cada compra ou venda passa depois pelas ferramentas de registro.
"""

import asyncio
import math
import re
import unicodedata
from decimal import Decimal
from typing import Any, Optional

from src.storage import allocation as targets_store
from src.storage import portfolio as store
from src.storage.cache import cached
from src.tools import market, portfolio
from src.tools.context import ToolContext, ToolFailure

BASE_CURRENCY = "BRL"

CLASSES = targets_store.CLASSES

CLASS_LABELS = {
    "acoes_br": "Ações brasileiras",
    "fundos": "Fundos listados",
    "etfs": "ETFs",
    "exterior": "Exterior",
    "cripto": "Cripto",
    "outros": "Outros",
}

# O tipo e o nome de um ativo quase nunca mudam.
CLASS_TTL = 7 * 24 * 60 * 60

# BDRs: quatro letras e 31 a 35 (patrocinados e não) ou 39 (BDR de ETF).
BDR_CODE = re.compile(r"[A-Z0-9]{4}(3[1-5]|39)")

ENQUADRAMENTO_NOTE = (
    "Pesos em reais, pelas cotações e pelo câmbio de agora, sobre o valor dos ativos "
    "classificados; os de `outside_allocation` ficam fora da conta. Uma classe está "
    "`dentro` quando o peso fica a até `tolerance` pontos percentuais do alvo."
)

REBALANCE_NOTE = (
    "Sugestão sobre a alocação-alvo do usuário, em reais, pelas cotações e pelo câmbio de "
    "agora. Dentro de cada classe, o valor é dividido na proporção do que o usuário já tem. "
    "Quantidades arredondadas para baixo (inteiras, menos cripto); o que sobra fica em "
    "`cash_left`. Nada foi registrado: cada ordem só entra na carteira por `registrar_compra` "
    "ou `registrar_venda`, com a confirmação do usuário. Não é recomendação de investimento."
)


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None or not math.isfinite(value) else round(value, digits)


# Classe de ativo ───────────────────────────────────────────────────────────


def _plain(text: Optional[str]) -> str:
    """Minúsculas e sem acento: a Yahoo escreve 'Imobiliário', 'Imobiliario' e 'Imobiliaro'."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def classify(ticker: str, quote_type: Optional[str], name: Optional[str]) -> str:
    """A classe de ativo pelo tipo e pelo nome que a Yahoo dá.

    A Yahoo marca FIIs e ETFs da B3 como `EQUITY`; o nome é o que os separa.
    """
    if quote_type == "CRYPTOCURRENCY":
        return "cripto"
    if quote_type == "ETF":
        return "etfs"
    if quote_type != "EQUITY":
        return "outros"
    if not ticker.endswith(".SA"):
        return "exterior"
    if BDR_CODE.fullmatch(ticker.removesuffix(".SA")):
        return "exterior"
    plain = _plain(name)
    # Antes dos fundos: ETFs antigos se chamam "fundo de índice".
    if "indice" in plain or re.search(r"\betf\b", plain):
        return "etfs"
    if "fundo" in plain or "fiagro" in plain or "imobili" in plain:
        return "fundos"
    return "acoes_br"


# Um ativo que a Yahoo não respondeu não fica no cache: pode ser a fonte fora do ar.
@cached("classe", ttl=CLASS_TTL, keep=lambda result: result["quote_type"] is not None)
def _asset_info(ticker: str) -> dict[str, Any]:
    info = market._safe(lambda: market._ticker(ticker).get_info()) or {}
    return {"quote_type": info.get("quoteType"), "name": info.get("longName") or info.get("shortName")}


async def asset_class(ticker: str) -> str:
    info = await asyncio.to_thread(_asset_info, ticker)
    return classify(ticker, info["quote_type"], info["name"])


# A carteira em reais ───────────────────────────────────────────────────────


async def _holdings(context: ToolContext) -> tuple[list[dict[str, Any]], list[str]]:
    """As posições em aberto com classe, cotação e valor em reais, e as sem cotação."""
    pool, user_id = context.require_user()
    positions = [
        position for position in store.replay(await store.list_trades(pool, user_id)).values()
        if position.quantity > 0
    ]
    quotes, classes = await asyncio.gather(
        asyncio.gather(*(portfolio._quote(position.ticker) for position in positions)),
        asyncio.gather(*(asset_class(position.ticker) for position in positions)),
    )
    currencies = sorted({(quote or {}).get("currency") or position.quote_currency
                         for position, quote in zip(positions, quotes)})
    rates = dict(zip(currencies, await asyncio.gather(
        *(portfolio._exchange_rate(currency, BASE_CURRENCY) for currency in currencies)
    )))

    assets, missing = [], []
    for position, quote, asset_class_ in zip(positions, quotes, classes):
        price = (quote or {}).get("price")
        currency = (quote or {}).get("currency") or position.quote_currency
        rate = rates.get(currency)
        if price is None or rate is None:
            missing.append(position.ticker)
            continue
        quantity = float(position.quantity)
        assets.append({
            "ticker_name": position.ticker,
            "asset_class": asset_class_,
            "quantity": quantity,
            "price": price,
            "currency": currency,
            "rate": float(rate),
            "value": quantity * price * float(rate),
        })
    return assets, missing


def _by_class(assets: list[dict[str, Any]]) -> dict[str, float]:
    values = {name: 0.0 for name in CLASSES}
    for asset in assets:
        if asset["asset_class"] in values:
            values[asset["asset_class"]] += asset["value"]
    return values


def _status(weight: float, target: float, tolerance: float) -> str:
    deviation = round(weight - target, 6)
    if deviation > tolerance:
        return "acima"
    if deviation < -tolerance:
        return "abaixo"
    return "dentro"


def _targets(row: dict[str, Any]) -> tuple[dict[str, float], float]:
    return {name: float(row[name]) for name in CLASSES}, float(row["tolerance"])


# Ferramentas ───────────────────────────────────────────────────────────────


async def set_allocation(
    context: ToolContext,
    acoes_br: float,
    fundos: float,
    etfs: float,
    exterior: float,
    cripto: float,
    tolerance: float = 5,
) -> dict[str, Any]:
    pool, user_id = context.require_user()
    weights = {"acoes_br": acoes_br, "fundos": fundos, "etfs": etfs, "exterior": exterior, "cripto": cripto}
    row = await targets_store.set_targets(
        pool, user_id, {name: Decimal(str(value)) for name, value in weights.items()}, Decimal(str(tolerance))
    )
    weights, tolerance = _targets(row)
    return {
        "targets": [
            {"asset_class": name, "label": CLASS_LABELS[name], "target_percent": weights[name]}
            for name in CLASSES
        ],
        "tolerance": tolerance,
        "updated_at": row["updated_at"].isoformat(),
    }


async def view_allocation(context: ToolContext) -> dict[str, Any]:
    pool, user_id = context.require_user()
    (assets, missing), row = await asyncio.gather(_holdings(context), targets_store.get_targets(pool, user_id))
    targets, tolerance = _targets(row) if row else (None, None)

    values = _by_class(assets)
    total = sum(values.values())
    classes = []
    for name in CLASSES:
        weight = values[name] / total * 100 if total else 0.0
        item: dict[str, Any] = {
            "asset_class": name,
            "label": CLASS_LABELS[name],
            "value": _round(values[name]),
            "weight_percent": _round(weight),
        }
        if targets:
            item["target_percent"] = targets[name]
            item["deviation_pp"] = _round(weight - targets[name])
            item["status"] = _status(weight, targets[name], tolerance) if total else None
        classes.append(item)

    outside = [asset for asset in assets if asset["asset_class"] not in CLASSES]
    output: dict[str, Any] = {
        "base_currency": BASE_CURRENCY,
        "total_value": _round(total),
        "has_targets": row is not None,
        "tolerance": tolerance,
        "in_range": all(item["status"] == "dentro" for item in classes) if targets and total else None,
        "classes": classes,
        "assets": [
            {
                "ticker_name": asset["ticker_name"],
                "asset_class": asset["asset_class"],
                "value": _round(asset["value"]),
                "weight_percent": _round(asset["value"] / total * 100) if total else None,
            }
            for asset in sorted(assets, key=lambda asset: asset["value"], reverse=True)
            if asset["asset_class"] in CLASSES
        ],
        "note": ENQUADRAMENTO_NOTE,
    }
    if not assets and not missing:
        output["note"] = "A carteira não tem posições em aberto."
    elif not row:
        output["note"] = (
            "Sem alocação-alvo: estes são os pesos atuais. Para comparar com um alvo, o "
            "usuário define e confirma a alocação-alvo por `definir_alocacao`. " + ENQUADRAMENTO_NOTE
        )
    if outside:
        output["outside_allocation"] = [asset["ticker_name"] for asset in outside]
    if missing:
        output["unavailable"] = missing
    return output


def _quantity(money: float, unit_value: float, asset_class: str) -> float:
    """Quantas unidades cabem no valor, arredondando para baixo."""
    if unit_value <= 0:
        return 0.0
    quantity = money / unit_value
    if asset_class == "cripto":
        return math.floor(quantity * 1e6) / 1e6
    return float(math.floor(quantity + 1e-9))


async def suggest_rebalance(
    context: ToolContext, contribution: float = 0, allow_sales: bool = False
) -> dict[str, Any]:
    pool, user_id = context.require_user()
    (assets, missing), row, watch = await asyncio.gather(
        _holdings(context), targets_store.get_targets(pool, user_id), store.list_watch(pool, user_id)
    )
    if row is None:
        raise ToolFailure(
            "O usuário ainda não definiu a alocação-alvo. Combine os pesos com ele e grave-os "
            "com `definir_alocacao` antes de sugerir um rebalanceamento."
        )
    if missing:
        raise ToolFailure(
            f"Sem cotação ou câmbio agora para {', '.join(missing)}; sem eles os pesos não fecham. "
            "Tente de novo em instantes."
        )
    targets, _ = _targets(row)

    values = _by_class(assets)
    total = sum(values.values()) + contribution
    if total <= 0:
        raise ToolFailure("A carteira não tem posições, e não há aporte para distribuir.")

    gaps = {name: targets[name] / 100 * total - values[name] for name in CLASSES}
    if allow_sales:
        amounts = gaps
    else:
        # Sem vender, o aporte vai às classes abaixo do alvo, na proporção do que falta a cada uma.
        short = {name: gap for name, gap in gaps.items() if gap > 0}
        missing_total = sum(short.values())
        amounts = {name: gap * contribution / missing_total for name, gap in short.items()} if missing_total else {}

    watched: dict[str, list[str]] = {}
    for entry in watch:
        if entry["operation"] == "compra":
            watched.setdefault(await asset_class(entry["ticker"]), []).append(entry["ticker"])

    orders, unassigned = [], []
    for name, amount in amounts.items():
        if abs(amount) < 0.01:
            continue
        in_class = [asset for asset in assets if asset["asset_class"] == name]
        if not in_class:
            if amount > 0:
                unassigned.append({
                    "asset_class": name,
                    "label": CLASS_LABELS[name],
                    "amount": _round(amount),
                    "watchlist_candidates": sorted(set(watched.get(name, []))),
                })
            continue
        for asset in in_class:
            share = asset["value"] / values[name] if values[name] else 1 / len(in_class)
            unit_value = asset["price"] * asset["rate"]
            quantity = _quantity(abs(amount) * share, unit_value, name)
            if amount < 0:
                quantity = min(quantity, asset["quantity"])
            if quantity <= 0:
                continue
            orders.append({
                "ticker_name": asset["ticker_name"],
                "asset_class": name,
                "side": "compra" if amount > 0 else "venda",
                "quantity": quantity,
                "price": asset["price"],
                "currency": asset["currency"],
                "amount": _round(quantity * unit_value),
            })

    bought = sum(order["amount"] for order in orders if order["side"] == "compra")
    sold = sum(order["amount"] for order in orders if order["side"] == "venda")
    after = dict(values)
    for order in orders:
        after[order["asset_class"]] += order["amount"] if order["side"] == "compra" else -order["amount"]
    after_total = sum(after.values())

    return {
        "base_currency": BASE_CURRENCY,
        "contribution": contribution,
        "allow_sales": allow_sales,
        "orders": sorted(orders, key=lambda order: (order["side"] != "venda", -order["amount"])),
        "unassigned": unassigned,
        "cash_left": _round(contribution - bought + sold),
        "classes": [
            {
                "asset_class": name,
                "label": CLASS_LABELS[name],
                "target_percent": targets[name],
                "weight_before": _round(values[name] / (total - contribution) * 100) if total > contribution else 0.0,
                "weight_after": _round(after[name] / after_total * 100) if after_total else 0.0,
            }
            for name in CLASSES
        ],
        "note": REBALANCE_NOTE,
    }
