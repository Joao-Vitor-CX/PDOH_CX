"""Inspect official RAW/Involves metadata and aggregates using SELECT only."""
import argparse
import json
from pathlib import Path
import sys

from dotenv import dotenv_values
from sqlalchemy import URL, create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def inspect_source():
    v = dotenv_values(ROOT / '.env.cadastro')
    if not v.get('PDOH_SOURCE_DB_USER') or not v.get('PDOH_SOURCE_DB_PASSWORD'):
        return dict(status='CREDENCIAIS_AUSENTES')
    engine = create_engine(URL.create('mysql+pymysql', host=v['PDOH_SOURCE_DB_HOST'],
        port=int(v['PDOH_SOURCE_DB_PORT']), database=v['PDOH_SOURCE_DB_NAME'],
        username=v['PDOH_SOURCE_DB_USER'], password=v['PDOH_SOURCE_DB_PASSWORD']),
        hide_parameters=True, connect_args=dict(connect_timeout=10, read_timeout=60))
    try:
        with engine.connect() as c:
            c.exec_driver_sql('SET SESSION TRANSACTION READ ONLY')
            rows = c.execute(text('SELECT TABLE_NAME,COLUMN_NAME,DATA_TYPE FROM information_schema.COLUMNS '
                "WHERE TABLE_SCHEMA=:schema AND (TABLE_NAME LIKE '%bracell%') ORDER BY TABLE_NAME,ORDINAL_POSITION"),
                dict(schema=v['PDOH_SOURCE_DB_NAME'])).mappings().all()
            tables = {}
            for r in rows:
                tables.setdefault(r['TABLE_NAME'], []).append(r['COLUMN_NAME'])
            report = dict(status='OK', schema=v['PDOH_SOURCE_DB_NAME'], tables=tables, aggregates={})
            report['journey_metadata'] = [dict(r) for r in c.execute(text(
                "SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA NOT IN ('mysql','sys','information_schema','performance_schema') "
                "AND (COLUMN_NAME LIKE '%pai%' OR COLUMN_NAME LIKE '%carga%hor%' OR COLUMN_NAME LIKE '%jornada%') "
                "ORDER BY 1,2,3")).mappings()]
            report['definitions'] = {}
            for table in ('colaboradores_ativos_bracell', 'raw_exclusivo_bracell_colaboradores_ativos'):
                definition = c.exec_driver_sql(f'SHOW CREATE TABLE `{table}`').first()
                report['definitions'][table] = definition[1]
                report.setdefault('snapshots', {})[table] = [dict(r) for r in c.exec_driver_sql(
                    f'SELECT data_evolucao,MIN(data_dimensao) primeira,MAX(data_dimensao) ultima,COUNT(*) n '
                    f'FROM `{table}` GROUP BY 1 ORDER BY 1 DESC LIMIT 8').mappings()]
            for table, columns in tables.items():
                relevant = [x for x in columns if any(k in x.lower() for k in ('pai','jornada','carga_hor','perfil_acesso','usuario_ativo'))]
                if not relevant:
                    continue
                report['aggregates'][table] = {}
                for column in relevant:
                    values = c.exec_driver_sql(f'SELECT `{column}` valor,COUNT(*) n FROM `{table}` GROUP BY 1 ORDER BY 2 DESC LIMIT 40').mappings()
                    report['aggregates'][table][column] = [dict(x) for x in values]
            records = {}
            for table in ('colaboradores_ativos_bracell', 'raw_exclusivo_bracell_colaboradores_ativos'):
                fields = [x for x in tables[table] if x in {
                    'id', 'usuario', 'nome_colaborador', 'usuario_ativo', 'perfil_acesso', 'perfil_de_acesso',
                    'nome_pai', 'nome_do_pai', 'jornada_trabalho', 'jornada_de_trabalho',
                    'colaborador_superior', 'data_dimensao', 'data_evolucao'}]
                records[table] = [dict(r) for r in c.exec_driver_sql(
                    'SELECT '+','.join('`'+x+'`' for x in fields)+f' FROM `{table}`').mappings()]
            (ROOT / 'artifacts/journey-source-records.json').write_text(
                json.dumps(records, ensure_ascii=False, default=str), encoding='utf-8')
            report['checkin_missing'] = [dict(r) for r in c.execute(text(
                "SELECT tipo_checkin,COUNT(*) n,SUM(hora_entrada IS NULL) entrada_ausente, "
                "SUM(hora_saida IS NULL) saida_ausente FROM relatorio_checkin_bracell "
                "WHERE data_roteiro BETWEEN '2026-08-31' AND '2026-09-05' GROUP BY 1")).mappings()]
            return report
    except Exception as exc:
        return dict(status='ORIGEM_INDISPONIVEL', error=type(exc).__name__)
    finally:
        engine.dispose()


if __name__ == '__main__':
    result = inspect_source()
    target = ROOT / 'artifacts/journey-source-inspection.json'
    target.write_text(json.dumps(result, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, default=str))
