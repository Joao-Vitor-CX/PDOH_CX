"""Explicit weekly-hours resolution over official snapshots; never guesses from labels."""
import hashlib
import json
import math
import re


def value(v):
    if v is None or str(v).strip().lower() in ('', 'nan', 'nat', 'none'):
        return None
    return str(v).strip()


def weekly_hours(v):
    raw = value(v)
    if not raw or not re.fullmatch(r'\d{1,3}(?:[.,]\d+)?\s*(?:h|horas)?', raw, re.I):
        return None
    number = float(re.sub(r'\s*(h|horas)$', '', raw, flags=re.I).replace(',', '.'))
    return number if math.isfinite(number) and 0 < number <= 168 else None


def date_value(v):
    raw = value(v)
    return raw[:10] if raw and re.match(r'^\d{4}-\d{2}-\d{2}', raw) else None


def identity(row):
    return value(row.get('usuario')) or value(row.get('id')) or value(row.get('nome_colaborador'))


def snapshot(records, as_of=None):
    """Latest complete extraction as of the reference, then most recent row per identity."""
    valid = [r for r in records if date_value(r.get('data_evolucao'))
             and (not as_of or (date_value(r.get('data_dimensao')) or '9999') <= as_of)]
    if not valid:
        return []
    latest = max(date_value(r['data_evolucao']) for r in valid)
    rows = [r for r in valid if date_value(r['data_evolucao']) == latest]
    grouped = {}
    for r in rows:
        if identity(r):
            grouped.setdefault(identity(r), []).append(r)
    result = []
    for candidates in grouped.values():
        recent = max(date_value(r.get('data_dimensao')) or '' for r in candidates)
        result.extend(r for r in candidates if (date_value(r.get('data_dimensao')) or '') == recent)
    return result


def resolve(sources, configs, *, brand, operation, profiles, as_of=None, complete=True):
    """Priority is explicit; incompatible hours are a cadastral conflict, never 'missing'."""
    configs = sorted(configs, key=lambda c: c['prioridade'])
    current = {c['tabela']: snapshot(sources.get(c['tabela'], []), as_of) for c in configs}
    primary = configs[0]
    people = {}
    for row in current[primary['tabela']]:
        people.setdefault(identity(row), row)
    result = []
    for key, row in people.items():
        reference = date_value(row.get('data_dimensao'))
        active = (value(row.get('usuario_ativo')) or '').lower() == 'sim'
        profile = value(row.get(primary['campo_perfil']))
        eligible = active and profile in profiles and row.get('nome_colaborador') != 'TESTE (NÃO INATIVAR)'
        candidates, examined = [], []
        for config in configs:
            table = config['tabela']
            matches = [r for r in current[table] if identity(r) == key]
            for match in matches:
                # A stale snapshot cannot resurrect a superseded contract.
                fresh = bool(reference and date_value(match.get('data_dimensao'))
                             and date_value(match.get('data_dimensao')) >= reference)
                raw = match.get(config['campo_horas'])
                hours = weekly_hours(raw) if fresh else None
                examined.append(dict(fonte=table, campo=config['campo_horas'], valor=value(raw),
                    data_referencia=date_value(match.get('data_dimensao')), vigente=fresh))
                if hours is not None:
                    candidates.append(dict(horas=hours, fonte=table, campo=config['campo_horas']))
        chosen = candidates[0] if candidates else {}
        conflict = len({c['horas'] for c in candidates}) > 1
        status = ('FORA_ESCOPO' if not eligible else 'CONFLITO' if conflict else 'RESOLVIDA' if chosen
                  else 'NAO_ENCONTRADA' if complete else 'RESOLUCAO_INCOMPLETA')
        evidence = dict(fontes_verificadas=examined, fontes_configuradas=[c['tabela'] for c in configs],
            resolucao_completa=complete, vigente=active, perfil_elegivel=eligible,
            campo_esperado='jornada_semanal', conflito=conflict,
            jornada_cadastral=value(row.get(primary.get('campo_jornada', ''))))
        item = dict(marca=brand, operacao=operation, colaborador_chave=key,
            colaborador=value(row.get('nome_colaborador')), usuario_origem=value(row.get('usuario')),
            data_referencia=reference, perfil=profile, vigente=active, elegivel=eligible,
            jornada_semanal=chosen.get('horas'), fonte=chosen.get('fonte'), campo=chosen.get('campo'),
            status_resolucao=status, evidencia=evidence)
        item['resolucao_id'] = hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()
        result.append(item)
    return result
