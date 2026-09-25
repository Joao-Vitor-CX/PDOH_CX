"""Camada De/Para parametrizada (padronizacao/validacao das informacoes de origem).

Camada shadow: consulta mapeamentos em ``pdoh_controle.de_para`` para validar e
padronizar valores recebidos, registrando oportunidades quando nao ha De/Para
cadastrado. NAO altera DataFrames, calculo ou processadores travados. Fail-open.
"""

from __future__ import annotations

import uuid
from typing import Any

import pandas as pd
from sqlalchemy import text

from .identity import normalizar_identificador
from .observability import (
    MARCA_PADRAO,
    obter_execution_id,
    registrar_evento,
    registrar_achado,
)


NAMESPACE_DE_PARA = uuid.UUID("6f2a1e3c-8b4d-4c2a-9f10-7e5d3b2a1c00")

# Pares (processo, campo_origem, dataframe_logico) governados pelo De/Para nesta fase.
PARES_DE_PARA = (
    ("JORNADA", "jornada_trabalho", "colaboradores"),
    ("PERFIL", "perfil_acesso", "colaboradores"),
)

# Mapeamentos iniciais (semeados pela aplicacao; ops podem evoluir sem codigo).
# Perfis: dominio padrao (global). Jornada: apenas normalizacao de texto observada
# na origem BRACELL (NAO define horas — decisao de negocio permanece fora daqui).
SEED_DE_PARA: tuple[dict[str, Any], ...] = (
    {"marca": None, "processo": "PERFIL", "campo_origem": "perfil_acesso", "valor_origem": "PROMOTOR EXCLUSIVO", "valor_padronizado": "PROMOTOR EXCLUSIVO"},
    {"marca": None, "processo": "PERFIL", "campo_origem": "perfil_acesso", "valor_origem": "SUPERVISOR EXCLUSIVO", "valor_padronizado": "SUPERVISOR EXCLUSIVO"},
    {"marca": None, "processo": "PERFIL", "campo_origem": "perfil_acesso", "valor_origem": "BACKOFFICE EXCLUSIVO", "valor_padronizado": "BACKOFFICE EXCLUSIVO"},
    {"marca": None, "processo": "PERFIL", "campo_origem": "perfil_acesso", "valor_origem": "GESTOR EXCLUSIVO", "valor_padronizado": "GESTOR EXCLUSIVO"},
    {"marca": None, "processo": "PERFIL", "campo_origem": "perfil_acesso", "valor_origem": "LIDER EXCLUSIVO", "valor_padronizado": "LIDER EXCLUSIVO"},
    {"marca": None, "processo": "PERFIL", "campo_origem": "perfil_acesso", "valor_origem": "PROMOTORES LIDERES", "valor_padronizado": "PROMOTORES LIDERES"},
    {"marca": None, "processo": "PERFIL", "campo_origem": "perfil_acesso", "valor_origem": "T&D", "valor_padronizado": "T&D"},
    {"marca": None, "processo": "PERFIL", "campo_origem": "perfil_acesso", "valor_origem": "CLIENTE", "valor_padronizado": "CLIENTE"},
    {"marca": "BRACELL", "processo": "JORNADA", "campo_origem": "jornada_trabalho", "valor_origem": "CX - JORNADA PADRÃO", "valor_padronizado": "JORNADA PADRAO"},
    {"marca": "BRACELL", "processo": "JORNADA", "campo_origem": "jornada_trabalho", "valor_origem": "CX - INTERMITENTE 24H-1", "valor_padronizado": "INTERMITENTE 24H"},
    {"marca": "BRACELL", "processo": "JORNADA", "campo_origem": "jornada_trabalho", "valor_origem": "CX - INTERMITENTE 24H-2", "valor_padronizado": "INTERMITENTE 24H"},
)

