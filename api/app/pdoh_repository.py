"""Indicador PDOH oficial: consolida e expoe, nunca recalcula nem estima.

FONTE
    A Platina gerada pelo processador travado no manifesto
    (``produtos_platina.exclusivo_bracell_platina_relatorio_pdoh``), com uma linha por
    colaborador e por dia. Esta API le essa tabela e nada mais; oportunidades, alertas e
    telemetria jamais entram em indicador.

REGRA DE CONSOLIDACAO
    Nao foi inventada aqui: e' a mesma do processador ``bracell/pdoh_bracell.py``, que ao
    montar a linha "TOTAL" do relatorio usa razao de somas -- nunca media de percentuais:

        PPROD   = SUM(produtividade)         / SUM(horas_programadas)   (l. 1751-1754)
        POCIO   = SUM(ocio)                  / SUM(horas_programadas)   (l. 1746-1749)
        PDESLOC = SUM(deslocamento)          / SUM(horas_programadas)   (l. 1741-1744)
        PHNR    = SUM(horas_nao_registradas) / SUM(horas_programadas)   (l. 1756-1759)
        MdVST   = SUM(visitas_realizadas)    / SUM(visitas)             (l. 1805-1808)
        MdPSQ   = SUM(pesquisas_realizadas)  / SUM(pesquisas)           (l. 1810-1813)
        efetividade = (PPROD*40 + MdVST*30 + MdPSQ*30) / 100            (l. 1869-1873)

    Os pesos 40/30/30 vem de ``bases_fixas/VALORES BASE DO CALCULO.xlsx`` (tambem travado
    no manifesto) e estao replicados em ``PESOS_EFETIVIDADE`` apenas para leitura.

DIVERGENCIA DELIBERADA
    Quando SUM(horas_programadas) e' zero o processador grava 0 na planilha. Uma API que
    devolvesse 0 estaria publicando um numero que se confunde com desempenho real, entao
    aqui a resposta e' ``disponivel=false`` com o motivo. Nenhum outro ponto diverge.
"""
import base64
import math
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import distinct, func, or_, select

from .daily_validation import (COLUNAS_JUSTIFICATIVA, chave_dia, classificar_dia, consolidar, justificativa_do_dia,
                               oportunidades_do_periodo, saidas_configuradas)
from .findings_repository import resolver_periodo

# Pesos oficiais de `bases_fixas/VALORES BASE DO CALCULO.xlsx` (Produtividade/Visitas/Pesquisas).
PESOS_EFETIVIDADE = {'produtividade': 40.0, 'visitas': 30.0, 'pesquisas': 30.0}
INDICADOR_PDOH = 'percentual_produtividade'
FORMULA_PDOH = 'SUM(produtividade) / SUM(horas_programadas)'
FONTE_PDOH = 'PLATINA'
SEMANA_OPERACIONAL = 'segunda a sabado (domingo nao e dia operacional)'

COLUNAS_TEMPO = ('produtividade', 'ocio', 'deslocamento', 'horas_nao_registradas', 'horas_programadas')
COLUNAS_CONTAGEM = ('visitas_diarias', 'visitas_diarias_realizadas',
                    'pesquisas_diarias', 'pesquisas_diarias_realizadas')
COLUNAS_PERCENTUAIS = ('percentual_produtividade', 'percentual_efetividade',
                       'percentual_visitas', 'percentual_pesquisas')
# Composicao exposta ao painel: parte da jornada / horas programadas.
COMPOSICAO = ('produtividade', 'ocio', 'deslocamento', 'horas_nao_registradas')
# Teto de leitura: acima disso a resposta explica em vez de varrer a Platina inteira.
MAX_LINHAS_PLATINA = 200_000
SEPARADOR_COLABORADOR = '\x1f'

MOTIVO_SEM_MARCA = 'O PDOH é apurado por marca: informe a marca para consultar o indicador.'
MOTIVO_SEM_FONTE = 'Não há fonte oficial do PDOH acessível para esta marca.'
MOTIVO_SEM_DADOS = 'Não há registros oficiais do PDOH no período selecionado.'
MOTIVO_SEM_JORNADA = (
    'A fonte oficial não registra horas programadas no período; sem essa base o percentual '
    'não é calculável e nenhum valor é publicado.'
)
MOTIVO_SEM_META = 'Não há meta de PDOH cadastrada na configuração da operação.'
MOTIVO_EXCESSO = (
    'O período selecionado excede o volume máximo de leitura da fonte oficial. '
    'Reduza o intervalo para consultar o indicador.'
)


