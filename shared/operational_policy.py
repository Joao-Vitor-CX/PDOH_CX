"""Catalog-driven operational eligibility. No brand or rule-name switch."""
import json


def object_value(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def assess(rule, item):
    """Return effective class and reason without changing the historical decision."""
    exception = bool(rule.get('origem_excecao')) and rule['origem_excecao'] == item.get('tabela_origem')
    classification = rule.get('classificacao_excecao') if exception else rule.get('classificacao')
    if classification != 'OPORTUNIDADE':
        return classification, 'CATALOGO_VIGENTE'
    impact = rule.get('impacto_negocio_excecao') if exception else rule.get('impacto_negocio')
    action = rule.get('acao_recomendada_excecao') if exception else rule.get('acao_recomendada')
    if not all((impact, action, rule.get('responsavel_padrao'), item.get('colaborador') or item.get('colaborador_id_interno'))):
        return 'ALERTA', 'SEM_IMPACTO_RESPONSAVEL_OU_ACAO'
    evidence = object_value(item.get('evidencia'))
    criteria = object_value(rule.get('criterios_operacionais'))
    for key, expected in criteria.get('evidencia', {}).items():
        actual = evidence.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return 'ALERTA', 'IMPACTO_NAO_COMPROVADO'
        elif actual != expected:
            return 'ALERTA', 'IMPACTO_NAO_COMPROVADO'
    return 'OPORTUNIDADE', 'IMPACTO_RESPONSAVEL_E_ACAO'
