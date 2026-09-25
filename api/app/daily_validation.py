"""Status de cada dia da validacao diaria do PDOH. Somente exibicao e contagem.

Nada aqui entra no calculo PDOH: a linha da Platina e a resolucao de jornada sao lidas como
estao. Ordem da regra (aprovada em 25/09/2026):
1. justificativa do dia                      -> DESCONSIDERADO (fora da analise, sem fallback);
2. sem visitas programadas e sem check-in    -> SEM_ATIVIDADE_PREVISTA (fora da analise);
3. check-in sem checkout real                -> CHECKOUT_ESQUECIDO (fallback: saida pela jornada);
4. demais                                    -> VALIDO.
"""
from datetime import date

from shared.operational_schedule import CHECKOUT, JORNADA_FALLBACK

VALIDO = 'VALIDO'
CHECKOUT_ESQUECIDO = 'CHECKOUT_ESQUECIDO'
DESCONSIDERADO = 'DESCONSIDERADO'
SEM_ATIVIDADE_PREVISTA = 'SEM_ATIVIDADE_PREVISTA'

ORIGEM_CONFIGURACAO = 'CONFIGURACAO'
ORIGEM_JORNADA_PADRAO = 'JORNADA_PADRAO'

# Uma coluna por dia util da semana operacional (segunda a sabado), como grava o processador.
COLUNAS_JUSTIFICATIVA = tuple(f'justificativas_{dia}' for dia in ('seg', 'ter', 'qua', 'qui', 'sex', 'sab'))
# O processador preenche "Hora Saida" vazia com 23:59 (pdoh_bracell.py); nao e checkout real.
CHECKOUT_DO_PROCESSADOR = '23:59'
# Unico tipo que e' oportunidade (decisao de 25/09/2026): checkout esquecido com fallback.
# Horas nao registradas impactam o PDOH, mas nao sao oportunidade; o registro gravado fica intacto.
TIPOS_OPORTUNIDADE = (CHECKOUT,)


def chave_dia(colaborador, dia):
    return ' '.join(str(colaborador or '').upper().split()), str(dia)[:10]


def oportunidades_do_periodo(repo, marca, inicio, fim):
    """Dias (colaborador, data) com oportunidade aberta gravada pela esteira; nada e' recalculado."""
    from sqlalchemy import select
    from shared.evidence_config import STATUS_OCORRENCIA_ENCERRADA
    tabela = repo.tables.get('oportunidade')
    if tabela is None:
        return set()
    o = tabela.c
    linhas = repo.rows(select(o.colaborador, o.data_referencia).distinct().where(
        o.marca == marca, o.tipo_problema.in_(TIPOS_OPORTUNIDADE),
        o.status_oportunidade != STATUS_OCORRENCIA_ENCERRADA,
        o.data_referencia >= inicio, o.data_referencia <= fim))
    return {chave_dia(linha['colaborador'], linha['data_referencia']) for linha in linhas}


def _hhmm(valor):
    texto = str(valor or '').strip()
    return texto[:5] if texto else None


def justificativa_do_dia(linha, dia):
    """Texto da coluna de justificativa do dia da semana da linha; domingo nao tem coluna."""
    dia = dia if isinstance(dia, date) else date.fromisoformat(str(dia)[:10])
    if dia.weekday() >= len(COLUNAS_JUSTIFICATIVA):
        return None
    texto = str(linha.get(COLUNAS_JUSTIFICATIVA[dia.weekday()]) or '').strip()
    return texto or None


def saidas_configuradas(repo, marca, operacao=None):
    """Saida padrao por jornada (horas -> HH:MM) das jornadas ativas de CHECKOUT_AUSENTE."""
    from sqlalchemy import select
    jornadas, regras = repo.tables.get('configuracao_jornada_operacao'), repo.tables.get('regra_configuracao')
    if jornadas is None or regras is None:
        return {}
    j, r = jornadas.c, regras.c
    condicoes = [j.marca == marca, j.ativo == 1, r.codigo_interno == CHECKOUT]
    if operacao:
        condicoes.append(j.operacao == operacao)
    linhas = repo.rows(select(j.jornada, j.hora_saida_padrao)
                       .select_from(jornadas.join(regras, r.configuracao_id == j.configuracao_id))
                       .where(*condicoes))
    return {float(linha['jornada']): _hhmm(linha['hora_saida_padrao']) for linha in linhas
            if linha['jornada'] is not None and _hhmm(linha['hora_saida_padrao'])}