def _colunas_faltantes(tabela):
    exigidas = set(COLUNAS_TEMPO) | set(COLUNAS_CONTAGEM) | {'colaborador', 'data'}
    return sorted(exigidas - set(tabela.c.keys()))


def chave_fonte_pdoh(marca):
    return f'platina_pdoh:{marca.upper()}'


def codificar_colaborador(marca, nome):
    """Identificador opaco e estavel. Nao carrega UUID interno nem chave tecnica."""
    bruto = SEPARADOR_COLABORADOR.join([(marca or '').upper(), nome or ''])
    return base64.urlsafe_b64encode(bruto.encode('utf-8')).decode('ascii').rstrip('=')


def decodificar_colaborador(identificador):
    try:
        preenchido = identificador + '=' * (-len(identificador) % 4)
        bruto = base64.urlsafe_b64decode(preenchido.encode('ascii')).decode('utf-8')
    except Exception:
        return None
    partes = bruto.split(SEPARADOR_COLABORADOR)
    return (partes[0] or None, partes[1]) if len(partes) == 2 and partes[1] else None


def _segundos(valor):
    """Converte TIME/timedelta/'HH:MM:SS'/numero em segundos. NULL conta como zero.

    O processador soma com pandas, que ignora nulos -- o efeito e' o mesmo.
    """
    if valor is None:
        return 0
    if isinstance(valor, timedelta):
        return int(valor.total_seconds())
    if isinstance(valor, (int, float)):
        return int(valor)
    if hasattr(valor, 'hour'):   # datetime.time
        return valor.hour * 3600 + valor.minute * 60 + valor.second
    texto = str(valor).strip()
    if not texto:
        return 0
    sinal = -1 if texto.startswith('-') else 1
    partes = texto.lstrip('-').split(':')
    try:
        numeros = [float(parte) for parte in partes]
    except ValueError:
        return 0
    while len(numeros) < 3:
        numeros.append(0.0)
    return sinal * int(numeros[0] * 3600 + numeros[1] * 60 + numeros[2])


def _fonte_vazia():
    return dict(tabela=None, acessivel=False, registros_no_periodo=0, colaboradores_no_periodo=0,
                dias_no_periodo=0, indicadores_disponiveis=[], disponivel_de=None, disponivel_ate=None)


def _nome_tabela(tabela):
    return f'{tabela.schema}.{tabela.name}' if tabela.schema else tabela.name


def _limites_da_fonte(repo, tabela):
    """Primeiro e ultimo dia da fonte oficial, sem nenhum filtro."""
    c = tabela.c
    linha = repo.rows(select(func.min(c.data).label('de'), func.max(c.data).label('ate')))[0]
    return linha['de'], linha['ate']


def _fonte(repo, tabela, cobertura):
    de, ate = _limites_da_fonte(repo, tabela)
    return dict(tabela=_nome_tabela(tabela), acessivel=True,
                registros_no_periodo=cobertura['registros'],
                colaboradores_no_periodo=cobertura['colaboradores'],
                dias_no_periodo=cobertura['dias'],
                indicadores_disponiveis=[nome for nome in COLUNAS_PERCENTUAIS if nome in tabela.c],
                disponivel_de=de, disponivel_ate=ate)


def _janela(repo, filters, tabela):
    """Janela do pedido. Devolve (inicio, fim, automatica).

    ``periodo=automatico`` usa a semana operacional (segunda a sabado) do ultimo dia com
    dados na Platina: o painel abre em numeros reais mesmo quando a semana anterior ainda
    nao foi processada. Escolha explicita de periodo nunca e' substituida.
    """
    if filters.periodo == 'automatico':
        if tabela is not None:
            _, ate = _limites_da_fonte(repo, tabela)
            if ate is not None:
                inicio = ate - timedelta(days=ate.weekday())
                filters.periodo_inicio, filters.periodo_fim = inicio, inicio + timedelta(days=5)
                return filters.periodo_inicio, filters.periodo_fim, True
        filters.periodo = 'semana'   # sem fonte ou sem dados: padrao documentado
    inicio, fim = resolver_periodo(filters, repo)
    return inicio, fim, False


