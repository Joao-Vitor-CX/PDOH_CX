"""Observa fallbacks ja existentes no legado, sem executa-los nem altera-los."""

from __future__ import annotations

import os
import re
from typing import Any

import pandas as pd

from .observability import obter_componente, registrar_evento, registrar_fallback


def _limite() -> int:
    return max(1, int(os.environ.get("PDOH_OBS_MAX_EVIDENCIAS_POR_REGRA", "500")))


def _texto(valor: Any) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    return str(valor)[:255]


def _jornada_valida_para_parser_legado(valor: Any) -> bool:
    if valor is None or pd.isna(valor):
        return False
    limpo = re.sub(r"[^\d.]", "", str(valor))
    try:
        float(limpo)
        return True
    except (TypeError, ValueError):
        return False


def _registrar_limitado(engine, ocorrencias: list[dict[str, Any]], *, codigo: str, motivo: str,
                        impacto: str, severidade: str = "MEDIA") -> int:
    maximo = _limite()
    for contexto in ocorrencias[:maximo]:
        registrar_fallback(
            engine,
            codigo=codigo,
            motivo=motivo,
            etapa="PROCESSAMENTO_PDOH",
            severidade=severidade,
            impacto_esperado=impacto,
            contexto=contexto,
        )
    if len(ocorrencias) > maximo:
        registrar_evento(
            engine,
            nivel="ALERTA",
            categoria="FALLBACK",
            codigo="VOLUME_FALLBACK_TRUNCADO",
            mensagem=(
                f"{codigo} ocorreu {len(ocorrencias)} vezes; {maximo} evidencias "
                "foram persistidas para proteger a execucao."
            ),
            etapa="PROCESSAMENTO_PDOH",
            contexto={"codigo_fallback": codigo, "total": len(ocorrencias), "armazenadas": maximo},
        )
    return len(ocorrencias)


def observar_fallbacks_entrada(engine, dataframe: pd.DataFrame, nome_tabela: str) -> int:
    """Detecta as condicoes que acionam ``fillna``/padroes no codigo original."""

    try:
        if nome_tabela == "checkin" and "hora_saida" in dataframe.columns:
            mascara = dataframe["hora_saida"].isna()
            ocorrencias = [
                {
                    "indice_origem": str(dataframe.index[pos]),
                    "tabela": "relatorio_checkin_bracell",
                    "colaborador": _texto(dataframe.iloc[pos].get("colaborador")),
                    "data_referencia": _texto(dataframe.iloc[pos].get("data_roteiro")),
                    "valor_alternativo_legado": "23:59:00",
                }
                for pos, usado in enumerate(mascara.tolist())
                if bool(usado)
            ]
            return _registrar_limitado(
                engine,
                ocorrencias,
                codigo="HORA_SAIDA_PADRAO_2359",
                motivo="Hora de saida ausente; o legado utiliza 23:59:00.",
                impacto="Pode ampliar o intervalo considerado no processamento.",
            )

        if nome_tabela == "pesquisas":
            ocorrencias = []
            for pos in range(len(dataframe)):
                linha = dataframe.iloc[pos]
                campos_nulos = [coluna for coluna in dataframe.columns if pd.isna(linha[coluna])]
                if campos_nulos:
                    ocorrencias.append(
                        {
                            "indice_origem": str(dataframe.index[pos]),
                            "tabela": "painel_pesquisas_bracell",
                            "colaborador": _texto(linha.get("responsavel")),
                            "data_referencia": _texto(linha.get("data_solicitacao")),
                            "campos_nulos": campos_nulos,
                            "valor_alternativo_legado": "1999-01-01 23:59:00",
                        }
                    )
            return _registrar_limitado(
                engine,
                ocorrencias,
                codigo="PESQUISA_NULOS_DATA_PADRAO_1999",
                motivo="Pesquisa contem nulos; o legado aplica a data/hora padrao de 1999.",
                impacto="Campos ausentes seguem a tratativa alternativa ja existente.",
            )
        return 0
    except Exception as exc:
        registrar_evento(
            engine,
            nivel="ERRO",
            categoria="OBSERVABILIDADE",
            codigo="DETECCAO_FALLBACK_INDISPONIVEL",
            mensagem="Falha ao observar fallbacks; o processamento principal continuara.",
            etapa="PROCESSAMENTO_PDOH",
            contexto={"dataframe": nome_tabela},
            excecao=exc,
        )
        return 0


def observar_fallback_jornada(engine, colaboradores: pd.DataFrame) -> int:
    """Observa o ``fillna(44.0)`` aplicado pelo processador apos seus filtros."""

    try:
        if "nome_pai" not in colaboradores.columns:
            return 0
        candidatos = colaboradores
        componente = obter_componente()
        perfil_esperado = "LIDER EXCLUSIVO" if componente == "LIDERES" else "PROMOTOR EXCLUSIVO"
        if "perfil_acesso" in candidatos.columns:
            perfil = candidatos["perfil_acesso"].astype("string")
            candidatos = candidatos[perfil.str.contains(perfil_esperado, na=False)]
        if "nome_colaborador" in candidatos.columns:
            candidatos = candidatos[
                candidatos["nome_colaborador"].astype("string") != "TESTE (NÃO INATIVAR)"
            ]
        ocorrencias = []
        for indice, linha in candidatos.iterrows():
            if _jornada_valida_para_parser_legado(linha.get("nome_pai")):
                continue
            ocorrencias.append(
                {
                    "indice_origem": str(indice),
                    "tabela": "colaboradores_ativos_bracell",
                    "colaborador": _texto(linha.get("nome_colaborador")),
                    "campo_origem_legado": "nome_pai",
                    "valor_observado": _texto(linha.get("nome_pai")),
                    "valor_alternativo_legado": 44.0,
                }
            )
        return _registrar_limitado(
            engine,
            ocorrencias,
            codigo="JORNADA_PADRAO_44H",
            motivo="Jornada nao numerica/ausente; o legado utiliza 44 horas.",
            impacto="Define a jornada semanal usada nos indicadores atuais.",
            severidade="ALTA",
        )
    except Exception as exc:
        registrar_evento(
            engine,
            nivel="ERRO",
            categoria="OBSERVABILIDADE",
            codigo="DETECCAO_FALLBACK_JORNADA_INDISPONIVEL",
            mensagem="Falha ao observar o fallback de jornada; o processamento continuara.",
            etapa="PROCESSAMENTO_PDOH",
            excecao=exc,
        )
        return 0
