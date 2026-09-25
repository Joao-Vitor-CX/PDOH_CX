"""Projecoes v2 de leitura. Legado consultado in-place; nenhum backfill."""
import base64
from datetime import date, timedelta
import math

from fastapi import HTTPException
from sqlalchemy import String, and_, case, cast, false, func, literal, null, or_, select, union_all

from .alerts import evidence_fields, occurrence_count
from shared.operational_policy import assess
from shared.rule_engine import codigos_liberados
from shared.evidence_config import STATUS_OCORRENCIA_ENCERRADA

# Chave do problema operacional: marca + regra + colaborador + contexto (origem +
# campo afetado). Nao depende de dia, execucao, registro nem repeticao. Reversivel e
# estavel, sem funcao de hash do banco (a suite roda em SQLite, a producao em MySQL).
# O mesmo formato e' gerado por `bracell/src/findings.py::grupo_operacional`.
SEPARADOR_GRUPO = '\x1f'
MAX_GRUPOS = 5000
MAX_OCORRENCIAS = 5000
MAX_REGISTROS_AGRUPAMENTO = 100_000
STATUS_ENCERRADOS = frozenset({'RESOLVIDA', 'IGNORADA'})
ORDEM_SEVERIDADE = {'CRITICA': 0, 'ALTA': 1, 'MEDIA': 2, 'BAIXA': 3}


def campo_do_registro(evidencia):
    """Campo afetado, na mesma forma usada pelo dispatcher ao notificar."""
    return '+'.join(campo for campo in evidence_fields(evidencia) if campo != 'Não informado')


def codificar_grupo(marca, tipo_problema, colaborador_id, colaborador, tabela_origem, campo, operacao='EXCLUSIVA'):
    """ID operacional opaco. Nao carrega UUID, fingerprint nem execution_id."""
    chave = SEPARADOR_GRUPO.join([marca or '', tipo_problema or '', colaborador_id or '',
                                  '' if colaborador_id else (colaborador or ''), tabela_origem or '', campo or ''])
    if operacao != 'EXCLUSIVA':
        chave += SEPARADOR_GRUPO + operacao
    return base64.urlsafe_b64encode(chave.encode('utf-8')).decode('ascii').rstrip('=')


def decodificar_grupo(grupo_id):
    try:
        bruto = base64.urlsafe_b64decode((grupo_id + '=' * (-len(grupo_id) % 4)).encode('ascii'))
        partes = bruto.decode('utf-8').split(SEPARADOR_GRUPO)
    except Exception:
        raise HTTPException(404, 'Grupo operacional nao encontrado.') from None
    if len(partes) not in (6, 7):
        raise HTTPException(404, 'Grupo operacional nao encontrado.')
    marca, tipo_problema, colaborador_id, colaborador, tabela_origem, campo = partes[:6]
    return (marca, tipo_problema, (colaborador_id or None), (colaborador or None),
            (tabela_origem or None), (campo or None), partes[6] if len(partes) == 7 else 'EXCLUSIVA')


def regras_de_oportunidade_liberadas(repo):
    """{(marca, operacao): {codigos}} das regras que podem gerar oportunidade agora.

    E' a mesma definicao usada pela esteira (`shared.rule_engine.gera_oportunidade`): cadastrada,
    ativa e configurada para gerar. Oportunidade de regra inexistente ou inativa continua no
    historico, mas nao aparece em nenhuma visao operacional.
    """
    regras, tratamentos = repo.tables['regra_configuracao'], repo.tables['regra_tratamento_configuracao']
    return codigos_liberados(
        repo.rows(select(regras.c.configuracao_id, regras.c.marca, regras.c.operacao,
                         regras.c.codigo_interno, regras.c.status, regras.c.geracao_automatica_ativa)),
        repo.rows(select(tratamentos.c.configuracao_id, tratamentos.c.resultado,
                         tratamentos.c.gera_oportunidade, tratamentos.c.status)))


def _condicao_regras_liberadas(liberadas, coluna_marca, coluna_operacao, coluna_tipo):
    """Filtro SQL equivalente ao filtro em memoria de `_linhas_operacionais`."""
    if not liberadas:
        return false()
    return or_(*[and_(coluna_marca == marca, coluna_operacao == operacao, coluna_tipo.in_(sorted(codigos)))
                 for (marca, operacao), codigos in sorted(liberadas.items())])


def hoje_local():
    """Data corrente (America/Sao_Paulo tratada como local). Isolada para teste."""
    return date.today()


def semana_fechada(hoje):
    """Ultima semana operacional encerrada: SEGUNDA a SABADO anteriores.

    Domingo nao e' dia operacional no PDOH, entao fica fora da janela. Nunca
    devolve a semana em curso.
    """
    segunda_atual = hoje - timedelta(days=hoje.weekday())
    inicio = segunda_atual - timedelta(days=7)   # segunda anterior
    fim = inicio + timedelta(days=5)             # sabado anterior
    return inicio, fim


def mes_fechado(hoje):
    """Primeiro e ultimo dia do mes anterior fechado."""
    primeiro_do_mes = hoje.replace(day=1)
    fim = primeiro_do_mes - timedelta(days=1)
    return fim.replace(day=1), fim


STATUS_EXECUCAO_COM_DADOS = ('CONCLUIDA', 'CONCLUIDA_COM_ALERTAS')


