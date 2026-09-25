"""Leitura e escrita auditada das jornadas pelo endpoint existente de regras."""
import uuid
from typing import Literal
from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select
from .models import Contract
from shared.governance_config import upsert_audited
from shared.operational_schedule import JORNADA_FALLBACK, TABLE, available_journeys


class ScheduleEdit(Contract):
    id: str | None = None
    nome_jornada: str | None = Field(None, min_length=1, max_length=120)
    intervalo: str | None = Field(None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    origem_configuracao: Literal['CADASTRO_OPERACIONAL', 'MANUAL'] = 'CADASTRO_OPERACIONAL'
    jornada: float = Field(gt=0, le=168, multiple_of=0.01, allow_inf_nan=False)
    hora_entrada_padrao: str | None = Field(None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    hora_saida_padrao: str | None = Field(None, pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    ativo: bool

    @model_validator(mode='after')
    def complete(self):
        if self.origem_configuracao == 'MANUAL':
            if not self.nome_jornada or not self.nome_jornada.strip() or self.intervalo is None:
                raise ValueError('Informe nome e intervalo da jornada manual.')
            self.nome_jornada = self.nome_jornada.strip()
            if not self.hora_entrada_padrao or not self.hora_saida_padrao:
                raise ValueError('Informe entrada e saída da jornada manual.')
        if self.ativo and (not self.hora_entrada_padrao or not self.hora_saida_padrao):
            raise ValueError('Informe entrada e saída para a jornada ativa.')
        if (self.ativo or self.origem_configuracao == 'MANUAL') and self.hora_entrada_padrao == self.hora_saida_padrao:
            raise ValueError('Entrada e saída devem ser diferentes.')
        return self


def save_schedules(connection, tables, rule_id, scope, edits, user, reason, code):
    table = tables.get(TABLE)
    if table is None:
        raise HTTPException(503, 'Cadastro de horários indisponível. Aplique a migração de jornada.')
    if code != 'CHECKOUT_AUSENTE':
        raise HTTPException(422, 'Jornadas são exclusivas da configuração CHECKOUT_AUSENTE.')
    allowed = available_journeys(connection, tables.get('jornada_consolidada'), **scope)
    if len({e.jornada for e in edits}) != len(edits):
        raise HTTPException(422, 'Jornada duplicada.')
    changes = []
    for edit in edits:
        existing = connection.execute(select(table).where(table.c.configuracao_id == rule_id,
            table.c.marca == scope['marca'], table.c.operacao == scope['operacao'],
            table.c.id == edit.id if edit.id else table.c.jornada == edit.jornada)).mappings().first()
        if edit.id and not existing:
            raise HTTPException(422, 'Jornada não pertence a esta configuração.')
        if existing and existing.get('origem_configuracao', 'CADASTRO_OPERACIONAL') != edit.origem_configuracao:
            raise HTTPException(422, 'A origem da jornada não pode ser alterada.')
        collision = connection.execute(select(table.c.id).where(table.c.configuracao_id == rule_id,
            table.c.jornada == edit.jornada)).scalar()
        if collision and (not existing or collision != existing['id']):
            raise HTTPException(422, 'Já existe uma configuração para esta carga semanal.')
        if edit.origem_configuracao != 'MANUAL' and edit.jornada not in allowed and (edit.ativo or not existing):
            raise HTTPException(422, 'Jornada não existe no cadastro vigente desta operação.')
        metadata = {'nome_jornada', 'intervalo', 'origem_configuracao'}
        # Sem as colunas da 019, gravar "com sucesso" perderia o valor em silencio: recusa explicita.
        informados = {campo for campo in metadata & edit.model_fields_set if getattr(edit, campo) is not None}
        if (edit.origem_configuracao == 'MANUAL' or informados) and not metadata.issubset(table.c.keys()):
            raise HTTPException(503, 'Aplique a migração 019 de jornadas manuais antes de salvar.')
        key = {'id': existing['id'] if existing else str(uuid.uuid4())}
        payload = edit.model_dump(exclude={'id'})
        payload = {k: v for k, v in payload.items() if k in table.c}
        if existing:
            for field in metadata - edit.model_fields_set:
                payload.pop(field, None)
        values = {**scope, 'configuracao_id': rule_id, **payload, 'usuario_alteracao': user}
        if existing:
            values = {**payload, 'usuario_alteracao': user}
        if upsert_audited(connection, table, tables['governanca_configuracao_historico'], key=key,
                          values=values, scope=scope, entity_type='JORNADA_OPERACAO', entity_id=key['id'],
                          reference=code, user=user, reason=reason):
            changes.append(dict(entidade='JORNADA', referencia=str(edit.jornada), campo='Horários padrão',
                                antes={k: existing.get(k) for k in ScheduleEdit.model_fields} if existing else None, depois=edit.model_dump()))
    return changes


def schedule_context(repo, marca, operacao, rule_id=None):
    available = available_journeys(repo.connection, repo.tables.get('jornada_consolidada'), marca, operacao)
    table = repo.tables.get(TABLE)
    configs = [] if table is None or rule_id is None else repo.rows(select(table).where(
        table.c.configuracao_id == rule_id, table.c.marca == marca, table.c.operacao == operacao))
    saved = {float(r['jornada']): r for r in configs}
    return [dict(jornada=h, id=saved.get(h, {}).get('id'),
                 nome_jornada=saved.get(h, {}).get('nome_jornada') or f'Jornada {h:g}h',
                 intervalo=saved.get(h, {}).get('intervalo'),
                 origem_configuracao=saved.get(h, {}).get('origem_configuracao', 'CADASTRO_OPERACIONAL'),
                 disponivel=h in available, ativo=bool(saved.get(h, {}).get('ativo', False)),
                 hora_entrada_padrao=saved.get(h, {}).get('hora_entrada_padrao'),
                 hora_saida_padrao=saved.get(h, {}).get('hora_saida_padrao'))
            for h in sorted(set(available) | set(saved), reverse=True)]


def default_journey():
    """Jornada padrao que o motor aplica quando o cadastro nao informa a jornada do colaborador."""
    return dict(jornada=float(JORNADA_FALLBACK['jornada']), hora_entrada_padrao=JORNADA_FALLBACK['hora_entrada_padrao'][:5],
                hora_saida_padrao=JORNADA_FALLBACK['hora_saida_padrao'][:5], origem='CODIGO')


def monitoring_context(repo, marca, operacao):
    # Metadados da ultima avaliacao real. Sem execucao, nao inventa data nem contagem.
    result = dict(fonte='Involves', campo='Último checkout', ultima_atualizacao=None,
                  colaboradores_analisados=None, motivo='Ainda não há avaliação operacional registrada.')
    table = repo.tables.get('execucao_evento')
    if table is not None:
        rows = repo.rows(select(table.c.contexto).where(table.c.codigo == 'JORNADA_MONITORAMENTO')
                         .order_by(table.c.ocorrido_em.desc()).limit(100))
        import json
        for row in rows:
            ctx = row['contexto']
            ctx = json.loads(ctx) if isinstance(ctx, str) else ctx
            if ctx and ctx.get('marca') == marca and ctx.get('operacao') == operacao:
                result.update({k: ctx[k] for k in result if k in ctx})
                break
    return result
