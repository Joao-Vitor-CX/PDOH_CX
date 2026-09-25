"""Projeção de leitura: nenhuma alteração de evidência, regra ou identidade."""
import hashlib
import json
import math

MAX_ALERT_RECORDS = 100_000
UF_TYPE = 'CADASTRO_UF_AUSENTE'


def uf_evidence(row):
    evidence = evidence_object(row.get('evidencia'))
    if (row.get('tipo_problema') == UF_TYPE and row.get('classificacao') == 'ALERTA'
            and evidence.get('versao_regra') == 1 and evidence.get('campo') == 'UF'):
        return evidence
    return {}


def occurrence_count(row):
    count = uf_evidence(row).get('quantidade_ocorrencias')
    if count is None:
        evidence = evidence_object(row.get('evidencia'))
        if evidence.get('campo_esperado') and 'fallback_usado' in evidence:
            count = evidence.get('ocorrencias')
    return count if type(count) is int and count > 0 else 1


def evidence_object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def evidence_fields(value):
    evidence = evidence_object(value)
    candidates = evidence.get('campo_esperado')
    if candidates is None:
        candidates = evidence.get('campo', evidence.get('campo_origem', evidence.get('coluna')))
    if candidates is None:
        candidates = [evidence.get('campo_inicio'), evidence.get('campo_fim')]
    if not isinstance(candidates, list):
        candidates = [candidates]
    return sorted({str(field) for field in candidates if isinstance(field, str) and field.strip()}) or ['Não informado']


def group_identity(row):
    # Nunca funde marcas nem supõe identidade única a partir de nome.
    # Nome+fonte é uma referência operacional explicitamente não confirmada.
    identifier = row.get('colaborador_id_interno')
    name = row.get('colaborador')
    source = row.get('tabela_origem')
    uf = uf_evidence(row)
    source_identity = uf.get('identidade_origem', {})
    if not isinstance(source_identity, dict):
        source_identity = {}
    if (uf and source_identity.get('criterio') in {'USUARIO_ORIGEM', 'NOME_NAO_CONFIRMADO'}
            and isinstance(source_identity.get('valor'), str) and source_identity['valor'].strip()):
        criterion, value = source_identity['criterio'], source_identity['valor']
    elif uf:
        criterion, value = 'REGISTRO_SEM_IDENTIDADE', row['oportunidade_id']
    elif identifier:
        criterion, value = 'ID_COLABORADOR', identifier
    elif name and name.strip():
        criterion, value = 'NOME_FONTE_NAO_CONFIRMADO', [source, name]
    else:
        reference = evidence_object(row.get('evidencia')).get('registro_afetado')
        # Só id explícito é estável; índice de DataFrame não identifica pessoa/registro.
        if isinstance(reference, str) and reference.startswith('id='):
            criterion, value = 'REGISTRO_ORIGEM', [source, reference]
        else:
            criterion, value = 'REGISTRO_SEM_IDENTIDADE', row['oportunidade_id']
    identity = [row['marca'], criterion, value]
    if uf:
        identity.append('UF')
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    return key, criterion, str(value[-1] if isinstance(value, list) else value)


def aggregate_alerts(rows, filters):
    groups = {}
    total = 0
    persisted = 0
    for index, row in enumerate(rows):
        if index >= MAX_ALERT_RECORDS:
            from fastapi import HTTPException
            raise HTTPException(422, 'Refine marca, período ou execução: limite de 100.000 registros para consolidação.')
        fields = evidence_fields(row['evidencia'])
        if filters.campo:
            fields = [field for field in fields if field.casefold() == filters.campo.casefold()]
        if not fields:
            continue
        key, criterion, reference = group_identity(row)
        group = groups.setdefault(key, dict(chave_grupo=key, marca=row['marca'], colaborador=row['colaborador'],
            colaborador_id_interno=row['colaborador_id_interno'], referencia=reference, criterio_agrupamento=criterion,
            quantidade_ocorrencias=0, quantidade_registros=0, primeira_data=None, ultima_data=None, campos={}))
        count = occurrence_count(row)
        evidence = uf_evidence(row)
        total += count
        persisted += 1
        group['quantidade_ocorrencias'] += count
        group['quantidade_registros'] += 1
        day = row['data_referencia']
        if day:
            group['primeira_data'] = min(group['primeira_data'] or day, day)
            group['ultima_data'] = max(group['ultima_data'] or day, day)
        for field in fields:
            item = group['campos'].setdefault((field, row['tipo_problema']), dict(campo=field,
                tipo=row['tipo_problema'], situacao=evidence.get('situacao') or row['titulo'] or row['tipo_problema'],
                categoria=evidence.get('categoria'), tratativa=evidence.get('tratativa'),
                quantidade_ocorrencias=0, amostra_ids=[]))
            item['quantidade_ocorrencias'] += count
            if len(item['amostra_ids']) < 3:
                item['amostra_ids'].append(row['oportunidade_id'])
    ordered = sorted(groups.values(), key=lambda group: (-group['quantidade_ocorrencias'], group['chave_grupo']))
    start = (filters.pagina - 1) * filters.tamanho
    items = ordered[start:start + filters.tamanho]
    for group in items:
        group['campos'] = sorted(group['campos'].values(), key=lambda field: (-field['quantidade_ocorrencias'], field['campo'], field['tipo']))
    return dict(items=items, total=len(groups), total_ocorrencias=total, total_registros=persisted, pagina=filters.pagina,
                tamanho=filters.tamanho, paginas=math.ceil(len(groups) / filters.tamanho))
