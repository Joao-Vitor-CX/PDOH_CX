"""Executa, na esteira, as regras de oportunidade CONFIGURADAS.

Fluxo (nada disto e' regra de negocio no codigo -- tudo vem das tabelas de configuracao):

    Configuracao de regra -> regra ativa -> motor valida os dados -> criterios atendidos
    -> oportunidade criada

    1. le as regras ativas de `regra_configuracao` (condicoes, excecoes, tempo minimo);
    2. le as linhas da fonte primaria mapeada em `fonte_semantica_configuracao`;
    3. `shared.rule_engine` decide cada linha (confirmado / nao aplicavel / indisponivel);
    4. so o CONFIRMADO segue para o dispatcher (`registrar_achado`), que ainda confere, na
       porta final, se a regra esta cadastrada, ativa e configurada para gerar.

Regra sem executor generico
    O executor cobre regras cujas condicoes vivem numa unica fonte mapeada. Uma regra ativa
    que cruza fontes (ex.: saida ausente COM entrada presente) e' avaliada pelo detector
    proprio -- este modulo registra isso, nao a executa pela metade.

Nunca interrompe a esteira: qualquer falha vira evento e o processamento segue.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
import hashlib
import json
import re
from typing import Any, Callable

from sqlalchemy import text

from shared.evidence_config import CONFIRMADO, INDISPONIVEL, NAO_APLICAVEL, STATUS_OCORRENCIA_ENCERRADA
from shared.evidence_engine import origem_da_jornada
from shared.rule_engine import (
    SEM_REGISTRO, STATUS_ATIVA, TIPO_CONDICAO, TIPO_EXCECAO, ConfiguracaoInvalida,
    avaliar_regra, gera_oportunidade,
)

from .observability import obter_execution_id, registrar_achado, registrar_evento

PREFIXO_CONTROLE = 'pdoh_controle.'
# Fontes lidas pelo banco LOCAL (com schema); as demais, pela conexao somente-leitura da origem.
SCHEMAS_LOCAIS = frozenset({'produtos_platina', 'pdoh_controle'})
MAX_LINHAS = 200_000
AMOSTRA = 20
ETAPA = 'REGRAS_CONFIGURADAS'
CATEGORIA = 'GOVERNANCA'
_AMBIGUO = object()


# --------------------------------------------------------------------------- utilitarios
def _identificador(nome):
    if not nome or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', str(nome)):
        raise ValueError('Identificador de fonte invalido')
    return '`' + str(nome) + '`'


def _json(valor):
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except ValueError:
            return valor
    return valor


def _nome(valor):
    """Chave de colaborador: mesmo nome com espacos ou caixa diferentes e' a mesma pessoa."""
    return ' '.join(str(valor or '').upper().split())


def _dia(valor):
    return str(valor)[:10] if valor is not None else ''


# --------------------------------------------------------------------------- configuracao
def carregar_regras(engine, marca, operacao, prefixo=PREFIXO_CONTROLE):
    """Regras da marca/operacao com condicoes, excecoes e tratativas ja montadas."""
    escopo = {'marca': marca, 'operacao': operacao}
    with engine.connect() as conexao:
        regras = conexao.execute(text(
            'SELECT configuracao_id,nome_regra,codigo_interno,categoria,status,prioridade,'
            f'tempo_minimo_minutos,descricao,geracao_automatica_ativa FROM {prefixo}regra_configuracao '
            'WHERE marca=:marca AND operacao=:operacao ORDER BY prioridade,codigo_interno'), escopo).mappings().all()
        condicoes = conexao.execute(text(
            'SELECT c.configuracao_id,c.tipo,c.ordem,c.papel_fonte,c.campo_logico,c.operador,'
            f'c.valor_esperado,c.descricao,c.status FROM {prefixo}regra_condicao_configuracao c '
            f'JOIN {prefixo}regra_configuracao r ON r.configuracao_id=c.configuracao_id '
            'WHERE r.marca=:marca AND r.operacao=:operacao ORDER BY c.configuracao_id,c.tipo,c.ordem'),
            escopo).mappings().all()
        tratamentos = conexao.execute(text(
            'SELECT t.configuracao_id,t.resultado,t.acao_recomendada,t.destino,t.gera_oportunidade,t.status '
            f'FROM {prefixo}regra_tratamento_configuracao t '
            f'JOIN {prefixo}regra_configuracao r ON r.configuracao_id=t.configuracao_id '
            'WHERE r.marca=:marca AND r.operacao=:operacao'), escopo).mappings().all()
    resultado = []
    for regra in regras:
        item = dict(regra)
        item['geracao_automatica_ativa'] = bool(item['geracao_automatica_ativa'])
        todas = [dict(c, valor_esperado=_json(c['valor_esperado']))
                 for c in condicoes if c['configuracao_id'] == item['configuracao_id']]
        item['condicoes'] = [c for c in todas if c['tipo'] == TIPO_CONDICAO]
        item['excecoes'] = [c for c in todas if c['tipo'] == TIPO_EXCECAO]
        item['tratamentos'] = [dict(t, gera_oportunidade=bool(t['gera_oportunidade']))
                               for t in tratamentos if t['configuracao_id'] == item['configuracao_id']]
        resultado.append(item)
    return resultado


