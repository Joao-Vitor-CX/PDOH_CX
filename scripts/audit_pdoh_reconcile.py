"""Read-only numerical audit with isolated, no-database legacy replay.

The replay verifies operational lineage, NOT independent correctness of legacy rules.
Independent SQL aggregates verify API arithmetic. No operational writes or observers.
"""
from audit_pdoh_readonly import ROOT, OUT, engine, query, safe_error, QUERIES
from dotenv import dotenv_values
import pandas as pd
import os, sys, types, tempfile, shutil, runpy, json, io, contextlib, warnings, hashlib
from collections import Counter
from pathlib import Path
from unittest.mock import patch

SOURCES = {'relatorio_de_operacao':('status_day_operacao_bracell','dia_referencia'),
           'colaboradores':('colaboradores_ativos_bracell',None),
           'checkin':('relatorio_checkin_bracell','data_roteiro'),
           'gerencial_de_visitas':('gerencial_visitas_bracell','data_visita'),
           'pesquisas':('painel_pesquisas_bracell','data_solicitacao')}
TIMES=['produtividade','ocio','deslocamento','horas_nao_registradas','horas_programadas']
COUNTS=['visitas_diarias','visitas_diarias_realizadas','pesquisas_diarias','pesquisas_diarias_realizadas']

def seconds(v):
    if pd.isna(v) or v=='': return 0
    return int(pd.to_timedelta(v).total_seconds())

def summary(df):
    sums={k:sum(seconds(v) for v in df[k]) for k in TIMES}
    sums.update({k:float(pd.to_numeric(df[k],errors='coerce').fillna(0).sum()) for k in COUNTS})
    hp=sums['horas_programadas']
    sums['pdoh']=round(100*sums['produtividade']/hp,4) if hp else None
    sums['efetividade']=round((sums['pdoh']*40 + (100*sums[COUNTS[1]]/sums[COUNTS[0]] if sums[COUNTS[0]] else 0)*30 + (100*sums[COUNTS[3]]/sums[COUNTS[2]] if sums[COUNTS[2]] else 0)*30)/100,4) if hp else None
    return dict(rows=len(df),people=int(df.colaborador.nunique()),days=int(df.data.nunique()),sums=sums)

def keyframe(df):
    df=df.copy()
    df['data']=pd.to_datetime(df['data']).dt.strftime('%Y-%m-%d')
    df['colaborador']=df['colaborador'].astype(str).str.upper().str.split().str.join(' ')
    return df.set_index(['colaborador','data'])

