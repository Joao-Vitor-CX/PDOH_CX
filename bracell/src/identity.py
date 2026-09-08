"""Identidade interna observacional de colaboradores.

A identidade e os aliases existem apenas no schema ``pdoh_controle``. O nome
original continua sendo a chave utilizada pelo processamento legado.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections import defaultdict
from typing import Any

import pandas as pd
from sqlalchemy import text

from .observability import (
    MARCA_PADRAO,
    obter_execution_id,
    registrar_evento,
    registrar_oportunidades,
)


NAMESPACE_IDENTIDADE = uuid.UUID("c52e70bd-05f2-45c4-9b4f-fad3b136a07f")

FONTES_NOME = {
    "relatorio_de_operacao": ("status_day_operacao_bracell", "colaborador"),
    "colaboradores": ("colaboradores_ativos_bracell", "nome_colaborador"),
    "checkin": ("relatorio_checkin_bracell", "colaborador"),
    "gerencial_de_visitas": ("gerencial_visitas_bracell", "colaborador"),
    "pesquisas": ("painel_pesquisas_bracell", "responsavel"),
}


def normalizar_identificador(valor: Any) -> str:
    if valor is None or pd.isna(valor):
        return ""
    texto = unicodedata.normalize("NFKD", str(valor))
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return re.sub(r"\s+", " ", texto).strip().upper()


def _uid(chave: str) -> str:
    return str(uuid.uuid5(NAMESPACE_IDENTIDADE, f"{MARCA_PADRAO}:{chave}"))


def _oportunidade_identidade(
    *,
    tipo: str,
    descricao: str,
    colaborador: str | None,
    colaborador_id: str | None,
    evidencia: dict[str, Any],
    severidade: str = "MEDIA",
) -> dict[str, Any]:
    return {
        "marca": MARCA_PADRAO,
        "origem": "IDENTIDADE_INTERNA",
        "tabela_origem": "colaboradores_ativos_bracell",
        "colaborador": colaborador,
        "colaborador_id_interno": colaborador_id,
        "tipo_problema": tipo,
        "descricao_detalhada": descricao,
        "severidade": severidade,
        "evidencia": evidencia,
    }


def observar_identidades(engine, dataframes: dict[str, pd.DataFrame]) -> int:
    """Registra identidade/aliases e divergencias sem tocar nos DataFrames."""

    try:
        identidades: dict[str, dict[str, Any]] = {}
        aliases: dict[tuple[str, str, str], dict[str, Any]] = {}
        nomes_para_ids: dict[str, set[str]] = defaultdict(set)
        usuarios_para_nomes: dict[str, set[str]] = defaultdict(set)
        nomes_para_usuarios: dict[str, set[str]] = defaultdict(set)

        cadastro = dataframes.get("colaboradores")
        if cadastro is not None and "nome_colaborador" in cadastro.columns:
            for _, linha in cadastro.iterrows():
                nome_original = linha.get("nome_colaborador")
                nome_normalizado = normalizar_identificador(nome_original)
                if not nome_normalizado:
                    continue
                usuario_original = linha.get("usuario") if "usuario" in cadastro.columns else None
                usuario_normalizado = normalizar_identificador(usuario_original)
                chave = f"USUARIO:{usuario_normalizado}" if usuario_normalizado else f"NOME:{nome_normalizado}"
                colaborador_id = _uid(chave)
                nomes_para_ids[nome_normalizado].add(colaborador_id)
                if usuario_normalizado:
                    usuarios_para_nomes[usuario_normalizado].add(nome_normalizado)
                    nomes_para_usuarios[nome_normalizado].add(usuario_normalizado)
                identidade = identidades.setdefault(
                    colaborador_id,
                    {
                        "colaborador_id": colaborador_id,
                        "chave": chave,
                        "usuario": str(usuario_original)[:255] if usuario_normalizado else None,
                        "nome": str(nome_original)[:255],
                        "normalizado": nome_normalizado[:255],
                        "quantidade": 0,
                    },
                )
                identidade["quantidade"] += 1
                alias_chave = (colaborador_id, str(nome_original)[:255], "colaboradores_ativos_bracell")
                alias = aliases.setdefault(
                    alias_chave,
                    {
                        "colaborador_id": colaborador_id,
                        "nome_original": str(nome_original)[:255],
                        "nome_normalizado": nome_normalizado[:255],
                        "tabela": "colaboradores_ativos_bracell",
                        "quantidade": 0,
                    },
                )
                alias["quantidade"] += 1

        for nome_logico, dataframe in dataframes.items():
            if nome_logico == "colaboradores" or nome_logico not in FONTES_NOME:
                continue
            tabela, coluna_nome = FONTES_NOME[nome_logico]
            if coluna_nome not in dataframe.columns:
                continue
            contagens = dataframe[coluna_nome].value_counts(dropna=True)
            for nome_original, quantidade in contagens.items():
                nome_normalizado = normalizar_identificador(nome_original)
                if not nome_normalizado:
                    continue
                candidatos = nomes_para_ids.get(nome_normalizado, set())
                if len(candidatos) == 1:
                    colaborador_id = next(iter(candidatos))
                    chave = identidades[colaborador_id]["chave"]
                else:
                    chave = f"NOME:{nome_normalizado}"
                    colaborador_id = _uid(chave)
                identidade = identidades.setdefault(
                    colaborador_id,
                    {
                        "colaborador_id": colaborador_id,
                        "chave": chave,
                        "usuario": None,
                        "nome": str(nome_original)[:255],
                        "normalizado": nome_normalizado[:255],
                        "quantidade": 0,
                    },
                )
                identidade["quantidade"] += int(quantidade)
                alias_chave = (colaborador_id, str(nome_original)[:255], tabela)
                alias = aliases.setdefault(
                    alias_chave,
                    {
                        "colaborador_id": colaborador_id,
                        "nome_original": str(nome_original)[:255],
                        "nome_normalizado": nome_normalizado[:255],
                        "tabela": tabela,
                        "quantidade": 0,
                    },
                )
                alias["quantidade"] += int(quantidade)

        execucao_id = obter_execution_id()
        with engine.begin() as conexao:
            if identidades:
                conexao.execute(
                    text(
                        "INSERT INTO pdoh_controle.colaborador_identidade "
                        "(colaborador_id_interno, marca, chave_identidade, usuario_referencia, "
                        " nome_referencia, nome_normalizado, primeira_execucao_id, ultima_execucao_id, "
                        " quantidade_observacoes) VALUES "
                        "(:colaborador_id, :marca, :chave, :usuario, :nome, :normalizado, "
                        " :execucao_id, :execucao_id, :quantidade) "
                        "ON DUPLICATE KEY UPDATE ultima_execucao_id = VALUES(ultima_execucao_id), "
                        "ultima_observacao_em = CURRENT_TIMESTAMP(6), "
                        "quantidade_observacoes = quantidade_observacoes + VALUES(quantidade_observacoes), "
                        "nome_referencia = COALESCE(nome_referencia, VALUES(nome_referencia)), "
                        "usuario_referencia = COALESCE(usuario_referencia, VALUES(usuario_referencia))"
                    ),
                    [
                        {**identidade, "marca": MARCA_PADRAO, "execucao_id": execucao_id}
                        for identidade in identidades.values()
                    ],
                )
            if aliases:
                conexao.execute(
                    text(
                        "INSERT INTO pdoh_controle.colaborador_alias "
                        "(colaborador_id_interno, marca, nome_original, nome_normalizado, origem, "
                        " tabela_origem, primeira_execucao_id, ultima_execucao_id, quantidade_observacoes) "
                        "VALUES (:colaborador_id, :marca, :nome_original, :nome_normalizado, "
                        " 'INVOLVES_BRACELL', :tabela, :execucao_id, :execucao_id, :quantidade) "
                        "ON DUPLICATE KEY UPDATE ultima_execucao_id = VALUES(ultima_execucao_id), "
                        "ultima_observacao_em = CURRENT_TIMESTAMP(6), "
                        "quantidade_observacoes = quantidade_observacoes + VALUES(quantidade_observacoes)"
                    ),
                    [
                        {**alias, "marca": MARCA_PADRAO, "execucao_id": execucao_id}
                        for alias in aliases.values()
                    ],
                )

        oportunidades = []
        for usuario, nomes in usuarios_para_nomes.items():
            if len(nomes) > 1:
                chave = f"USUARIO:{usuario}"
                oportunidades.append(
                    _oportunidade_identidade(
                        tipo="DIVERGENCIA_CADASTRAL",
                        descricao="Um mesmo usuario foi observado com mais de um nome cadastral.",
                        colaborador=sorted(nomes)[0],
                        colaborador_id=_uid(chave),
                        evidencia={"usuario_normalizado": usuario, "nomes_normalizados": sorted(nomes)},
                        severidade="ALTA",
                    )
                )
        for nome, usuarios in nomes_para_usuarios.items():
            if len(usuarios) > 1:
                oportunidades.append(
                    _oportunidade_identidade(
                        tipo="IDENTIFICACAO_AMBIGUA",
                        descricao="O mesmo nome normalizado esta associado a usuarios distintos.",
                        colaborador=nome,
                        colaborador_id=None,
                        evidencia={"nome_normalizado": nome, "usuarios_normalizados": sorted(usuarios)},
                        severidade="ALTA",
                    )
                )
        registrar_oportunidades(engine, oportunidades)
        registrar_evento(
            engine,
            nivel="INFO",
            categoria="IDENTIDADE",
            codigo="IDENTIDADE_SHADOW_CONCLUIDA",
            mensagem="Camada interna de identidade atualizada sem interferir no processamento por nome.",
            etapa="IDENTIDADE_COLABORADOR",
            contexto={"identidades": len(identidades), "aliases": len(aliases)},
        )
        return len(identidades)
    except Exception as exc:
        registrar_evento(
            engine,
            nivel="ERRO",
            categoria="OBSERVABILIDADE",
            codigo="IDENTIDADE_SHADOW_INDISPONIVEL",
            mensagem="A identidade interna falhou e foi ignorada; nomes originais permanecem em uso.",
            etapa="IDENTIDADE_COLABORADOR",
            excecao=exc,
        )
        return 0
