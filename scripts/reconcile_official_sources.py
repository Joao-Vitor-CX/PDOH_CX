"""Reconcile official read-only source against control history. No PDOH/ETL run."""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

from dotenv import dotenv_values
from sqlalchemy import URL, create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'bracell'))
from audit_architecture import engine
from shared.geography import valid_state
from src.journey_observer import resolve_official, persist


def main():
    from src.database import criar_engine_origem
    import os
    values = dotenv_values(ROOT / '.env.cadastro')
    os.environ.update({k: v for k, v in values.items() if v is not None})
    source, local = criar_engine_origem(), engine()
    with source.connect() as c:
        records = c.execute(text("SELECT colaborador,data_roteiro,tipo_checkin,hora_entrada,"
            "hora_saida,checkout_sistema,checkout_registrado FROM relatorio_checkin_bracell "
            "WHERE data_roteiro BETWEEN '2026-08-01' AND '2026-09-18' AND hora_entrada IS NULL")).mappings().all()
    missing = defaultdict(set)
    for r in records:
        missing[(r['colaborador'], str(r['data_roteiro'])[:10])].add((r['tipo_checkin'] or '').strip().lower())
    resolutions = resolve_official(local, source)
    persist(local, resolutions)
    historical = resolve_official(local, source, as_of='2026-09-05')
    persist(local, historical)
    stats = Counter()
    with local.begin() as c:
        rows = c.execute(text("SELECT o.* FROM pdoh_controle.oportunidade o "
            "WHERE marca='BRACELL' AND tipo_problema IN ('CAMPO_OBRIGATORIO_VAZIO','DADO_FORA_DO_PADRAO') "
            "AND NOT EXISTS (SELECT 1 FROM pdoh_controle.execucao_contexto x WHERE x.execution_id=o.execution_id "
            "AND x.finalidade='VALIDACAO')")).mappings().all()
        inserts = []
        for row in rows:
            evidence = json.loads(row['evidencia']) if isinstance(row['evidencia'], str) else row['evidencia'] or {}
            field = evidence.get('campo',evidence.get('campo_esperado'))
            reason = None
            if row['tipo_problema'] == 'CAMPO_OBRIGATORIO_VAZIO' and field == 'hora_entrada':
                matches = missing.get((row['colaborador'],str(row['data_referencia'])[:10]))
                if matches == {'sem checkin'}:
                    reason = 'Entrada nao se aplica: fonte oficial confirma exclusivamente Sem Checkin para colaborador/data.'
            if row['tipo_problema'] == 'DADO_FORA_DO_PADRAO' and field in ('uf','estado') and valid_state(evidence.get('valor')):
                reason = 'Nome de estado brasileiro valido; detector anterior exigia indevidamente apenas duas letras.'
            if reason:
                proof = dict(regra_validacao='arquitetura-v1', fonte=row['tabela_origem'], campo=field,
                    valor=evidence.get('valor'), data_referencia=str(row['data_referencia']),
                    criterio='Consulta oficial somente leitura e validacao de dominio', motivo=reason)
                key = hashlib.sha256((row['oportunidade_id']+reason).encode()).hexdigest()
                inserts.append(dict(key=key, id=row['oportunidade_id'], execution_id=row['execution_id'],
                    brand=row['marca'], reason=reason, evidence=json.dumps(proof,ensure_ascii=False)))
                stats[row['tipo_problema']] += 1
        if inserts:
            c.execute(text("INSERT IGNORE INTO pdoh_controle.achado_revisao "
                "(chave_validacao,registro_id,origem_registro,execution_id,marca,operacao,classificacao,motivo,evidencia) "
                "VALUES (:key,:id,'oportunidade',:execution_id,:brand,'EXCLUSIVA','TELEMETRIA',:reason,CAST(:evidence AS JSON))"), inserts)
    report = dict(consultas_origem='SOMENTE_LEITURA', revisoes=dict(stats),
        jornada_atual=dict(total=len(resolutions),elegiveis=sum(r['elegivel'] for r in resolutions),
            status=dict(Counter(r['status_resolucao'] for r in resolutions)),
            horas=dict(Counter(str(r['jornada_semanal']) for r in resolutions if r['elegivel']))),
        jornada_periodo=dict(total=len(historical), elegiveis=sum(r['elegivel'] for r in historical),
            status=dict(Counter(r['status_resolucao'] for r in historical))))
    (ROOT / 'artifacts/official-reconciliation.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True))


if __name__ == '__main__':
    main()
