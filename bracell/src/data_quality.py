"""Regras observacionais de qualidade para os dados de entrada BRACELL.

Os validadores nunca alteram o DataFrame recebido. Eles apenas produzem
oportunidades laterais e nao participam de filtros, joins ou calculos PDOH.
"""

from __future__ import annotations

import os
import hashlib
import json
from typing import Any

import pandas as pd

from .observability import registrar_evento, registrar_oportunidades


CONFIGURACAO_TABELAS = {
    "relatorio_de_operacao": {
        "obrigatorias": ("colaborador", "dia_referencia"),
        "colaborador": "colaborador",
        "data": "dia_referencia",
        "pares_tempo": (("primeiro_checkin", "ultimo_checkout"),),
    },
    "colaboradores": {
        "obrigatorias": ("nome_colaborador", "usuario_ativo", "data_evolucao"),
        "colaborador": "nome_colaborador",
        "data": "data_dimensao",
        "pares_tempo": (),
    },
    "checkin": {
        "obrigatorias": ("colaborador", "data_roteiro", "hora_entrada"),
        "colaborador": "colaborador",
        "data": "data_roteiro",
        "pares_tempo": (("hora_entrada", "hora_saida"),),
    },
    "gerencial_de_visitas": {
        "obrigatorias": ("colaborador", "data_visita"),
        "colaborador": "colaborador",
        "data": "data_visita",
        "pares_tempo": (),
    },
    "pesquisas": {
        "obrigatorias": (
            "id",
            "responsavel",
            "data_solicitacao",
            "data_expiracao",
            "status",
        ),
        "colaborador": "responsavel",
        "data": "data_solicitacao",
        "pares_tempo": (
            ("data_solicitacao", "data_conclusao"),
            ("data_solicitacao", "data_expiracao"),
        ),
    },
}


def _vazio(serie: pd.Series) -> pd.Series:
    return serie.isna() | serie.astype("string").str.strip().eq("")


def _valor_curto(valor: Any) -> str | None:
    if pd.isna(valor):
        return None
    return str(valor)[:500]


def _valor_linha(linha: pd.Series, coluna: str | None) -> Any:
    if not coluna or coluna not in linha.index:
        return None
    return linha[coluna]


def _nova_oportunidade(
    *,
    nome_tabela: str,
    tabela_origem: str,
    config: dict[str, Any],
    linha: pd.Series | None,
    indice: Any,
    tipo: str,
    descricao: str,
    severidade: str,
    evidencia: dict[str, Any],
) -> dict[str, Any]:
    colaborador = _valor_linha(linha, config.get("colaborador")) if linha is not None else None
    data_referencia = _valor_linha(linha, config.get("data")) if linha is not None else None
    return {
        "marca": "BRACELL",
        "data_referencia": data_referencia,
        "origem": "INVOLVES_BRACELL",
        "tabela_origem": tabela_origem,
        "colaborador": _valor_curto(colaborador),
        "tipo_problema": tipo,
        "descricao_detalhada": descricao,
        "severidade": severidade,
        "evidencia": {"dataframe": nome_tabela, "indice_origem": str(indice), **evidencia},
    }


def _adicionar_por_mascara(
    oportunidades: list[dict[str, Any]],
    *,
    dataframe: pd.DataFrame,
    mascara: pd.Series,
    nome_tabela: str,
    tabela_origem: str,
    config: dict[str, Any],
    tipo: str,
    descricao: str,
    severidade: str,
    evidencia_factory,
    maximo: int,
) -> None:
    posicoes = [pos for pos, invalido in enumerate(mascara.fillna(False).tolist()) if bool(invalido)]
    for posicao in posicoes[:maximo]:
        linha = dataframe.iloc[posicao]
        oportunidades.append(
            _nova_oportunidade(
                nome_tabela=nome_tabela,
                tabela_origem=tabela_origem,
                config=config,
                linha=linha,
                indice=dataframe.index[posicao],
                tipo=tipo,
                descricao=descricao,
                severidade=severidade,
                evidencia=evidencia_factory(linha),
            )
        )
    if len(posicoes) > maximo:
        oportunidades.append(
            _nova_oportunidade(
                nome_tabela=nome_tabela,
                tabela_origem=tabela_origem,
                config=config,
                linha=None,
                indice="RESUMO",
                tipo="VOLUME_OPORTUNIDADES_TRUNCADO",
                descricao=(
                    f"A regra {tipo} encontrou {len(posicoes)} registros; "
                    f"{maximo} evidencias individuais foram armazenadas para proteger a esteira."
                ),
                severidade="MEDIA",
                evidencia={"regra": tipo, "total": len(posicoes), "armazenadas": maximo},
            )
        )


