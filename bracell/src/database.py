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

from sqlalchemy import create_engine


HOSTS_LOCAIS_AUTORIZADOS = frozenset({"mysql", "localhost", "127.0.0.1"})


def validar_host_local(host: str) -> str:
    """Aceita somente os endpoints locais previstos para o PDOH_CX."""

    host_normalizado = str(host).strip().lower()
    if host_normalizado in HOSTS_LOCAIS_AUTORIZADOS:
        return host_normalizado

    evento = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "nivel": "CRITICO",
        "categoria": "SEGURANCA",
        "codigo": "CONEXAO_BANCO_NAO_AUTORIZADA",
        "host_informado": host_normalizado,
        "mensagem": "O ambiente PDOH_CX aceita somente hosts locais autorizados.",
    }
    print(json.dumps(evento, ensure_ascii=False, sort_keys=True), file=sys.stderr, flush=True)
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