def janela_do_ultimo_processamento(repo, filters):
    """Janela da execucao mais recente que de fato produziu dados.

    Falha tecnica, execucao em andamento e execucao de validacao nao contam: apontar para
    elas mostraria uma janela sem dado algum. Devolve None quando nao ha nenhuma.
    """
    e = repo.tables['execucao']
    contexto = repo.tables['execucao_contexto']
    condicoes = [e.c.periodo_inicio.is_not(None), e.c.periodo_fim.is_not(None),
                 e.c.status_execucao.in_(STATUS_EXECUCAO_COM_DADOS),
                 ~select(contexto.c.execution_id).where(
                     contexto.c.execution_id == e.c.execution_id,
                     contexto.c.marca == e.c.marca, contexto.c.finalidade == 'VALIDACAO').exists()]
    if filters.marca is not None:
        condicoes.append(e.c.marca == filters.marca)
    if getattr(filters, 'operacao', None) is not None:
        condicoes.append(e.c.operacao == filters.operacao)
    linhas = repo.rows(select(e.c.periodo_inicio, e.c.periodo_fim).where(*condicoes)
                       .order_by(e.c.periodo_fim.desc(), e.c.periodo_inicio.desc()).limit(1))
    return (linhas[0]['periodo_inicio'], linhas[0]['periodo_fim']) if linhas else None


def resolver_periodo(filters, repo=None):
    """Resolve a janela efetiva e a fixa em ``filters`` (mesma regra p/ os 3 endpoints).

    - ``periodo=automatico`` -> janela do processamento mais recente com dados (sem ``repo``
      ou sem processamento, cai na ultima semana fechada);
    - ``periodo=semana`` ou ausencia total de datas -> ultima semana fechada (padrao do PDOH);
    - ``periodo=mes`` -> mes anterior fechado;
    - ``periodo=personalizado`` -> exige periodo_inicio e periodo_fim informados;
    - datas informadas sem ``periodo`` -> respeitadas como estao (janela custom).
    """
    hoje = hoje_local()
    modo = filters.periodo
    if modo == 'automatico':
        janela = janela_do_ultimo_processamento(repo, filters) if repo is not None else None
        inicio, fim = janela or semana_fechada(hoje)
    elif modo == 'hoje':
        inicio = fim = hoje
    elif modo == 'ontem':
        inicio = fim = hoje - timedelta(days=1)
    elif modo == 'ultimos_7_dias':
        inicio, fim = hoje - timedelta(days=6), hoje
    elif modo == 'ultimos_30_dias':
        inicio, fim = hoje - timedelta(days=29), hoje
    elif modo in ('tres_meses', 'doze_meses'):
        meses = 3 if modo == 'tres_meses' else 12
        fim = hoje.replace(day=1) - timedelta(days=1)
        inicio = fim.replace(day=1)
        for _ in range(meses - 1):
            inicio = (inicio - timedelta(days=1)).replace(day=1)
    elif modo == 'relativo':
        quantidade = getattr(filters, 'periodo_quantidade', None)
        unidade = getattr(filters, 'periodo_unidade', None)
        if not quantidade or not unidade:
            from fastapi import HTTPException
            raise HTTPException(422, 'periodo=relativo exige periodo_quantidade e periodo_unidade.')
        dias = quantidade
        if unidade == 'semanas':
            dias = quantidade * 7
        elif unidade == 'meses':
            # Intervalo movel: meses equivalem aos meses civis precedentes, incluindo hoje.
            cursor = hoje.replace(day=1)
            for _ in range(quantidade):
                cursor = (cursor - timedelta(days=1)).replace(day=1)
            inicio, fim = cursor, hoje
            dias = None
        if dias is not None:
            inicio, fim = hoje - timedelta(days=dias - 1), hoje
    elif modo == 'mes':
        inicio, fim = mes_fechado(hoje)
    elif modo == 'semana':
        inicio, fim = semana_fechada(hoje)
    elif modo == 'personalizado':
        if filters.periodo_inicio is None or filters.periodo_fim is None:
            from fastapi import HTTPException
            raise HTTPException(422, "periodo=personalizado exige periodo_inicio e periodo_fim.")
        inicio, fim = filters.periodo_inicio, filters.periodo_fim
    elif filters.periodo_inicio is None and filters.periodo_fim is None:
        inicio, fim = semana_fechada(hoje)   # padrao: semana fechada
    else:
        inicio, fim = filters.periodo_inicio, filters.periodo_fim
    filters.periodo_inicio, filters.periodo_fim = inicio, fim
    return inicio, fim


def _classificacao_efetiva(regra, origem_col):
    """Excecao por origem declarada na propria regra do catalogo."""
    return case(
        (and_(regra.c.origem_excecao.is_not(None), regra.c.origem_excecao == origem_col),
         regra.c.classificacao_excecao),
        else_=regra.c.classificacao,
    )


def _regra_por_tipo(repo, coluna, tipo_col, marca_col, origem_col):
    """Regra ATIVA vigente por tipo_problema: marca especifica antes da global.

    Subconsulta escalar (nunca duplica linhas) que espelha `resolver_tratativa` do
    pipeline. E' o fallback para o historico sem `regra_id`, que hoje e' a maioria.
    """
    rt = repo.tables['regra_tratativa'].alias('regra_por_tipo')
    valor = _classificacao_efetiva(rt, origem_col) if coluna == 'classificacao' else rt.c[coluna]
    return (
        select(valor)
        .where(rt.c.tipo_problema == tipo_col, rt.c.status_regra == 'ATIVA',
               or_(rt.c.marca == marca_col, rt.c.marca.is_(None)))
        .order_by(case((rt.c.marca.is_(None), 1), else_=0), rt.c.prioridade, rt.c.regra_id)
        .limit(1)
        .correlate_except(rt)
        .scalar_subquery()
    )