def carregar_fontes(engine, marca, operacao, prefixo=PREFIXO_CONTROLE):
    """{papel: [fontes MAPEADAS por prioridade]} da marca/operacao."""
    with engine.connect() as conexao:
        linhas = conexao.execute(text(
            'SELECT fonte_id,papel,tipo,prioridade,schema_fisico,tabela_fisica,mapeamento_campos,descricao '
            f"FROM {prefixo}fonte_semantica_configuracao WHERE marca=:marca AND operacao=:operacao "
            "AND status='MAPEADA' ORDER BY papel,prioridade"),
            {'marca': marca, 'operacao': operacao}).mappings().all()
    fontes = {}
    for linha in linhas:
        item = dict(linha)
        mapa = _json(item['mapeamento_campos'])
        item['mapeamento_campos'] = mapa if isinstance(mapa, dict) else {}
        fontes.setdefault(item['papel'], []).append(item)
    return fontes


def _fonte_com_campos(candidatas, campos):
    """Primeira fonte (por prioridade) que mapeia TODOS os campos pedidos."""
    return next((f for f in candidatas or ()
                 if f.get('tabela_fisica') and all(campo in f['mapeamento_campos'] for campo in campos)), None)


def _campos_da_regra(condicoes):
    campos = set()
    for condicao in condicoes:
        campos.add(condicao['campo_logico'])
        valor = condicao.get('valor_esperado')
        if condicao['operador'] == 'MENOR_QUE_CAMPO':
            campos.add(valor.get('campo') if isinstance(valor, dict) else valor)
    return {campo for campo in campos if campo}


def fonte_primaria(regra, fontes):
    """(fonte, motivo): a fonte que traz as linhas candidatas, ou por que nao ha executor."""
    condicoes = [c for c in regra['condicoes'] if c.get('status') == STATUS_ATIVA]
    if not condicoes:
        return None, 'Regra sem condição ativa.'
    papeis = {c['papel_fonte'] for c in condicoes}
    if len(papeis) != 1:
        return None, 'As condições cruzam mais de uma fonte; a regra é avaliada por detector próprio.'
    papel = next(iter(papeis))
    campos = _campos_da_regra(condicoes) | {'colaborador', 'data'}
    fonte = _fonte_com_campos(fontes.get(papel), campos)
    if fonte is None:
        return None, f'Nenhuma fonte mapeada do papel "{papel}" cobre os campos da regra.'
    return fonte, None


