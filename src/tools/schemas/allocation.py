"""Schemas de entrada das ferramentas de alocação: alvo, classe de um ativo,
enquadramento e rebalanceamento."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.tools.schemas.common import TickerSymbol


def _weight(title: str, description: str):
    return Annotated[float, Field(title=title, description=description, ge=0, le=100)]


class AllocationInput(BaseModel):
    """A alocação-alvo do usuário: o peso de cada classe, em %, somando 100."""

    acoes_br: _weight("Ações brasileiras (%)", "Ações e units da B3.")
    fundos: _weight("Fundos listados (%)", "FIIs, Fiagros e FI-Infra negociados na B3.")
    etfs: _weight("ETFs (%)", "ETFs da B3 e de fora.")
    exterior: _weight("Exterior (%)", "Ações estrangeiras e BDRs.")
    cripto: _weight("Cripto (%)", "Criptomoedas.")
    tolerance: float = Field(
        default=5,
        title="Banda de tolerância (p.p.)",
        description=(
            "Quantos pontos percentuais o peso de uma classe pode se afastar do alvo "
            "antes de a carteira ficar desenquadrada."
        ),
        ge=0,
        le=50,
    )

    @model_validator(mode="after")
    def _sums_to_100(self) -> "AllocationInput":
        total = self.acoes_br + self.fundos + self.etfs + self.exterior + self.cripto
        if abs(total - 100) > 0.01:
            raise ValueError(f"Os pesos somam {total:g}%; precisam somar 100%.")
        return self


class AllocationViewInput(BaseModel):
    """O enquadramento não tem filtros: é sempre a carteira inteira."""


class RebalanceInput(BaseModel):
    """Argumentos da sugestão de rebalanceamento."""

    contribution: float = Field(
        default=0,
        title="Aporte (R$)",
        description="Dinheiro novo a investir, em reais. É usado antes de qualquer venda.",
        ge=0,
    )
    allow_sales: bool = Field(
        default=False,
        title="Permitir vendas",
        description=(
            "Se a sugestão pode vender o que está acima do alvo. Sem vendas, só o aporte "
            "corrige os pesos, indo para as classes abaixo do alvo."
        ),
    )


# Rótulos que a interface mostra no lugar dos valores, no cartão de confirmação.
ASSET_CLASS_LABELS = {
    "acoes_br": "Ações brasileiras",
    "fundos": "Fundos listados",
    "etfs": "ETFs",
    "exterior": "Exterior",
    "cripto": "Cripto",
    "fora": "Fora da alocação",
    "automatica": "Automática (pelo tipo e nome na Yahoo)",
}


class AssetClassInput(BaseModel):
    """A classe que o usuário escolhe para um ativo, no lugar da automática."""

    ticker_name: TickerSymbol
    asset_class: Literal["acoes_br", "fundos", "etfs", "exterior", "cripto", "fora", "automatica"] = Field(
        title="Classe",
        description=(
            "A classe em que o ativo conta na alocação: 'acoes_br', 'fundos', 'etfs', 'exterior' "
            "ou 'cripto'; 'fora' para deixá-lo fora da conta; 'automatica' para voltar à classe "
            "que sai do tipo e do nome na Yahoo."
        ),
        json_schema_extra={"x-labels": ASSET_CLASS_LABELS},
    )

    @field_validator("ticker_name")
    @classmethod
    def _clean(cls, value: str) -> str:
        return value.strip().upper()