def _filtros_combinados(filters, combined):
    """Condicoes aplicadas sobre a projecao unificada (pos-union)."""
    conditions = []
    for param, field in [('tipo', 'tipo_problema'), ('status', 'status'),
                         ('execution_id', 'execution_id'), ('regra', 'regra_id')]:
        value = getattr(filters, param)
        if value is not None:
            conditions.append(combined.c[field] == value)
    # Severidade vem do catalogo (regra_tratativa.severidade_padrao) via coalesce nas
    # branches; aqui apenas compara sem case fixo em codigo.
    if filters.severidade is not None:
        conditions.append(func.upper(combined.c.severidade) == filters.severidade.upper())
    # Colaborador: casa por ID interno confiavel quando informado, senao por nome/
    # referencia de origem (busca parcial, sem depender apenas do nome).
    if filters.colaborador is not None:
        alvo = filters.colaborador.strip()
        conditions.append(or_(
            combined.c.colaborador_id_interno == alvo,
            func.upper(combined.c.colaborador).like('%' + alvo.upper() + '%'),
        ))
    return conditions


def finding_page(repo, filters, classification):
    resolver_periodo(filters, repo)
    if classification == 'TELEMETRIA':
        return telemetry_page(repo, filters)
    tables = repo.tables
    o, a, e, r, route, event = (tables[name] for name in (
        'oportunidade', 'alerta', 'execucao', 'regra_tratativa', 'achado_roteamento', 'execucao_evento'))
    branches = []

    # Novos OP e legado permanecem fisicamente em oportunidade. Ledger congela novos.
    source = o.join(e, and_(o.c.execution_id == e.c.execution_id, o.c.marca == e.c.marca))
    source = source.outerjoin(route, and_(route.c.destino == 'oportunidade', route.c.registro_id == o.c.oportunidade_id,
        route.c.execution_id == o.c.execution_id, route.c.marca == o.c.marca))
    source = source.outerjoin(r, and_(o.c.regra_id == r.c.regra_id, o.c.tipo_problema == r.c.tipo_problema,
        or_(r.c.marca == o.c.marca, r.c.marca.is_(None))))
    # Precedencia: ledger congelado -> regra vinculada por regra_id -> regra por
    # tipo_problema + marca (especifica antes da global). Nada e' decidido no frontend.
    por_tipo = lambda coluna: _regra_por_tipo(repo, coluna, o.c.tipo_problema, o.c.marca, o.c.tabela_origem)
    chosen = func.coalesce(route.c.classificacao, _classificacao_efetiva(r, o.c.tabela_origem),
                           por_tipo('classificacao'))
    # Ocorrencia encerrada pelo reprocessamento (dado corrigido) sai da fila; fica no historico.
    conditions = repo.period_conditions(filters) + [chosen == classification,
                                                    o.c.status_oportunidade != STATUS_OCORRENCIA_ENCERRADA]
    if classification == 'OPORTUNIDADE':
        conditions.append(_condicao_regras_liberadas(
            regras_de_oportunidade_liberadas(repo), o.c.marca, e.c.operacao, o.c.tipo_problema))
    if not filters.incluir_legado:
        conditions.append(route.c.achado_id.is_not(None))
    branches.append(select(
        o.c.oportunidade_id.label('id'),
        case((route.c.achado_id.is_not(None), 'OPORTUNIDADE'), else_='OPORTUNIDADE_LEGADO').label('origem_registro'),
        chosen.label('classificacao'),
        case((route.c.achado_id.is_not(None), 'CATALOGO_NA_GRAVACAO'),
             (r.c.regra_id.is_not(None), 'CATALOGO_POR_REGRA_ID'),
             else_='CATALOGO_POR_TIPO_MARCA').label('criterio_classificacao'),
        o.c.execution_id, o.c.marca,
        func.coalesce(o.c.regra_id, por_tipo('regra_id')).label('regra_id'),
        o.c.tipo_problema, o.c.data_referencia,
        o.c.colaborador, o.c.colaborador_id_interno, o.c.descricao_detalhada.label('descricao'),
        func.coalesce(r.c.severidade_padrao, por_tipo('severidade_padrao'), o.c.severidade).label('severidade'),
        o.c.status_oportunidade.label('status'), null().label('campo'),
        case((route.c.achado_id.is_not(None), route.c.regra_snapshot['tratamento_esperado'].as_string()),
            else_=func.coalesce(r.c.tratamento_esperado, por_tipo('tratamento_esperado'))).label('tratativa'),
        o.c.evidencia, route.c.regra_snapshot, o.c.identificada_em.label('registrado_em')
    ).select_from(source).where(*conditions))

    if classification == 'ALERTA':
        source = a.join(e, and_(a.c.execution_id == e.c.execution_id, a.c.marca == e.c.marca)).join(route, and_(
            route.c.destino == 'alerta', route.c.registro_id == a.c.alerta_id, route.c.marca == a.c.marca,
            route.c.execution_id == a.c.execution_id, route.c.classificacao == 'ALERTA'))
        source = source.outerjoin(r, and_(a.c.regra_id == r.c.regra_id, a.c.tipo_problema == r.c.tipo_problema,
            or_(r.c.marca == a.c.marca, r.c.marca.is_(None))))
        branches.append(select(a.c.alerta_id.label('id'), literal('ALERTA').label('origem_registro'),
            route.c.classificacao, literal('CATALOGO_NA_GRAVACAO').label('criterio_classificacao'),
            a.c.execution_id, a.c.marca, a.c.regra_id, a.c.tipo_problema, a.c.data_referencia,
            a.c.colaborador, a.c.colaborador_id_interno, a.c.descricao_detalhada.label('descricao'),
            func.coalesce(r.c.severidade_padrao, a.c.severidade).label('severidade'),
            a.c.status_alerta.label('status'), a.c.campo, a.c.tratativa, a.c.evidencia, route.c.regra_snapshot,
            a.c.identificada_em.label('registrado_em')).select_from(source).where(*repo.period_conditions(filters)))

    if classification == 'TELEMETRIA':
        source = event.join(e, event.c.execution_id == e.c.execution_id).outerjoin(route, and_(
            route.c.destino == 'execucao_evento', route.c.registro_id == cast(event.c.id, String),
            route.c.execution_id == event.c.execution_id, route.c.marca == e.c.marca))
        conditions = repo.period_conditions(filters) + [or_(route.c.classificacao == 'TELEMETRIA',
            and_(route.c.achado_id.is_(None), event.c.categoria == 'TELEMETRIA'))]
        if not filters.incluir_legado:
            conditions.append(route.c.achado_id.is_not(None))
        branches.append(select(cast(event.c.id, String).label('id'), literal('EXECUCAO_EVENTO').label('origem_registro'),
            literal('TELEMETRIA').label('classificacao'), case((route.c.achado_id.is_not(None), 'CATALOGO_NA_GRAVACAO'),
                else_='CATEGORIA_EVENTO_LEGADO').label('criterio_classificacao'), event.c.execution_id, e.c.marca,
            route.c.regra_id, event.c.codigo.label('tipo_problema'), null().label('data_referencia'),
            null().label('colaborador'), null().label('colaborador_id_interno'), event.c.mensagem.label('descricao'),
            event.c.nivel.label('severidade'), null().label('status'), null().label('campo'), null().label('tratativa'),
            event.c.contexto.label('evidencia'), route.c.regra_snapshot, event.c.ocorrido_em.label('registrado_em')
        ).select_from(source).where(*conditions))
    combined = union_all(*branches).subquery()
    conditions = _filtros_combinados(filters, combined)
    return repo.page(select(combined).where(*conditions).order_by(combined.c.registrado_em.desc(),
        combined.c.origem_registro, combined.c.id), filters)