# --------------------------------------------------------------------------- leitura das fontes
def criar_leitor(engine_local, engine_origem):
    """Leitor de fonte: `Platina` pelo banco local, o restante pela origem somente-leitura."""
    def leitor(fonte, colunas, coluna_data, inicio, fim):
        schema, tabela = fonte['schema_fisico'], fonte['tabela_fisica']
        local = schema in SCHEMAS_LOCAIS
        engine = engine_local if local else engine_origem
        if engine is None:
            raise ValueError(f'Sem conexao para a fonte {tabela}.')
        nome = f'{_identificador(schema)}.{_identificador(tabela)}' if local else _identificador(tabela)
        consulta = (f"SELECT {', '.join(_identificador(c) for c in sorted(set(colunas)))} FROM {nome} "
                    f'WHERE DATE({_identificador(coluna_data)}) BETWEEN :inicio AND :fim '
                    f'LIMIT {MAX_LINHAS + 1}')
        with engine.connect() as conexao:
            linhas = conexao.execute(text(consulta), {'inicio': _dia(inicio), 'fim': _dia(fim)}).mappings().all()
        if len(linhas) > MAX_LINHAS:
            raise ValueError(f'Fonte {tabela} excede o limite de leitura ({MAX_LINHAS} linhas).')
        return [dict(linha) for linha in linhas]
    return leitor


def criar_resolvedor_jornada(engine_local, engine_origem, marca, operacao):
    """Resolucao oficial de jornada de um dia. `None` quando a origem nao esta disponivel."""
    def resolver(dia):
        if engine_origem is None:
            return None
        from .journey_observer import resolve_official
        return resolve_official(engine_local, engine_origem, brand=marca, operation=operacao, as_of=dia)
    return resolver


def _linha_logica(linha, mapa):
    return {logico: linha.get(fisico) for logico, fisico in mapa.items() if fisico in linha}


class ProvedorDeExcecoes:
    """Entrega o valor que cada excecao precisa examinar, por colaborador e dia.

    Cada fonte e' lida UMA vez por execucao. `status_day` e' tabela de snapshot: o mesmo dia
    aparece em varias extracoes e vale a mais recente (`evolucao`), nunca a do proprio dia,
    que costuma vir incompleta. Divergencia dentro da mesma extracao e' ambiguidade real.
    """

    def __init__(self, fontes, leitor, resolver_jornada, inicio, fim):
        self.fontes, self.leitor, self.resolver_jornada = fontes, leitor, resolver_jornada
        self.inicio, self.fim = inicio, fim
        self._indices, self._resolucoes = {}, {}

    # -- fontes em tabela
    def _indice(self, papel, campo):
        fonte = _fonte_com_campos(self.fontes.get(papel), {campo, 'colaborador', 'data'})
        if fonte is None:
            return None
        if fonte['fonte_id'] not in self._indices:
            self._indices[fonte['fonte_id']] = self._carregar(fonte)
        return self._indices[fonte['fonte_id']]

    def _carregar(self, fonte):
        mapa = fonte['mapeamento_campos']
        linhas = self.leitor(fonte, list(mapa.values()), mapa['data'], self.inicio, self.fim)
        agrupado = {}
        for linha in linhas:
            logica = _linha_logica(linha, mapa)
            agrupado.setdefault((_nome(logica.get('colaborador')), _dia(logica.get('data'))), []).append(logica)
        indice = {}
        for chave, candidatas in agrupado.items():
            if 'evolucao' in mapa:
                ultima = max(str(c.get('evolucao') or '') for c in candidatas)
                candidatas = [c for c in candidatas if str(c.get('evolucao') or '') == ultima]
            comparaveis = [{k: v for k, v in c.items() if k not in ('evolucao', 'dimensao')} for c in candidatas]
            indice[chave] = candidatas[0] if all(x == comparaveis[0] for x in comparaveis) else _AMBIGUO
        return indice

    # -- resolucao de jornada
    def _resolucao(self, colaborador, data):
        dia = _dia(data)
        if dia not in self._resolucoes:
            indice = {}
            for linha in (self.resolver_jornada(dia) if self.resolver_jornada else None) or ():
                chave = _nome(linha.get('colaborador'))
                indice[chave] = _AMBIGUO if chave in indice and indice[chave] != linha else linha
            self._resolucoes[dia] = indice
        linha = self._resolucoes[dia].get(_nome(colaborador))
        return None if linha is None or linha is _AMBIGUO else linha

    def jornada_origem(self, colaborador, data):
        linha = self._resolucao(colaborador, data)
        return origem_da_jornada(dict(linha)) if linha else None

    def jornada_semanal(self, colaborador, data):
        linha = self._resolucao(colaborador, data)
        horas = (linha or {}).get('jornada_semanal')
        return float(horas) if horas is not None and (linha or {}).get('status_resolucao') == 'RESOLVIDA' else None

    def __call__(self, excecao, colaborador, data):
        papel, campo = excecao['papel_fonte'], excecao['campo_logico']
        if papel == 'jornada' and campo == 'status_resolucao':
            linha = self._resolucao(colaborador, data)
            return SEM_REGISTRO if linha is None else linha.get('status_resolucao')
        indice = self._indice(papel, campo)
        if indice is None:
            return SEM_REGISTRO
        registro = indice.get((_nome(colaborador), _dia(data)))
        if registro is None or registro is _AMBIGUO:
            return SEM_REGISTRO
        return registro.get(campo)


