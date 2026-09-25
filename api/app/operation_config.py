"""Configuracao operacional exposta para leitura. Nenhuma escrita nesta fase.

Tudo vem do cadastro que ja existe -- `configuracao_operacao`, `regra_fallback_config` e
`regra_tratativa`. Os parametros do calculo nao sao opiniao desta API: sao os valores do
processador travado no manifesto, devolvidos como documentacao consultavel para que o
lider veja de onde sai o indicador antes de poder administra-lo.
"""
import json

from fastapi import HTTPException
from sqlalchemy import select

from shared.rule_engine import (
    CAMPOS, STATUS_ATIVA, descrever_condicao, gera_oportunidade, operadores_do_tipo, rotulo_do_campo,
    rotulo_do_operador, rotulo_do_papel, tipo_do_campo,
)

from .pdoh_repository import (
    FORMULA_PDOH, INDICADOR_PDOH, PESOS_EFETIVIDADE, SEMANA_OPERACIONAL, _meta,
)
from .schedule_config import default_journey, schedule_context, monitoring_context
from shared.operational_schedule import CHECKOUT

BASE_PESOS = 'bracell/bases_fixas/VALORES BASE DO CALCULO.xlsx (travado no manifesto)'


def _json(valor, padrao):
    """O driver devolve JSON ja convertido no MySQL e texto no SQLite."""
    if valor is None:
        return padrao
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            return padrao
    return valor if isinstance(valor, type(padrao)) else padrao


def _jornada(fontes):
    """Fontes oficiais da jornada, na ordem de prioridade que o pipeline respeita."""
    resultado = []
    for fonte in _json(fontes, []):
        if not isinstance(fonte, dict) or not fonte.get('tabela'):
            continue
        resultado.append(dict(
            tabela=str(fonte['tabela']),
            prioridade=int(fonte.get('prioridade') or 0),
            campo_jornada=fonte.get('campo_jornada'),
            campo_perfil=fonte.get('campo_perfil'),
            campo_horas=fonte.get('campo_horas'),
        ))
    return sorted(resultado, key=lambda item: item['prioridade'])


def _fallback(repo, marca):
    tabela = repo.tables.get('regra_fallback_config')
    if tabela is None:
        return []
    c = tabela.c
    consulta = (select(c.regra, c.escopo, c.chave, c.valor_fallback, c.vigencia_inicio,
                       c.vigencia_fim, c.status)
                .where(c.marca == marca)
                .order_by(c.regra, c.escopo, c.chave, c.vigencia_inicio))
    return repo.rows(consulta)


def _regras(repo, marca):
    """Catalogo vigente da marca e as regras globais que valem para ela."""
    tabela = repo.tables.get('regra_tratativa')
    if tabela is None:
        return []
    c = tabela.c
    consulta = (select(c.tipo_problema, c.titulo_exibicao.label('titulo'), c.classificacao,
                       c.severidade_padrao, c.impacto_negocio, c.acao_recomendada,
                       c.origem_excecao, c.classificacao_excecao, c.status_regra, c.prioridade)
                .where(c.status_regra == 'ATIVA', (c.marca == marca) | (c.marca.is_(None)))
                .order_by(c.prioridade, c.tipo_problema))
    return repo.rows(consulta)


def _fontes_semanticas(repo, marca, operacao):
    tabela = repo.tables.get('fonte_semantica_configuracao')
    if tabela is None:
        return []
    c = tabela.c
    linhas = repo.rows(select(tabela).where(c.marca == marca, c.operacao == operacao)
                       .order_by(c.papel, c.prioridade))
    return [dict(papel=linha['papel'], tipo=linha['tipo'], prioridade=linha['prioridade'],
                 schema_fisico=linha['schema_fisico'], tabela_fisica=linha['tabela_fisica'],
                 mapeamento_campos=_json(linha['mapeamento_campos'], {}), status=linha['status'],
                 descricao=linha['descricao']) for linha in linhas]


def _campos_disponiveis(fontes):
    """Campos que a tela de criação pode oferecer: só os que têm fonte física MAPEADA.

    Vem do cruzamento do vocabulário de negócio (`CAMPOS`, em `shared.rule_engine`) com o que
    está realmente mapeado em `fonte_semantica_configuracao` -- nunca um campo sem fonte.
    """
    papeis_mapeados = {fonte['papel'] for fonte in fontes if fonte['status'] == 'MAPEADA' and fonte['tabela_fisica']}
    return [dict(papel_fonte=papel, campo_logico=campo, rotulo=rotulo, tipo=tipo,
                operadores=operadores_do_tipo(tipo))
            for papel in sorted(papeis_mapeados) for campo, (rotulo, tipo) in CAMPOS.get(papel, {}).items()]


