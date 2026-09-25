"""Comprovacao das oportunidades exibidas. Somente leitura, nada e' recalculado.

De onde vem a prova
    A conta desta API tem SELECT apenas em `pdoh_controle` (mais a Platina oficial). Ela
    NAO alcanca `involves_exclusivos`. Logo, a comprovacao nao pode ser refeita aqui: ela
    e' montada pela esteira no momento da deteccao, com a origem aberta em leitura, e
    persistida dentro da propria evidencia do achado.

    Consequencia honesta e deliberada: achado gravado antes do motor de evidencias nao
    tem comprovacao. A resposta diz "evidência indisponível" com o motivo, e nunca
    fabrica uma validacao que ninguem executou.

O que esta camada faz
    Le a matriz de origem (`configuracao_evidencia`), a regra de comprovacao
    (`configuracao_evidencia_regra`) e o bloco `comprovacao` gravado na evidencia, e
    projeta tudo no contrato do endpoint. Sem UUID, sem fingerprint, sem execution_id.
"""
from sqlalchemy import select

from shared.evidence_config import (
    CONFIRMADO, DESCRICAO_CRITERIO, INDISPONIVEL, JORNADA_INDISPONIVEL, NAO_APLICAVEL,
    matriz_de_linhas, regras_de_linhas,
)
from shared.evidence_engine import MOTIVO_SEM_MATRIZ, MOTIVO_SEM_REGRA

from .alerts import evidence_object
from .findings_repository import _catalogo_por_tipo, _regra_do_grupo, group_details

MOTIVO_SEM_COMPROVACAO = (
    'Evidência indisponível: este registro foi identificado antes da camada de '
    'comprovação e a origem não é reconsultada na leitura.'
)
CHAVE_COMPROVACAO = 'comprovacao'
# Rotulos do resultado para a visao do lider. O codigo continua estavel no contrato.
ROTULO_RESULTADO = {
    CONFIRMADO: 'Confirmado na fonte oficial',
    NAO_APLICAVEL: 'Não aplicável: dia abonado',
    INDISPONIVEL: 'Evidência indisponível',
}


def _matriz(repo, marca, operacao):
    tabela = repo.tables.get('configuracao_evidencia')
    if tabela is None:
        return None
    linhas = repo.rows(select(tabela).where(tabela.c.marca == marca, tabela.c.operacao == operacao))
    return matriz_de_linhas(linhas).get((marca.upper(), operacao.upper()))


def _regras(repo, marca, operacao):
    tabela = repo.tables.get('configuracao_evidencia_regra')
    if tabela is None:
        return {}
    return regras_de_linhas(
        repo.rows(select(tabela).where(tabela.c.marca == marca, tabela.c.operacao == operacao)))


def comprovacao_da_evidencia(evidencia):
    """Bloco gravado pela esteira. Ausente significa ausente, nunca aprovado."""
    bloco = evidence_object(evidencia).get(CHAVE_COMPROVACAO)
    return bloco if isinstance(bloco, dict) else None


def resumo_validacao(evidencia):
    """Status curto para o card da fila: resultado + motivo, sem detalhe tecnico."""
    comprovacao = comprovacao_da_evidencia(evidencia)
    if not comprovacao:
        return dict(resultado=INDISPONIVEL, rotulo=ROTULO_RESULTADO[INDISPONIVEL],
                    motivo=MOTIVO_SEM_COMPROVACAO, jornada_origem=JORNADA_INDISPONIVEL)
    resultado = comprovacao.get('resultado') or INDISPONIVEL
    return dict(resultado=resultado,
                rotulo=ROTULO_RESULTADO.get(resultado, resultado),
                motivo=comprovacao.get('motivo'),
                jornada_origem=comprovacao.get('jornada_origem') or JORNADA_INDISPONIVEL)


def evidencia_resumida(evidencia, campo_do_grupo=None):
    """Uma linha de prova para o card: campo, esperado e encontrado."""
    bruta = evidence_object(evidencia)
    comprovacao = comprovacao_da_evidencia(evidencia) or {}
    esperado = comprovacao.get('esperado') or bruta.get('valor_esperado')
    encontrado = comprovacao.get('encontrado') or bruta.get('valor_encontrado')
    return dict(
        campo=comprovacao.get('campo') or campo_do_grupo,
        valor_esperado=str(esperado) if esperado is not None else None,
        valor_encontrado=str(encontrado) if encontrado is not None else None,
        fonte=comprovacao.get('fonte') or bruta.get('origem'),
    )


