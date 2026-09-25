"""Monta o contexto oficial e carimba a comprovacao nos achados, antes de rotea-los.

Por que aqui e nao na API
    Somente a esteira tem conexao de leitura com a origem (`involves_exclusivos`). A conta
    da API de consulta ve apenas `pdoh_controle` e a Platina. Entao a prova e' produzida no
    momento da deteccao, com a fonte aberta, e viaja dentro da propria evidencia do achado.

Contrato
    `comprovar` devolve apenas os achados com evidencia CONFIRMADA. Os demais nao somem:
    viram evento de execucao com o motivo (abono, fonte ausente, contexto incompleto), o
    que mantem a governanca sem transformar duvida em cobranca.

Nao altera nada do calculo
    Nenhum DataFrame e' tocado, nenhuma jornada e' recalculada, nenhuma regra e' criada.
    Leitura da origem e escrita apenas em tabelas de controle.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text

from shared.evidence_config import (
    CONFIRMADO, PAPEL_STATUS_DAY, matriz_de_linhas, regras_de_linhas,
)
from shared.evidence_engine import avaliar

from .observability import registrar_evento

BASE_JUSTIFICATIVAS = Path(__file__).resolve().parents[1] / 'bases_fixas' / 'Lista_justificativas_abonaveis.xlsx'
# Teto de leitura do status day por execucao; acima disso a comprovacao fica indisponivel
# em vez de varrer a origem inteira.
MAX_LINHAS_STATUS_DAY = 200_000


def _identificador(nome):
    if not nome or not all(c.isalnum() or c == '_' for c in str(nome)):
        raise ValueError('Identificador de fonte invalido')
    return '`' + str(nome) + '`'


def carregar_matriz(engine, *, marca='BRACELL', operacao='EXCLUSIVA'):
    """Matriz de origem e regras de comprovacao cadastradas para a marca."""
    with engine.connect() as c:
        fontes = c.execute(text('SELECT marca,operacao,papel,tabela,campos FROM '
            'pdoh_controle.configuracao_evidencia WHERE marca=:marca AND operacao=:operacao'),
            dict(marca=marca, operacao=operacao)).mappings().all()
        regras = c.execute(text('SELECT tipo_problema,papel,campo,valor_esperado,criterios,papeis_apoio '
            'FROM pdoh_controle.configuracao_evidencia_regra WHERE marca=:marca AND operacao=:operacao'),
            dict(marca=marca, operacao=operacao)).mappings().all()
    matriz = matriz_de_linhas([dict(linha) for linha in fontes]).get((marca.upper(), operacao.upper()))
    return matriz, regras_de_linhas([dict(linha) for linha in regras])


def justificativas_abonaveis(caminho=BASE_JUSTIFICATIVAS):
    """Lista oficial travada no manifesto. Ausente devolve vazio, nunca um palpite."""
    try:
        import pandas as pd
        planilha = pd.read_excel(caminho)
    except Exception:
        return []
    coluna = next((c for c in planilha.columns if 'justificativ' in str(c).casefold()), None)
    if coluna is None:
        return []
    return sorted({str(v).strip() for v in planilha[coluna].dropna() if str(v).strip()})


def _chave(colaborador, data):
    colaborador = (str(colaborador).strip().upper() if colaborador else '')
    data = str(data)[:10] if data else ''
    return (colaborador, data)


def carregar_status_day(source_engine, matriz, *, periodo_inicio=None, periodo_fim=None):
    """Indexa o status day por (colaborador, data). Sem fonte configurada, devolve None."""
    fonte = matriz.fonte(PAPEL_STATUS_DAY) if matriz else None
    if fonte is None or source_engine is None:
        return None
    campo_colaborador = fonte.campo('colaborador') or 'colaborador'
    campo_data = fonte.campo('data') or 'dia_referencia'
    colunas = sorted({campo_colaborador, campo_data, fonte.campo('evolucao') or 'data_evolucao'} |
                     {valor for valor in fonte.campos.values() if valor})
    consulta = ('SELECT ' + ','.join(_identificador(c) for c in colunas) +
                ' FROM ' + _identificador(fonte.tabela))
    parametros = {}
    if periodo_inicio and periodo_fim:
        consulta += f' WHERE DATE({_identificador(campo_data)}) BETWEEN :inicio AND :fim'
        parametros = dict(inicio=str(periodo_inicio)[:10], fim=str(periodo_fim)[:10])
    with source_engine.connect() as c:
        linhas = c.execute(text(consulta + f' LIMIT {MAX_LINHAS_STATUS_DAY + 1}'), parametros).mappings().all()
    if len(linhas) > MAX_LINHAS_STATUS_DAY:
        return None
    # `status_day` e' tabela de snapshot: `data_evolucao` e' a data da extracao, e o mesmo
    # dia aparece uma vez por extracao. O snapshot do proprio dia costuma trazer a entrada
    # ainda vazia; os seguintes ja trazem o horario real. Vale a ultima evolucao -- a mesma
    # regra que `data_loader` e `shared.journey.snapshot` aplicam ao cadastro.
    campo_evolucao = fonte.campo('evolucao') or 'data_evolucao'
    por_chave = {}
    for linha in linhas:
        chave = _chave(linha.get(campo_colaborador), linha.get(campo_data))
        por_chave.setdefault(chave, []).append(dict(linha))
    indice = {}
    for chave, candidatos in por_chave.items():
        evolucoes = [str(item.get(campo_evolucao) or '') for item in candidatos]
        if any(evolucoes):
            ultima = max(evolucoes)
            candidatos = [item for item, evolucao in zip(candidatos, evolucoes) if evolucao == ultima]
        # Divergencia DENTRO da mesma extracao e' ambiguidade real: nao e' prova.
        indice[chave] = candidatos[0] if all(item == candidatos[0] for item in candidatos) else None
    return indice


def carregar_checkins(source_engine, matriz, *, periodo_inicio=None, periodo_fim=None):
    fonte = matriz.fonte('checkin') if matriz else None
    if fonte is None or source_engine is None:
        return None
    data = fonte.campo('data') or 'data_roteiro'
    nome = fonte.campo('colaborador') or 'colaborador'
    colunas = set(fonte.campos.values()) | {'checkout_sistema', 'checkout_registrado'}
    query = 'SELECT ' + ','.join(_identificador(c) for c in sorted(colunas))
    query += ' FROM ' + _identificador(fonte.tabela)
    params = {}
    if periodo_inicio and periodo_fim:
        query += f' WHERE DATE({_identificador(data)}) BETWEEN :inicio AND :fim'
        params = dict(inicio=str(periodo_inicio)[:10], fim=str(periodo_fim)[:10])
    with source_engine.connect() as c:
        rows = c.execute(text(query + f' LIMIT {MAX_LINHAS_STATUS_DAY + 1}'), params).mappings().all()
    if len(rows) > MAX_LINHAS_STATUS_DAY:
        raise ValueError('Fonte de check-ins excede o limite de comprovação completa.')
    indice = {}
    for row in rows:
        indice.setdefault(_chave(row.get(nome), row.get(data)), []).append(dict(row))
    return indice


def indexar_jornada(resolucoes):
    """Resolucao oficial por colaborador, com o rotulo de origem ja anexado."""
    from shared.evidence_engine import origem_da_jornada
    indice = {}
    for linha in resolucoes or ():
        nome = (str(linha.get('colaborador')).strip().upper() if linha.get('colaborador') else '')
        if not nome:
            continue
        item = dict(linha)
        item['jornada_origem'] = origem_da_jornada(item)
        if nome in indice and indice[nome] != item:
            indice[nome] = None
        else:
            indice[nome] = item
    return indice


def montar_contexto(*, status_day, jornada, abonaveis):
    """Fecha o contexto que o motor consome. `status_day=None` = fonte nao consultada."""
    return dict(status_day=status_day, jornada=jornada, justificativas_abonaveis=abonaveis)


def comprovar(engine, achados, *, matriz, regras, status_day, jornada, abonaveis,
              registros_origem=None, registrar=True):
    """Carimba a comprovacao e devolve somente os achados com evidencia confirmada.

    O achado nao confirmado vira evento de execucao com o motivo — governanca preservada,
    fila operacional protegida de falso positivo.
    """
    confirmados, recusados = [], []
    for achado in achados or ():
        nome = (str(achado.get('colaborador')).strip().upper() if achado.get('colaborador') else '')
        chave = _chave(achado.get('colaborador'), achado.get('data_referencia'))
        contexto = dict(jornada=jornada.get(chave, jornada.get(nome)) if jornada else None,
                        justificativas_abonaveis=abonaveis)
        if registros_origem is not None:
            contexto['registros_origem'] = registros_origem.get(chave)
        if status_day is not None:
            contexto['status_day'] = status_day.get(_chave(achado.get('colaborador'),
                                                           achado.get('data_referencia')))
        comprovacao = avaliar(achado, contexto, matriz, regras)
        item = dict(achado)
        evidencia = dict(item.get('evidencia')) if isinstance(item.get('evidencia'), dict) else {}
        evidencia['comprovacao'] = comprovacao
        item['evidencia'] = evidencia
        (confirmados if comprovacao.get('resultado') == CONFIRMADO else recusados).append(item)

    for item in recusados if registrar else ():
        comprovacao = item['evidencia']['comprovacao']
        registrar_evento(
            engine, nivel='INFO', categoria='EVIDENCIA',
            codigo='ACHADO_SEM_EVIDENCIA_CONFIRMADA',
            mensagem=comprovacao.get('motivo') or 'Evidência não confirmada na fonte oficial.',
            etapa='COMPROVACAO',
            contexto={'tipo_problema': item.get('tipo_problema'), 'colaborador': item.get('colaborador'),
                      'data_referencia': str(item.get('data_referencia') or ''),
                      'resultado': comprovacao.get('resultado'),
                      'motivo': comprovacao.get('motivo'), 'comprovacao': comprovacao,
                      'verificacoes': comprovacao.get('verificacoes')})
    return confirmados, recusados


# A resolucao oficial de jornada e' cara e nao muda dentro de uma execucao. O cache vive
# apenas no processo da esteira e some com ele; nada e' persistido aqui.
_CACHE_JORNADA: dict = {}


def resolucao_oficial(engine, source_engine, *, marca='BRACELL', operacao='EXCLUSIVA', as_of=None):
    """Resolucao de jornada da execucao, calculada uma vez por processo."""
    from .observability import obter_execution_id
    chave = (id(source_engine), obter_execution_id(criar=False), marca, operacao, as_of)
    if chave not in _CACHE_JORNADA:
        from .journey_observer import resolve_official
        _CACHE_JORNADA[chave] = resolve_official(engine, source_engine, brand=marca, operation=operacao, as_of=as_of)
    return _CACHE_JORNADA[chave]


def limpar_cache_jornada():
    _CACHE_JORNADA.clear()


def comprovar_e_registrar(engine, source_engine, achados, *, marca='BRACELL', operacao='EXCLUSIVA',
                          resolucoes=None, periodo_inicio=None, periodo_fim=None):
    """Caminho completo: carrega contexto, comprova e roteia somente o confirmado.

    Sem matriz cadastrada ou sem a fonte oficial acessivel, nenhuma oportunidade e' criada
    e o motivo fica registrado em nivel ALERTA -- a fila encolher em silencio seria pior
    do que cobrar errado.
    """
    from .observability import registrar_achado
    if not achados:
        return 0
    try:
        matriz, regras = carregar_matriz(engine, marca=marca, operacao=operacao)
        if matriz is None:
            registrar_evento(engine, nivel='ALERTA', categoria='EVIDENCIA',
                codigo='MATRIZ_EVIDENCIA_AUSENTE',
                mensagem='Marca sem matriz de origem cadastrada; nenhuma oportunidade comprovada.',
                etapa='COMPROVACAO', contexto={'marca': marca, 'operacao': operacao,
                                               'achados_descartados': len(achados)})
        status_day = carregar_status_day(source_engine, matriz,
                                         periodo_inicio=periodo_inicio, periodo_fim=periodo_fim)
        if status_day is None:
            registrar_evento(engine, nivel='ALERTA', categoria='EVIDENCIA',
                codigo='FONTE_EVIDENCIA_INACESSIVEL',
                mensagem='Status day nao consultado; achados sem comprovacao nao viram oportunidade.',
                etapa='COMPROVACAO', contexto={'marca': marca,
                                               'tabela': matriz.tabela(PAPEL_STATUS_DAY) if matriz else None,
                                               'achados_descartados': len(achados)})
        jornadas = indexar_jornada(resolucoes) if resolucoes is not None else {}
        if resolucoes is None:
            for data in sorted({str(a.get('data_referencia'))[:10] for a in achados if a.get('data_referencia')}):
                for nome, row in indexar_jornada(resolucao_oficial(
                        engine, source_engine, marca=marca, operacao=operacao, as_of=data)).items():
                    jornadas[(nome, data)] = row
        registros = carregar_checkins(source_engine, matriz, periodo_inicio=periodo_inicio, periodo_fim=periodo_fim)
        confirmados, recusados = comprovar(engine, achados, matriz=matriz, regras=regras,
                                           status_day=status_day, jornada=jornadas, registros_origem=registros,
                                           abonaveis=justificativas_abonaveis())
        if recusados:
            registrar_evento(engine, nivel='INFO', categoria='EVIDENCIA',
                codigo='ACHADOS_SEM_COMPROVACAO',
                mensagem=f'{len(recusados)} achado(s) sem evidencia confirmada nao entraram na fila.',
                etapa='COMPROVACAO', contexto={'marca': marca, 'confirmados': len(confirmados),
                                               'recusados': len(recusados)})
        return registrar_achado(engine, confirmados) if confirmados else 0
    except Exception as erro:
        registrar_evento(engine, nivel='ERRO', categoria='EVIDENCIA',
            codigo='COMPROVACAO_INDISPONIVEL',
            mensagem='Falha ao comprovar achados; o processamento principal continua.',
            etapa='COMPROVACAO', excecao=erro)
        return 0


def resumo_matriz(matriz, regras):
    """Diagnostico legivel da configuracao carregada (usado em scripts e testes)."""
    return json.dumps(dict(
        fontes=matriz.como_dicionario() if matriz else None,
        regras=sorted(regras) if regras else []), ensure_ascii=False, indent=1)
