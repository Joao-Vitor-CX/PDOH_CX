"""Read-only SQL/API checks. Persists aggregate evidence only, no collaborator identities."""
import datetime
import json
import urllib.parse
import urllib.request
from dotenv import dotenv_values
from audit_pdoh_readonly import ROOT, OUT, engine, query, safe_error, QUERIES

TIMES = ['produtividade', 'ocio', 'deslocamento', 'horas_nao_registradas', 'horas_programadas']
COUNTS = ['visitas_diarias', 'visitas_diarias_realizadas', 'pesquisas_diarias', 'pesquisas_diarias_realizadas']
PCTS = ['percentual_produtividade', 'percentual_visitas', 'percentual_pesquisas', 'percentual_efetividade']
WINDOWS = [('2026-08-31', '2026-09-05'), ('2026-09-21', '2026-09-22')]


def profile(c, table, start, end):
    params = {'inicio': start, 'fim': end}
    where = ' WHERE data BETWEEN :inicio AND :fim'
    sums = ', '.join(f'SUM(COALESCE(TIME_TO_SEC({n}),0)) {n}_segundos' for n in TIMES)
    sums += ', ' + ', '.join(f'SUM(COALESCE({n},0)) {n}' for n in COUNTS)
    base = 'COUNT(*) linhas, COUNT(DISTINCT colaborador) colaboradores, COUNT(DISTINCT data) dias, ' + sums
    out = {'total': query(c, f'SELECT {base} FROM {table}{where}', params)[0]}
    out['por_data_estado'] = query(c, f'SELECT data, estado, {base} FROM {table}{where} GROUP BY data, estado ORDER BY data, estado', params)
    tests = []
    for n in TIMES:
        tests += [f'SUM({n} IS NULL) {n}_nulos', f'SUM(TIME_TO_SEC({n}) < 0) {n}_negativos']
    for n in PCTS:
        tests += [f'MIN({n}) {n}_min', f'MAX({n}) {n}_max', f'SUM({n} IS NULL) {n}_nulos', f'SUM({n}<0 OR {n}>100) {n}_fora_0_100', f'SUM({n}<0 OR {n}>1) {n}_fora_fracao_0_1']
    components = '+'.join(f'COALESCE(TIME_TO_SEC({n}),0)' for n in TIMES[:-1])
    delta = f'({components}-COALESCE(TIME_TO_SEC(horas_programadas),0))'
    tests += [f'SUM({delta}<>0) fechamento_divergente_linhas', f'SUM({delta}) fechamento_delta_segundos', f'MIN({delta}) fechamento_delta_min', f'MAX({delta}) fechamento_delta_max', 'SUM(TIME_TO_SEC(horas_programadas)=0) jornada_zero']
    out['qualidade'] = query(c, f'SELECT {", ".join(tests)} FROM {table}{where}', params)[0]
    reason = "CASE DAYOFWEEK(data) WHEN 2 THEN justificativas_seg WHEN 3 THEN justificativas_ter WHEN 4 THEN justificativas_qua WHEN 5 THEN justificativas_qui WHEN 6 THEN justificativas_sex WHEN 7 THEN justificativas_sab ELSE NULL END"
    out['fechamento_contexto'] = query(c, f'SELECT COUNT(*) linhas, SUM(({components})=0) componentes_zerados, SUM(primeiro_checkin IS NULL) sem_checkin, SUM(ultimo_checkout IS NULL) sem_checkout, SUM(NULLIF(TRIM({reason}),\'\') IS NOT NULL) justificativa_preenchida, SUM(TIME_TO_SEC(horas_programadas)) programadas_segundos FROM {table}{where} AND {delta}<>0', params)[0]
    status = f"CASE WHEN NULLIF(TRIM({reason}),'') IS NOT NULL THEN 'DESCONSIDERADO' WHEN primeiro_checkin IS NULL AND COALESCE(visitas_diarias,0)=0 THEN 'SEM_ATIVIDADE_PREVISTA' ELSE 'CONSIDERADO' END"
    out['denominador_por_validacao_sql'] = query(c, f'SELECT {status} status_validacao, COUNT(*) linhas, SUM({delta}<0) deficit_linhas, SUM(TIME_TO_SEC(horas_programadas)) programadas_segundos, SUM(CASE WHEN {delta}<0 THEN -{delta} ELSE 0 END) deficit_segundos, SUM(TIME_TO_SEC(produtividade)) produtividade_segundos FROM {table}{where} GROUP BY status_validacao', params)
    out['deficit_grupos'] = query(c, f'SELECT {status} status_validacao, (COALESCE(visitas_diarias,0)=0) sem_visitas, (primeiro_checkin IS NULL) sem_checkin, (horas_nao_registradas IS NULL) hnr_nulas, (produtividade IS NULL) produtividade_nula, COUNT(*) linhas, SUM(TIME_TO_SEC(horas_programadas)) programadas_segundos, SUM(-{delta}) deficit_segundos FROM {table}{where} AND {delta}<0 GROUP BY status_validacao,sem_visitas,sem_checkin,hnr_nulas,produtividade_nula', params)
    out['duplicacao'] = query(c, f'SELECT COUNT(*) chaves_duplicadas, COALESCE(SUM(n-1),0) linhas_excedentes FROM (SELECT COUNT(*) n FROM {table}{where} GROUP BY colaborador,data HAVING COUNT(*)>1) d', params)[0]
    t = out['total']
    denom = float(t['horas_programadas_segundos'] or 0)
    ratios = {n: round(100 * float(t[n+'_segundos'] or 0)/denom, 4) if denom else None for n in TIMES[:-1]}
    for n, actual in [('visitas', 'visitas_diarias'), ('pesquisas', 'pesquisas_diarias')]:
        ratios[n] = round(100 * float(t[actual+'_realizadas'] or 0)/float(t[actual]), 4) if t[actual] else None
    ratios['efetividade'] = round((ratios['produtividade']*40+(ratios['visitas'] or 0)*30+(ratios['pesquisas'] or 0)*30)/100, 4) if denom else None
    out['razoes_sql'] = ratios
    return out