def _verificacoes(comprovacao, matriz, regra):
    """Uma linha por criterio. Sem comprovacao, devolve o que a regra exigiria."""
    if comprovacao:
        return [
            dict(fonte=item.get('fonte'), campo=item.get('campo'),
                 valor_encontrado=None if item.get('valor') is None else str(item['valor']),
                 valor_esperado=item.get('descricao'),
                 # Regra configuravel traz o rotulo legivel; as legadas, o identificador.
                 validacao=item.get('rotulo') or item.get('criterio'), atendido=item.get('atendido'))
            for item in (comprovacao.get('verificacoes') or [])
        ]
    if regra is None or matriz is None:
        return []
    # Sem avaliacao, cada linha explica o que o criterio EXIGE — repetir o valor esperado
    # da regra em todos eles diria "check-out real" ate para "colaborador vigente".
    return [dict(fonte=matriz.tabela(regra.papel), campo=regra.campo, valor_encontrado=None,
                 valor_esperado=DESCRICAO_CRITERIO.get(criterio, regra.valor_esperado),
                 validacao=criterio, atendido=None)
            for criterio in regra.criterios]


def group_evidence(repo, grupo_id, filters):
    """GET /api/v2/oportunidades/{grupo_id}/evidencias."""
    detalhe = group_details(repo, grupo_id, filters)
    marca, operacao = detalhe['marca'], detalhe['operacao']
    matriz = _matriz(repo, marca, operacao)
    regras = _regras(repo, marca, operacao)
    regra = regras.get(detalhe['tipo_problema'])
    catalogo_regra = _regra_do_grupo(_catalogo_por_tipo(repo), detalhe['tipo_problema'], marca)

    ocorrencias = detalhe['ocorrencias']['items']
    comprovadas = [comprovacao_da_evidencia(item['evidencia']) for item in ocorrencias]
    presentes = [bloco for bloco in comprovadas if bloco]
    # A prova e' por ocorrencia; o cabecalho usa a mais recente, que e' a primeira da lista.
    referencia = presentes[0] if presentes else None
    # Regra configuravel: a propria prova carrega a configuracao usada, entao ela nao depende
    # de linha em `configuracao_evidencia_regra` (matriz das regras legadas).
    configuravel = bool(referencia and referencia.get('configuracao_utilizada'))
    motivo = None
    if configuravel:
        pass
    elif matriz is None:
        motivo = MOTIVO_SEM_MATRIZ
    elif regra is None:
        motivo = MOTIVO_SEM_REGRA
    elif not presentes:
        motivo = MOTIVO_SEM_COMPROVACAO

    resultado = (referencia or {}).get('resultado') or INDISPONIVEL
    motivo = motivo or (referencia or {}).get('motivo')
    # Uma linha por criterio comprovado. Sem comprovacao os criterios sao os mesmos em
    # todas as ocorrencias, entao aparecem uma vez -- repetir 4 criterios x N dias seria
    # ruido, nao prova.
    evidencias = []
    for bloco in comprovadas:
        if bloco:
            evidencias.extend(_verificacoes(bloco, matriz, regra))
    if not evidencias:
        evidencias = _verificacoes(None, matriz, regra) or [
            dict(fonte=detalhe['origem'], campo=detalhe['campo'], valor_encontrado=None,
                 valor_esperado=None, validacao='sem_comprovacao', atendido=None)]

    return dict(
        oportunidade=dict(
            grupo_id=grupo_id, regra=detalhe['tipo_problema'], titulo=detalhe['titulo'],
            impacto=detalhe['impacto'], colaborador=detalhe['colaborador'],
            campo=detalhe['campo'], origem=detalhe['origem'],
            quantidade=detalhe['quantidade'], status_operacional=detalhe['status_operacional'],
            periodo=detalhe['periodo'],
        ),
        validacao=dict(
            resultado=resultado, rotulo=ROTULO_RESULTADO.get(resultado, resultado), motivo=motivo,
            jornada_origem=(referencia or {}).get('jornada_origem') or JORNADA_INDISPONIVEL,
            justificativa=(referencia or {}).get('justificativa'),
            atestado=(referencia or {}).get('atestado'),
            ocorrencias_comprovadas=len(presentes),
            ocorrencias_avaliadas=len(ocorrencias),
        ),
        fonte=(dict(
            papel=None, tabela=referencia.get('fonte_tabela') or detalhe['origem'],
            campo=referencia.get('campo') or detalhe['campo'],
            valor_esperado=referencia.get('esperado'),
            criterios=[item.get('rotulo') or item.get('criterio')
                       for item in referencia.get('verificacoes') or []],
        ) if configuravel else dict(
            papel=regra.papel if regra else None,
            tabela=matriz.tabela(regra.papel) if (matriz and regra) else detalhe['origem'],
            campo=regra.campo if regra else detalhe['campo'],
            valor_esperado=regra.valor_esperado if regra else None,
            criterios=list(regra.criterios) if regra else [],
        )),
        evidencias=evidencias,
        tratamento=dict(
            acao_recomendada=detalhe['acao_recomendada'],
            responsavel=catalogo_regra.get('responsavel_padrao'),
        ),
        ocorrencias=[dict(
            regra=detalhe['tipo_problema'], colaborador=detalhe['colaborador'],
            data=str((bloco or {}).get('data') or item.get('data_referencia') or '') or None,
            resultado_validacao=(bloco or {}).get('resultado') or INDISPONIVEL,
            fonte=(bloco or {}).get('fonte') or detalhe['origem'],
            campo=(bloco or {}).get('campo') or detalhe['campo'],
            valor_esperado=(bloco or {}).get('esperado'),
            valor_encontrado=(bloco or {}).get('encontrado'),
            motivo=(bloco or {}).get('motivo') if bloco else MOTIVO_SEM_COMPROVACAO,
            impacto=detalhe['impacto'], tratativa=detalhe['acao_recomendada'],
            jornada_origem=(bloco or {}).get('jornada_origem') or JORNADA_INDISPONIVEL,
            resultado_regra=(bloco or {}).get('resultado_regra'),
            configuracao=(bloco or {}).get('configuracao_utilizada'),
        ) for item, bloco in zip(ocorrencias, comprovadas)],
        regra_aplicada=(dict(
            codigo=referencia.get('regra') or detalhe['tipo_problema'], nome=detalhe['titulo'],
            fonte=referencia.get('fonte'), fonte_tabela=referencia.get('fonte_tabela'),
            campo=referencia.get('campo'), esperado=referencia.get('esperado'),
            encontrado=referencia.get('encontrado'), resultado=referencia.get('resultado_regra'),
            configuracao=referencia['configuracao_utilizada']) if configuravel else None),
    )


