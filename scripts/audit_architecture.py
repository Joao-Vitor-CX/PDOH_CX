"""Read-only evidence for the architecture correction; never runs the ETL."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys

from dotenv import dotenv_values
from sqlalchemy import URL, create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def engine():
    values = dotenv_values(ROOT / '.env')
    return create_engine(URL.create('mysql+pymysql', username='root',
        password=values['MYSQL_ROOT_PASSWORD'], host='127.0.0.1',
        port=int(values.get('PDOH_MYSQL_PORT', 3307))), hide_parameters=True)


def snapshot():
    report = {}
    with engine().connect() as conn:
        conn.exec_driver_sql('SET SESSION TRANSACTION READ ONLY')
        objects = conn.exec_driver_sql("SELECT TABLE_SCHEMA,TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_TYPE='BASE TABLE' AND TABLE_SCHEMA NOT IN "
            "('mysql','sys','information_schema','performance_schema') ORDER BY 1,2").all()
        report['tables'] = {}
        for schema, table in objects:
            rows = conn.exec_driver_sql(f'SELECT * FROM `{schema}`.`{table}`').mappings()
            hashes = sorted(hashlib.sha256(json.dumps(dict(row), sort_keys=True,
                default=str, ensure_ascii=False).encode()).hexdigest() for row in rows)
            report['tables'][schema+'.'+table] = dict(rows=len(hashes),
                sha256=hashlib.sha256(''.join(hashes).encode()).hexdigest())
        # regra_tratativa nao existe mais como tabela: o catalogo agora vive em codigo
        # (shared/treatment_catalog.py). Mantem a chave 'catalog' com o mesmo formato
        # para nao quebrar comparacoes de snapshot anteriores.
        from shared.treatment_catalog import listar_regras
        report['catalog'] = sorted(listar_regras(), key=lambda r: (r['marca'] or '', r['tipo_problema']))
        report['findings'] = [dict(r) for r in conn.exec_driver_sql(
            "SELECT tipo_problema,tabela_origem,COUNT(*) registros,COUNT(DISTINCT colaborador) pessoas "
            "FROM pdoh_controle.oportunidade GROUP BY 1,2").mappings()]
        report['fields'] = {}
        for kind in ('CAMPO_OBRIGATORIO_VAZIO', 'JORNADA_NAO_ENCONTRADA', 'CHECKOUT_AUSENTE'):
            counts = Counter()
            for row in conn.execute(text('SELECT tabela_origem,evidencia FROM pdoh_controle.oportunidade '
                    'WHERE tipo_problema=:kind'), dict(kind=kind)).mappings():
                ev = row['evidencia']
                ev = json.loads(ev) if isinstance(ev, str) else (ev or {})
                field = ev.get('campo_esperado', ev.get('campo', ev.get('coluna')))
                counts[str((row['tabela_origem'], field))] += 1
            report['fields'][kind] = dict(counts)
    from api.app.config import Settings
    from api.app.database import Database
    from api.app.repository import Repository
    from api.app.finding_models import GroupFilter, FindingFilter
    from api.app.findings_repository import opportunity_summary, alert_summary, finding_resumo
    db = Database(Settings.load())
    db.initialize()
    try:
        with db.connection() as conn:
            repo = Repository(conn, db.tables)
            f = dict(marca='BRACELL', periodo_inicio='2026-08-31', periodo_fim='2026-09-05', tamanho=200)
            opp = opportunity_summary(repo, GroupFilter(**f))
            alerts = alert_summary(repo, GroupFilter(**f))
            report['api'] = dict(period=f, cards=opp['total'], alert_groups=alerts['total'],
                alert_summary=alerts['resumo'], summary=finding_resumo(repo, FindingFilter(**f)),
                cards_by_rule=dict(Counter(x['tipo_problema'] for x in opp['items'])))
    finally:
        db.close()
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    result = snapshot()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print(json.dumps(dict(api=result['api'], fields=result['fields']), ensure_ascii=True, default=str))
