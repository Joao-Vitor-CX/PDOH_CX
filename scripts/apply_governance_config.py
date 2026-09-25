"""Cria e cadastra a governanca inicial sem executar a esteira.

Uso local: ``python scripts/apply_governance_config.py``. O script e idempotente e
registra cada mudanca no historico.

Regra de convivencia com a tela de Configuracoes
    Regras, condicoes, excecoes, tratativas e fontes sao cadastradas SOMENTE quando ausentes
    (`insert_audited`). Reexecutar o script nunca desfaz o que o usuario alterou na tela.
    A unica alteracao sobre linhas existentes e' a normalizacao pontual das regras que ainda
    estao `EM_VALIDACAO` para `INATIVA` (definicao de negocio de 21/09/2026) -- e so' quando
    ainda estao naquele estado.

Definicao de negocio de 21/09/2026
    Somente HORAS_AUSENTES esta cadastrada (e ATIVA). Nenhuma outra oportunidade existe ate que
    o usuario a crie na tela de Configuracoes: as cinco regras pre-cadastradas pela primeira
    camada foram retiradas da configuracao (com o antes registrado no historico). O catalogo de
    tratativas e o historico de oportunidades nao sao tocados.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import uuid

from sqlalchemy import MetaData, Table, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_architecture import engine
from shared.governance_config import insert_audited, upsert_audited
from shared.treatment_catalog import regra_id_para

MIGRATIONS = (ROOT / 'docker/mysql/migrations/015_governanca_regras.sql',
              ROOT / 'docker/mysql/migrations/016_regra_tempo_minimo.sql')
JUSTIFICATIVAS = ROOT / 'bracell/bases_fixas/Lista_justificativas_abonaveis.xlsx'
SCOPE = {'marca': 'BRACELL', 'operacao': 'EXCLUSIVA'}
USER = 'bootstrap_governanca'
REASON = 'Cadastro inicial da camada de governanca; sem ativar geracao automatica'
REASON_DEFINICAO = ('Definição de negócio de 21/09/2026: oportunidades só existem quando criadas '
                    'pelo usuário; regra pré-cadastrada retirada da configuração. Catálogo e histórico '
                    'de oportunidades preservados; o antes está neste registro.')
REASON_ROTULOS = ('Rótulos e ordem das exceções alinhados à definição de negócio de 21/09/2026')
# Regras pre-cadastradas pela primeira camada de governanca: nao fazem parte do ambiente inicial.
LEGADO = ('CHECKIN_ENTRADA_AUSENTE', 'CHECKOUT_AUSENTE', 'INCONSISTENCIA_HORARIO',
          'JORNADA_NAO_ENCONTRADA', 'CADASTRO_INCONSISTENTE')
ROTULOS_ANTIGOS = {'Atestado', 'Afastamento', 'Sem jornada', 'Sem roteiro'}


def uid(kind, *parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'pdoh-cx/governanca/' + kind + '/' + '/'.join(map(str, parts))))


def abonaveis():
    """Lista oficial (travada no manifesto). Sem ela a excecao "Afastamento" ficaria vazia."""
    import pandas as pd
    planilha = pd.read_excel(JUSTIFICATIVAS)
    coluna = next(c for c in planilha.columns if 'justificativ' in str(c).casefold())
    valores = sorted({str(v).strip() for v in planilha[coluna].dropna() if str(v).strip()})
    if not valores:
        raise RuntimeError('Lista de justificativas abonaveis vazia; cadastro interrompido.')
    return valores


# Unica regra do ambiente inicial. As demais so' existem quando o usuario as cria.
RULES = [
    dict(codigo='HORAS_AUSENTES', nome='Horas ausentes', categoria='Jornada', prioridade=1,
         status='ATIVA', geracao=True, tempo_minimo=0,
         descricao='Colaborador possui jornada sem registro correspondente.',
         comportamento=('Sinaliza o dia em que as horas não registradas superam o mínimo '
                        'configurado, exceto quando uma das exceções ativas se aplica.'),
         condicoes=[('pdoh', 'horas_nao_registradas', 'MAIOR_QUE', '00:00',
                     'Horas não registradas maior que 00:00.')],
         # A descricao do bloqueio e' o rotulo exibido na tela (caixa "Não gerar quando"); o ultimo
         # item e' a ordem de exibicao. O identificador segue a posicao desta lista (nao muda).
         bloqueios=lambda: [
             ('colaborador', 'afastado', 'CONTEM', 'ATESTADO', 'Atestado válido no período', 2),
             ('colaborador', 'afastado', 'EM_LISTA', abonaveis(), 'Colaborador afastado', 1),
             ('jornada', 'status_resolucao', 'DIFERENTE_DE', 'RESOLVIDA', 'Jornada não resolvida', 4),
             ('colaborador', 'tem_roteiro', 'IGUAL_A', False, 'Dia sem roteiro', 3)],
         tratamentos=[
             ('CONFIRMADO', 'Validar com o colaborador o período sem registro e orientar o '
                            'apontamento correto das atividades.', 'OPORTUNIDADE', True),
             ('NAO_APLICAVEL', 'Registrar a exceção somente na governança.', 'GOVERNANCA', False),
             ('INDISPONIVEL', 'Aguardar complemento ou recuperação da fonte de dados.',
              'AGUARDAR_DADOS', False)]),
    # O texto de negocio (titulo/impacto/acao/severidade) deste codigo vive em
    # shared/treatment_catalog.py -- unica fonte, nao duplicar aqui.
]
CODIGOS_ATIVOS = {rule['codigo'] for rule in RULES if rule.get('status') == 'ATIVA'}

# (papel, tipo, prioridade, schema, tabela, campos, descricao)
BRACELL_SOURCES = [
    ('pdoh', 'PRINCIPAL', 1, 'produtos_platina', 'exclusivo_bracell_platina_relatorio_pdoh',
     {'colaborador': 'colaborador', 'data': 'data', 'estado': 'estado',
      'horas_nao_registradas': 'horas_nao_registradas', 'ocio': 'ocio', 'deslocamento': 'deslocamento',
      'produtividade': 'produtividade', 'horas_programadas': 'horas_programadas', 'almoco': 'almoco',
      'percentual_produtividade': 'percentual_produtividade', 'percentual_visitas': 'percentual_visitas',
      'percentual_pesquisas': 'percentual_pesquisas', 'percentual_efetividade': 'percentual_efetividade',
      'primeiro_checkin': 'primeiro_checkin', 'ultimo_checkout': 'ultimo_checkout'},
     'PDOH Platina'),
    ('checkin', 'PRINCIPAL', 1, 'involves_bracell', 'relatorio_checkin_bracell',
     {'colaborador': 'colaborador', 'data': 'data_roteiro', 'hora_entrada': 'hora_entrada'}, None),
    ('checkin', 'ALTERNATIVA', 2, 'involves_bracell', 'status_day_operacao_bracell',
     {'colaborador': 'colaborador', 'data': 'dia_referencia', 'hora_entrada': 'primeiro_checkin'}, None),
    ('checkout', 'PRINCIPAL', 1, 'involves_bracell', 'relatorio_checkin_bracell',
     {'colaborador': 'colaborador', 'data': 'data_roteiro', 'hora_saida': 'hora_saida'}, None),
    ('checkout', 'ALTERNATIVA', 2, 'involves_bracell', 'status_day_operacao_bracell',
     {'colaborador': 'colaborador', 'data': 'dia_referencia', 'hora_saida': 'ultimo_checkout'}, None),
    ('jornada', 'PRINCIPAL', 1, 'involves_bracell', 'colaboradores_ativos_bracell',
     {'colaborador': 'nome_colaborador', 'jornada_semanal': 'nome_pai', 'perfil': 'perfil_acesso'}, None),
    ('jornada', 'ALTERNATIVA', 2, 'involves_bracell', 'raw_exclusivo_bracell_colaboradores_ativos',
     {'colaborador': 'nome_colaborador', 'jornada_semanal': 'nome_do_pai', 'perfil': 'perfil_de_acesso'}, None),
    ('colaborador', 'PRINCIPAL', 1, 'involves_bracell', 'colaboradores_ativos_bracell',
     {'colaborador': 'nome_colaborador', 'ativo': 'usuario_ativo', 'perfil': 'perfil_acesso'}, None),
    ('colaborador', 'ALTERNATIVA', 2, 'involves_bracell', 'status_day_operacao_bracell',
     {'colaborador': 'colaborador', 'data': 'dia_referencia', 'afastado': 'afastado',
      'tem_roteiro': 'tem_roteiro', 'perfil': 'perfil_acesso', 'evolucao': 'data_evolucao'}, None),
    ('visitas', 'PRINCIPAL', 1, 'involves_bracell', 'gerencial_visitas_bracell',
     {'colaborador': 'colaborador', 'data': 'data_visita', 'situacao': 'situacao_checkin'}, None),
    ('pesquisas', 'PRINCIPAL', 1, 'involves_bracell', 'painel_pesquisas_bracell',
     {'colaborador': 'responsavel', 'data': 'data_solicitacao', 'status': 'status'}, None),
]

JOURNEY_STEPS = [
    (1, 'INVOLVES', 'jornada', False, 'Cadastro vigente do Involves.'),
    (2, 'RAW_OPERACIONAL', 'jornada', False, 'Snapshot RAW operacional.'),
    (3, 'CONFIGURACAO_OPERACAO', 'jornada', True, 'Configuração específica da operação.'),
    (4, 'JORNADA_PADRAO', 'jornada', True, 'Jornada padrão, somente após validação arquitetural.'),
]
PAPEIS_RESERVADOS = ('pdoh', 'checkin', 'checkout', 'jornada', 'colaborador', 'visitas', 'pesquisas')


def _execute_ddl(connection):
    for migration in MIGRATIONS:
        for statement in migration.read_text(encoding='utf-8').split(';'):
            if statement.strip():
                connection.exec_driver_sql(statement)


def _tables(connection):
    metadata = MetaData(schema='pdoh_controle')
    names = ('regra_configuracao', 'regra_condicao_configuracao',
             'fonte_semantica_configuracao', 'regra_tratamento_configuracao',
             'jornada_prioridade_configuracao', 'governanca_configuracao_historico')
    return {name: Table(name, metadata, autoload_with=connection) for name in names}


def _add(connection, tables, table_name, *, key, values, entity_type, entity_id, reference,
         reason=REASON):
    """Cadastra se ausente; nunca sobrescreve."""
    return insert_audited(connection, tables[table_name],
        tables['governanca_configuracao_historico'], key=key, values=values, scope=SCOPE,
        entity_type=entity_type, entity_id=entity_id, reference=reference, user=USER, reason=reason)


def _save(connection, tables, table_name, *, key, values, entity_type, entity_id, reference):
    return upsert_audited(connection, tables[table_name],
        tables['governanca_configuracao_historico'], key=key, values=values, scope=SCOPE,
        entity_type=entity_type, entity_id=entity_id, reference=reference,
        user=USER, reason=REASON)


def _instantaneo(linha):
    return {chave: (str(valor) if hasattr(valor, 'isoformat') else valor) for chave, valor in dict(linha).items()}


def _retirar_legado(connection, tables):
    """Retira da configuracao as regras pre-cadastradas (definicao de negocio de 21/09/2026).

    Cada retirada grava no historico o antes completo (regra, condicoes e tratativas), entao nada
    se perde. Regra que o usuario ja ATIVOU pela tela nao e' tocada. O catalogo `regra_tratativa`
    e as oportunidades ja registradas ficam como estao.
    """
    rules, conditions, treatments = (tables[n] for n in (
        'regra_configuracao', 'regra_condicao_configuracao', 'regra_tratamento_configuracao'))
    history, removed = tables['governanca_configuracao_historico'], 0
    for code in LEGADO:
        rule = connection.execute(select(rules).where(
            rules.c.marca == SCOPE['marca'], rules.c.operacao == SCOPE['operacao'],
            rules.c.codigo_interno == code)).mappings().first()
        if not rule or rule['status'] == 'ATIVA':
            continue
        config_id = rule['configuracao_id']
        children = [_instantaneo(row) for row in connection.execute(
            select(conditions).where(conditions.c.configuracao_id == config_id)).mappings()]
        outcomes = [_instantaneo(row) for row in connection.execute(
            select(treatments).where(treatments.c.configuracao_id == config_id)).mappings()]
        snapshot = {**_instantaneo(rule), 'condicoes': children, 'tratativas': outcomes}
        connection.execute(treatments.delete().where(treatments.c.configuracao_id == config_id))
        connection.execute(conditions.delete().where(conditions.c.configuracao_id == config_id))
        connection.execute(rules.delete().where(rules.c.configuracao_id == config_id))
        connection.execute(history.insert().values(
            marca=SCOPE['marca'], operacao=SCOPE['operacao'], entidade_tipo='REGRA',
            entidade_id=str(config_id), codigo_referencia=code, acao='EXCLUSAO',
            valor_anterior=snapshot, valor_novo=None, usuario=USER, motivo=REASON_DEFINICAO))
        removed += 1
    return removed


def _alinhar_excecoes(connection, tables):
    """Rotulos e ordem das excecoes da HORAS_AUSENTES na linguagem do negocio.

    So' toca linha que ainda tem o rotulo antigo; identificador e regra da excecao nao mudam.
    """
    table = tables['regra_condicao_configuracao']
    history = tables['governanca_configuracao_historico']
    rule = next(r for r in RULES if r['codigo'] == 'HORAS_AUSENTES')
    desired = {}
    for index, entry in enumerate(rule['bloqueios'](), 1):
        desired[uid('condicao', rule['codigo'], 'BLOQUEIO', index)] = (entry[4], entry[5])
    rows = {row['condicao_id']: dict(row) for row in connection.execute(
        select(table).where(table.c.condicao_id.in_(list(desired)))).mappings()}
    pending = {cid: row for cid, row in rows.items()
               if row['descricao'] in ROTULOS_ANTIGOS and (row['descricao'], row['ordem']) != desired[cid]}
    if not pending:
        return 0
    before = {cid: _instantaneo(row) for cid, row in pending.items()}
    # A chave unica (regra, tipo, ordem) nao aceita troca direta: desloca, depois fixa.
    connection.execute(table.update().where(table.c.condicao_id.in_(list(pending)))
                       .values(ordem=table.c.ordem + 100))
    for cid in pending:
        name, order = desired[cid]
        connection.execute(table.update().where(table.c.condicao_id == cid)
                           .values(descricao=name, ordem=order, usuario_alteracao=USER))
    for cid in pending:
        after = _instantaneo(connection.execute(select(table).where(table.c.condicao_id == cid)).mappings().one())
        connection.execute(history.insert().values(
            marca=SCOPE['marca'], operacao=SCOPE['operacao'], entidade_tipo='BLOQUEIO', entidade_id=cid,
            codigo_referencia=rule['codigo'], acao='ALTERACAO', valor_anterior=before[cid],
            valor_novo=after, usuario=USER, motivo=REASON_ROTULOS))
    return len(pending)


def _complementar_mapeamentos(connection, tables):
    """Acrescenta campos novos a mapeamentos que ja existiam (ex.: data da extracao)."""
    table, changed = tables['fonte_semantica_configuracao'], 0
    for role, kind, priority, _schema, _physical, fields, _description in BRACELL_SOURCES:
        source_id = uid('fonte', SCOPE['marca'], role, priority)
        current = connection.execute(select(table).where(table.c.fonte_id == source_id)).mappings().first()
        if not current:
            continue
        stored = current['mapeamento_campos']
        stored = json.loads(stored) if isinstance(stored, str) else dict(stored or {})
        missing = {name: column for name, column in fields.items() if name not in stored}
        if not missing:
            continue
        changed += upsert_audited(connection, table, tables['governanca_configuracao_historico'],
            key={'fonte_id': source_id}, values={'mapeamento_campos': {**stored, **missing},
                                                 'usuario_alteracao': USER},
            scope=SCOPE, entity_type='FONTE', entity_id=source_id, reference=role,
            user=USER, reason='Complemento de campos mapeados: ' + ', '.join(sorted(missing)))
    return changed


def apply():
    changed = 0
    db = engine()
    with db.begin() as connection:
        before = connection.exec_driver_sql('SELECT COUNT(*) FROM pdoh_controle.oportunidade').scalar_one()
        _execute_ddl(connection)
        tables = _tables(connection)

        for rule in RULES:
            config_id = uid('regra', SCOPE['marca'], SCOPE['operacao'], rule['codigo'])
            changed += _add(connection, tables, 'regra_configuracao',
                key={'configuracao_id': config_id},
                values={**SCOPE, 'nome_regra': rule['nome'], 'codigo_interno': rule['codigo'],
                        'categoria': rule['categoria'], 'status': rule.get('status', 'INATIVA'),
                        'prioridade': rule['prioridade'],
                        'tempo_minimo_minutos': rule.get('tempo_minimo', 0),
                        'descricao': rule['descricao'], 'comportamento_esperado': rule['comportamento'],
                        'regra_catalogo_id': regra_id_para(SCOPE['marca'], rule['codigo']),
                        'geracao_automatica_ativa': rule.get('geracao', False),
                        'usuario_alteracao': USER},
                entity_type='REGRA', entity_id=config_id, reference=rule['codigo'])

            blockers = rule['bloqueios']() if callable(rule.get('bloqueios')) else []
            for kind, entries in (('CONDICAO', rule['condicoes']), ('BLOQUEIO', blockers)):
                for index, (role, field, operator, expected, description, *extra) in enumerate(entries, 1):
                    order = extra[0] if extra else index
                    condition_id = uid('condicao', rule['codigo'], kind, index)
                    changed += _add(connection, tables, 'regra_condicao_configuracao',
                        key={'condicao_id': condition_id},
                        values={'configuracao_id': config_id, 'tipo': kind, 'ordem': order,
                                'papel_fonte': role, 'campo_logico': field, 'operador': operator,
                                'valor_esperado': expected, 'descricao': description,
                                'status': 'ATIVA', 'usuario_alteracao': USER},
                        entity_type=kind, entity_id=condition_id, reference=rule['codigo'])

            for result, action, destination, generates in rule['tratamentos']:
                treatment_id = uid('tratamento', rule['codigo'], result)
                changed += _add(connection, tables, 'regra_tratamento_configuracao',
                    key={'tratamento_id': treatment_id},
                    values={'configuracao_id': config_id, 'resultado': result,
                            'acao_recomendada': action, 'destino': destination,
                            'gera_oportunidade': generates, 'status': 'ATIVO',
                            'usuario_alteracao': USER},
                    entity_type='TRATAMENTO', entity_id=treatment_id, reference=rule['codigo'])

        for role, kind, priority, schema, physical, fields, description in BRACELL_SOURCES:
            source_id = uid('fonte', SCOPE['marca'], role, priority)
            changed += _add(connection, tables, 'fonte_semantica_configuracao',
                key={'fonte_id': source_id},
                values={**SCOPE, 'papel': role, 'tipo': kind, 'prioridade': priority,
                        'schema_fisico': schema, 'tabela_fisica': physical,
                        'mapeamento_campos': fields, 'status': 'MAPEADA',
                        'descricao': description or f'Fonte {kind.lower()} do papel {role}.',
                        'usuario_alteracao': USER},
                entity_type='FONTE', entity_id=source_id, reference=role)
        changed += _complementar_mapeamentos(connection, tables)

        for brand in ('FLORA', 'TANGARA'):
            for role in PAPEIS_RESERVADOS:
                source_id = uid('fonte', brand, role, 1)
                changed += upsert_audited(connection, tables['fonte_semantica_configuracao'],
                    tables['governanca_configuracao_historico'], key={'fonte_id': source_id},
                    values={'marca': brand, 'operacao': 'EXCLUSIVA', 'papel': role,
                            'tipo': 'PRINCIPAL', 'prioridade': 1, 'schema_fisico': None,
                            'tabela_fisica': None, 'mapeamento_campos': {},
                            'status': 'PENDENTE_MAPEAMENTO',
                            'descricao': 'Papel reservado; fonte física depende de mapeamento.',
                            'usuario_alteracao': USER},
                    scope={'marca': brand, 'operacao': 'EXCLUSIVA'}, entity_type='FONTE',
                    entity_id=source_id, reference=role, user=USER, reason=REASON)

        for priority, origin, role, fallback, description in JOURNEY_STEPS:
            step_id = uid('jornada', SCOPE['marca'], SCOPE['operacao'], priority)
            changed += _save(connection, tables, 'jornada_prioridade_configuracao',
                key={'etapa_id': step_id},
                values={**SCOPE, 'prioridade': priority, 'origem_codigo': origin,
                        'papel_fonte': role, 'fallback': fallback, 'status': 'EM_VALIDACAO',
                        'aplicado_no_processamento': False, 'descricao': description,
                        'usuario_alteracao': USER},
                entity_type='JORNADA_PRIORIDADE', entity_id=step_id, reference=origin)

        changed += _retirar_legado(connection, tables)
        changed += _alinhar_excecoes(connection, tables)
        after = connection.exec_driver_sql('SELECT COUNT(*) FROM pdoh_controle.oportunidade').scalar_one()
    db.dispose()
    if before != after:
        raise RuntimeError(f'Oportunidades alteradas durante o cadastro: {before} -> {after}')
    result = {'configuracoes_alteradas': changed, 'oportunidades_antes': before,
              'oportunidades_depois': after, 'regras_ativas': sorted(CODIGOS_ATIVOS)}
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == '__main__':
    apply()