def evidence_matrix(repo, marca=None, operacao='EXCLUSIVA'):
    """GET /api/v2/configuracoes/evidencias — a matriz como esta cadastrada."""
    fontes = repo.tables.get('configuracao_evidencia')
    regras = repo.tables.get('configuracao_evidencia_regra')
    if fontes is None or regras is None:
        return dict(marcas=[])
    consulta_fontes, consulta_regras = select(fontes), select(regras)
    if marca:
        consulta_fontes = consulta_fontes.where(fontes.c.marca == marca)
        consulta_regras = consulta_regras.where(regras.c.marca == marca)
    matrizes = matriz_de_linhas(repo.rows(consulta_fontes))
    por_marca = {}
    for (chave_marca, chave_operacao), matriz in matrizes.items():
        if operacao and chave_operacao != operacao.upper():
            continue
        por_marca[chave_marca] = dict(
            marca=chave_marca, operacao=chave_operacao,
            fontes=[fonte for fonte in matriz.como_dicionario()['fontes']], regras=[])
    for linha in repo.rows(consulta_regras):
        destino = por_marca.get((linha.get('marca') or '').upper())
        if destino is None:
            continue
        regra = regras_de_linhas([linha]).get(linha['tipo_problema'])
        if regra is not None:
            destino['regras'].append(regra.como_dicionario())
    for destino in por_marca.values():
        destino['regras'].sort(key=lambda item: item['tipo_problema'])
    return dict(marcas=[por_marca[chave] for chave in sorted(por_marca)])
