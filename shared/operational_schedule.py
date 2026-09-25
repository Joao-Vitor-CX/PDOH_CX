"""Jornadas cadastradas e validacao pura de checkout, sem alterar o dado observado."""
from datetime import datetime, time, timedelta, timezone
from sqlalchemy import select
from shared.rule_engine import segundos

TABLE = 'configuracao_jornada_operacao'
CHECKOUT = 'CHECKOUT_AUSENTE'

# Jornada padrao (fallback operacional). Usada SOMENTE quando o colaborador e' ativo e elegivel,
# mas o cadastro de origem nao informa a jornada (status NAO_ENCONTRADA). Fora de escopo, conflito
# de horas e resolucao incompleta continuam sem gerar: sao problema de cadastro, nao falta de dado.
ORIGEM_FALLBACK = 'FALLBACK'
STATUS_COM_FALLBACK = frozenset({'NAO_ENCONTRADA'})
MOTIVO_FALLBACK = 'Jornada não encontrada no cadastro de origem; aplicada a jornada padrão 44H.'
JORNADA_FALLBACK = dict(id='JORNADA_PADRAO_44H', jornada=44.0, hora_entrada_padrao='08:00:00',
                        hora_saida_padrao='19:00:00', ativo=1)


def fallback_schedule():
    """Copia da jornada padrao; quem usa nunca altera a definicao."""
    return dict(JORNADA_FALLBACK)


def available_journeys(connection, table, marca, operacao):
    """Ultima resolucao de cada identidade; conflitos e desligados nao viram opcoes."""
    if table is None:
        return []
    rows = connection.execute(select(table).where(table.c.marca == marca, table.c.operacao == operacao)
                              .order_by(table.c.registrado_em.desc())).mappings()
    latest = {}
    for row in rows:
        key = row['colaborador_chave']
        stamp = row['registrado_em']
        if key not in latest:
            latest[key] = (stamp, [])
        if latest[key][0] == stamp:
            latest[key][1].append(row)
    hours = set()
    for _, candidates in latest.values():
        valid = [r for r in candidates if r['elegivel'] and r['vigente'] and r['status_resolucao'] == 'RESOLVIDA']
        values = {float(r['jornada_semanal']) for r in valid if r['jornada_semanal'] is not None}
        if len(valid) == len(candidates) and len(values) == 1:
            hours.update(values)
    return sorted(hours, reverse=True)


def checkout_due(schedule, row, now=None):
    """Ausencia apos a saida esperada. Saida existente, mesmo antecipada, nao e ausencia.

    O instante de extracao precisa cobrir a saida esperada: relogio atual nao prova que uma
    extracao antiga foi completada. Entrada real tambem e obrigatoria.
    """
    if not schedule or not schedule.get('ativo'):
        return False
    if row.get('hora_saida') is not None and str(row['hora_saida']).strip():
        return False
    try:
        entrada = time.fromisoformat(str(schedule['hora_entrada_padrao']))
        saida = time.fromisoformat(str(schedule['hora_saida_padrao']))
        real = row.get('hora_entrada')
        if real is None:
            return False
        measured = segundos(real)
        if measured is None or not 0 <= measured < 86400:
            return False
        day = datetime.fromisoformat(str(row['data'])[:10])
        deadline = datetime.combine(day.date(), saida)
        if saida <= entrada:
            deadline += timedelta(days=1)
        observed = datetime.fromisoformat(str(row['evolucao']))
        # Mesmo offset do contrato DATETIME e da sessao MySQL desta operacao.
        zone = timezone(timedelta(hours=-3))
        if observed.tzinfo:
            observed = observed.astimezone(zone).replace(tzinfo=None)
        current = now or datetime.now(zone).replace(tzinfo=None)
        if current.tzinfo:
            current = current.astimezone(zone).replace(tzinfo=None)
        return observed >= deadline and current >= deadline
    except (ValueError, TypeError, KeyError):
        return False