# Estados por extenso -> sigla (De/Para global de cadastro). Normaliza o campo
# `estado` recebido por extenso na origem (ex.: gerencial_visitas), evitando falso
# positivo de "fora do padrao" sem alterar o dado nem o calculo.
_ESTADOS_BR = {
    "Acre": "AC", "Alagoas": "AL", "Amapa": "AP", "Amazonas": "AM", "Bahia": "BA",
    "Ceara": "CE", "Distrito Federal": "DF", "Espirito Santo": "ES", "Goias": "GO",
    "Maranhao": "MA", "Mato Grosso": "MT", "Mato Grosso do Sul": "MS", "Minas Gerais": "MG",
    "Para": "PA", "Paraiba": "PB", "Parana": "PR", "Pernambuco": "PE", "Piaui": "PI",
    "Rio de Janeiro": "RJ", "Rio Grande do Norte": "RN", "Rio Grande do Sul": "RS",
    "Rondonia": "RO", "Roraima": "RR", "Santa Catarina": "SC", "Sao Paulo": "SP",
    "Sergipe": "SE", "Tocantins": "TO",
}
SEED_DE_PARA = SEED_DE_PARA + tuple(
    {"marca": None, "processo": "CADASTRO", "campo_origem": "estado",
     "valor_origem": nome, "valor_padronizado": sigla}
    for nome, sigla in _ESTADOS_BR.items()
)


def _uid_de_para(marca: Any, processo: str, campo: str, valor_norm: str) -> str:
    return str(uuid.uuid5(NAMESPACE_DE_PARA, f"{marca or 'GLOBAL'}:{processo}:{campo}:{valor_norm}"))


def carregar_de_para(engine, processo: str, campo_origem: str, marca: str = MARCA_PADRAO) -> list[dict[str, Any]]:
    """Le mapeamentos ATIVOS aplicaveis (marca especifica + globais). Fail-open."""

    try:
        with engine.connect() as conexao:
            linhas = conexao.execute(
                text(
                    "SELECT de_para_id, marca, processo, campo_origem, valor_origem, valor_padronizado "
                    "FROM pdoh_controle.de_para "
                    "WHERE status = 'ATIVO' AND processo = :processo AND campo_origem = :campo "
                    "AND (marca = :marca OR marca IS NULL) "
                    "ORDER BY (marca IS NULL)"
                ),
                {"processo": processo, "campo": campo_origem, "marca": marca},
            ).mappings().all()
        return [dict(linha) for linha in linhas]
    except Exception as exc:
        registrar_evento(
            engine, nivel="ERRO", categoria="OBSERVABILIDADE", codigo="DE_PARA_INDISPONIVEL",
            mensagem="Consulta De/Para indisponivel; comportamento atual preservado.",
            etapa="DE_PARA", excecao=exc,
        )
        return []


def resolver_de_para(engine, processo: str, campo_origem: str, valor_origem: Any, marca: str = MARCA_PADRAO) -> dict[str, Any] | None:
    """Resolve um valor de origem para o padronizado (marca-especifica > global).

    Normaliza o valor para a comparacao. Read-only e fail-open (None se nao houver)."""

    alvo = normalizar_identificador(valor_origem)
    if not alvo:
        return None
    for mapeamento in carregar_de_para(engine, processo, campo_origem, marca):
        if normalizar_identificador(mapeamento["valor_origem"]) == alvo:
            return mapeamento
    return None


