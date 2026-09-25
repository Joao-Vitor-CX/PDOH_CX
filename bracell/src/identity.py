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
    registrar_achado,
    resolver_tratativa,  # compatibilidade de testes/consumidores; dispatcher resolve o destino
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
        registrar_achado(engine, oportunidades)
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


# Fontes de PDV por dataframe logico e a prioridade de chave (id > codigo > nome).
FONTES_PDV = {
    "gerencial_de_visitas": {
        "tabela": "gerencial_visitas_bracell",
        "id": "id_pdv",
        "codigos": ["codigo_pdv", "cnpj_pdv"],
        "nome": "ponto_venda",
    },
    "checkin": {
        "tabela": "relatorio_checkin_bracell",
        "id": None,
        "codigos": ["cod_pdv"],
        "nome": "ponto_venda",
    },
    "pesquisas": {
        "tabela": "painel_pesquisas_bracell",
        "id": None,
        "codigos": ["codigo_pdv"],
        "nome": "ponto_venda",
    },
}


def _valor_limpo(valor: Any) -> str:
    """Normaliza um identificador tabular para string comparavel; vazio se nulo/zero."""

    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2].isdigit():  # id_pdv lido como float pelo pandas
        texto = texto[:-2]
    if texto.lower() in {"", "0", "none", "nan", "null"}:
        return ""
    return texto


def _uid_entidade(tipo: str, chave: str) -> str:
    return str(uuid.uuid5(NAMESPACE_IDENTIDADE, f"{MARCA_PADRAO}:{tipo}:{chave}"))