def _saida_da_jornada(jornada, saidas):
    """Mesma escolha do motor: jornada padrao em codigo quando o cadastro nao informa a jornada."""
    if (jornada or {}).get('origem') == 'FALLBACK':
        return _hhmm(JORNADA_FALLBACK['hora_saida_padrao']), ORIGEM_JORNADA_PADRAO
    rotulo = str((jornada or {}).get('jornada_aplicada') or '').upper().removesuffix('H')
    try:
        saida = saidas.get(float(rotulo))
    except ValueError:
        saida = None
    return (saida, ORIGEM_CONFIGURACAO) if saida else (None, None)


def classificar_dia(linha, justificativa, jornada, saidas):
    """Status do dia. `linha` usa os nomes da Platina; `jornada` e' a auditoria da linha."""
    base = dict(considerado=False, fallback_aplicado=False, saida_considerada=None, origem_saida=None)
    if justificativa:
        return dict(base, status=DESCONSIDERADO,
                    motivo=f'Dia justificado ({justificativa}): fora da análise, sem fallback e sem oportunidade.')
    entrada, saida = _hhmm(linha.get('primeiro_checkin')), _hhmm(linha.get('ultimo_checkout'))
    if not entrada and not int(linha.get('visitas_diarias') or 0):
        return dict(base, status=SEM_ATIVIDADE_PREVISTA,
                    motivo='Sem visitas programadas e sem check-in: sem atividade prevista, dia fora da análise.')
    base['considerado'] = True
    if entrada and (not saida or saida == CHECKOUT_DO_PROCESSADOR):
        considerada, origem = _saida_da_jornada(jornada, saidas)
        rotulo = (jornada or {}).get('jornada_aplicada')
        inicio = f'Entrada registrada às {entrada} sem checkout informado'
        if not considerada:
            detalhe = f'jornada {rotulo} sem horário de saída configurado' if rotulo else 'jornada não identificada'
            return dict(base, status=CHECKOUT_ESQUECIDO, motivo=f'{inicio}; {detalhe}: fallback não aplicado.')
        fonte = 'jornada padrão, cadastro sem jornada' if origem == ORIGEM_JORNADA_PADRAO else 'configuração da operação'
        return dict(base, status=CHECKOUT_ESQUECIDO, fallback_aplicado=True, saida_considerada=considerada,
                    origem_saida=origem,
                    motivo=f'{inicio}; saída considerada às {considerada} pela jornada {rotulo} ({fonte}).')
    if not entrada:
        return dict(base, status=VALIDO, motivo='Sem check-in e sem justificativa: dia considerado na análise.')
    return dict(base, status=VALIDO, motivo='Entrada e saída registradas.')


def consolidar(classificados):
    """Contagem do periodo inteiro. `classificados`: (colaborador, justificativa, validacao)."""
    total = dict(dias=0, considerados=0, validos=0, checkout_esquecido=0, fallback_aplicado=0,
                 desconsiderados=0, sem_atividade_prevista=0, colaboradores=0, oportunidades=0, justificativas={})
    pessoas = set()
    for colaborador, justificativa, validacao in classificados:
        total['dias'] += 1
        pessoas.add(colaborador)
        total['considerados'] += validacao['considerado']
        total['fallback_aplicado'] += validacao['fallback_aplicado']
        total['oportunidades'] += validacao.get('gerou_oportunidade', False)
        chave = {VALIDO: 'validos', CHECKOUT_ESQUECIDO: 'checkout_esquecido', DESCONSIDERADO: 'desconsiderados',
                 SEM_ATIVIDADE_PREVISTA: 'sem_atividade_prevista'}[validacao['status']]
        total[chave] += 1
        if justificativa:
            total['justificativas'][justificativa] = total['justificativas'].get(justificativa, 0) + 1
    total['colaboradores'] = len(pessoas)
    return total