def _condicoes(tabela, inicio, fim, colaborador=None, estado=None):
    c = tabela.c
    condicoes = [c.data >= inicio, c.data <= fim]
    if colaborador is not None:
        condicoes.append(func.upper(c.colaborador).like('%' + colaborador.strip().upper() + '%'))
    if estado is not None:
        if 'estado' not in c:
            condicoes.append(c.data.is_(None))
        else:
            condicoes.append(func.upper(c.estado) == estado.strip().upper())
    return condicoes


def _cobertura(repo, tabela, inicio, fim, colaborador=None, estado=None):
    c = tabela.c
    condicoes = _condicoes(tabela, inicio, fim, colaborador, estado)
    return repo.rows(
        select(func.count().label('registros'),
               func.count(distinct(c.colaborador)).label('colaboradores'),
               func.count(distinct(c.data)).label('dias')).where(*condicoes)
    )[0]


def _linhas(repo, tabela, inicio, fim, colaborador=None, estado=None):
    c = tabela.c
    condicoes = _condicoes(tabela, inicio, fim, colaborador, estado)
    colunas = [c.data] + [c[nome] for nome in COLUNAS_TEMPO + COLUNAS_CONTAGEM]
    return repo.rows(select(*colunas).where(*condicoes).limit(MAX_LINHAS_PLATINA + 1))


def _totais(linhas):
    totais = {nome: 0 for nome in COLUNAS_TEMPO + COLUNAS_CONTAGEM}
    for linha in linhas:
        for nome in COLUNAS_TEMPO:
            totais[nome] += _segundos(linha[nome])
        for nome in COLUNAS_CONTAGEM:
            totais[nome] += int(linha[nome] or 0)
    return totais


def _pct(numerador, denominador):
    return None if not denominador else round(100.0 * numerador / denominador, 4)


def _consolidar(linhas):
    """Aplica a regra do processador. Devolve None quando nao ha horas programadas."""
    totais = _totais(linhas)
    programadas = totais['horas_programadas']
    if not programadas:
        return None
    composicao = {nome: _pct(totais[nome], programadas) for nome in COMPOSICAO}
    visitas = _pct(totais['visitas_diarias_realizadas'], totais['visitas_diarias'])
    pesquisas = _pct(totais['pesquisas_diarias_realizadas'], totais['pesquisas_diarias'])
    pesos = PESOS_EFETIVIDADE
    efetividade = round(
        (composicao['produtividade'] * pesos['produtividade']
         + (visitas or 0.0) * pesos['visitas']
         + (pesquisas or 0.0) * pesos['pesquisas']) / sum(pesos.values()), 4)
    return dict(composicao, visitas=visitas, pesquisas=pesquisas, efetividade=efetividade,
                pdoh=composicao['produtividade'])


def janela_anterior(inicio, fim):
    """Janela imediatamente anterior, de mesmo tamanho.

    Semana operacional (segunda a sabado) recua 7 dias para cair na semana anterior
    inteira; qualquer outra janela recua o proprio tamanho.
    """
    dias = (fim - inicio).days + 1
    passo = 7 if (dias == 6 and inicio.weekday() == 0 and fim.weekday() == 5) else dias
    return inicio - timedelta(days=passo), fim - timedelta(days=passo)


def _indicador(valor, anterior=None):
    if valor is None:
        return None
    variacao = None if anterior is None else round(valor - anterior, 4)
    return dict(valor=valor, unidade='%', variacao_periodo_anterior=variacao)


def _resolver_fonte(repo, filters):
    """Devolve (tabela, motivo). Motivo preenchido => nao ha o que consolidar."""
    if not filters.marca:
        return None, MOTIVO_SEM_MARCA
    tabela = repo.tables.get(chave_fonte_pdoh(filters.marca))
    if tabela is None:
        return None, MOTIVO_SEM_FONTE
    faltantes = _colunas_faltantes(tabela)
    if faltantes:
        return None, ('A fonte oficial não expõe as colunas necessárias para consolidar o '
                      'PDOH: ' + ', '.join(faltantes) + '.')
    return tabela, None