# --------------------------------------------------------------------------- achado
def fingerprint_ocorrencia(codigo, marca, operacao, colaborador, data):
    """Identidade da ocorrencia: regra + marca + operacao + colaborador + dia (igual em toda execucao)."""
    return hashlib.sha256('|'.join([
        codigo, marca, operacao, _nome(colaborador), _dia(data)]).encode('utf-8')).hexdigest()


def montar_achado(regra, prova, *, marca, operacao, fonte):
    """Achado no formato do dispatcher. A comprovacao viaja dentro da evidencia."""
    colaborador, data = prova['colaborador'], prova['data']
    fingerprint = fingerprint_ocorrencia(regra['codigo_interno'], marca, operacao, colaborador, data)
    return dict(
        marca=marca, origem='INVOLVES' if prova.get('configuracao_operacional') else 'PDOH_PLATINA', tabela_origem=fonte['tabela_fisica'],
        colaborador=colaborador, data_referencia=data, tipo_problema=regra['codigo_interno'],
        descricao_detalhada=f"{regra['nome_regra']}: {prova['esperado']} (encontrado {prova['encontrado']}).",
        fingerprint=fingerprint,
        evidencia=dict(campo_esperado=prova['campo'], valor_esperado=prova['esperado'],
                       valor_encontrado=prova['encontrado'], fallback_usado=prova.get('jornada_origem') == 'FALLBACK',
                       origem=prova['fonte'], ocorrencias=1, comprovacao=prova))


# --------------------------------------------------------------------------- execucao
def _eventos(engine, registrar, nivel, codigo, mensagem, contexto):
    if registrar:
        registrar_evento(engine, nivel=nivel, categoria=CATEGORIA, codigo=codigo,
                         mensagem=mensagem, etapa=ETAPA, contexto=contexto)


