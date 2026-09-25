"""Contratos da configuracao futura; nenhum deles ativa fallback no processador."""
from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import Contract

HOUR_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class FallbackConfig(Contract):
    id: str
    marca: str
    regra: str
    escopo: str
    chave: str
    valor_fallback: str
    vigencia_inicio: date
    vigencia_fim: date | None
    status: str
    usuario_alteracao: str
    data_alteracao: datetime


class FallbackHistory(Contract):
    id: int
    config_id: str
    acao: str
    valor_anterior: str | None
    novo_valor: str
    usuario_alteracao: str
    data_alteracao: datetime
    regra: str
    marca: str
    escopo: str
    chave: str
    estado_anterior: dict | None
    estado_novo: dict


class FallbackQuery(Contract):
    regra: Literal["CHECKOUT_AUSENTE"] = "CHECKOUT_AUSENTE"
    marca: str = Field(min_length=1, max_length=80)
    lider_id: str | None = Field(None, min_length=1, max_length=160)
    data_referencia: date | None = None

    @field_validator("marca")
    @classmethod
    def brand(cls, value):
        value = value.strip().upper()
        if not value:
            raise ValueError("marca nao pode ser vazia")
        return value

    @field_validator("lider_id")
    @classmethod
    def leader(cls, value):
        if value is not None and (not value.strip() or value.strip() == "*"):
            raise ValueError("identificador do lider invalido")
        return value.strip() if value else None


class FallbackResolution(Contract):
    regra: Literal["CHECKOUT_AUSENTE"] = "CHECKOUT_AUSENTE"
    origem: Literal["LIDER", "MARCA", "DEFAULT"]
    valor: str = Field(pattern=HOUR_PATTERN)
    config_id: str | None = None
    data_referencia: date
    aplicado_no_processador: bool = False
    fallback_efetivo_processador: str = "23:59"


class SimulationRequest(Contract):
    regra: Literal["CHECKOUT_AUSENTE"]
    marca: str = Field(min_length=1, max_length=80)
    novo_valor: str = Field(pattern=HOUR_PATTERN)
    execution_id: str | None = Field(None, min_length=1, max_length=80)
    periodo_inicio: date | None = None
    periodo_fim: date | None = None

    @field_validator("marca")
    @classmethod
    def brand(cls, value):
        return FallbackQuery.brand(value)

    @model_validator(mode="after")
    def dates(self):
        if self.periodo_inicio and self.periodo_fim and self.periodo_inicio > self.periodo_fim:
            raise ValueError("periodo_inicio deve ser menor ou igual a periodo_fim")
        return self


class SimulationResult(Contract):
    regra: str
    marca: str
    execution_id: str
    criterio_execucao: str
    periodo_inicio: date
    periodo_fim: date
    fallback_atual: str
    fallback_simulado: str
    configuracao_marca: FallbackResolution
    registros_identificados: int
    registros_afetados: int
    colaboradores_identificados: int
    colaboradores_afetados: int
    criterio_colaboradores: str
    grupos_observados: int
    grupos_sem_colaborador: int
    evidencias_duplicadas_desconsideradas: int
    dados_alterados: bool = False
    pdoh_recalculado: bool = False
    abrangencia: str
    avisos: list[str]
