"""Inspeção local somente leitura. Não executa ETL, DDL, UPDATE ou bootstrap."""
import json
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy import URL, create_engine

values = dotenv_values(Path(__file__).resolve().parents[2] / '.env')
engine = create_engine(URL.create('mysql+pymysql', host='127.0.0.1',
    port=int(values.get('PDOH_MYSQL_PORT', '3307')), username=values['PDOH_DB_USER'],
    password=values['PDOH_DB_PASSWORD'], database='involves_bracell'), hide_parameters=True,
    connect_args={'connect_timeout':5, 'read_timeout':15})
try:
    with engine.connect() as conn:
        conn.exec_driver_sql('SET SESSION TRANSACTION READ ONLY')
        columns = conn.exec_driver_sql("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='involves_bracell' AND TABLE_NAME='colaboradores_ativos_bracell' ORDER BY ORDINAL_POSITION").scalars().all()
        print(json.dumps({'local_source_columns': columns}, ensure_ascii=False))
        print(json.dumps({'local_source_rows': conn.exec_driver_sql('SELECT COUNT(*) FROM involves_bracell.colaboradores_ativos_bracell').scalar()}))
finally:
    engine.dispose()
