"""Dry-run de cadastro. So SELECT; nao importa ETL, nao persiste nem semeia regras.

python scripts/simulate-cadastral-alerts.py --env-file CAMINHO_LOCAL
O JSON de saida contem dados cadastrais: nao publicar em logs/artefatos publicos.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
import pandas as pd
from sqlalchemy import URL, create_engine, event, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bracell"))
from src.cadastral_alerts import avaliar_uf_ausente, FONTES_CADASTRO
from src.database import validar_comando_somente_leitura

MAX_ROWS = 100_000


def configuration(path):
    # Sem fallback para credenciais do destino local ou banco de escrita.
    values = {**dotenv_values(path), **os.environ}
    keys = ("PDOH_SOURCE_DB_HOST", "PDOH_SOURCE_DB_PORT", "PDOH_SOURCE_DB_NAME",
        "PDOH_SOURCE_DB_USER", "PDOH_SOURCE_DB_PASSWORD", "PDOH_CADASTRO_SOURCE_TABLE")
    missing = [key for key in keys if not values.get(key)]
    if missing:
        raise ValueError("Configuracao incompleta: " + ", ".join(missing))
    if values["PDOH_SOURCE_DB_NAME"] != "involves_exclusivos":
        raise ValueError("Esta simulacao requer a origem involves_exclusivos, sem redirecionamento automatico.")
    if values["PDOH_CADASTRO_SOURCE_TABLE"] not in FONTES_CADASTRO:
        raise ValueError("Tabela de cadastro fora do escopo autorizado.")
    return values


def simulate(values):
    schema, table = values["PDOH_SOURCE_DB_NAME"], values["PDOH_CADASTRO_SOURCE_TABLE"]
    engine = create_engine(URL.create("mysql+pymysql", host=values["PDOH_SOURCE_DB_HOST"],
        port=int(values["PDOH_SOURCE_DB_PORT"]), database=schema,
        username=values["PDOH_SOURCE_DB_USER"], password=values["PDOH_SOURCE_DB_PASSWORD"]),
        hide_parameters=True, connect_args={"connect_timeout": 5, "read_timeout": 30})

    @event.listens_for(engine, "connect")
    def readonly(connection, _):
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")

    @event.listens_for(engine, "before_cursor_execute")
    def guard(_conn, _cursor, statement, _parameters, _context, _many):
        validar_comando_somente_leitura(statement)

    try:
        with engine.connect() as conn:
            columns = conn.execute(text("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=:schema AND TABLE_NAME=:table ORDER BY ORDINAL_POSITION"),
                dict(schema=schema, table=table)).scalars().all()
            report = dict(modo="SOMENTE_LEITURA", origem=dict(banco=schema, tabela=table,
                marca="BRACELL", criterio_marca="Tabela exclusiva BRACELL; coluna marca validada quando presente",
                colunas=columns), registros_alterados=0, classificacao_proposta="ALERTA",
                categoria="QUALIDADE_CADASTRAL", impacto_oportunidades_operacionais=0)
            lookup = {column.strip().lower(): column for column in columns}
            required = {"nome_colaborador", "usuario_ativo", "data_evolucao", "data_dimensao"}
            if not required.issubset(lookup) or not {"uf", "estado"}.intersection(lookup):
                report.update(status="SCHEMA_REQUER_VALIDACAO", quantidade_proposta=None)
                return report
            selected = sorted((required | {"usuario", "uf", "estado", "marca"}).intersection(lookup))
            projection = ", ".join('`' + lookup[key].replace('`', '``') + '`' for key in selected)
            frame = pd.read_sql_query(text(f"SELECT {projection} FROM `{schema}`.`{table}` LIMIT {MAX_ROWS + 1}"), conn)
            if len(frame) > MAX_ROWS:
                report.update(status="LIMITE_DE_LEITURA_EXCEDIDO", quantidade_proposta=None)
                return report
            frame = frame.rename(columns={lookup[key]: key for key in selected})
            result = avaliar_uf_ausente(frame, tabela_origem=table)
            report.update(result)
            blocked = result["diagnostico"].get("motivo")
            if not blocked and (result["diagnostico"].get("grupos_sem_data_referencia")
                    or result["diagnostico"].get("datas_evolucao_invalidas")):
                blocked = "ANALISE_PARCIAL_DATAS_INVALIDAS"
            report.update(status=blocked or "SIMULACAO_PENDENTE_APROVACAO",
                quantidade_proposta=None if blocked else len(result["alertas"]))
            return report
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error("Arquivo local de configuracao nao encontrado.")
    try:
        values = configuration(args.env_file)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        print(json.dumps(simulate(values), ensure_ascii=True, default=str, indent=2))
    except Exception as exc:
        # Nao imprimir URL, credenciais, parametros SQL ou stack trace de conexao.
        print(json.dumps(dict(status="ORIGEM_INDISPONIVEL", erro_tipo=type(exc).__name__,
            registros_alterados=0)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