def executar_regra(engine, regra, fonte, provedor, leitor, inicio, fim, *, marca, operacao,
                   criar=True, registrar=True):
    """Avalia UMA regra ativa. Devolve o resumo; cria oportunidade so' se `criar` e o gate liberar."""
    mapa = fonte['mapeamento_campos']
    campos = _campos_da_regra([c for c in regra['condicoes'] if c.get('status') == STATUS_ATIVA])
    colunas = sorted({mapa[c] for c in campos | {'colaborador', 'data'}})
    linhas = [_linha_logica(l, mapa) for l in leitor(fonte, colunas, mapa['data'], inicio, fim)]

    confirmados, contagem, situacao = [], Counter(), {}
    motivos = {NAO_APLICAVEL: Counter(), INDISPONIVEL: Counter()}
    amostra = {NAO_APLICAVEL: [], INDISPONIVEL: []}
    for linha in linhas:
        prova = avaliar_regra(regra, linha, provedor, colaborador=linha.get('colaborador'),
                              data=linha.get('data'), fonte_rotulo=fonte.get('descricao'),
                              fonte_tabela=fonte['tabela_fisica'])
        chave = (fingerprint_ocorrencia(regra['codigo_interno'], marca, operacao, linha.get('colaborador'),
                                        linha.get('data')) if linha.get('colaborador') and linha.get('data') else None)
        # Condicao nao atendida ou excecao aplicada = sem divergencia; indisponivel nao decide nada.
        if chave and (prova is None or prova['resultado'] == NAO_APLICAVEL):
            situacao.setdefault(chave, SITUACAO_RESOLVIDA)
        if prova is None:
            continue
        contagem[prova['resultado']] += 1
        if prova['resultado'] == CONFIRMADO:
            if chave:
                situacao[chave] = SITUACAO_ABERTA
            confirmados.append(prova)
            continue
        motivos[prova['resultado']][prova['motivo']] += 1
        if len(amostra[prova['resultado']]) < AMOSTRA:
            amostra[prova['resultado']].append(dict(colaborador=prova['colaborador'], data=prova['data'],
                                                    motivo=prova['motivo']))

    liberado, motivo_gate = gera_oportunidade(regra, regra['tratamentos'])
    criadas = 0
    if confirmados and liberado and criar:
        criadas = registrar_achado(engine, [montar_achado(regra, p, marca=marca, operacao=operacao, fonte=fonte)
                                            for p in confirmados])
    resumo = dict(
        regra=regra['codigo_interno'], avaliadas=len(linhas), candidatas=sum(contagem.values()),
        confirmadas=contagem[CONFIRMADO], nao_aplicaveis=contagem[NAO_APLICAVEL],
        indisponiveis=contagem[INDISPONIVEL], criadas=criadas, gera_oportunidade=liberado,
        motivos_nao_aplicaveis=dict(motivos[NAO_APLICAVEL]), motivos_indisponiveis=dict(motivos[INDISPONIVEL]),
        amostra_nao_aplicaveis=amostra[NAO_APLICAVEL], amostra_indisponiveis=amostra[INDISPONIVEL],
        situacao=situacao)

    _eventos(engine, registrar, 'INFO', 'REGRA_EXECUTADA',
             f"Regra {regra['codigo_interno']}: {resumo['avaliadas']} linha(s) avaliada(s), "
             f"{resumo['confirmadas']} confirmada(s), {resumo['nao_aplicaveis']} com exceção, "
             f"{resumo['indisponiveis']} sem dado suficiente, {criadas} oportunidade(s) criada(s).",
             dict(marca=marca, operacao=operacao, periodo_inicio=_dia(inicio), periodo_fim=_dia(fim),
                  **{k: resumo[k] for k in ('regra', 'avaliadas', 'candidatas', 'confirmadas',
                                            'nao_aplicaveis', 'indisponiveis', 'criadas')}))
    if resumo['indisponiveis']:
        _eventos(engine, registrar, 'ALERTA', 'REGRA_DADOS_INDISPONIVEIS',
                 f"{resumo['indisponiveis']} candidato(s) da regra {regra['codigo_interno']} sem dado "
                 'suficiente para decidir; nenhuma oportunidade foi criada para eles.',
                 dict(regra=regra['codigo_interno'], total=resumo['indisponiveis'],
                      motivos=resumo['motivos_indisponiveis'], amostra=resumo['amostra_indisponiveis']))
    if resumo['nao_aplicaveis']:
        _eventos(engine, registrar, 'INFO', 'REGRA_EXCECAO_APLICADA',
                 f"{resumo['nao_aplicaveis']} candidato(s) da regra {regra['codigo_interno']} barrado(s) "
                 'por exceção configurada.',
                 dict(regra=regra['codigo_interno'], total=resumo['nao_aplicaveis'],
                      motivos=resumo['motivos_nao_aplicaveis'], amostra=resumo['amostra_nao_aplicaveis']))
    if resumo['confirmadas'] and not liberado:
        _eventos(engine, registrar, 'INFO', motivo_gate,
                 f"Regra {regra['codigo_interno']} confirmou {resumo['confirmadas']} ocorrência(s), "
                 'mas está configurada para não gerar oportunidade.',
                 dict(regra=regra['codigo_interno'], confirmadas=resumo['confirmadas']))
    return resumo