def analisar_dataframe(
    dataframe: pd.DataFrame,
    nome_tabela: str,
    tabela_origem: str,
    *,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
) -> list[dict[str, Any]]:
    """Retorna achados sem modificar dados, indice, colunas ou dtypes."""

    config = CONFIGURACAO_TABELAS.get(nome_tabela, {})
    oportunidades: list[dict[str, Any]] = []
    maximo = max(1, int(os.environ.get("PDOH_OBS_MAX_EVIDENCIAS_POR_REGRA", "500")))

    for coluna in config.get("obrigatorias", ()):
        if coluna not in dataframe.columns:
            oportunidades.append(
                _nova_oportunidade(
                    nome_tabela=nome_tabela,
                    tabela_origem=tabela_origem,
                    config=config,
                    linha=None,
                    indice="SCHEMA",
                    tipo="COLUNA_OBRIGATORIA_AUSENTE",
                    descricao=f"A coluna obrigatoria '{coluna}' nao foi recebida.",
                    severidade="CRITICA",
                    evidencia={"coluna": coluna},
                )
            )
            continue
        mascara = _vazio(dataframe[coluna])
        _adicionar_por_mascara(
            oportunidades,
            dataframe=dataframe,
            mascara=mascara,
            nome_tabela=nome_tabela,
            tabela_origem=tabela_origem,
            config=config,
            tipo="CAMPO_OBRIGATORIO_VAZIO",
            descricao=f"O campo obrigatorio '{coluna}' esta nulo ou vazio.",
            severidade="ALTA",
            evidencia_factory=lambda linha, c=coluna: {"campo": c, "valor": _valor_curto(linha[c])},
            maximo=maximo,
        )

    if len(dataframe.columns):
        colunas_duplicidade = [
            coluna for coluna in dataframe.columns if coluna not in {"data_dimensao", "data_evolucao"}
        ]
        if colunas_duplicidade:
            mascara_duplicada = dataframe.duplicated(subset=colunas_duplicidade, keep=False)
            _adicionar_por_mascara(
                oportunidades,
                dataframe=dataframe,
                mascara=mascara_duplicada,
                nome_tabela=nome_tabela,
                tabela_origem=tabela_origem,
                config=config,
                tipo="REGISTRO_DUPLICADO",
                descricao="Registro duplicado segundo a mesma chave usada pelo tratamento atual.",
                severidade="MEDIA",
                evidencia_factory=lambda linha: {
                    "campos_comparados": colunas_duplicidade,
                    "assinatura": hashlib.sha256(
                        json.dumps(
                            [_valor_curto(linha[c]) for c in colunas_duplicidade],
                            ensure_ascii=False,
                        ).encode("utf-8")
                    ).hexdigest(),
                },
                maximo=maximo,
            )

    coluna_nome = config.get("colaborador")
    if coluna_nome in dataframe.columns:
        nomes = dataframe[coluna_nome].astype("string")
        mascara_espacos = (~_vazio(dataframe[coluna_nome])) & nomes.ne(nomes.str.strip())
        _adicionar_por_mascara(
            oportunidades,
            dataframe=dataframe,
            mascara=mascara_espacos,
            nome_tabela=nome_tabela,
            tabela_origem=tabela_origem,
            config=config,
            tipo="IDENTIFICACAO_COLABORADOR",
            descricao="Nome do colaborador contem espacos externos; apenas observacao, sem correcao.",
            severidade="BAIXA",
            evidencia_factory=lambda linha: {"nome_observado": _valor_curto(linha[coluna_nome])},
            maximo=maximo,
        )

    colunas_data = set(config.get("obrigatorias", ()))
    colunas_data.update(coluna for par in config.get("pares_tempo", ()) for coluna in par)
    for coluna in sorted(colunas_data):
        if coluna not in dataframe.columns or not any(
            termo in coluna for termo in ("data", "hora", "checkin", "checkout")
        ):
            continue
        nao_vazio = ~_vazio(dataframe[coluna])
        convertido = pd.to_datetime(dataframe[coluna], errors="coerce")
        mascara_invalida = nao_vazio & convertido.isna()
        _adicionar_por_mascara(
            oportunidades,
            dataframe=dataframe,
            mascara=mascara_invalida,
            nome_tabela=nome_tabela,
            tabela_origem=tabela_origem,
            config=config,
            tipo="DATA_HORA_INVALIDA",
            descricao=f"O campo '{coluna}' nao pode ser interpretado como data/hora.",
            severidade="ALTA",
            evidencia_factory=lambda linha, c=coluna: {"campo": c, "valor": _valor_curto(linha[c])},
            maximo=maximo,
        )

    for inicio, fim in config.get("pares_tempo", ()):
        if inicio not in dataframe.columns or fim not in dataframe.columns:
            continue
        valores_inicio = pd.to_datetime(dataframe[inicio], errors="coerce")
        valores_fim = pd.to_datetime(dataframe[fim], errors="coerce")
        mascara_inconsistente = valores_inicio.notna() & valores_fim.notna() & (valores_fim < valores_inicio)
        _adicionar_por_mascara(
            oportunidades,
            dataframe=dataframe,
            mascara=mascara_inconsistente,
            nome_tabela=nome_tabela,
            tabela_origem=tabela_origem,
            config=config,
            tipo="INCONSISTENCIA_HORARIO",
            descricao=f"'{fim}' ocorre antes de '{inicio}'.",
            severidade="ALTA",
            evidencia_factory=lambda linha, a=inicio, b=fim: {
                "campo_inicio": a,
                "valor_inicio": _valor_curto(linha[a]),
                "campo_fim": b,
                "valor_fim": _valor_curto(linha[b]),
            },
            maximo=maximo,
        )

    coluna_data = config.get("data")
    if (
        nome_tabela != "colaboradores"
        and coluna_data in dataframe.columns
        and periodo_inicio
        and periodo_fim
    ):
        datas = pd.to_datetime(dataframe[coluna_data], errors="coerce")
        inicio_periodo = pd.to_datetime(periodo_inicio, errors="coerce")
        fim_periodo = pd.to_datetime(periodo_fim, errors="coerce")
        if pd.notna(inicio_periodo) and pd.notna(fim_periodo):
            mascara_fora = datas.notna() & ((datas < inicio_periodo) | (datas > fim_periodo))
            _adicionar_por_mascara(
                oportunidades,
                dataframe=dataframe,
                mascara=mascara_fora,
                nome_tabela=nome_tabela,
                tabela_origem=tabela_origem,
                config=config,
                tipo="DATA_FORA_DO_PERIODO",
                descricao="Data de referencia fora da janela solicitada para a execucao.",
                severidade="MEDIA",
                evidencia_factory=lambda linha: {
                    "campo": coluna_data,
                    "valor": _valor_curto(linha[coluna_data]),
                    "periodo_inicio": periodo_inicio,
                    "periodo_fim": periodo_fim,
                },
                maximo=maximo,
            )

    if nome_tabela == "colaboradores" and "usuario_ativo" in dataframe.columns:
        valores = dataframe["usuario_ativo"].astype("string").str.strip().str.lower()
        mascara_padrao = (~_vazio(dataframe["usuario_ativo"])) & ~valores.isin(
            {"sim", "nao", "não"}
        )
        _adicionar_por_mascara(
            oportunidades,
            dataframe=dataframe,
            mascara=mascara_padrao,
            nome_tabela=nome_tabela,
            tabela_origem=tabela_origem,
            config=config,
            tipo="DADO_FORA_DO_PADRAO",
            descricao="Valor de usuario_ativo fora do padrao conhecido sim/nao.",
            severidade="MEDIA",
            evidencia_factory=lambda linha: {
                "campo": "usuario_ativo",
                "valor": _valor_curto(linha["usuario_ativo"]),
            },
            maximo=maximo,
        )

    for coluna_uf in ("uf", "estado"):
        if coluna_uf not in dataframe.columns:
            continue
        valores = dataframe[coluna_uf].astype("string").str.strip()
        mascara_uf = (~_vazio(dataframe[coluna_uf])) & ~valores.str.fullmatch(r"[A-Za-z]{2}")
        _adicionar_por_mascara(
            oportunidades,
            dataframe=dataframe,
            mascara=mascara_uf,
            nome_tabela=nome_tabela,
            tabela_origem=tabela_origem,
            config=config,
            tipo="DADO_FORA_DO_PADRAO",
            descricao=f"O campo '{coluna_uf}' nao possui uma sigla de UF com duas letras.",
            severidade="BAIXA",
            evidencia_factory=lambda linha, c=coluna_uf: {"campo": c, "valor": _valor_curto(linha[c])},
            maximo=maximo,
        )

    if nome_tabela == "pesquisas" and {"status", "data_conclusao"}.issubset(dataframe.columns):
        respondida = dataframe["status"].astype("string").str.strip().str.lower().isin(
            {"respondida", "concluida", "concluída"}
        )
        mascara_sem_conclusao = respondida & _vazio(dataframe["data_conclusao"])
        _adicionar_por_mascara(
            oportunidades,
            dataframe=dataframe,
            mascara=mascara_sem_conclusao,
            nome_tabela=nome_tabela,
            tabela_origem=tabela_origem,
            config=config,
            tipo="DADO_INCOMPLETO",
            descricao="Pesquisa concluida/respondida sem data de conclusao.",
            severidade="ALTA",
            evidencia_factory=lambda linha: {
                "status": _valor_curto(linha["status"]),
                "data_conclusao": _valor_curto(linha["data_conclusao"]),
            },
            maximo=maximo,
        )

    return oportunidades


def observar_qualidade(
    engine,
    dataframe: pd.DataFrame,
    nome_tabela: str,
    tabela_origem: str,
    *,
    periodo_inicio: str | None = None,
    periodo_fim: str | None = None,
) -> int:
    """Executa analise e persiste resultados; falhas ficam isoladas."""

    try:
        oportunidades = analisar_dataframe(
            dataframe,
            nome_tabela,
            tabela_origem,
            periodo_inicio=periodo_inicio,
            periodo_fim=periodo_fim,
        )
        return registrar_oportunidades(engine, oportunidades)
    except Exception as exc:
        registrar_evento(
            engine,
            nivel="ERRO",
            categoria="OBSERVABILIDADE",
            codigo="QUALIDADE_INDISPONIVEL",
            mensagem="A verificacao de qualidade falhou e foi ignorada para preservar a esteira.",
            etapa="QUALIDADE_DADOS",
            contexto={"tabela": tabela_origem},
            excecao=exc,
        )
        return 0
