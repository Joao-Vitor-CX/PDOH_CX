"""Observa fallbacks ja existentes no legado, sem executa-los nem altera-los."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any

import pandas as pd

from .data_quality import CONFIGURACAO_TABELAS
from .observability import (
    evidencia_padrao,
    obter_componente,
    registrar_evento,
    registrar_fallback,
    registrar_achado,
)


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


def observar_fallbacks_entrada(engine, dataframe: pd.DataFrame, nome_tabela: str, *,
                               source_engine=None, periodo_inicio=None, periodo_fim=None) -> int:
    """Detecta as condicoes que acionam ``fillna``/padroes no codigo original.

    Com `source_engine`, o CHECKOUT_AUSENTE passa pelo motor de evidencias antes de virar
    oportunidade: sem entrada registrada, sem roteiro no dia ou com abono, o achado fica
    como evento de governanca e nao chega a fila do lider.
    """

    try:
        if nome_tabela in ('relatorio_de_operacao', 'checkin'):
            from .operational_detectors import observar_operacionais
            observar_operacionais(engine, source_engine, dataframe, nome_tabela,
                                  periodo_inicio=periodo_inicio, periodo_fim=periodo_fim)
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
            total = _registrar_limitado(
                engine,
                ocorrencias,
                codigo="HORA_SAIDA_PADRAO_2359",
                motivo="Hora de saida ausente; o legado utiliza 23:59:00.",
                impacto="Pode ampliar o intervalo considerado no processamento.",
            )
            # CHECKOUT_AUSENTE (regra de negocio): SOMENTE quando houve check-in,
            # nao houve check-out (nem sistema/registrado) e o fallback 23:59 foi usado.
            # "Sem Checkin" e casos com checkout alternativo NAO geram oportunidade.
            # O fallback em si (23:59) permanece INALTERADO acima.
            def _coluna_nula(coluna):
                return dataframe[coluna].isna() if coluna in dataframe.columns else pd.Series(True, index=dataframe.index)

            tipo_com_checkin = (
                dataframe["tipo_checkin"].astype("string").str.strip().str.lower().ne("sem checkin")
                if "tipo_checkin" in dataframe.columns else pd.Series(False, index=dataframe.index)
            )
            mascara_checkout = mascara & tipo_com_checkin & _coluna_nula("checkout_sistema") & _coluna_nula("checkout_registrado")
            ocorrencias_checkout = [
                {
                    "indice_origem": str(dataframe.index[pos]),
                    "colaborador": _texto(dataframe.iloc[pos].get("colaborador")),
                    "data_referencia": _texto(dataframe.iloc[pos].get("data_roteiro")),
                }
                for pos, usado in enumerate(mascara_checkout.tolist())
                if bool(usado)
            ]
            if ocorrencias_checkout:
                grupos: dict[tuple, dict[str, Any]] = defaultdict(lambda: {"ocorrencias": 0, "indices": []})
                for item in ocorrencias_checkout:
                    chave = (item.get("colaborador"), item.get("data_referencia"))
                    grupo = grupos[chave]
                    grupo["ocorrencias"] += 1
                    if len(grupo["indices"]) < 20:
                        grupo["indices"].append(item.get("indice_origem"))
                achados_checkout = [
                    {
                        "marca": "BRACELL",
                        "origem": "INVOLVES_BRACELL",
                        "tabela_origem": "relatorio_checkin_bracell",
                        "colaborador": colaborador,
                        "data_referencia": data_ref,
                        "tipo_problema": "CHECKOUT_AUSENTE",
                        "severidade": "MEDIA",
                        "evidencia": evidencia_padrao(
                            campo_esperado="hora_saida",
                            valor_esperado="check-out real",
                            valor_encontrado="(ausente)",
                            fallback_usado=True,
                            fallback_valor="23:59:00",
                            origem="relatorio_checkin_bracell",
                            registro_afetado=grupo["indices"],
                            ocorrencias=grupo["ocorrencias"],
                        ),
                    }
                    for (colaborador, data_ref), grupo in grupos.items()
                ]
                # Sem a origem aberta nao ha como comprovar entrada, roteiro ou abono.
                # Cobrar sem prova seria falso positivo, entao o achado fica em governanca.
                if source_engine is None:
                    registrar_evento(
                        engine, nivel="ALERTA", categoria="EVIDENCIA",
                        codigo="COMPROVACAO_SEM_ORIGEM",
                        mensagem=("Origem nao disponivel para comprovar o check-out ausente; "
                                  "nenhuma oportunidade foi criada."),
                        etapa="COMPROVACAO",
                        contexto={"tipo_problema": "CHECKOUT_AUSENTE",
                                  "achados_descartados": len(achados_checkout)},
                    )
                else:
                    from .evidence_context import comprovar_e_registrar
                    comprovar_e_registrar(engine, source_engine, achados_checkout,
                                          periodo_inicio=periodo_inicio, periodo_fim=periodo_fim)
            return total

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
            total = _registrar_limitado(
                engine,
                ocorrencias,
                codigo="PESQUISA_NULOS_DATA_PADRAO_1999",
                motivo="Pesquisa contem nulos; o legado aplica a data/hora padrao de 1999.",
                impacto="Campos ausentes seguem a tratativa alternativa ja existente.",
            )
            # Oportunidade apenas para campos COMPROVADAMENTE obrigatorios (config de
            # qualidade existente) — campos opcionais nulos NAO geram oportunidade.
            # O fallback (1999) permanece inalterado. Agregado por id da pesquisa.
            obrigatorias = [
                c for c in CONFIGURACAO_TABELAS.get("pesquisas", {}).get("obrigatorias", ())
                if c in dataframe.columns
            ]
            if obrigatorias:
                por_id: dict[str, dict[str, Any]] = {}
                for pos in range(len(dataframe)):
                    linha = dataframe.iloc[pos]
                    nulos = [c for c in obrigatorias if pd.isna(linha[c])]
                    if not nulos:
                        continue
                    pid = _texto(linha.get("id")) or str(dataframe.index[pos])
                    registro = por_id.setdefault(pid, {
                        "campos": set(),
                        "responsavel": _texto(linha.get("responsavel")),
                        "data": _texto(linha.get("data_solicitacao")),
                    })
                    registro["campos"].update(nulos)
                if por_id:
                    registrar_achado(engine, [
                        {
                            "marca": "BRACELL",
                            "origem": "INVOLVES_BRACELL",
                            "tabela_origem": "painel_pesquisas_bracell",
                            "colaborador": dados["responsavel"],
                            "data_referencia": dados["data"],
                            "tipo_problema": "PESQUISA_CAMPOS_NULOS",
                            "severidade": "MEDIA",
                            "evidencia": evidencia_padrao(
                                campo_esperado=sorted(dados["campos"]),
                                valor_encontrado="(ausente)",
                                fallback_usado=True,
                                fallback_valor="1999-01-01",
                                origem="painel_pesquisas_bracell",
                                registro_afetado=f"id={pid}",
                            ),
                        }
                        for pid, dados in por_id.items()
                    ])
            return total
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


def observar_fallback_jornada(engine, colaboradores: pd.DataFrame, *, source_engine=None, resolutions=None) -> int:
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
        total = _registrar_limitado(
            engine,
            ocorrencias,
            codigo="JORNADA_PADRAO_44H",
            motivo="Jornada nao numerica/ausente; o legado utiliza 44 horas.",
            impacto="Define a jornada semanal usada nos indicadores atuais.",
            severidade="ALTA",
        )
        # Fallback is a technical observation, not proof that the official journey is missing.
        if resolutions is None and source_engine is not None:
            from .journey_observer import resolve_official, persist
            from .observability import obter_execution_id
            resolutions = resolve_official(engine, source_engine)
            persist(engine, resolutions, obter_execution_id(criar=False))
        if resolutions is None:
            registrar_evento(engine, nivel='ALERTA', categoria='TELEMETRIA',
                codigo='RESOLUCAO_JORNADA_INCOMPLETA', mensagem='Fontes oficiais nao resolvidas; ausencia de jornada nao comprovada.',
                etapa='PROCESSAMENTO_PDOH')
        else:
            registrar_achado(engine, [dict(
                marca=row['marca'], origem='RESOLUCAO_OFICIAL', tabela_origem='jornada_consolidada',
                colaborador=row['colaborador'], data_referencia=row['data_referencia'],
                tipo_problema='JORNADA_NAO_ENCONTRADA', severidade='ALTA',
                descricao_detalhada='Jornada ausente apos consulta completa das fontes oficiais vigentes.',
                evidencia={**row['evidencia'], 'resolucao_id': row['resolucao_id'], 'ocorrencias': 1})
                for row in resolutions if row['status_resolucao'] == 'NAO_ENCONTRADA'
                and row['elegivel'] and row['vigente'] and row['evidencia']['resolucao_completa']])
        return total
    except Exception as exc:
        registrar_evento(
            engine,
            nivel="ERRO",
            categoria="TELEMETRIA",
            codigo="DETECCAO_FALLBACK_JORNADA_INDISPONIVEL",
            mensagem="Falha ao observar o fallback de jornada; o processamento continuara.",
            etapa="PROCESSAMENTO_PDOH",
            excecao=exc,
        )
        return 0