SITUACAO_ABERTA = 'ABERTA'
SITUACAO_RESOLVIDA = 'RESOLVIDA'

def encerrar_resolvidas(engine, codigo, situacao, *, marca, operacao, inicio, fim, prefixo=PREFIXO_CONTROLE):
    """Encerra, com historico, as ocorrencias abertas da janela que esta execucao avaliou e nao
    encontrou mais (checkout identificado, horas zeradas, excecao passou a valer). Ocorrencia que
    nao foi avaliada (dado ausente, ambiguo, prazo nao vencido) nunca e' encerrada."""
    resolvidas = sorted(chave for chave, estado in situacao.items() if estado == SITUACAO_RESOLVIDA)
    if not resolvidas:
        return 0
    execution_id = obter_execution_id(criar=False)
    if not execution_id:
        raise ValueError('Reprocessamento exige execucao aberta para auditar o encerramento.')
    encerradas = 0
    with engine.begin() as conexao:
        for inicio_lote in range(0, len(resolvidas), 500):
            lote = resolvidas[inicio_lote:inicio_lote + 500]
            chaves = {f'k{i}': chave for i, chave in enumerate(lote)}
            alvos = conexao.execute(text(
                f'SELECT o.oportunidade_id, o.status_oportunidade FROM {prefixo}oportunidade o '
                f'JOIN {prefixo}execucao e ON e.execution_id=o.execution_id AND e.marca=o.marca '
                'WHERE o.marca=:marca AND e.operacao=:operacao AND o.tipo_problema=:codigo '
                "AND o.data_referencia BETWEEN :inicio AND :fim AND o.status_oportunidade IN ('ABERTA','REABERTA') "
                f"AND o.fingerprint IN ({','.join(':' + nome for nome in chaves)})"),
                dict(marca=marca, operacao=operacao, codigo=codigo, inicio=_dia(inicio), fim=_dia(fim),
                     **chaves)).mappings().all()
            for alvo in alvos:
                conexao.execute(text(
                    f'UPDATE {prefixo}oportunidade SET status_oportunidade=:novo '
                    'WHERE oportunidade_id=:id AND status_oportunidade=:atual'),
                    dict(novo=STATUS_OCORRENCIA_ENCERRADA, id=alvo['oportunidade_id'],
                         atual=alvo['status_oportunidade']))
                conexao.execute(text(
                    f'INSERT INTO {prefixo}oportunidade_historico (oportunidade_id,execution_id,status_anterior,'
                    'status_novo,acao,observacao) VALUES (:id,:execucao,:atual,:novo,'
                    "'ENCERRADA_REPROCESSAMENTO',:observacao)"),
                    dict(id=alvo['oportunidade_id'], execucao=execution_id, atual=alvo['status_oportunidade'],
                         novo=STATUS_OCORRENCIA_ENCERRADA,
                         observacao='Reprocessamento não encontrou mais a divergência nesta data.'))
                encerradas += 1
    return encerradas


def _reconciliar(engine, resultado, *, ativo, marca, operacao, inicio, fim, prefixo):
    """Tira do resumo o mapa interno de situacao e, no reprocessamento, encerra o que foi resolvido."""
    situacao = resultado.pop('situacao', None) or {}
    if not ativo:
        return resultado
    resultado['encerradas'] = encerrar_resolvidas(engine, resultado['regra'], situacao, marca=marca,
        operacao=operacao, inicio=inicio, fim=fim, prefixo=prefixo)
    _eventos(engine, True, 'INFO', 'REPROCESSAMENTO_ENCERRAMENTO',
             f"Regra {resultado['regra']}: {resultado['encerradas']} ocorrência(s) encerrada(s) por não "
             'apresentarem mais divergência.',
             dict(regra=resultado['regra'], marca=marca, operacao=operacao, periodo_inicio=_dia(inicio),
                  periodo_fim=_dia(fim), encerradas=resultado['encerradas'],
                  avaliadas_sem_divergencia=sum(1 for e in situacao.values() if e == SITUACAO_RESOLVIDA)))
    return resultado