def _catalogo_por_tipo(repo):
    """Regra ATIVA vigente por (tipo, marca), marca especifica antes da global."""
    rt = repo.tables['regra_tratativa']
    linhas = repo.rows(
        select(rt)
        .where(rt.c.status_regra == 'ATIVA')
        .order_by(case((rt.c.marca.is_(None), 1), else_=0), rt.c.prioridade, rt.c.regra_id)
    )
    catalogo = {}
    for linha in linhas:
        catalogo.setdefault((linha['tipo_problema'], linha['marca']), linha)
    return catalogo


def _linhas_operacionais(repo, filters, classificacao):
    """Current catalog projection; immutable historical routes remain available separately."""
    catalogo = _catalogo_por_tipo(repo)
    liberadas = regras_de_oportunidade_liberadas(repo) if classificacao == 'OPORTUNIDADE' else None
    e = repo.tables['execucao']
    context = repo.tables['execucao_contexto']
    reviews = repo.tables['achado_revisao']
    revisoes = {}
    for r in repo.rows(select(reviews).order_by(reviews.c.id)):
        revisoes[(r['origem_registro'], r['registro_id'], r['marca'], r['execution_id'])] = r
    linhas = []
    for name, id_column in (('oportunidade', 'oportunidade_id'), ('alerta', 'alerta_id')):
        t = repo.tables[name]
        condicoes = _filtros_de_linha(t, filters, repo.period_conditions(filters))
        if name == 'oportunidade':
            condicoes.append(t.c.status_oportunidade != STATUS_OCORRENCIA_ENCERRADA)
        condicoes.append(~select(context.c.execution_id).where(context.c.execution_id == e.c.execution_id,
            context.c.marca == e.c.marca, context.c.finalidade == 'VALIDACAO').exists())
        if filters.periodo_inicio and classificacao != 'TELEMETRIA':
            condicoes.append(or_(t.c.data_referencia.is_(None), t.c.data_referencia >= filters.periodo_inicio))
        if filters.periodo_fim and classificacao != 'TELEMETRIA':
            condicoes.append(or_(t.c.data_referencia.is_(None), t.c.data_referencia <= filters.periodo_fim))
        if not filters.incluir_legado:
            route = repo.tables['achado_roteamento']
            condicoes.append(select(route.c.achado_id).where(route.c.registro_id == t.c[id_column],
                route.c.destino == name, route.c.marca == t.c.marca,
                route.c.execution_id == t.c.execution_id).exists())
        consulta = select(*_colunas_evento(t, id_column), e.c.operacao).select_from(
            t.join(e, and_(t.c.execution_id == e.c.execution_id, t.c.marca == e.c.marca))).where(*condicoes)
        for linha in _limitar(repo, consulta):
            regra = _regra_do_grupo(catalogo, linha['tipo_problema'], linha['marca'])
            classe, motivo = assess(regra, linha)
            revisao = revisoes.get((name, linha['registro_id'], linha['marca'], linha['execution_id']))
            if revisao:
                classe, motivo = revisao['classificacao'], revisao['motivo']
            if classe != classificacao:
                continue
            if liberadas is not None and linha['tipo_problema'] not in liberadas.get(
                    (linha['marca'], linha.get('operacao') or 'EXCLUSIVA'), ()):
                continue
            if filters.severidade and (regra.get('severidade_padrao') or 'MEDIA').upper() != filters.severidade.upper():
                continue
            linha['criterio_operacional'] = motivo
            linha['origem_registro'] = name
            linhas.append(linha)
    return linhas