def api_read(start, end):
    av = dotenv_values(ROOT/'api/.env.api')
    path = '/api/v2/pdoh/resumo?' + urllib.parse.urlencode(dict(marca='BRACELL',operacao='EXCLUSIVA',periodo='personalizado',periodo_inicio=start,periodo_fim=end,tamanho=1))
    req = urllib.request.Request('http://127.0.0.1:8000'+path, headers={'Authorization': 'Bearer '+av['PDOH_API_TOKEN']})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.load(response)
    data.pop('detalhes',None)
    data.pop('filtros_disponiveis',None)
    return {'path':path,'response':data}


def main():
    vals = dotenv_values(ROOT/'.env')
    sv = {**vals, **dotenv_values(ROOT/'.env.cadastro')}
    result = {'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'method':'SELECT/EXPLAIN only; ratios of SUM components, 40/30/30 effectiveness; Gold comparison only; no PII persisted', 'windows':{}}
    for start,end in WINDOWS:
        key = start+'..'+end
        report = {}
        for label, settings, source, table in [('platina', vals, False, 'produtos_platina.exclusivo_bracell_platina_relatorio_pdoh'),('gold_referencia', sv, True, 'produtos.exclusivo_bracell_gold_relatorio_pdoh')]:
            try:
                with engine(settings,source).connect() as c:
                    report[label] = profile(c,table,start,end)
            except Exception as e:
                report[label] = {'error':safe_error(e)}
        try:
            report['api'] = api_read(start,end)
            raw = report['api']['response']
            observed = {k:(raw.get('indicadores') or {}).get(k,{}).get('valor') for k in TIMES[:-1]}
            observed['pdoh'] = raw.get('percentual')
            observed['efetividade'] = (raw.get('efetividade') or {}).get('valor')
            expected = {**report['platina']['razoes_sql'], 'pdoh':report['platina']['razoes_sql']['produtividade']}
            report['api_menos_sql_pp'] = {k:round(v-expected[k],8) if v is not None and expected[k] is not None else None for k,v in observed.items()}
        except Exception as e:
            report['api_error'] = safe_error(e)
        if 'razoes_sql' in report.get('gold_referencia',{}) and 'razoes_sql' in report.get('platina',{}):
            p=report['platina']['razoes_sql'];g=report['gold_referencia']['razoes_sql']
            report['gold_menos_platina_pp'] = {k:round(g[k]-p[k],4) if p[k] is not None and g[k] is not None else None for k in p}
            report['gold_sobre_platina_componentes'] = {k:round(g[k]/p[k],6) if p[k] and g[k] is not None else None for k in TIMES[:-1]}
        result['windows'][key] = report
    try:
        with engine(sv,True).connect() as c:
            a='DATE(data_solicitacao) BETWEEN :inicio AND :fim'
            b='DATE(data_expiracao) BETWEEN :inicio AND :fim'
            overlap='DATE(data_solicitacao)<=:fim AND DATE(data_expiracao)>=:inicio'
            result['source_research_windows'] = {}
            for start,end in WINDOWS:
                result['source_research_windows'][start+'..'+end] = query(c, f'SELECT COUNT(DISTINCT CASE WHEN ({a}) AND ({b}) THEN id END) ambas_dentro_AND, COUNT(DISTINCT CASE WHEN ({a}) OR ({b}) THEN id END) uma_dentro_OR, COUNT(DISTINCT CASE WHEN {overlap} THEN id END) intersecao_intervalos, COUNT(DISTINCT CASE WHEN {a} THEN id END) solicitadas_no_periodo, COUNT(DISTINCT CASE WHEN ({a}) AND ({b}) AND data_conclusao IS NOT NULL THEN id END) ambas_dentro_com_conclusao FROM involves_exclusivos.painel_pesquisas_bracell', {'inicio':start,'fim':end})
    except Exception as e:
        result['research_error'] = safe_error(e)
    try:
        with engine(vals).connect() as c:
            result['indexes'] = query(c,"SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='produtos_platina' AND TABLE_NAME='exclusivo_bracell_platina_relatorio_pdoh' ORDER BY INDEX_NAME,SEQ_IN_INDEX")
            result['explain_range'] = query(c,'EXPLAIN SELECT data,produtividade,ocio,deslocamento,horas_nao_registradas,horas_programadas FROM produtos_platina.exclusivo_bracell_platina_relatorio_pdoh WHERE data BETWEEN :inicio AND :fim',{'inicio':WINDOWS[0][0],'fim':WINDOWS[0][1]})
    except Exception as e:
        result['index_error'] = safe_error(e)
    result['queries'] = QUERIES
    (OUT/'integrity.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'output':'integrity.json','windows':{k:{'sql':v.get('platina',{}).get('razoes_sql'),'rows':v.get('platina',{}).get('total',{}).get('linhas'),'api_minus_sql':v.get('api_menos_sql_pp'),'gold_composition_ratio':v.get('gold_sobre_platina_componentes'),'errors':{a:b['error'] for a,b in v.items() if isinstance(b,dict) and 'error' in b}} for k,v in result['windows'].items()}},default=str))


if __name__ == '__main__':
    main()