def executar_regras(engine, source_engine, *, periodo_inicio, periodo_fim, marca='BRACELL',
                    operacao='EXCLUSIVA', criar=True, registrar=True,
                    leitor: Callable | None = None, resolver_jornada: Callable | None = None,
                    prefixo=PREFIXO_CONTROLE, reconciliar=False):
    """Executa todas as regras ATIVAS do escopo. Nunca levanta: falha vira evento e resumo.

    `criar=False` avalia sem criar oportunidade; `registrar=False` tambem nao grava eventos
    (dry-run puro, usado para validar antes de aplicar). `reconciliar=True` (reprocessamento)
    encerra as ocorrencias abertas da janela que esta execucao avaliou e nao encontrou mais.
    """
    resumo = dict(marca=marca, operacao=operacao, periodo_inicio=_dia(periodo_inicio),
                  periodo_fim=_dia(periodo_fim), regras=[], ignoradas=[], sem_executor=[], erros=[])
    try:
        regras = carregar_regras(engine, marca, operacao, prefixo)
        fontes = carregar_fontes(engine, marca, operacao, prefixo)
        leitor = leitor or criar_leitor(engine, source_engine)
        resolver_jornada = resolver_jornada or criar_resolvedor_jornada(engine, source_engine, marca, operacao)
        for regra in regras:
            if regra['status'] != STATUS_ATIVA or not regra['geracao_automatica_ativa']:
                resumo['ignoradas'].append(regra['codigo_interno'])          # inativa: nada a fazer
                continue
            fonte, motivo = fonte_primaria(regra, fontes)
            if regra['codigo_interno'] == 'CHECKOUT_AUSENTE':
                from .operational_schedule import execute
                provedor = ProvedorDeExcecoes(fontes, leitor, resolver_jornada, periodo_inicio, periodo_fim)
                resumo['regras'].append(_reconciliar(engine, execute(engine, regra, fontes, provedor, leitor,
                    periodo_inicio, periodo_fim, marca=marca, operacao=operacao, criar=criar,
                    registrar=registrar, prefixo=prefixo), ativo=reconciliar and criar and registrar,
                    marca=marca, operacao=operacao, inicio=periodo_inicio, fim=periodo_fim, prefixo=prefixo))
                continue
            if fonte is None:
                resumo['sem_executor'].append(dict(regra=regra['codigo_interno'], motivo=motivo))
                _eventos(engine, registrar, 'INFO', 'REGRA_SEM_EXECUTOR_GENERICO',
                         f"Regra {regra['codigo_interno']} ativa, sem executor genérico: {motivo}",
                         dict(regra=regra['codigo_interno'], motivo=motivo))
                continue
            try:
                provedor = ProvedorDeExcecoes(fontes, leitor, resolver_jornada, periodo_inicio, periodo_fim)
                resumo['regras'].append(_reconciliar(engine, executar_regra(
                    engine, regra, fonte, provedor, leitor, periodo_inicio, periodo_fim,
                    marca=marca, operacao=operacao, criar=criar, registrar=registrar),
                    ativo=reconciliar and criar and registrar, marca=marca, operacao=operacao,
                    inicio=periodo_inicio, fim=periodo_fim, prefixo=prefixo))
            except ConfiguracaoInvalida as erro:
                resumo['erros'].append(dict(regra=regra['codigo_interno'], erro=str(erro)))
                _eventos(engine, registrar, 'ERRO', 'REGRA_CONFIGURACAO_INVALIDA', str(erro),
                         dict(regra=regra['codigo_interno']))
    except Exception as erro:                                                # fail-open
        resumo['erros'].append(dict(regra=None, erro=f'{type(erro).__name__}: {erro}'))
        if registrar:
            try:
                registrar_evento(engine, nivel='ERRO', categoria=CATEGORIA, codigo='REGRAS_CONFIGURADAS_INDISPONIVEL',
                                 mensagem='Falha ao executar as regras configuradas; o processamento continua.',
                                 etapa=ETAPA, excecao=erro)
            except Exception:
                pass
    return resumo