def telemetry_page(repo, filters):
    """Technical feed includes reviewed historical findings, events and raw fallbacks."""
    records = []
    catalog = _catalogo_por_tipo(repo)
    for row in _linhas_operacionais(repo, filters, 'TELEMETRIA'):
        rule = _regra_do_grupo(catalog, row['tipo_problema'], row['marca'])
        records.append(dict(id=row['registro_id'], origem_registro='OPORTUNIDADE_LEGADO' if row['origem_registro']=='oportunidade' else 'ALERTA',
            classificacao='TELEMETRIA', criterio_classificacao=row['criterio_operacional'],
            execution_id=row['execution_id'], marca=row['marca'], regra_id=rule.get('regra_id'),
            tipo_problema=row['tipo_problema'], data_referencia=row['data_referencia'],
            colaborador=row['colaborador'], colaborador_id_interno=row['colaborador_id_interno'],
            descricao=row['criterio_operacional'], severidade=row['severidade'], status=None,
            campo=campo_do_registro(row['evidencia']) or None, tratativa=None, evidencia=row['evidencia'],
            regra_snapshot=None, registrado_em=row['identificada_em']))
    e, context, route = (repo.tables[name] for name in (
        'execucao', 'execucao_contexto', 'achado_roteamento'))
    for name, id_field, code, description, severity, evidence in (
            ('execucao_evento','id','codigo','mensagem','nivel','contexto'),
            ('fallback_evento','fallback_id','codigo','motivo','severidade','contexto')):
        t = repo.tables[name]
        conditions = repo.period_conditions(filters)
        conditions.append(~select(context.c.execution_id).where(context.c.execution_id == e.c.execution_id,
            context.c.marca == e.c.marca, context.c.finalidade == 'VALIDACAO').exists())
        if name == 'execucao_evento':
            conditions.append(t.c.categoria != 'CONFIGURACAO')
        if filters.tipo:
            conditions.append(t.c[code] == filters.tipo)
        if filters.execution_id:
            conditions.append(t.c.execution_id == filters.execution_id)
        source = t.join(e, t.c.execution_id == e.c.execution_id)
        route_snapshot = null().label('regra_snapshot')
        route_regra_id = null().label('rota_regra_id')
        if name == 'execucao_evento':
            # Eventos provenientes do dispatcher preservam a decisao congelada no
            # roteamento. Eventos tecnicos nativos continuam sem snapshot.
            source = source.outerjoin(route, and_(
                route.c.destino == 'execucao_evento',
                route.c.registro_id == cast(t.c.id, String),
                route.c.execution_id == t.c.execution_id,
                route.c.marca == e.c.marca,
            ))
            route_snapshot = route.c.regra_snapshot
            route_regra_id = route.c.regra_id.label('rota_regra_id')
        for row in _limitar(repo, select(t, e.c.marca, route_snapshot, route_regra_id).select_from(source).where(*conditions)):
            records.append(dict(id=str(row[id_field]), origem_registro=name.upper(), classificacao='TELEMETRIA',
                criterio_classificacao='EVENTO_TECNICO', execution_id=row['execution_id'], marca=row['marca'],
                regra_id=row['rota_regra_id'],tipo_problema=row[code],data_referencia=None,colaborador=None,colaborador_id_interno=None,
                descricao=row[description],severidade=row[severity],status=None,campo=None,tratativa=None,
                evidencia=row[evidence],regra_snapshot=row['regra_snapshot'],registrado_em=row['ocorrido_em']))
    if filters.severidade:
        records = [r for r in records if r['severidade'].upper() == filters.severidade.upper()]
    if filters.colaborador:
        records = [r for r in records if filters.colaborador.upper() in (r['colaborador'] or '').upper()
                   or r['colaborador_id_interno'] == filters.colaborador]
    if filters.regra:
        records = [r for r in records if r['regra_id'] == filters.regra]
    records.sort(key=lambda r: (r['registrado_em'],r['origem_registro'],r['id']), reverse=True)
    return _pagina_em_memoria(records, filters)


def _regra_do_grupo(catalogo, tipo_problema, marca):
    return catalogo.get((tipo_problema, marca)) or catalogo.get((tipo_problema, None)) or {}


def _textos_de_negocio(regra, tipo_problema, tabela_origem):
    """Linguagem do lider vem do catalogo; sem texto cadastrado, nada e' inventado.

    Na origem de excecao da regra (a mesma que muda a classificacao) valem os textos de
    excecao, para a mensagem nunca contradizer a classificacao exibida.
    """
    excecao = (bool(regra.get('origem_excecao')) and regra.get('origem_excecao') == tabela_origem
               and bool(regra.get('impacto_negocio_excecao')))
    # Com texto de excecao cadastrado, ele e' autoritativo inteiro: acao nula significa
    # "sem acao" (ex.: telemetria) e nunca herda a acao operacional da regra base.
    impacto = regra.get('impacto_negocio_excecao') if excecao else regra.get('impacto_negocio')
    acao = regra.get('acao_recomendada_excecao') if excecao else regra.get('acao_recomendada')
    return dict(
        titulo=regra.get('titulo_exibicao') or regra.get('titulo') or tipo_problema,
        impacto=impacto or regra.get('tratamento_esperado'),
        acao_recomendada=acao,
        severidade=(regra.get('severidade_padrao') or 'MEDIA'),
    )