def observar_identidades_entidades(engine, dataframes: dict[str, pd.DataFrame]) -> int:
    """Gera a identidade interna de PDV e MARCA como camada shadow.

    Nao toca nos DataFrames nem no calculo. Chave do PDV por prioridade:
    id_pdv > codigo/cnpj > nome normalizado. Registra oportunidades de
    ambiguidade/ausencia de identificador. Fail-open: nunca interrompe a esteira.
    """

    try:
        identidades: dict[str, dict[str, Any]] = {}
        aliases: dict[tuple[str, str, str], dict[str, Any]] = {}
        nome_para_ids: dict[str, set[str]] = defaultdict(set)
        id_para_nomes: dict[str, set[str]] = defaultdict(set)
        sem_identificador = 0

        def _registra(tipo, chave, origem_chave, nome_original, tabela, quantidade):
            nome_norm = normalizar_identificador(nome_original)
            ident = _uid_entidade(tipo, chave)
            identidades.setdefault(
                ident,
                {
                    "identificador_id": ident,
                    "tipo": tipo,
                    "chave": chave[:350],
                    "nome": (str(nome_original)[:255] if nome_original is not None else None),
                    "normalizado": nome_norm[:255] if nome_norm else None,
                    "origem": origem_chave,
                    "quantidade": 0,
                },
            )["quantidade"] += int(quantidade)
            if nome_original is not None and nome_norm:
                alias_chave = (ident, str(nome_original)[:255], tabela)
                aliases.setdefault(
                    alias_chave,
                    {
                        "identificador_id": ident,
                        "tipo": tipo,
                        "nome_original": str(nome_original)[:255],
                        "nome_normalizado": nome_norm[:255],
                        "tabela": tabela,
                        "quantidade": 0,
                    },
                )["quantidade"] += int(quantidade)
                nome_para_ids[nome_norm].add(ident)
                id_para_nomes[ident].add(nome_norm)

        for chave_logica, cfg in FONTES_PDV.items():
            dataframe = dataframes.get(chave_logica)
            if dataframe is None:
                continue
            col_id = cfg["id"] if cfg["id"] and cfg["id"] in dataframe.columns else None
            cols_cod = [c for c in cfg["codigos"] if c in dataframe.columns]
            col_nome = cfg["nome"] if cfg["nome"] in dataframe.columns else None
            colunas = [c for c in ([col_id] + cols_cod + [col_nome]) if c]
            if not colunas:
                continue
            agrupado = dataframe.groupby(colunas, dropna=False).size().reset_index(name="qtd")
            for _, linha in agrupado.iterrows():
                quantidade = int(linha["qtd"])
                id_val = _valor_limpo(linha[col_id]) if col_id else ""
                cod_val = ""
                for coluna in cols_cod:
                    cod_val = _valor_limpo(linha[coluna])
                    if cod_val:
                        break
                nome_val = linha[col_nome] if col_nome else None
                if id_val:
                    chave, origem_chave = f"ID:{id_val}", "id_pdv"
                elif cod_val:
                    chave, origem_chave = f"COD:{cod_val}", "codigo"
                else:
                    nome_norm = normalizar_identificador(nome_val)
                    if not nome_norm:
                        continue
                    chave, origem_chave = f"NOME:{nome_norm}", "nome"
                    sem_identificador += quantidade
                _registra("PDV", chave, origem_chave, nome_val, cfg["tabela"], quantidade)

        marca_norm = normalizar_identificador(MARCA_PADRAO)
        if marca_norm:
            _registra("MARCA", f"MARCA:{marca_norm}", "marca", MARCA_PADRAO, "pdoh_controle", 1)

        execucao_id = obter_execution_id()
        with engine.begin() as conexao:
            if identidades:
                conexao.execute(
                    text(
                        "INSERT INTO pdoh_controle.identificador_entidade "
                        "(identificador_id, tipo_entidade, identificador_interno, chave_identidade, "
                        " nome_original, nome_normalizado, origem_dado, marca, primeira_execucao_id, "
                        " ultima_execucao_id, quantidade_observacoes) VALUES "
                        "(:identificador_id, :tipo, :identificador_id, :chave, :nome, :normalizado, "
                        " :origem, :marca, :execucao_id, :execucao_id, :quantidade) "
                        "ON DUPLICATE KEY UPDATE ultima_execucao_id = VALUES(ultima_execucao_id), "
                        " data_atualizacao = CURRENT_TIMESTAMP(6), "
                        " quantidade_observacoes = quantidade_observacoes + VALUES(quantidade_observacoes), "
                        " nome_original = COALESCE(nome_original, VALUES(nome_original)), "
                        " nome_normalizado = COALESCE(nome_normalizado, VALUES(nome_normalizado))"
                    ),
                    [{**item, "marca": MARCA_PADRAO, "execucao_id": execucao_id} for item in identidades.values()],
                )
            if aliases:
                conexao.execute(
                    text(
                        "INSERT INTO pdoh_controle.identificador_entidade_alias "
                        "(identificador_id, tipo_entidade, marca, nome_original, nome_normalizado, "
                        " origem, tabela_origem, primeira_execucao_id, ultima_execucao_id, "
                        " quantidade_observacoes) VALUES "
                        "(:identificador_id, :tipo, :marca, :nome_original, :nome_normalizado, "
                        " 'INVOLVES_BRACELL', :tabela, :execucao_id, :execucao_id, :quantidade) "
                        "ON DUPLICATE KEY UPDATE ultima_execucao_id = VALUES(ultima_execucao_id), "
                        " ultima_observacao_em = CURRENT_TIMESTAMP(6), "
                        " quantidade_observacoes = quantidade_observacoes + VALUES(quantidade_observacoes)"
                    ),
                    [{**alias, "marca": MARCA_PADRAO, "execucao_id": execucao_id} for alias in aliases.values()],
                )

        oportunidades = []
        for nome_norm, ids in nome_para_ids.items():
            if len(ids) > 1:
                oportunidades.append(
                    {
                        "marca": MARCA_PADRAO,
                        "origem": "IDENTIDADE_INTERNA",
                        "tabela_origem": "identificador_entidade",
                        "colaborador": None,
                        "tipo_problema": "PDV_MESMO_NOME_IDS_DISTINTOS",
                        "descricao_detalhada": "Um mesmo nome de PDV esta associado a identificadores distintos.",
                        "severidade": "ALTA",
                        "evidencia": {"nome_normalizado": nome_norm, "identificadores": sorted(ids)},
                    }
                )
        for ident, nomes in id_para_nomes.items():
            if len(nomes) > 1:
                oportunidades.append(
                    {
                        "marca": MARCA_PADRAO,
                        "origem": "IDENTIDADE_INTERNA",
                        "tabela_origem": "identificador_entidade",
                        "colaborador": None,
                        "tipo_problema": "PDV_NOME_DIVERGENTE_MESMO_ID",
                        "descricao_detalhada": "Um mesmo PDV (mesmo identificador) aparece com nomes diferentes.",
                        "severidade": "MEDIA",
                        "evidencia": {"identificador": ident, "nomes_normalizados": sorted(nomes)},
                    }
                )
        if sem_identificador:
            oportunidades.append(
                {
                    "marca": MARCA_PADRAO,
                    "origem": "IDENTIDADE_INTERNA",
                    "tabela_origem": "identificador_entidade",
                    "colaborador": None,
                    "tipo_problema": "PDV_SEM_IDENTIFICADOR",
                    "descricao_detalhada": "Registros de PDV sem id_pdv/codigo confiavel; identificados por nome.",
                    "severidade": "MEDIA",
                    "evidencia": {"ocorrencias": int(sem_identificador)},
                }
            )
        registrar_achado(engine, oportunidades)

        registrar_evento(
            engine,
            nivel="INFO",
            categoria="IDENTIDADE",
            codigo="IDENTIDADE_ENTIDADE_CONCLUIDA",
            mensagem="Identidade interna de PDV/MARCA atualizada sem interferir no processamento.",
            etapa="IDENTIDADE_ENTIDADE",
            contexto={
                "identidades": len(identidades),
                "aliases": len(aliases),
                "pdv_sem_identificador": int(sem_identificador),
            },
        )
        return len(identidades)
    except Exception as exc:
        registrar_evento(
            engine,
            nivel="ERRO",
            categoria="OBSERVABILIDADE",
            codigo="IDENTIDADE_ENTIDADE_INDISPONIVEL",
            mensagem="A identidade de entidades falhou e foi ignorada; processamento por nome permanece.",
            etapa="IDENTIDADE_ENTIDADE",
            excecao=exc,
        )
        return 0