def _consolidado(repo, tabela, inicio, fim, colaborador=None, estado=None):
    """(consolidado, anterior, cobertura, motivo). Consolidado None => motivo preenchido."""
    cobertura = _cobertura(repo, tabela, inicio, fim, colaborador, estado)
    if not cobertura['registros']:
        return None, None, cobertura, MOTIVO_SEM_DADOS
    if cobertura['registros'] > MAX_LINHAS_PLATINA:
        return None, None, cobertura, MOTIVO_EXCESSO
    atual = _consolidar(_linhas(repo, tabela, inicio, fim, colaborador, estado))
    if atual is None:
        return None, None, cobertura, MOTIVO_SEM_JORNADA
    anterior_inicio, anterior_fim = janela_anterior(inicio, fim)
    anterior = _consolidar(_linhas(repo, tabela, anterior_inicio, anterior_fim, colaborador, estado))
    return atual, anterior, cobertura, None


def _composicao(atual, anterior):
    anterior = anterior or {}
    return {nome: _indicador(atual[nome], anterior.get(nome)) for nome in COMPOSICAO}


def _meta():
    """Meta oficial do PDOH. Nao ha cadastro na base: nunca inventar um numero."""
    return None, MOTIVO_SEM_META


def _texto_tempo(valor):
    if valor is None:
        return None
    if isinstance(valor, timedelta):
        segundos = int(valor.total_seconds())
        sinal = '-' if segundos < 0 else ''
        segundos = abs(segundos)
        return f'{sinal}{segundos // 3600:02d}:{segundos % 3600 // 60:02d}:{segundos % 60:02d}'
    return str(valor)


def _pagina_vazia(filters):
    return dict(items=[], total=0, pagina=filters.pagina, tamanho=filters.tamanho, paginas=0)


def _opcoes_filtro(repo, tabela, inicio, fim):
    c = tabela.c
    condicoes = [c.data >= inicio, c.data <= fim]
    colaboradores = [linha['colaborador'] for linha in repo.rows(
        select(distinct(c.colaborador).label('colaborador')).where(*condicoes)
        .order_by(c.colaborador).limit(2000)) if linha['colaborador']]
    estados = []
    if 'estado' in c:
        estados = [linha['estado'] for linha in repo.rows(
            select(distinct(c.estado).label('estado')).where(*condicoes, c.estado.is_not(None))
            .order_by(c.estado).limit(100)) if linha['estado']]
    return dict(colaboradores=colaboradores, estados=estados)


ROTULO_FONTE_JORNADA = {
    'colaboradores_ativos_bracell': 'Cadastro Involves',
    'raw_exclusivo_bracell_colaboradores_ativos': 'RAW operacional',
}
MOTIVOS_JORNADA_NAO_RESOLVIDA = {
    'FORA_ESCOPO': 'Colaborador inativo ou fora do perfil operacional; sem fallback.',
    'CONFLITO': 'Fontes oficiais com horas divergentes; cadastro a corrigir, sem fallback.',
    'RESOLUCAO_INCOMPLETA': 'Fontes oficiais incompletas; sem fallback.',
}


def _json_de(valor):
    if isinstance(valor, str):
        import json
        try:
            return json.loads(valor)
        except ValueError:
            return {}
    return valor or {}


def _chave_nome(nome):
    return ' '.join(str(nome or '').upper().split())