def _filtros_de_linha(tabela, filters, condicoes):
    if filters.tipo is not None:
        condicoes.append(tabela.c.tipo_problema == filters.tipo)
    if filters.regra is not None:
        condicoes.append(tabela.c.regra_id == filters.regra)
    if filters.colaborador is not None:
        alvo = filters.colaborador.strip()
        condicoes.append(or_(tabela.c.colaborador_id_interno == alvo,
                             func.upper(tabela.c.colaborador).like('%' + alvo.upper() + '%')))
    return condicoes


def _fonte_historico(repo, filters, classificacao_alvo):
    """Linhas de `oportunidade` (historico) na classificacao pedida, mesma precedencia dos endpoints."""
    tables = repo.tables
    o, e, r, route = (tables[n] for n in ('oportunidade', 'execucao', 'regra_tratativa', 'achado_roteamento'))
    source = o.join(e, and_(o.c.execution_id == e.c.execution_id, o.c.marca == e.c.marca))
    source = source.outerjoin(route, and_(
        route.c.destino == 'oportunidade', route.c.registro_id == o.c.oportunidade_id,
        route.c.execution_id == o.c.execution_id, route.c.marca == o.c.marca))
    source = source.outerjoin(r, and_(
        o.c.regra_id == r.c.regra_id, o.c.tipo_problema == r.c.tipo_problema,
        or_(r.c.marca == o.c.marca, r.c.marca.is_(None))))
    classificacao = func.coalesce(
        route.c.classificacao,
        _classificacao_efetiva(r, o.c.tabela_origem),
        _regra_por_tipo(repo, 'classificacao', o.c.tipo_problema, o.c.marca, o.c.tabela_origem),
    )
    condicoes = repo.period_conditions(filters) + [classificacao == classificacao_alvo]
    if not filters.incluir_legado:
        condicoes.append(route.c.achado_id.is_not(None))
    return o, source, _filtros_de_linha(o, filters, condicoes)


def _colunas_evento(tabela, id_coluna):
    return (tabela.c.marca, tabela.c.tipo_problema, tabela.c.colaborador_id_interno, tabela.c.colaborador,
            tabela.c.tabela_origem, tabela.c.fingerprint, tabela.c.evidencia, tabela.c.data_referencia,
            tabela.c.identificada_em, tabela.c.execution_id, tabela.c.origem, tabela.c.severidade,
            tabela.c[id_coluna].label('registro_id'))


def _limitar(repo, consulta):
    linhas = repo.rows(consulta.limit(MAX_REGISTROS_AGRUPAMENTO + 1))
    if len(linhas) > MAX_REGISTROS_AGRUPAMENTO:
        raise HTTPException(422, 'Refine marca, periodo ou regra: limite de registros para consolidacao excedido.')
    return linhas


def _tipos_da_severidade(catalogo, severidade):
    alvo = severidade.upper()
    return sorted({tipo for (tipo, _marca), regra in catalogo.items()
                   if (regra['severidade_padrao'] or 'MEDIA').upper() == alvo})


def _agrupar(linhas, classificacao):
    """Um grupo por problema operacional. Ocorrencia e' contador, nunca novo card.

    A mesma evidencia regravada por dia de processamento, execucao ou repeticao
    compartilha o fingerprint e conta uma unica vez; as regravacoes ficam em
    `registros_historicos`.
    """
    grupos = {}
    for linha in linhas:
        campo = campo_do_registro(linha['evidencia'])
        chave = (linha['marca'], linha['tipo_problema'], linha['colaborador_id_interno'],
                 None if linha['colaborador_id_interno'] else linha['colaborador'], linha['tabela_origem'], campo, linha.get('operacao') or 'EXCLUSIVA')
        grupo = grupos.get(chave)
        if grupo is None:
            grupo = grupos[chave] = dict(chave=chave, campo=campo or None, evidencias={}, registros=0,
                                         dias=set(), primeira=None, ultima=None, ultima_identificacao=None,
                                         colaborador_exibicao=linha['colaborador'], evidencia_referencia=None)
        grupo['registros'] += 1
        if linha['fingerprint'] not in grupo['evidencias']:
            grupo['evidencias'][linha['fingerprint']] = occurrence_count(
                dict(tipo_problema=linha['tipo_problema'], classificacao=classificacao, evidencia=linha['evidencia']))
        dia = linha['data_referencia']
        if dia:
            grupo['dias'].add(dia)
            grupo['primeira'] = min(grupo['primeira'] or dia, dia)
            grupo['ultima'] = max(grupo['ultima'] or dia, dia)
        identificada = linha['identificada_em']
        if identificada and (grupo['ultima_identificacao'] is None or identificada > grupo['ultima_identificacao']):
            grupo['ultima_identificacao'] = identificada
        # A prova exibida no card e' a da ocorrencia mais recente do grupo.
        if grupo['evidencia_referencia'] is None or (
                identificada and identificada == grupo['ultima_identificacao']):
            grupo['evidencia_referencia'] = linha['evidencia']
    return grupos


