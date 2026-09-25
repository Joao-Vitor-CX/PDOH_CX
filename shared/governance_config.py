"""Escrita auditada da camada shadow de governanca.

Este modulo nao e importado pelo calculo PDOH nem pelos processadores. Toda futura tela
de edicao deve usar ``upsert_audited`` para manter o antes/depois na mesma transacao.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, insert, select, update


def _plain(value):
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return value
        return decoded if isinstance(decoded, (dict, list)) else value
    if isinstance(value, (datetime, date, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def upsert_audited(connection, table, history_table, *, key, values, scope,
                   entity_type, entity_id, reference=None, user, reason):
    """Insere/atualiza configuracao e registra a mudanca na mesma transacao.

    Reaplicar o mesmo cadastro e idempotente: nenhum UPDATE e nenhum evento duplicado.
    """
    predicate = and_(*(table.c[name] == value for name, value in key.items()))
    current = connection.execute(select(table).where(predicate)).mappings().first()
    before = dict(current) if current else None
    desired = {**key, **values}
    comparable = {name: _plain(before.get(name)) for name in desired} if before else None
    expected = {name: _plain(value) for name, value in desired.items()}
    if comparable == expected:
        return False

    if current:
        connection.execute(update(table).where(predicate).values(**values))
        action = 'ALTERACAO'
    else:
        connection.execute(insert(table).values(**desired))
        action = 'CADASTRO'
    after = dict(connection.execute(select(table).where(predicate)).mappings().one())
    connection.execute(insert(history_table).values(
        marca=scope['marca'], operacao=scope['operacao'], entidade_tipo=entity_type,
        entidade_id=str(entity_id), codigo_referencia=reference, acao=action,
        valor_anterior=_plain(before), valor_novo=_plain(after), usuario=user, motivo=reason,
    ))
    return True


def insert_audited(connection, table, history_table, *, key, values, scope,
                   entity_type, entity_id, reference=None, user, reason):
    """Cadastra somente se AUSENTE; nunca sobrescreve nem gera evento quando ja existe.

    E' o que permite reexecutar o cadastro inicial depois que a tela de configuracao passou
    a alterar as regras: `upsert_audited` reaplicaria os valores do script e desfaria a
    escolha do usuario.
    """
    predicate = and_(*(table.c[name] == value for name, value in key.items()))
    if connection.execute(select(table).where(predicate)).first():
        return False
    connection.execute(insert(table).values(**{**key, **values}))
    after = dict(connection.execute(select(table).where(predicate)).mappings().one())
    connection.execute(insert(history_table).values(
        marca=scope['marca'], operacao=scope['operacao'], entidade_tipo=entity_type,
        entidade_id=str(entity_id), codigo_referencia=reference, acao='CADASTRO',
        valor_anterior=None, valor_novo=_plain(after), usuario=user, motivo=reason,
    ))
    return True