def _auditoria_jornada(repo, marca, inicio, fim):
    """Jornada de cada linha diaria, lida da resolucao oficial ja gravada (nada e' recalculado).

    Resolucao: a versao de `jornada_consolidada` vigente na DATA da linha (maior data de referencia
    ate a data; empate = registro mais recente). Fallback de jornada = o que a resolucao decide
    (NAO_ENCONTRADA com colaborador ativo e elegivel -> jornada padrao). O fallback proprio do
    processador PDOH (`fallback_evento` JORNADA_PADRAO_44H, `fillna(44)`) e' exibido a parte e so'
    vale para linhas dentro do periodo da execucao que o registrou.
    """
    from shared.evidence_engine import origem_da_jornada
    from shared.operational_schedule import JORNADA_FALLBACK, MOTIVO_FALLBACK, STATUS_COM_FALLBACK

    resolucoes = {}
    jornada = repo.tables.get('jornada_consolidada')
    if jornada is not None:
        c = jornada.c
        linhas = repo.rows(select(c.colaborador, c.data_referencia, c.fonte, c.campo, c.status_resolucao,
                                  c.jornada_semanal, c.elegivel, c.vigente, c.evidencia, c.registrado_em)
                           .where(c.marca == marca, c.data_referencia <= fim))
        for linha in linhas:
            resolucoes.setdefault(_chave_nome(linha['colaborador']), []).append(linha)
        for lista in resolucoes.values():
            lista.sort(key=lambda r: (str(r['data_referencia']), str(r['registrado_em'])), reverse=True)

    processador = {}
    evento, execucao = repo.tables.get('fallback_evento'), repo.tables.get('execucao')
    if evento is not None and execucao is not None:
        e, x = evento.c, execucao.c
        for linha in repo.rows(
                select(e.codigo, e.contexto, x.periodo_inicio, x.periodo_fim)
                .select_from(evento.join(execucao, e.execution_id == x.execution_id))
                .where(x.marca == marca, x.periodo_inicio <= fim, x.periodo_fim >= inicio,
                       e.codigo == JORNADA_FALLBACK['id'])):
            chave = _chave_nome(_json_de(linha['contexto']).get('colaborador'))
            if chave:
                processador.setdefault(chave, []).append((str(linha['periodo_inicio']), str(linha['periodo_fim'])))

    padrao = f"{JORNADA_FALLBACK['jornada']:g}H"

    def jornada_da_linha(colaborador, data):
        chave, dia = _chave_nome(colaborador), str(data)[:10]
        vigente = next((r for r in resolucoes.get(chave, []) if str(r['data_referencia'])[:10] <= dia), None)
        do_processador = any(i <= dia <= f for i, f in processador.get(chave, []))
        base = dict(fallback_processador_pdoh=True if do_processador else None,
                    origem_fallback=JORNADA_FALLBACK['id'] if do_processador else None)
        if vigente is None:
            return dict(base, fonte=None, jornada_aplicada=None, origem=None, houve_fallback=None,
                        status_resolucao=None, data_resolucao=None,
                        motivo='Colaborador sem registro no cadastro de jornada na data.')
        status, evidencia = vigente['status_resolucao'], _json_de(vigente['evidencia'])
        comum = dict(base, status_resolucao=status, data_resolucao=str(vigente['data_referencia'])[:10])
        if status == 'RESOLVIDA':
            horas = float(vigente['jornada_semanal'])
            posterior = evidencia.get('preenchimento_posterior')
            return dict(comum, jornada_aplicada=f'{horas:g}H', houve_fallback=False,
                        origem=origem_da_jornada(dict(jornada_origem=None, **vigente)),
                        fonte=f"{ROTULO_FONTE_JORNADA.get(vigente['fonte'], vigente['fonte'])} "
                              f"({vigente['fonte']}.{vigente['campo']})",
                        motivo=(f"Sem jornada na data; usada a versão de {posterior['data_referencia']} "
                                'da mesma fonte oficial.') if posterior else None)
        if status in STATUS_COM_FALLBACK and vigente['elegivel'] and vigente['vigente']:
            return dict(comum, jornada_aplicada=padrao, houve_fallback=True, origem='FALLBACK',
                        origem_fallback=JORNADA_FALLBACK['id'], motivo=MOTIVO_FALLBACK,
                        fonte='Jornada padrão (fallback em código)')
        return dict(comum, jornada_aplicada=None, houve_fallback=False, origem=None, fonte=None,
                    motivo=MOTIVOS_JORNADA_NAO_RESOLVIDA.get(status, status))

    return jornada_da_linha


def _validacao_do_dia(linha, jornada, contexto):
    """`contexto`: saidas configuradas e dias com oportunidade gravada (lidos uma vez por consulta)."""
    justificativa = justificativa_do_dia(linha, linha['data'])
    validacao = classificar_dia(linha, justificativa, jornada, contexto['saidas'])
    validacao['gerou_oportunidade'] = chave_dia(linha['colaborador'], linha['data']) in contexto['oportunidades']
    return justificativa, validacao


def _validacao_periodo(repo, tabela, filters, inicio, fim, jornada_da_linha, contexto):
    """Status de todos os dias da janela (nao so da pagina). Nao participa do calculo PDOH."""
    c = tabela.c
    nomes = ('colaborador', 'data', 'primeiro_checkin', 'ultimo_checkout', 'visitas_diarias',
             *COLUNAS_JUSTIFICATIVA)
    linhas = repo.rows(select(*[c[nome] for nome in nomes if nome in c])
                       .where(*_condicoes(tabela, inicio, fim, filters.colaborador, filters.estado))
                       .limit(MAX_LINHAS_PLATINA + 1))
    if len(linhas) > MAX_LINHAS_PLATINA:
        return None
    return consolidar((linha['colaborador'], *_validacao_do_dia(
        linha, jornada_da_linha(linha['colaborador'], linha['data']), contexto)) for linha in linhas)