def _condicao_para_tela(item):
    """Acrescenta ao registro cadastrado o vocabulario que a tela mostra ao lider."""
    papel, campo, operador = item['papel_fonte'], item['campo_logico'], item['operador']
    opcoes = operadores_do_tipo(tipo_do_campo(papel, campo), operador)
    return dict(item, campo_rotulo=rotulo_do_campo(papel, campo), operador_rotulo=rotulo_do_operador(operador),
                texto=descrever_condicao(item), operadores=opcoes,
                editavel=any(opcao['codigo'] == operador for opcao in opcoes) and len(opcoes) > 1)


def _fonte_da_regra(condicoes, fontes):
    """Fonte que alimenta a condicao principal: papel, tabela mapeada e campo."""
    ativas = [item for item in condicoes if item['status'] == STATUS_ATIVA] or condicoes
    if not ativas:
        return None
    papel, campo = ativas[0]['papel_fonte'], ativas[0]['campo_logico']
    candidatas = [f for f in fontes if f['papel'] == papel and f['status'] == 'MAPEADA' and f['tabela_fisica']]
    fonte = next((f for f in candidatas if campo in f['mapeamento_campos']), None) or (
        candidatas[0] if candidatas else None)
    return dict(papel=papel, rotulo=rotulo_do_papel(papel), tabela=fonte['tabela_fisica'] if fonte else None,
                campo=campo, campo_rotulo=rotulo_do_campo(papel, campo))


def _governance_rules(repo, marca, operacao, fontes=()):
    rules = repo.tables.get('regra_configuracao')
    conditions = repo.tables.get('regra_condicao_configuracao')
    treatments = repo.tables.get('regra_tratamento_configuracao')
    if rules is None or conditions is None or treatments is None:
        return []
    rc, cc, tc = rules.c, conditions.c, treatments.c
    rows = repo.rows(select(rules).where(rc.marca == marca, rc.operacao == operacao)
                     .order_by(rc.prioridade, rc.codigo_interno))
    rule_ids = [row['configuracao_id'] for row in rows]
    if not rule_ids:
        return []
    condition_rows = repo.rows(select(conditions).where(cc.configuracao_id.in_(rule_ids))
                               .order_by(cc.configuracao_id, cc.tipo, cc.ordem))
    treatment_rows = repo.rows(select(treatments).where(tc.configuracao_id.in_(rule_ids))
                               .order_by(tc.configuracao_id, tc.resultado))
    # "Ultima alteracao" da regra = a mais recente entre a regra, suas condicoes/excecoes e tratativas.
    latest = {row['configuracao_id']: row['atualizada_em'] for row in rows}
    for child in (*condition_rows, *treatment_rows):
        if child['atualizada_em'] and child['atualizada_em'] > latest[child['configuracao_id']]:
            latest[child['configuracao_id']] = child['atualizada_em']
    schedules = repo.tables.get('configuracao_jornada_operacao')
    if schedules is not None:
        for child in repo.rows(select(schedules).where(schedules.c.configuracao_id.in_(rule_ids))):
            if child['atualizada_em'] and child['atualizada_em'] > latest[child['configuracao_id']]:
                latest[child['configuracao_id']] = child['atualizada_em']
    by_rule_conditions = {}
    for row in condition_rows:
        value = row['valor_esperado']
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        item = _condicao_para_tela(dict(
            tipo=row['tipo'], ordem=row['ordem'], papel_fonte=row['papel_fonte'],
            campo_logico=row['campo_logico'], operador=row['operador'],
            valor_esperado=value, descricao=row['descricao'], status=row['status']))
        by_rule_conditions.setdefault(row['configuracao_id'], []).append(item)
    by_rule_treatments = {}
    for row in treatment_rows:
        by_rule_treatments.setdefault(row['configuracao_id'], []).append(dict(
            resultado=row['resultado'], acao_recomendada=row['acao_recomendada'],
            destino=row['destino'], gera_oportunidade=bool(row['gera_oportunidade']),
            status=row['status']))
    result = []
    for row in rows:
        all_conditions = by_rule_conditions.get(row['configuracao_id'], [])
        treatments_of_rule = by_rule_treatments.get(row['configuracao_id'], [])
        release = dict(status=row['status'], geracao_automatica_ativa=bool(row['geracao_automatica_ativa']))
        liberada, motivo = gera_oportunidade(release, treatments_of_rule)
        jornadas = schedule_context(repo, marca, operacao, row['configuracao_id']) if row['codigo_interno'] == CHECKOUT else []
        if row['codigo_interno'] == CHECKOUT and liberada and not any(j['ativo'] and j['disponivel'] for j in jornadas):
            liberada, motivo = False, 'SEM_JORNADA_ATIVA'
        result.append(dict(
            modelo_configuracao='JORNADA' if row['codigo_interno'] == CHECKOUT else 'CONDICAO',
            jornadas=jornadas,
            monitoramento=monitoring_context(repo, marca, operacao) if row['codigo_interno'] == CHECKOUT else None,
            # Jornada padrao do motor (em codigo) para quem nao tem jornada no cadastro; so' leitura.
            jornada_padrao=default_journey() if row['codigo_interno'] == CHECKOUT else None,
            configuracao_id=row['configuracao_id'], nome_regra=row['nome_regra'],
            codigo_interno=row['codigo_interno'], categoria=row['categoria'], status=row['status'],
            prioridade=row['prioridade'], tempo_minimo_minutos=int(row['tempo_minimo_minutos'] or 0),
            ativa=row['status'] == STATUS_ATIVA and release['geracao_automatica_ativa'],
            gera_oportunidade=liberada, motivo_sem_geracao=motivo,
            fonte=_fonte_da_regra([c for c in all_conditions if c['tipo'] == 'CONDICAO'], fontes),
            descricao=row['descricao'],
            comportamento_esperado=row['comportamento_esperado'],
            regra_catalogo_id=row['regra_catalogo_id'],
            geracao_automatica_ativa=bool(row['geracao_automatica_ativa']),
            condicoes=[item for item in all_conditions if item['tipo'] == 'CONDICAO'],
            excecoes=[item for item in all_conditions if item['tipo'] != 'CONDICAO'],
            tratativas=treatments_of_rule,
            atualizado_em=latest[row['configuracao_id']]))
    return result


