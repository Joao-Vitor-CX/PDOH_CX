"""Diagnóstico de impacto por campo; não reclassifica catálogo nem histórico."""
from .alerts import evidence_fields, evidence_object


def assess_field(field, status=None):
    impacts = {
        'responsavel': 'Usado no agrupamento e vínculo do indicador de pesquisas ao colaborador; ausência pode impedir a atribuição.',
        'status': 'Usado para definir pesquisas respondidas no numerador do indicador.',
        'data_expiracao': 'Usada na seleção de pesquisas do período e no agrupamento diário.',
        'data_solicitacao': 'Usada no filtro de entrada das pesquisas; pode modificar o universo recebido pelo cálculo.',
    }
    if field in impacts:
        kind, reason = 'OPORTUNIDADE', impacts[field]
    elif field == 'id':
        kind, reason = 'ALERTA', 'Compromete identificação e rastreabilidade; impacto aritmético direto não demonstrado.'
    elif field == 'data_conclusao' and str(status).strip().lower() in {'respondida', 'concluida', 'concluída'}:
        kind, reason = 'OPORTUNIDADE', 'Pesquisa respondida sem conclusão afeta seleção temporal; já há a regra DADO_INCOMPLETO.'
    elif field == 'data_conclusao' and str(status).strip().lower() in {'pendente', 'não respondida', 'nao respondida'}:
        kind, reason = 'TELEMETRIA', 'Pesquisa não concluída pode não ter data de conclusão; NULL isolado não caracteriza problema.'
    else:
        kind, reason = 'ALERTA', 'Impacto não comprovado neste contexto; exige validação do campo antes de elevar a oportunidade.'
    return dict(campo=field, classificacao_sugerida=kind, impacto=reason)


def research_assessment(opportunity):
    if opportunity['tipo_problema'] != 'PESQUISA_CAMPOS_NULOS':
        return []
    evidence = evidence_object(opportunity['evidencia'])
    return [assess_field(field, evidence.get('status')) for field in evidence_fields(evidence)]