def _detalhes(repo, tabela, filters, inicio, fim, jornada_da_linha, contexto):
    c = tabela.c
    condicoes = _condicoes(tabela, inicio, fim, filters.colaborador, filters.estado)
    total = repo.rows(select(func.count().label('total')).select_from(tabela).where(*condicoes))[0]['total']
    nomes = (
        'colaborador', 'estado', 'data', 'nome_do_dia', 'deslocamento', 'ocio',
        'produtividade', 'horas_nao_registradas', 'horas_programadas', 'primeiro_checkin',
        'ultimo_checkout', 'visitas_diarias', 'visitas_diarias_realizadas',
        'pesquisas_diarias', 'pesquisas_diarias_realizadas', 'percentual_produtividade',
        'percentual_visitas', 'percentual_pesquisas', 'percentual_efetividade', *COLUNAS_JUSTIFICATIVA,
    )
    colunas = [c[nome] for nome in nomes if nome in c]
    offset = (filters.pagina - 1) * filters.tamanho
    linhas = repo.rows(select(*colunas).where(*condicoes)
                       .order_by(c.data.desc(), c.colaborador).offset(offset).limit(filters.tamanho))
    origem = _nome_tabela(tabela)
    items = []
    for linha in linhas:
        jornada = jornada_da_linha(linha['colaborador'], linha['data'])
        justificativa, validacao = _validacao_do_dia(linha, jornada, contexto)
        items.append(dict(
            colaborador=linha['colaborador'], estado=linha.get('estado'), data=linha['data'],
            nome_do_dia=linha.get('nome_do_dia'),
            deslocamento=_texto_tempo(linha.get('deslocamento')),
            ocio=_texto_tempo(linha.get('ocio')),
            produtividade=_texto_tempo(linha.get('produtividade')),
            horas_nao_registradas=_texto_tempo(linha.get('horas_nao_registradas')),
            horas_programadas=_texto_tempo(linha.get('horas_programadas')),
            primeiro_checkin=_texto_tempo(linha.get('primeiro_checkin')),
            ultimo_checkout=_texto_tempo(linha.get('ultimo_checkout')),
            visitas=int(linha.get('visitas_diarias') or 0),
            visitas_realizadas=int(linha.get('visitas_diarias_realizadas') or 0),
            pesquisas=int(linha.get('pesquisas_diarias') or 0),
            pesquisas_realizadas=int(linha.get('pesquisas_diarias_realizadas') or 0),
            percentuais={
                'produtividade': float(linha['percentual_produtividade']) if linha.get('percentual_produtividade') is not None else None,
                'visitas': float(linha['percentual_visitas']) if linha.get('percentual_visitas') is not None else None,
                'pesquisas': float(linha['percentual_pesquisas']) if linha.get('percentual_pesquisas') is not None else None,
                'efetividade': float(linha['percentual_efetividade']) if linha.get('percentual_efetividade') is not None else None,
            },
            jornada=dict(jornada, horario_aplicado=_texto_tempo(linha.get('horas_programadas'))),
            justificativa=justificativa,
            validacao=validacao,
            origem_dado=origem,
        ))
    return dict(items=items, total=total, pagina=filters.pagina, tamanho=filters.tamanho,
                paginas=math.ceil(total / filters.tamanho) if total else 0)


