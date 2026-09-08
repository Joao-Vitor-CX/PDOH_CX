"""Conexoes locais do PDOH_CX.

O modulo centraliza apenas a configuracao tecnica. Nenhuma regra de negocio ou
consulta da esteira BRACELL e definida aqui.
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine


def criar_engine(database: str = "involves_bracell"):
    """Cria um engine lazy usando exclusivamente as variaveis do PDOH_CX."""

    host = os.environ.get("PDOH_DB_HOST", "mysql")
    port = int(os.environ.get("PDOH_DB_PORT", "3306"))
    usuario = os.environ.get("PDOH_DB_USER", "pdoh_cx_app")
    senha = quote_plus(os.environ.get("PDOH_DB_PASSWORD", "pdoh_cx_dev"))
    return create_engine(
        f"mysql+pymysql://{usuario}:{senha}@{host}:{port}/{database}"
        "?charset=utf8mb4",
        pool_pre_ping=True,
    )