def bootstrap_de_para(engine, marca_padrao: str = MARCA_PADRAO) -> int:
    """Semeia mapeamentos iniciais (idempotente) e registra historico 'CRIADA'.

    Usa a conta da aplicacao (INSERT em pdoh_controle). Fail-open."""

    criadas = 0
    try:
        with engine.begin() as conexao:
            for item in SEED_DE_PARA:
                valor_norm = normalizar_identificador(item["valor_origem"])
                de_para_id = _uid_de_para(item["marca"], item["processo"], item["campo_origem"], valor_norm)
                resultado = conexao.execute(
                    text(
                        "INSERT IGNORE INTO pdoh_controle.de_para "
                        "(de_para_id, marca, processo, campo_origem, valor_origem, valor_padronizado, "
                        " descricao, status, responsavel) VALUES "
                        "(:id, :marca, :processo, :campo, :valor_origem, :valor_padronizado, "
                        " :descricao, 'ATIVO', 'BOOTSTRAP')"
                    ),
                    {
                        "id": de_para_id,
                        "marca": item["marca"],
                        "processo": item["processo"],
                        "campo": item["campo_origem"],
                        "valor_origem": item["valor_origem"],
                        "valor_padronizado": item["valor_padronizado"],
                        "descricao": "Mapeamento inicial semeado pela aplicacao.",
                    },
                )
                if resultado.rowcount == 1:
                    criadas += 1
                    conexao.execute(
                        text(
                            "INSERT INTO pdoh_controle.de_para_historico "
                            "(de_para_id, acao, valor_padronizado_novo, status_novo, responsavel, observacao) "
                            "VALUES (:id, 'CRIADA', :valor_padronizado, 'ATIVO', 'BOOTSTRAP', "
                            " 'Mapeamento inicial semeado pela aplicacao.')"
                        ),
                        {"id": de_para_id, "valor_padronizado": item["valor_padronizado"]},
                    )
    except Exception as exc:
        registrar_evento(
            engine, nivel="ERRO", categoria="OBSERVABILIDADE", codigo="DE_PARA_BOOTSTRAP_INDISPONIVEL",
            mensagem="Seed do De/Para falhou e foi ignorado; a esteira continua.",
            etapa="DE_PARA", excecao=exc,
        )
    return criadas


def observar_padronizacao(engine, dataframes: dict[str, pd.DataFrame], marca: str = MARCA_PADRAO) -> int:
    """Confere os valores de origem contra o De/Para e registra oportunidade para os
    nao mapeados. Nao altera dados nem calculo. Fail-open. Retorna nao-mapeados."""

    try:
        oportunidades: list[dict[str, Any]] = []
        total_nao_mapeados = 0
        total_mapeados = 0
        for processo, campo, chave_df in PARES_DE_PARA:
            dataframe = dataframes.get(chave_df)
            if dataframe is None or campo not in dataframe.columns:
                continue
            mapeados_norm = {
                normalizar_identificador(m["valor_origem"])
                for m in carregar_de_para(engine, processo, campo, marca)
            }
            valores = dataframe[campo].dropna().astype(str).str.strip()
            distintos = list(dict.fromkeys(v for v in valores.tolist() if v))
            for valor in distintos:
                if normalizar_identificador(valor) in mapeados_norm:
                    total_mapeados += 1
                    continue
                total_nao_mapeados += 1
                oportunidades.append(
                    {
                        "marca": marca,
                        "origem": "INVOLVES_BRACELL",
                        "tabela_origem": "colaboradores_ativos_bracell",
                        "colaborador": None,
                        "tipo_problema": "VALOR_SEM_PADRONIZACAO",
                        "descricao_detalhada": (
                            f"Valor sem padronizacao cadastrada no De/Para (processo {processo}, "
                            f"campo {campo})."
                        ),
                        "severidade": "MEDIA",
                        "evidencia": {"processo": processo, "campo_origem": campo, "valor_origem": valor[:350]},
                    }
                )
        registrar_achado(engine, oportunidades)
        registrar_evento(
            engine, nivel="INFO", categoria="DE_PARA", codigo="DE_PARA_VALIDACAO_CONCLUIDA",
            mensagem="Validacao De/Para concluida sem interferir no processamento.",
            etapa="DE_PARA", contexto={"mapeados": total_mapeados, "nao_mapeados": total_nao_mapeados},
        )
        return total_nao_mapeados
    except Exception as exc:
        registrar_evento(
            engine, nivel="ERRO", categoria="OBSERVABILIDADE", codigo="DE_PARA_VALIDACAO_INDISPONIVEL",
            mensagem="Validacao De/Para falhou e foi ignorada; o processamento continua.",
            etapa="DE_PARA", excecao=exc,
        )
        return 0