def pdoh_summary(repo, filters):
    """GET /api/v2/pdoh/resumo."""
    tabela, motivo = _resolver_fonte(repo, filters)
    inicio, fim, automatica = _janela(repo, filters, tabela)
    base = dict(marca=filters.marca, operacao=filters.operacao,
                periodo={'inicio': inicio, 'fim': fim}, periodo_automatico=automatica,
                disponivel=False, percentual=None,
                variacao_periodo_anterior=None, indicador=INDICADOR_PDOH,
                detalhes=_pagina_vazia(filters),
                filtros_disponiveis={'colaboradores': [], 'estados': []})
    if tabela is None:
        return dict(base, motivo=motivo, cobertura=_fonte_vazia())

    jornada_da_linha = _auditoria_jornada(repo, filters.marca, inicio, fim)
    contexto = dict(saidas=saidas_configuradas(repo, filters.marca, filters.operacao),
                    oportunidades=oportunidades_do_periodo(repo, filters.marca, inicio, fim))
    base['detalhes'] = _detalhes(repo, tabela, filters, inicio, fim, jornada_da_linha, contexto)
    base['validacao'] = _validacao_periodo(repo, tabela, filters, inicio, fim, jornada_da_linha, contexto)
    base['filtros_disponiveis'] = _opcoes_filtro(repo, tabela, inicio, fim)
    atual, anterior, cobertura, motivo = _consolidado(
        repo, tabela, inicio, fim, filters.colaborador, filters.estado)
    fonte = _fonte(repo, tabela, cobertura)
    if atual is None:
        return dict(base, motivo=motivo, cobertura=fonte)

    composicao = _composicao(atual, anterior)
    variacao = None if not anterior else round(atual['pdoh'] - anterior['pdoh'], 4)
    meta, motivo_meta = _meta()
    return dict(
        base, disponivel=True, motivo=None, fonte=FONTE_PDOH, cobertura=fonte,
        pdoh=dict(valor=atual['pdoh'], unidade='%', variacao_periodo_anterior=variacao,
                  meta=meta, motivo_meta=motivo_meta),
        composicao=composicao,
        efetividade=_indicador(atual['efetividade'],
                               anterior['efetividade'] if anterior else None),
        # Campos ja consumidos pelo painel.
        percentual=atual['pdoh'], variacao_periodo_anterior=variacao, indicadores=composicao,
        evolucao=[dict(data=ponto['periodo'], percentual=ponto['pdoh'])
                  for ponto in _pontos(repo, tabela, inicio, fim, 'dia',
                                       filters.colaborador, filters.estado)],
    )


def pdoh_composicao(repo, filters):
    """GET /api/v2/pdoh/composicao. Mesma consolidacao oficial do resumo."""
    tabela, motivo = _resolver_fonte(repo, filters)
    inicio, fim, _ = _janela(repo, filters, tabela)
    base = dict(marca=filters.marca, periodo={'inicio': inicio, 'fim': fim}, disponivel=False)
    if tabela is None:
        return dict(base, motivo=motivo, cobertura=_fonte_vazia())
    atual, anterior, cobertura, motivo = _consolidado(
        repo, tabela, inicio, fim, filters.colaborador, filters.estado)
    fonte = _fonte(repo, tabela, cobertura)
    if atual is None:
        return dict(base, motivo=motivo, cobertura=fonte)
    return dict(base, disponivel=True, motivo=None, fonte=FONTE_PDOH, cobertura=fonte,
                **_composicao(atual, anterior))


def _fatiar(inicio, fim, granularidade):
    """Janelas da evolucao. Semana sempre segunda a sabado; mes, o mes civil."""
    janelas = []
    cursor = inicio
    while cursor <= fim:
        if granularidade == 'dia':
            comeco = termino = cursor
            seguinte = cursor + timedelta(days=1)
        elif granularidade == 'semana':
            comeco = cursor - timedelta(days=cursor.weekday())   # segunda da semana do cursor
            termino = comeco + timedelta(days=5)                 # sabado
            # O cursor avanca sempre para a proxima segunda: um domingo recai na semana
            # que ja foi fatiada e, sem isso, o laco nunca sairia do lugar.
            seguinte = comeco + timedelta(days=7)
        else:
            comeco = cursor.replace(day=1)
            seguinte = (comeco + timedelta(days=32)).replace(day=1)
            termino = seguinte - timedelta(days=1)
        recorte_inicio, recorte_fim = max(comeco, inicio), min(termino, fim)
        if recorte_inicio <= recorte_fim:       # domingo isolado nao vira janela vazia
            janelas.append((recorte_inicio, recorte_fim, comeco))
        cursor = seguinte
    return janelas


def _pontos(repo, tabela, inicio, fim, granularidade, colaborador=None, estado=None):
    """Serie oficial. Janela sem horas programadas nao vira ponto zero: fica de fora."""
    linhas = _linhas(repo, tabela, inicio, fim, colaborador, estado)
    if len(linhas) > MAX_LINHAS_PLATINA:
        return []
    pontos = []
    for comeco, termino, rotulo in _fatiar(inicio, fim, granularidade):
        recorte = [linha for linha in linhas if comeco <= linha['data'] <= termino]
        consolidado = _consolidar(recorte) if recorte else None
        if consolidado is not None:
            pontos.append(dict(periodo=rotulo, inicio=comeco, fim=termino, pdoh=consolidado['pdoh']))
    return pontos


