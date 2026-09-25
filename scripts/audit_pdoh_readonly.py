"""Audit evidence only: SELECT/SHOW on existing sources, authenticated GET on API.

Never imports or runs the ETL. Credentials stay in the existing env files.
"""
from pathlib import Path
import json, sys, datetime, urllib.request, urllib.parse
from dotenv import dotenv_values
from sqlalchemy import create_engine, URL, event, text

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/auditoria-pdoh-2026-09-25'
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
QUERIES = []

def engine(values, source=False):
    if source:
        args = dict(username=values.get('PDOH_SOURCE_DB_USER') or values.get('PDOH_DB_USER'),
                    password=values.get('PDOH_SOURCE_DB_PASSWORD') or values.get('PDOH_DB_PASSWORD'),
                    host=values.get('PDOH_SOURCE_DB_HOST', '127.0.0.1'),
                    port=int(values.get('PDOH_SOURCE_DB_PORT',3306)),
                    database=values.get('PDOH_SOURCE_DB_NAME','involves_exclusivos'))
    else:
        args = dict(username='root', password=values['MYSQL_ROOT_PASSWORD'], host='127.0.0.1',
                    port=int(values.get('PDOH_MYSQL_PORT',3307)))
    e = create_engine(URL.create('mysql+pymysql', **args), hide_parameters=True,
                     connect_args=dict(connect_timeout=8, read_timeout=30))
    @event.listens_for(e, 'connect')
    def readonly(c, _):
        with c.cursor() as cur:
            cur.execute('SET SESSION TRANSACTION READ ONLY')
            cur.execute('SET SESSION MAX_EXECUTION_TIME = 20000')
    @event.listens_for(e, 'before_cursor_execute')
    def guard(c, cur, sql, params, context, many):
        if sql.lstrip().split()[0].upper() not in ('SELECT','SHOW','DESCRIBE','EXPLAIN'):
            raise RuntimeError('Audit forbids mutations')
    return e

def query(c, sql, params=None):
    QUERIES.append(dict(sql=sql,params=params))
    return [dict(r) for r in c.execute(text(sql),params or {}).mappings()]

def safe_error(e):
    # No URL, credentials, records or SQL parameter values in errors.
    orig = getattr(e,'orig',None)
    return dict(type=type(e).__name__, code=orig.args[0] if orig and orig.args else None)

def main():
    result = dict(checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
    localvals = dotenv_values(ROOT/'.env')
    sourcevals = {**localvals, **dotenv_values(ROOT/'.env.cadastro')}
    result['configured_source'] = dict(schema=sourcevals.get('PDOH_SOURCE_DB_NAME'),
        external_host=sourcevals.get('PDOH_SOURCE_DB_HOST') not in ('mysql','localhost','127.0.0.1',None))
    for label, vals, source in [('local',localvals,False),('involves',sourcevals,True)]:
        report={}
        try:
            with engine(vals,source).connect() as c:
                report['server']=query(c,'SELECT VERSION() version, DATABASE() current_schema')
                schemas = "'involves_exclusivos','produtos'" if source else "'involves_bracell','produtos_platina','pdoh_controle'"
                report['tables']=query(c,f'SELECT TABLE_SCHEMA,TABLE_NAME,TABLE_TYPE,TABLE_ROWS FROM information_schema.TABLES WHERE TABLE_SCHEMA IN ({schemas}) ORDER BY 1,2')
                report['columns']=query(c,f'SELECT TABLE_SCHEMA,TABLE_NAME,COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY FROM information_schema.COLUMNS WHERE TABLE_SCHEMA IN ({schemas}) ORDER BY TABLE_SCHEMA,TABLE_NAME,ORDINAL_POSITION')
                report['indexes']=query(c,f'SELECT TABLE_SCHEMA,TABLE_NAME,INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA IN ({schemas}) ORDER BY 1,2,3,5')
                if not source:
                    report['platina_period']=query(c,'SELECT MIN(data) inicio,MAX(data) fim,COUNT(*) linhas,COUNT(DISTINCT colaborador) pessoas FROM produtos_platina.exclusivo_bracell_platina_relatorio_pdoh')
                    report['executions']=query(c,'SELECT execution_id,periodo_inicio,periodo_fim,status_execucao,iniciado_em FROM pdoh_controle.execucao ORDER BY iniciado_em DESC LIMIT 12')
                    report['source_lineage']=query(c,'SELECT schema_origem,tabela_origem,COUNT(*) registros,MAX(filtro_periodo_fim) ate FROM pdoh_controle.execucao_fonte GROUP BY schema_origem,tabela_origem')
                else:
                    for table,col in [('status_day_operacao_bracell','dia_referencia'),('colaboradores_ativos_bracell','data_dimensao'),('relatorio_checkin_bracell','data_roteiro'),('gerencial_visitas_bracell','data_visita'),('painel_pesquisas_bracell','data_solicitacao')]:
                        report.setdefault('source_periods',{})[table]=query(c,f'SELECT MIN(`{col}`) inicio,MAX(`{col}`) fim,COUNT(*) linhas FROM `{table}`')
        except Exception as e:
            report['error']=safe_error(e)
        result[label]=report
    av=dotenv_values(ROOT/'api/.env.api')
    for name,path in [('openapi','/openapi.json'),('resumo','/api/v2/pdoh/resumo?marca=BRACELL&periodo=automatico')]:
        try:
            req=urllib.request.Request('http://127.0.0.1:8000'+path,headers={'Authorization':'Bearer '+av['PDOH_API_TOKEN']})
            with urllib.request.urlopen(req,timeout=30) as resp:
                data=json.load(resp)
            if name=='resumo':
                # Persist counts and metrics without person records/filter names.
                for key in ['detalhes','filtros_disponiveis']:
                    data.pop(key,None)
            result[name]=data
        except Exception as e:
            result[name]={'error':safe_error(e)}
    (OUT/'live-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    (OUT/'queries.json').write_text(json.dumps(QUERIES,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:({a:b for a,b in v.items() if a not in ('tables','columns','indexes','executions','source_lineage')} if isinstance(v,dict) and k!='openapi' else 'saved') for k,v in result.items()},ensure_ascii=True,default=str))

if __name__=='__main__':
    main()