def _base_card(grupo, catalogo):
    # Import local: `evidence_repository` depende deste modulo (ciclo na carga).
    from .evidence_repository import evidencia_resumida, resumo_validacao
    marca, tipo, colaborador_id, colaborador, origem, campo, operacao = grupo['chave']
    regra = _regra_do_grupo(catalogo, tipo, marca)
    return dict(
        grupo_id=codificar_grupo(marca, tipo, colaborador_id, colaborador, origem, campo, operacao),
        marca=marca, operacao=operacao, tipo_problema=tipo, colaborador=grupo['colaborador_exibicao'], campo=grupo['campo'], origem=origem,
        registros_historicos=grupo['registros'], dias_afetados=len(grupo['dias']),
        primeira_ocorrencia=grupo['primeira'], ultima_ocorrencia=grupo['ultima'],
        # Toda linha exibida carrega de onde veio e se a prova foi comprovada.
        evidencia=evidencia_resumida(grupo['evidencia_referencia'], grupo['campo']),
        validacao=resumo_validacao(grupo['evidencia_referencia']),
        **_textos_de_negocio(regra, tipo, origem),
    )


def _status_efetivo(estado, ultima_identificacao):
    """Reabre sozinho: ocorrencia identificada depois da resolucao volta para a fila."""
    if not estado:
        return 'ABERTA'
    atual = estado['status_operacional']
    resolvido_em = estado.get('resolvido_em')
    if atual == 'RESOLVIDA' and resolvido_em and ultima_identificacao and ultima_identificacao > resolvido_em:
        return 'REABERTA'
    return atual


def _pagina_em_memoria(itens, filters):
    total = len(itens)
    inicio = (filters.pagina - 1) * filters.tamanho
    return dict(items=itens[inicio:inicio + filters.tamanho], total=total,
                pagina=filters.pagina, tamanho=filters.tamanho,
                paginas=math.ceil(total / filters.tamanho) if total else 0)


def _ordenar(cards, contador):
    cards.sort(key=lambda card: (ORDEM_SEVERIDADE.get(card['severidade'].upper(), 9),
                                 -card[contador], card['tipo_problema'], card['colaborador'] or '',
                                 card['campo'] or ''))
    return cards


def opportunity_summary(repo, filters):
    """Fila operacional: um card por problema (marca + regra + colaborador + contexto)."""
    resolver_periodo(filters, repo)
    catalogo = _catalogo_por_tipo(repo)
    grupos = _agrupar(_linhas_operacionais(repo, filters, 'OPORTUNIDADE'), 'OPORTUNIDADE')
    if len(grupos) > MAX_GRUPOS:
        raise HTTPException(422, 'Refine marca, periodo ou regra: limite de grupos operacionais excedido.')

    estados = {linha['grupo_id']: linha
               for linha in repo.rows(select(repo.tables['oportunidade_grupo_status']))}
    cards = []
    for grupo in grupos.values():
        card = _base_card(grupo, catalogo)
        estado = estados.get(card['grupo_id'])
        card.update(quantidade=sum(grupo['evidencias'].values()),
                    status_operacional=_status_efetivo(estado, grupo['ultima_identificacao']),
                    responsavel=(estado or {}).get('responsavel') or
                        _regra_do_grupo(catalogo, card['tipo_problema'], card['marca']).get('responsavel_padrao'))
        cards.append(card)
    if filters.status is not None:
        cards = [card for card in cards if card['status_operacional'] == filters.status]
    elif not filters.incluir_encerradas:
        cards = [card for card in cards if card['status_operacional'] not in STATUS_ENCERRADOS]
    return _pagina_em_memoria(_ordenar(cards, 'quantidade'), filters)


def alert_summary(repo, filters):
    """Alertas consolidados por problema (marca + regra + colaborador + contexto).

    Le o historico legado classificado como ALERTA e a tabela `alerta` do roteamento.
    Linha historica nunca vira card; o bloco `resumo` cobre todos os grupos do filtro
    (nao so a pagina), para o dashboard montar categorias em uma unica chamada.
    """
    inicio, fim = resolver_periodo(filters, repo)
    catalogo = _catalogo_por_tipo(repo)
    linhas = _linhas_operacionais(repo, filters, 'ALERTA')
    grupos = _agrupar(linhas, 'ALERTA')
    if len(grupos) > MAX_GRUPOS:
        raise HTTPException(422, 'Refine marca, periodo ou regra: limite de grupos de alerta excedido.')

    cards, por_regra, pessoas = [], {}, set()
    for grupo in grupos.values():
        card = _base_card(grupo, catalogo)
        card.update(quantidade_alertas=len(grupo['evidencias']),
                    ocorrencias_acumuladas=sum(grupo['evidencias'].values()))
        cards.append(card)
        marca, tipo, colaborador_id, colaborador = grupo['chave'][:4]
        pessoa = (marca, colaborador_id or colaborador) if (colaborador_id or colaborador) else None
        if pessoa:
            pessoas.add(pessoa)
        regra = por_regra.setdefault(tipo, dict(tipo_problema=tipo, titulo=card['titulo'], severidade=card['severidade'],
                                                 grupos=0, alertas=0, ocorrencias_acumuladas=0, pessoas=set()))
        regra['grupos'] += 1
        regra['alertas'] += card['quantidade_alertas']
        regra['ocorrencias_acumuladas'] += card['ocorrencias_acumuladas']
        if pessoa:
            regra['pessoas'].add(pessoa)
    categorias = sorted(({**{k: v for k, v in regra.items() if k != 'pessoas'},
                          'colaboradores_afetados': len(regra['pessoas'])} for regra in por_regra.values()),
                        key=lambda item: (-item['alertas'], item['tipo_problema']))
    pagina = _pagina_em_memoria(_ordenar(cards, 'quantidade_alertas'), filters)
    pagina['resumo'] = dict(
        periodo={'inicio': inicio, 'fim': fim},
        grupos=len(cards),
        alertas=sum(card['quantidade_alertas'] for card in cards),
        ocorrencias_acumuladas=sum(card['ocorrencias_acumuladas'] for card in cards),
        colaboradores_afetados=len(pessoas),
        por_regra=categorias,
    )
    return pagina