def pdoh_evolucao(repo, filters, granularidade='dia'):
    """GET /api/v2/pdoh/evolucao."""
    tabela, motivo = _resolver_fonte(repo, filters)
    inicio, fim, _ = _janela(repo, filters, tabela)
    base = dict(marca=filters.marca, periodo={'inicio': inicio, 'fim': fim},
                granularidade=granularidade, disponivel=False, pontos=[])
    if tabela is None:
        return dict(base, motivo=motivo)
    cobertura = _cobertura(repo, tabela, inicio, fim, filters.colaborador, filters.estado)
    if not cobertura['registros']:
        return dict(base, motivo=MOTIVO_SEM_DADOS)
    if cobertura['registros'] > MAX_LINHAS_PLATINA:
        return dict(base, motivo=MOTIVO_EXCESSO)
    pontos = _pontos(repo, tabela, inicio, fim, granularidade,
                     filters.colaborador, filters.estado)
    if not pontos:
        return dict(base, motivo=MOTIVO_SEM_JORNADA)
    return dict(base, disponivel=True, motivo=None, fonte=FONTE_PDOH, pontos=pontos)


def _resolver_colaborador(repo, identificador, marca):
    """Aceita o id opaco, o id interno da identidade ou o proprio nome."""
    decodificado = decodificar_colaborador(identificador)
    if decodificado:
        return decodificado[0] or marca, decodificado[1]
    identidade = repo.tables.get('colaborador_identidade')
    if identidade is not None:
        linhas = repo.rows(
            select(identidade.c.marca, identidade.c.nome_referencia)
            .where(identidade.c.colaborador_id_interno == identificador).limit(1))
        if linhas and linhas[0]['nome_referencia']:
            return linhas[0]['marca'] or marca, linhas[0]['nome_referencia']
    return marca, identificador


def _impactadores(repo, filters, marca, nome):
    """Impactadores ja consolidados pela fila operacional. Nunca alimentam indicador."""
    from .finding_models import GroupFilter
    from .findings_repository import opportunity_summary
    consulta = GroupFilter(marca=marca, colaborador=nome, periodo='personalizado',
                           periodo_inicio=filters.periodo_inicio, periodo_fim=filters.periodo_fim,
                           pagina=1, tamanho=200)
    pagina = opportunity_summary(repo, consulta)
    return [dict(regra=item['tipo_problema'], titulo=item['titulo'], quantidade=item['quantidade'],
                 impacto=item['impacto'], acao_recomendada=item['acao_recomendada'],
                 severidade=item['severidade'])
            for item in pagina['items']]


def pdoh_colaborador(repo, identificador, filters):
    """GET /api/v2/pdoh/colaborador/{id}. Somente os dados daquele colaborador."""
    marca, nome = _resolver_colaborador(repo, identificador, filters.marca)
    if not nome:
        raise HTTPException(404, 'Colaborador nao encontrado.')
    filtros_marca = filters.model_copy(update={'marca': marca})
    tabela, motivo = _resolver_fonte(repo, filtros_marca)
    inicio, fim, _ = _janela(repo, filtros_marca, tabela)
    base = dict(colaborador=dict(id=codificar_colaborador(marca, nome), nome=nome), marca=marca,
                periodo={'inicio': inicio, 'fim': fim}, disponivel=False, dias_no_periodo=0,
                impactadores=_impactadores(repo, filtros_marca, marca, nome))
    if tabela is None:
        return dict(base, motivo=motivo)
    atual, anterior, cobertura, motivo = _consolidado(repo, tabela, inicio, fim, nome,
                                                       filters.estado)
    if atual is None:
        return dict(base, motivo=motivo, dias_no_periodo=cobertura['dias'])
    variacao = None if not anterior else round(atual['pdoh'] - anterior['pdoh'], 4)
    meta, motivo_meta = _meta()
    return dict(base, disponivel=True, motivo=None, fonte=FONTE_PDOH,
                dias_no_periodo=cobertura['dias'],
                pdoh=dict(valor=atual['pdoh'], unidade='%', variacao_periodo_anterior=variacao,
                          meta=meta, motivo_meta=motivo_meta),
                composicao=_composicao(atual, anterior),
                efetividade=_indicador(atual['efetividade'],
                                       anterior['efetividade'] if anterior else None))