def main():
    vals=dotenv_values(ROOT/'.env')
    sv={**vals,**dotenv_values(ROOT/'.env.cadastro')}
    remote,local=engine(sv,True),engine(vals)
    sys.path.insert(0,str(ROOT/'bracell'))
    from src.data_loader import cadastro_do_periodo,deduplicar_pesquisas
    from src.alch import filtrar_vinculo_do_dia
    reports=[]
    for start,end in [('2026-08-31','2026-09-05'),('2026-09-21','2026-09-22')]:
        record=dict(start=start,end=end,source_counts={})
        frames={}
        with remote.connect() as c:
            for name,(table,col) in SOURCES.items():
                sql=f'SELECT * FROM `{table}`'
                if col: sql+=f' WHERE DATE(`{col}`) BETWEEN :start AND :end'
                if name=='pesquisas':sql+=' AND DATE(data_expiracao) BETWEEN :start AND :end'
                rows=query(c,sql,dict(start=start,end=end))
                df=pd.DataFrame(rows)
                raw=len(df)
                if name!='colaboradores':
                    df=df.drop_duplicates(subset=[k for k in df.columns if k not in ('data_dimensao','data_evolucao')])
                    if name=='pesquisas':df=deduplicar_pesquisas(df)
                frames[name]=df
                record['source_counts'][name]=dict(raw=raw,treated=len(df))
            # Gold is comparison ONLY. Never passed to the replay loader.
            try:
                gold=pd.DataFrame(query(c,'SELECT * FROM produtos.exclusivo_bracell_gold_relatorio_pdoh WHERE data BETWEEN :start AND :end',dict(start=start,end=end)))
                record['gold']=summary(gold) if len(gold) else {'rows':0}
            except Exception as e:record['gold']={'error':safe_error(e)}
        frames['colaboradores'],cad=cadastro_do_periodo(frames['colaboradores'],start,end)
        record['cadastro']=dict(people=len(frames['colaboradores']),snapshots=cad.get('extracoes'))
        with local.connect() as c:
            persisted=pd.DataFrame(query(c,'SELECT * FROM produtos_platina.exclusivo_bracell_platina_relatorio_pdoh WHERE data BETWEEN :start AND :end',dict(start=start,end=end)))
            record['platina']=summary(persisted)
            metrics=','.join(f'SUM(TIME_TO_SEC(`{k}`)) AS `{k}`' for k in TIMES)
            record['independent_sql']=query(c,f'SELECT COUNT(*) n,{metrics} FROM produtos_platina.exclusivo_bracell_platina_relatorio_pdoh WHERE data BETWEEN :start AND :end',dict(start=start,end=end))
        captured=[]
        loader=types.ModuleType('src.data_loader')
        loader.carregar_dados_involves=lambda **kw:({k:v.copy(deep=True) for k,v in frames.items()},None)
        sink=types.ModuleType('src.alch')
        def capture(df,engine,**kw):
            filtered,removed=filtrar_vinculo_do_dia(df,cad.get('ativos_por_dia') or {})
            captured.append(filtered.copy(deep=True))
            record['excluded_inactive_days']=len(removed)
        sink.inserir_produto=capture
        oldcwd,oldargv=os.getcwd(),sys.argv[:]
        # Temp directory holds any generated spreadsheets; existing outputs untouched.
        with tempfile.TemporaryDirectory(prefix='pdoh_audit_') as tmp:
            shutil.copytree(ROOT/'bracell/bases_fixas',Path(tmp)/'bases_fixas')
            os.chdir(tmp)
            sys.argv=['audit',start,end]
            log=io.StringIO()
            try:
                with patch.dict(sys.modules,{'src.data_loader':loader,'src.alch':sink}), \
                     patch('sqlalchemy.create_engine',side_effect=RuntimeError('No DB in replay')), \
                     patch('socket.socket.connect',side_effect=RuntimeError('No network in replay')), \
                     contextlib.redirect_stdout(log),contextlib.redirect_stderr(log),warnings.catch_warnings():
                    warnings.simplefilter('ignore')
                    runpy.run_path(str(ROOT/'bracell/pdoh_bracell_sem_atestados_e_declaracoes_medicas.py'),run_name='__main__')
            except BaseException as e:
                record['replay_exception']=safe_error(e)
            finally:os.chdir(oldcwd);sys.argv=oldargv
            record['replay_log_sha256']=hashlib.sha256(log.getvalue().encode()).hexdigest()
            if not captured:
                errfile=Path(tmp)/'Erro na automação.txt'
                errtext=errfile.read_text(errors='replace') if errfile.exists() else ''
                record['replay_error']=errtext[-1600:] if errtext else 'No captured result; see runtime compatibility.'
        if captured:
            replay=pd.concat(captured,ignore_index=True)
            record['replay']=summary(replay)
            a,b=keyframe(persisted),keyframe(replay)
            common=a.index.intersection(b.index)
            record['comparison']=dict(common=len(common),only_platina=len(a.index.difference(b.index)),only_replay=len(b.index.difference(a.index)),differences={})
            for col in TIMES+COUNTS:
                av=a.loc[common,col].map(seconds) if col in TIMES else pd.to_numeric(a.loc[common,col],errors='coerce').fillna(0)
                bv=b.loc[common,col].map(seconds) if col in TIMES else pd.to_numeric(b.loc[common,col],errors='coerce').fillna(0)
                diff=av-bv
                record['comparison']['differences'][col]=dict(rows=int((diff.abs()>0.01).sum()),delta=float(diff.sum()))
        reports.append(record)
        (OUT/'reconciliation.json').write_text(json.dumps(reports,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
        print(json.dumps(record,ensure_ascii=True,default=str),flush=True)
    (OUT/'reconciliation-queries.json').write_text(json.dumps(QUERIES,indent=2,ensure_ascii=False,default=str),encoding='utf-8')

if __name__=='__main__':main()