def group_details(repo, grupo_id, filters):
    """Ocorrencias individuais do grupo: datas, origem, evidencia e execution_id."""
    inicio, fim = resolver_periodo(filters, repo)
    marca, tipo_problema, colaborador_id, colaborador, tabela_origem, campo, operacao = decodificar_grupo(grupo_id)
    if filters.marca and filters.marca != marca or filters.operacao and filters.operacao != operacao:
        raise HTTPException(404, 'Grupo fora do escopo solicitado.')
    escopo = filters.model_copy(update={'tipo': tipo_problema, 'marca': marca, 'colaborador': None,
                                        'operacao': operacao, 'severidade': None, 'status': None, 'regra': None})
    linhas = [linha for linha in _linhas_operacionais(repo, escopo, 'OPORTUNIDADE')
              if (campo_do_registro(linha['evidencia']) or None) == campo
              and linha['colaborador_id_interno'] == colaborador_id and (colaborador_id or linha['colaborador'] == colaborador)
              and linha['tabela_origem'] == tabela_origem]
    if not linhas:
        raise HTTPException(404, 'Grupo operacional nao encontrado neste periodo.')
    linhas.sort(key=lambda row: (row['data_referencia'] or date.min, row['identificada_em'], row['registro_id']), reverse=True)
    if len(linhas) > MAX_OCORRENCIAS:
        raise HTTPException(422, 'Refine o periodo: limite de ocorrencias do grupo excedido.')

    # Uma ocorrencia por fingerprint; as regravacoes por execucao viram `repeticoes`.
    unicas = {}
    for linha in linhas:
        existente = unicas.get(linha['fingerprint'])
        if existente:
            existente['repeticoes'] += 1
            continue
        unicas[linha['fingerprint']] = dict(
            fingerprint=linha['fingerprint'], oportunidade_id=linha['registro_id'],
            execution_id=linha['execution_id'], data_referencia=linha['data_referencia'],
            tabela_origem=linha['tabela_origem'], origem=linha['origem'], severidade=linha['severidade'],
            evidencia=linha['evidencia'], identificada_em=linha['identificada_em'], repeticoes=1)
    ocorrencias = list(unicas.values())

    status = repo.tables['oportunidade_grupo_status']
    estado = next(iter(repo.rows(select(status).where(status.c.grupo_id == grupo_id))), None)
    ultima = max((linha['identificada_em'] for linha in linhas), default=None)
    regra = _regra_do_grupo(_catalogo_por_tipo(repo), tipo_problema, marca)
    textos = _textos_de_negocio(regra, tipo_problema, tabela_origem)
    return dict(
        grupo_id=grupo_id, marca=marca, operacao=operacao, tipo_problema=tipo_problema, titulo=textos['titulo'],
        colaborador=linhas[0]['colaborador'], colaborador_id_interno=colaborador_id, campo=campo, origem=tabela_origem,
        quantidade=sum(occurrence_count(dict(tipo_problema=tipo_problema, classificacao='OPORTUNIDADE', evidencia=r['evidencia']))
                       for r in ocorrencias), impacto=textos['impacto'], acao_recomendada=textos['acao_recomendada'],
        status_operacional=_status_efetivo(estado, ultima),
        periodo={'inicio': inicio, 'fim': fim},
        ocorrencias=_pagina_em_memoria(ocorrencias, filters),
    )


def _total(repo, filters, classification, **override):
    """Total de uma classificacao reaproveitando exatamente o mesmo filtro do endpoint."""
    from .finding_models import GroupFilter
    consulta = filters.model_copy(update=override)
    if classification in ('OPORTUNIDADE', 'ALERTA'):
        group = GroupFilter(**{k: v for k, v in consulta.model_dump().items() if k in GroupFilter.model_fields})
        return (opportunity_summary if classification == 'OPORTUNIDADE' else alert_summary)(repo, group)['total']
    return finding_page(repo, consulta, classification)['total']


def finding_resumo(repo, filters):
    """Agrega os cards do dashboard numa unica resposta, evitando N chamadas.

    Usa a mesma resolucao de periodo e os mesmos filtros dos endpoints individuais,
    de modo que os totais batem com /oportunidades, /alertas e /telemetria.
    """
    inicio, fim = resolver_periodo(filters, repo)
    base = filters.model_copy(update={'periodo': None, 'periodo_inicio': inicio, 'periodo_fim': fim})
    from .finding_models import GroupFilter
    group_filters = GroupFilter(**{k: v for k, v in base.model_dump().items() if k in GroupFilter.model_fields})
    all_groups = opportunity_summary(repo, group_filters.model_copy(update={'pagina': 1, 'tamanho': MAX_GRUPOS}))
    oportunidades = {'total': all_groups['total'], **{severity: sum(
        g['severidade'].lower() == severity for g in all_groups['items']) for severity in ('critica','alta','media','baixa')}}
    return {
        'oportunidades': oportunidades,
        'alertas': {'total': _total(repo, base, 'ALERTA')},
        'telemetria': {'total': _total(repo, base, 'TELEMETRIA')},
        'periodo': {'inicio': inicio, 'fim': fim},
    }