def _prioridade_jornada(repo, marca, operacao):
    tabela = repo.tables.get('jornada_prioridade_configuracao')
    if tabela is None:
        return []
    c = tabela.c
    rows = repo.rows(select(tabela).where(c.marca == marca, c.operacao == operacao)
                     .order_by(c.prioridade))
    return [dict(prioridade=row['prioridade'], origem_codigo=row['origem_codigo'],
                 papel_fonte=row['papel_fonte'], fallback=bool(row['fallback']),
                 status=row['status'], aplicado_no_processamento=bool(row['aplicado_no_processamento']),
                 descricao=row['descricao']) for row in rows]


def _historico_governanca(repo, marca, operacao):
    tabela = repo.tables.get('governanca_configuracao_historico')
    if tabela is None:
        return []
    c = tabela.c
    rows = repo.rows(select(tabela).where(c.marca == marca, c.operacao == operacao)
                     .order_by(c.registrado_em.desc(), c.id.desc()).limit(100))
    return [dict(id=row['id'], entidade_tipo=row['entidade_tipo'],
                 codigo_referencia=row['codigo_referencia'], acao=row['acao'],
                 valor_anterior=row['valor_anterior'], valor_novo=row['valor_novo'],
                 usuario=row['usuario'], motivo=row['motivo'], registrado_em=row['registrado_em'])
            for row in rows]


def _parametros():
    meta, motivo_meta = _meta()
    return dict(
        pesos_efetividade=dict(PESOS_EFETIVIDADE),
        base_pesos=BASE_PESOS,
        formula_pdoh=FORMULA_PDOH,
        indicador_pdoh=INDICADOR_PDOH,
        semana_operacional=SEMANA_OPERACIONAL,
        meta_pdoh=meta,
        motivo_meta=motivo_meta,
    )


def operation_config(repo, marca=None, operacao=None):
    """GET /api/v2/configuracoes/operacao."""
    tabela = repo.tables.get('configuracao_operacao')
    if tabela is None:
        raise HTTPException(404, 'Configuracao da operacao nao encontrada.')
    c = tabela.c
    condicoes = []
    if marca:
        condicoes.append(c.marca == marca)
    if operacao:
        condicoes.append(c.operacao == operacao)
    linhas = repo.rows(select(tabela).where(*condicoes).order_by(c.marca, c.operacao).limit(1))
    if not linhas:
        raise HTTPException(404, 'Configuracao da operacao nao encontrada.')
    linha = linhas[0]
    fontes = _fontes_semanticas(repo, linha['marca'], linha['operacao'])
    return dict(
        marca=linha['marca'], operacao=linha['operacao'], descricao=linha['descricao'],
        jornadas_disponiveis=schedule_context(repo, linha['marca'], linha['operacao']),
        somente_leitura=True,
        jornada=_jornada(linha['fontes_jornada']),
        perfis_operacionais=[str(perfil) for perfil in _json(linha['perfis_operacionais'], [])],
        fallback=_fallback(repo, linha['marca']),
        regras=_regras(repo, linha['marca']),
        regras_governanca=_governance_rules(repo, linha['marca'], linha['operacao'], fontes),
        fontes_semanticas=fontes,
        campos_disponiveis=_campos_disponiveis(fontes),
        prioridade_jornada=_prioridade_jornada(repo, linha['marca'], linha['operacao']),
        historico_governanca=_historico_governanca(repo, linha['marca'], linha['operacao']),
        parametros=_parametros(),
        atualizado_em=linha['atualizado_em'],
    )
