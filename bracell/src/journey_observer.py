"""Official source observation. Reads selected columns and writes only control data."""
import json
import re
from sqlalchemy import text
from shared.journey import resolve


def _identifier(name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('Identificador de fonte invalido')
    return '`' + name + '`'


def resolve_official(engine, source_engine, *, brand='BRACELL', operation='EXCLUSIVA', as_of=None):
    with engine.connect() as c:
        config = c.execute(text('SELECT fontes_jornada,perfis_operacionais FROM pdoh_controle.configuracao_operacao '
            'WHERE marca=:brand AND operacao=:operation'), dict(brand=brand, operation=operation)).mappings().one()
    configs = config['fontes_jornada']
    configs = json.loads(configs) if isinstance(configs, str) else configs
    profiles = config['perfis_operacionais']
    profiles = json.loads(profiles) if isinstance(profiles, str) else profiles
    sources = {}
    with source_engine.connect() as c:
        for source in configs:
            fields = {'id','usuario','nome_colaborador','usuario_ativo','data_evolucao','data_dimensao',
                      source['campo_horas'],source['campo_perfil'],source['campo_jornada']}
            query = 'SELECT '+','.join(_identifier(x) for x in sorted(fields))+' FROM '+_identifier(source['tabela'])
            rows = c.execute(text(query+' LIMIT 100001')).mappings().all()
            if len(rows) > 100000:
                raise ValueError('Fonte excede limite de resolucao completa')
            sources[source['tabela']] = [dict(r) for r in rows]
    return resolve(sources, configs, brand=brand, operation=operation, profiles=profiles, as_of=as_of)


def persist(engine, resolutions, execution_id=None):
    with engine.begin() as c:
        for row in resolutions:
            params = {**row, 'execution_id': execution_id, 'evidencia': json.dumps(row['evidencia'], default=str)}
            if execution_id:
                import hashlib
                params['resolucao_id'] = hashlib.sha256((row['resolucao_id']+execution_id).encode()).hexdigest()
            columns = list(params)
            values = ['CAST(:evidencia AS JSON)' if x == 'evidencia' else ':'+x for x in columns]
            c.execute(text('INSERT IGNORE INTO pdoh_controle.jornada_consolidada ('+','.join(columns)+') VALUES ('+
                ','.join(values)+')'), params)
