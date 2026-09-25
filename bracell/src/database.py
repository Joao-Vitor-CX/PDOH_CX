"""Conexoes locais do PDOH_CX.

O modulo centraliza apenas a configuracao tecnica. Nenhuma regra de negocio ou
consulta da esteira BRACELL e definida aqui.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event


HOSTS_LOCAIS_AUTORIZADOS = frozenset({"mysql", "localhost", "127.0.0.1"})
BANCOS_ORIGEM_AUTORIZADOS = frozenset({"involves_bracell", "involves_exclusivos"})
COMANDOS_SOMENTE_LEITURA = frozenset({"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"})


def _registrar_evento_seguranca(codigo: str, mensagem: str, **detalhes) -> None:
    evento = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nivel": "CRITICO",
        "categoria": "SEGURANCA",
        "codigo": codigo,
        "mensagem": mensagem,
        **detalhes,
    }
    print(json.dumps(evento, ensure_ascii=False, sort_keys=True), file=sys.stderr, flush=True)


def validar_host_local(host: str) -> str:
    """Aceita somente os endpoints locais previstos para o PDOH_CX."""

    host_normalizado = str(host).strip().lower()
    if host_normalizado in HOSTS_LOCAIS_AUTORIZADOS:
        return host_normalizado

    _registrar_evento_seguranca(
        "CONEXAO_BANCO_NAO_AUTORIZADA",
        "O ambiente PDOH_CX aceita somente hosts locais autorizados.",
        host_informado=host_normalizado,
    )
    raise RuntimeError(
        f"Conexao recusada: o host '{host_normalizado}' nao esta autorizado no PDOH_CX local."
    )


def criar_engine(database: str = "involves_bracell"):
    """Cria um engine lazy usando exclusivamente as variaveis do PDOH_CX."""

    host = validar_host_local(os.environ.get("PDOH_DB_HOST", "mysql"))
    port = int(os.environ.get("PDOH_DB_PORT", "3306"))
    usuario = os.environ.get("PDOH_DB_USER")
    senha_configurada = os.environ.get("PDOH_DB_PASSWORD")
    if not usuario or not senha_configurada:
        raise RuntimeError(
            "Configuracao recusada: PDOH_DB_USER e PDOH_DB_PASSWORD devem vir do ambiente local."
        )
    senha = quote_plus(senha_configurada)
    return create_engine(
        f"mysql+pymysql://{usuario}:{senha}@{host}:{port}/{database}"
        "?charset=utf8mb4",
        pool_pre_ping=True,
    )


def validar_comando_somente_leitura(statement: str) -> None:
    """Bloqueia qualquer comando que nao seja leitura na conexao da origem."""

    sql = str(statement).lstrip()
    while sql.startswith("/*") and "*/" in sql:
        sql = sql.split("*/", 1)[1].lstrip()
    while sql.startswith("--") and "\n" in sql:
        sql = sql.split("\n", 1)[1].lstrip()

    comando = sql.split(None, 1)[0].upper() if sql else ""
    sql_sem_terminador = sql.rstrip().rstrip(";")
    tokens_bloqueados = (
        " INTO OUTFILE",
        " INTO DUMPFILE",
        " FOR UPDATE",
        " LOCK IN SHARE MODE",
    )
    somente_leitura = (
        comando in COMANDOS_SOMENTE_LEITURA
        and ";" not in sql_sem_terminador
        and not any(token in f" {sql.upper()}" for token in tokens_bloqueados)
    )
    if somente_leitura:
        return

    _registrar_evento_seguranca(
        "COMANDO_ORIGEM_NAO_AUTORIZADO",
        "A conexao com involves_exclusivos permite exclusivamente consultas de leitura.",
        comando=comando or "VAZIO",
    )
    raise RuntimeError(
        "Operacao recusada: a origem BRACELL permite exclusivamente SELECT e comandos de leitura."
    )


def criar_engine_origem():
    """Cria a conexao de leitura da origem, separada do destino local."""

    host = os.environ.get("PDOH_SOURCE_DB_HOST", os.environ.get("PDOH_DB_HOST", "mysql"))
    host = str(host).strip()
    host_normalizado = host.lower()
    origem_local = host_normalizado in HOSTS_LOCAIS_AUTORIZADOS

    database_padrao = "involves_bracell" if origem_local else "involves_exclusivos"
    database = os.environ.get("PDOH_SOURCE_DB_NAME", database_padrao).strip()
    if database not in BANCOS_ORIGEM_AUTORIZADOS:
        _registrar_evento_seguranca(
            "BANCO_ORIGEM_NAO_AUTORIZADO",
            "A origem deve ser involves_bracell local ou involves_exclusivos somente leitura.",
            banco_informado=database,
        )
        raise RuntimeError(f"Banco de origem nao autorizado: '{database}'.")
    if not origem_local and database != "involves_exclusivos":
        raise RuntimeError(
            "Configuracao recusada: hosts externos podem apontar somente para involves_exclusivos."
        )

    port = int(os.environ.get("PDOH_SOURCE_DB_PORT", os.environ.get("PDOH_DB_PORT", "3306")))
    usuario = os.environ.get("PDOH_SOURCE_DB_USER") or os.environ.get("PDOH_DB_USER")
    senha_configurada = os.environ.get("PDOH_SOURCE_DB_PASSWORD") or os.environ.get(
        "PDOH_DB_PASSWORD"
    )
    if not usuario or not senha_configurada:
        raise RuntimeError(
            "Configuracao recusada: informe as credenciais da origem por variaveis de ambiente."
        )

    engine = create_engine(
        "mysql+pymysql://"
        f"{quote_plus(usuario)}:{quote_plus(senha_configurada)}@{host}:{port}/{database}"
        "?charset=utf8mb4",
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _configurar_sessao_somente_leitura(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
        finally:
            cursor.close()

    @event.listens_for(engine, "before_cursor_execute")
    def _bloquear_escrita(_conn, _cursor, statement, _parameters, _context, _executemany):
        validar_comando_somente_leitura(statement)

    return engine
