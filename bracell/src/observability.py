"""Observabilidade lateral e *fail-open* da esteira BRACELL.

Todas as funcoes deste modulo capturam suas proprias falhas. Uma indisponibilidade
da camada de controle nunca deve interromper ETL, calculo ou gravacao Platina.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy import text

from .database import criar_engine
from shared.treatment_catalog import (
    classificacao_efetiva,
    listar_regras as _listar_regras_catalogo,
    resolver_regra as _resolver_regra_catalogo,
)


SCHEMA_CONTROLE = "pdoh_controle"
MARCA_PADRAO = "BRACELL"


def gerar_execution_id(marca: str = MARCA_PADRAO) -> str:
    instante = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{marca.upper()}_{instante}_{uuid.uuid4().hex[:8].upper()}"


def definir_execution_id(execution_id: str) -> str:
    os.environ["PDOH_EXECUTION_ID"] = execution_id
    return execution_id


def obter_execution_id(criar: bool = True) -> str | None:
    execution_id = os.environ.get("PDOH_EXECUTION_ID")
    if not execution_id and criar:
        execution_id = definir_execution_id(gerar_execution_id())
    return execution_id


def obter_componente() -> str:
    return os.environ.get("PDOH_COMPONENTE", "BACKEND")[:80]


def _texto(valor: Any, limite: int) -> str | None:
    if valor is None:
        return None
    return str(valor)[:limite]


def _json(valor: Any, limite: int = 32000) -> str:
    serializado = json.dumps(valor or {}, ensure_ascii=False, default=str, sort_keys=True)
    if len(serializado) <= limite:
        return serializado
    return json.dumps(
        {"resumo": "contexto truncado pela observabilidade", "tamanho_original": len(serializado)},
        ensure_ascii=False,
    )


def _data(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, (date, datetime)):
        return valor.date().isoformat() if isinstance(valor, datetime) else valor.isoformat()
    texto_valor = str(valor).strip()
    if len(texto_valor) >= 10 and texto_valor[4:5] == "-" and texto_valor[7:8] == "-":
        return texto_valor[:10]
    return None


def _emitir(nivel: str, codigo: str, mensagem: str, **contexto: Any) -> None:
    registro = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nivel": nivel,
        "codigo": codigo,
        "execution_id": obter_execution_id(criar=False),
        "marca": MARCA_PADRAO,
        "componente": obter_componente(),
        "mensagem": mensagem,
    }
    if contexto:
        registro["contexto"] = contexto
    try:
        print(json.dumps(registro, ensure_ascii=False, default=str, sort_keys=True), flush=True)
    except Exception:
        sys.stderr.write(f"[PDOH_CX_OBS] {nivel} {codigo}: {mensagem}\n")


def _falha_observabilidade(operacao: str, exc: Exception) -> None:
    _emitir(
        "ERRO",
        "OBSERVABILIDADE_INDISPONIVEL",
        "Falha isolada na camada de controle; a esteira principal continuara.",
        operacao=operacao,
        excecao_tipo=type(exc).__name__,
        erro=str(exc)[:1000],
    )


def iniciar_execucao(
    engine=None,
    *,
    execution_id: str | None = None,
    marca: str = MARCA_PADRAO,
    periodo_inicio: Any = None,
    periodo_fim: Any = None,
    componente: str | None = None,
    operacao: str = 'EXCLUSIVA',
    finalidade: str | None = None,
) -> str:
    execution_id = definir_execution_id(execution_id or obter_execution_id() or gerar_execution_id(marca))
    componente = componente or obter_componente()
    try:
        engine = engine or criar_engine()
        comando = text(
            "INSERT INTO pdoh_controle.execucao "
            "(execution_id, marca, operacao, periodo_inicio, periodo_fim, status_execucao, "
            " componente_atual, etapa_atual, versao_aplicacao) "
            "VALUES (:id, :marca, :operacao, :inicio, :fim, 'INICIADA', :componente, 'INICIALIZACAO', :versao) "
            "ON DUPLICATE KEY UPDATE "
            "periodo_inicio = COALESCE(VALUES(periodo_inicio), periodo_inicio), "
            "periodo_fim = COALESCE(VALUES(periodo_fim), periodo_fim), "
            "componente_atual = VALUES(componente_atual), atualizado_em = CURRENT_TIMESTAMP(6)"
        )
        with engine.begin() as conexao:
            conexao.execute(
                comando,
                {
                    "id": execution_id,
                    "marca": marca,
                    "operacao": operacao,
                    "inicio": _data(periodo_inicio),
                    "fim": _data(periodo_fim),
                    "componente": componente,
                    "versao": os.environ.get("PDOH_CX_VERSION", "fase-observabilidade-1"),
                },
            )
            conexao.execute(text('INSERT IGNORE INTO pdoh_controle.execucao_contexto '
                '(execution_id,marca,operacao,finalidade,justificativa) '
                'VALUES (:id,:marca,:operacao,:finalidade,:motivo)'), dict(
                    id=execution_id, marca=marca, operacao=operacao,
                    finalidade=finalidade or ('VALIDACAO' if componente == 'VALIDACAO' else 'OPERACIONAL'),
                    motivo='Escopo declarado pelo executor'))
        _emitir("INFO", "EXECUCAO_INICIADA", "Execucao PDOH_CX registrada.")
    except Exception as exc:
        _falha_observabilidade("iniciar_execucao", exc)
    return execution_id


def atualizar_periodo(engine, periodo_inicio: Any, periodo_fim: Any) -> None:
    try:
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "UPDATE pdoh_controle.execucao SET periodo_inicio = :inicio, periodo_fim = :fim "
                    "WHERE execution_id = :id"
                ),
                {
                    "id": obter_execution_id(),
                    "inicio": _data(periodo_inicio),
                    "fim": _data(periodo_fim),
                },
            )
    except Exception as exc:
        _falha_observabilidade("atualizar_periodo", exc)


def registrar_evento(
    engine,
    *,
    nivel: str,
    categoria: str,
    codigo: str,
    mensagem: str,
    etapa: str | None = None,
    contexto: Any = None,
    excecao: Exception | None = None,
) -> None:
    try:
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "INSERT INTO pdoh_controle.execucao_evento "
                    "(execution_id, componente, etapa, nivel, categoria, codigo, mensagem, "
                    " excecao_tipo, contexto) "
                    "VALUES (:id, :componente, :etapa, :nivel, :categoria, :codigo, :mensagem, "
                    " :excecao_tipo, CAST(:contexto AS JSON))"
                ),
                {
                    "id": obter_execution_id(),
                    "componente": obter_componente(),
                    "etapa": _texto(etapa, 80),
                    "nivel": _texto(nivel.upper(), 20),
                    "categoria": _texto(categoria, 50),
                    "codigo": _texto(codigo, 100),
                    "mensagem": _texto(mensagem, 65000),
                    "excecao_tipo": type(excecao).__name__ if excecao else None,
                    "contexto": _json(contexto),
                },
            )
        _emitir(nivel.upper(), codigo, mensagem, etapa=etapa, detalhes=contexto or {})
    except Exception as exc:
        _falha_observabilidade("registrar_evento", exc)


def registrar_etapa(
    engine,
    *,
    etapa: str,
    status: str,
    origem: str | None = None,
    tabela_origem: str | None = None,
    linhas_recebidas: int | None = None,
    linhas_tratadas: int | None = None,
    linhas_geradas: int | None = None,
    linhas_persistidas: int | None = None,
    mensagem: str | None = None,
    contexto: Any = None,
) -> None:
    try:
        parametros = {
            "id": obter_execution_id(),
            "componente": obter_componente(),
            "etapa": _texto(etapa, 80),
            "status": _texto(status, 40),
            "origem": _texto(origem, 80),
            "tabela": _texto(tabela_origem, 160),
            "recebidas": linhas_recebidas,
            "tratadas": linhas_tratadas,
            "geradas": linhas_geradas,
            "persistidas": linhas_persistidas,
            "mensagem": _texto(mensagem, 65000),
            "contexto": _json(contexto),
        }
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "INSERT INTO pdoh_controle.execucao_etapa "
                    "(execution_id, componente, etapa, status_etapa, origem, tabela_origem, "
                    " linhas_recebidas, linhas_tratadas, linhas_geradas, linhas_persistidas, "
                    " mensagem, contexto) VALUES "
                    "(:id, :componente, :etapa, :status, :origem, :tabela, :recebidas, :tratadas, "
                    " :geradas, :persistidas, :mensagem, CAST(:contexto AS JSON))"
                ),
                parametros,
            )
            conexao.execute(
                text(
                    "UPDATE pdoh_controle.execucao SET componente_atual = :componente, "
                    "etapa_atual = :etapa WHERE execution_id = :id"
                ),
                parametros,
            )
        _emitir("INFO", f"ETAPA_{status}", mensagem or etapa, etapa=etapa)
    except Exception as exc:
        _falha_observabilidade("registrar_etapa", exc)


def registrar_fonte(
    engine,
    *,
    tabela_origem: str,
    periodo_inicio: Any,
    periodo_fim: Any,
    linhas_recebidas: int,
    linhas_tratadas: int,
    duplicatas: int,
    consulta: str,
) -> None:
    try:
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "INSERT INTO pdoh_controle.execucao_fonte "
                    "(execution_id, componente, schema_origem, tabela_origem, "
                    " filtro_periodo_inicio, filtro_periodo_fim, linhas_recebidas, "
                    " linhas_apos_tratamento, duplicatas_identificadas, query_hash) "
                    "VALUES (:id, :componente, 'involves_bracell', :tabela, :inicio, :fim, "
                    " :recebidas, :tratadas, :duplicatas, :query_hash)"
                ),
                {
                    "id": obter_execution_id(),
                    "componente": obter_componente(),
                    "tabela": tabela_origem,
                    "inicio": _data(periodo_inicio),
                    "fim": _data(periodo_fim),
                    "recebidas": int(linhas_recebidas),
                    "tratadas": int(linhas_tratadas),
                    "duplicatas": int(duplicatas),
                    "query_hash": hashlib.sha256(consulta.encode("utf-8")).hexdigest(),
                },
            )
            conexao.execute(
                text(
                    "UPDATE pdoh_controle.execucao SET "
                    "linhas_recebidas = linhas_recebidas + :recebidas, "
                    "linhas_tratadas = linhas_tratadas + :tratadas "
                    "WHERE execution_id = :id"
                ),
                {
                    "id": obter_execution_id(),
                    "recebidas": int(linhas_recebidas),
                    "tratadas": int(linhas_tratadas),
                },
            )
    except Exception as exc:
        _falha_observabilidade("registrar_fonte", exc)


def registrar_fallback(
    engine,
    *,
    codigo: str,
    motivo: str,
    etapa: str = "PROCESSAMENTO_PDOH",
    severidade: str = "MEDIA",
    impacto_esperado: str | None = None,
    contexto: Any = None,
) -> str:
    fallback_id = str(uuid.uuid4())
    try:
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "INSERT INTO pdoh_controle.fallback_evento "
                    "(fallback_id, execution_id, componente, etapa, codigo, motivo, "
                    " impacto_esperado, severidade, contexto) VALUES "
                    "(:fallback_id, :id, :componente, :etapa, :codigo, :motivo, "
                    " :impacto, :severidade, CAST(:contexto AS JSON))"
                ),
                {
                    "fallback_id": fallback_id,
                    "id": obter_execution_id(),
                    "componente": obter_componente(),
                    "etapa": etapa,
                    "codigo": codigo,
                    "motivo": _texto(motivo, 65000),
                    "impacto": _texto(impacto_esperado, 65000),
                    "severidade": severidade,
                    "contexto": _json(contexto),
                },
            )
            conexao.execute(
                text(
                    "UPDATE pdoh_controle.execucao SET total_fallbacks = total_fallbacks + 1 "
                    "WHERE execution_id = :id"
                ),
                {"id": obter_execution_id()},
            )
            # Fallback bruto e telemetria: nao gera notificacao operacional.
        _emitir("AVISO", codigo, motivo, etapa=etapa)
    except Exception as exc:
        _falha_observabilidade("registrar_fallback", exc)
    return fallback_id


def _fingerprint_oportunidade(item: dict[str, Any]) -> str:
    base = {
        "origem": item.get("origem"),
        "tabela": item.get("tabela_origem"),
        "colaborador": item.get("colaborador"),
        "data": _data(item.get("data_referencia")),
        "tipo": item.get("tipo_problema"),
        "evidencia": item.get("evidencia"),
    }
    return hashlib.sha256(_json(base).encode("utf-8")).hexdigest()


def evidencia_padrao(
    *,
    campo_esperado: str | None = None,
    valor_esperado: Any = None,
    valor_encontrado: Any = None,
    fallback_usado: bool = False,
    fallback_valor: Any = None,
    origem: str | None = None,
    registro_afetado: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    """Monta o JSON de evidencia no padrao operacional (chaves opcionais quando aplicaveis)."""

    base: dict[str, Any] = {"fallback_usado": bool(fallback_usado)}
    if campo_esperado is not None:
        base["campo_esperado"] = campo_esperado
    if valor_esperado is not None:
        base["valor_esperado"] = valor_esperado
    if valor_encontrado is not None:
        base["valor_encontrado"] = valor_encontrado
    if fallback_valor is not None:
        base["fallback_valor"] = fallback_valor
    if origem is not None:
        base["origem"] = origem
    if registro_afetado is not None:
        base["registro_afetado"] = registro_afetado
    base.update({k: v for k, v in extra.items() if v is not None})
    return base


_TIPOS_META_OPORTUNIDADE = {"FALHA_PARAMETRIZACAO", "VOLUME_OPORTUNIDADES_TRUNCADO"}


def registrar_achado(engine, achados) -> int:
    """Entrada central (import tardio evita ciclo). Destino vem somente do catalogo."""
    from .findings import registrar_achado as dispatch
    return dispatch(engine, achados)


def registrar_oportunidades(engine, oportunidades: Iterable[dict[str, Any]]) -> int:
    """Compatibilidade com chamadores legados: nunca grava diretamente."""
    return registrar_achado(engine, oportunidades)


def atualizar_status_oportunidade(
    engine,
    oportunidade_id: str,
    status_novo: str,
    *,
    observacao: str | None = None,
    responsavel: str | None = None,
    contexto: Any = None,
) -> bool:
    """Atualiza o estado e acrescenta auditoria; nao remove historico anterior."""

    try:
        with engine.begin() as conexao:
            atual = conexao.execute(
                text(
                    "SELECT status_oportunidade FROM pdoh_controle.oportunidade "
                    "WHERE oportunidade_id = :oportunidade_id FOR UPDATE"
                ),
                {"oportunidade_id": oportunidade_id},
            ).scalar_one_or_none()
            if atual is None:
                return False
            conexao.execute(
                text(
                    "UPDATE pdoh_controle.oportunidade SET status_oportunidade = :status_novo "
                    "WHERE oportunidade_id = :oportunidade_id"
                ),
                {"oportunidade_id": oportunidade_id, "status_novo": status_novo[:30]},
            )
            conexao.execute(
                text(
                    "INSERT INTO pdoh_controle.oportunidade_historico "
                    "(oportunidade_id, execution_id, status_anterior, status_novo, acao, "
                    " observacao, responsavel, contexto) VALUES "
                    "(:oportunidade_id, :id, :status_anterior, :status_novo, "
                    " 'STATUS_ATUALIZADO', :observacao, :responsavel, CAST(:contexto AS JSON))"
                ),
                {
                    "oportunidade_id": oportunidade_id,
                    "id": obter_execution_id(),
                    "status_anterior": atual,
                    "status_novo": status_novo[:30],
                    "observacao": _texto(observacao, 65000),
                    "responsavel": _texto(responsavel, 120),
                    "contexto": _json(contexto),
                },
            )
        return True
    except Exception as exc:
        _falha_observabilidade("atualizar_status_oportunidade", exc)
        return False


# --------------------------------------------------------------------------
# Camada de parametrizacao de tratativas (ex-tabela regra_tratativa).
# O catalogo agora vive em codigo (shared.treatment_catalog). A tabela e' seguida
# semeada (bootstrap_regras) so' para manter as FKs existentes em oportunidade/
# alerta/achado_roteamento vivas ate a remocao completa da tabela.
# --------------------------------------------------------------------------


def resolver_classificacao(
    engine, tipo_problema: str, marca: str = MARCA_PADRAO, tabela_origem: str | None = None
) -> str | None:
    """Retorna a classificacao operacional (OPORTUNIDADE/ALERTA/TELEMETRIA) da regra vigente."""

    return classificacao_efetiva(resolver_tratativa(engine, tipo_problema, marca), tabela_origem)


def resolver_tratativa(engine, tipo_problema: str, marca: str = MARCA_PADRAO) -> dict[str, Any] | None:
    """Resolve a regra vigente para um tipo de problema.

    Le do catalogo em codigo (shared.treatment_catalog), nao mais do banco. `engine'
    e mantido na assinatura por compatibilidade dos chamadores existentes.
    """

    return _resolver_regra_catalogo(tipo_problema, marca)


def carregar_regras_tratativa(engine, marca: str = MARCA_PADRAO) -> list[dict[str, Any]]:
    """Le todas as regras aplicaveis do catalogo em codigo (nao mais do banco)."""

    return _listar_regras_catalogo(marca)


def registrar_linhagem_saida(engine, dataframe, tabela_destino: str) -> int:
    """Relaciona a execucao as chaves da Platina em tabela lateral."""

    try:
        registros = []
        for _, linha in dataframe.iterrows():
            dados = {coluna: linha[coluna] for coluna in dataframe.columns}
            colaborador = dados.get("colaborador")
            data_referencia = _data(dados.get("data"))
            chave = _json({"colaborador": colaborador, "data": data_referencia})
            registros.append(
                {
                    "id": obter_execution_id(),
                    "marca": MARCA_PADRAO,
                    "tabela": tabela_destino,
                    "colaborador": _texto(colaborador, 255),
                    "data": data_referencia,
                    "chave_hash": hashlib.sha256(chave.encode("utf-8")).hexdigest(),
                    "linha_hash": hashlib.sha256(_json(dados).encode("utf-8")).hexdigest(),
                    "acao": "UPSERT_CONCLUIDO",
                }
            )
        if registros:
            with engine.begin() as conexao:
                conexao.execute(
                    text(
                        "INSERT INTO pdoh_controle.saida_linhagem "
                        "(execution_id, marca, tabela_destino, colaborador, data_referencia, "
                        " chave_negocio_hash, linha_hash, acao) VALUES "
                        "(:id, :marca, :tabela, :colaborador, :data, :chave_hash, :linha_hash, :acao) "
                        "ON DUPLICATE KEY UPDATE linha_hash = VALUES(linha_hash), "
                        "acao = VALUES(acao), registrado_em = CURRENT_TIMESTAMP(6)"
                    ),
                    registros,
                )
        return len(registros)
    except Exception as exc:
        _falha_observabilidade("registrar_linhagem_saida", exc)
        return 0


def registrar_resultado_persistencia(
    engine,
    *,
    linhas_geradas: int,
    linhas_persistidas: int,
    afetadas_banco: int | None = None,
) -> None:
    try:
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "UPDATE pdoh_controle.execucao SET linhas_geradas = linhas_geradas + :geradas, "
                    "linhas_persistidas = linhas_persistidas + :persistidas, houve_persistencia = 1 "
                    "WHERE execution_id = :id"
                ),
                {
                    "id": obter_execution_id(),
                    "geradas": int(linhas_geradas),
                    "persistidas": int(linhas_persistidas),
                },
            )
        registrar_etapa(
            engine,
            etapa="PERSISTENCIA_PLATINA",
            status="CONCLUIDA",
            linhas_geradas=linhas_geradas,
            linhas_persistidas=linhas_persistidas,
            mensagem="UPSERT Platina concluido.",
            contexto={"linhas_afetadas_reportadas_mysql": afetadas_banco},
        )
    except Exception as exc:
        _falha_observabilidade("registrar_resultado_persistencia", exc)


def registrar_erro_tecnico(engine, *, etapa: str, mensagem: str, excecao: Exception | None = None) -> None:
    try:
        registrar_evento(
            engine,
            nivel="ERRO",
            categoria="TECNICO",
            codigo="FALHA_TECNICA",
            mensagem=mensagem,
            etapa=etapa,
            excecao=excecao,
        )
        registrar_etapa(engine, etapa=etapa, status="FALHA", mensagem=mensagem)
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "UPDATE pdoh_controle.execucao SET status_execucao = 'FALHA_TECNICA', "
                    "erro_resumo = :erro WHERE execution_id = :id"
                ),
                {"id": obter_execution_id(), "erro": _texto(mensagem, 65000)},
            )
    except Exception as exc:
        _falha_observabilidade("registrar_erro_tecnico", exc)


def obter_resumo_execucao(engine) -> dict[str, Any]:
    try:
        with engine.connect() as conexao:
            linha = conexao.execute(
                text(
                    "SELECT status_execucao, houve_persistencia, total_alertas, total_fallbacks, "
                    "linhas_geradas, linhas_persistidas FROM pdoh_controle.execucao "
                    "WHERE execution_id = :id"
                ),
                {"id": obter_execution_id()},
            ).mappings().first()
        return dict(linha or {})
    except Exception as exc:
        _falha_observabilidade("obter_resumo_execucao", exc)
        return {}


def finalizar_execucao(engine, status: str | None = None, erro_resumo: str | None = None) -> str:
    status_final = status or "CONCLUIDA"
    try:
        resumo = obter_resumo_execucao(engine)
        if resumo.get("status_execucao") == "FALHA_TECNICA":
            status_final = "FALHA_TECNICA"
        elif status_final == "CONCLUIDA" and not resumo.get("houve_persistencia"):
            status_final = "CONCLUIDA_SEM_RESULTADO"
        elif status_final == "CONCLUIDA" and (
            int(resumo.get("total_alertas") or 0) > 0
            or int(resumo.get("total_fallbacks") or 0) > 0
        ):
            status_final = "CONCLUIDA_COM_ALERTAS"
        with engine.begin() as conexao:
            conexao.execute(
                text(
                    "UPDATE pdoh_controle.execucao SET status_execucao = :status, "
                    "finalizado_em = CURRENT_TIMESTAMP(6), etapa_atual = 'FINALIZACAO', "
                    "componente_atual = :componente, "
                    "erro_resumo = COALESCE(:erro, erro_resumo) WHERE execution_id = :id"
                ),
                {
                    "id": obter_execution_id(),
                    "status": status_final,
                    "componente": obter_componente(),
                    "erro": _texto(erro_resumo, 65000),
                },
            )
        _emitir("INFO", "EXECUCAO_FINALIZADA", f"Execucao finalizada com status {status_final}.")
    except Exception as exc:
        _falha_observabilidade("finalizar_execucao", exc)
    return status_final
