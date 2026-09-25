"""Executor de jornada: somente fontes Involves mapeadas; jornada padrao so' quando a origem nao a informa."""
from collections import defaultdict
from sqlalchemy import text
from shared.operational_schedule import (TABLE, CHECKOUT, MOTIVO_FALLBACK, ORIGEM_FALLBACK, STATUS_COM_FALLBACK,
                                         checkout_due, fallback_schedule)
from shared.rule_engine import avaliar_regra, gera_oportunidade, STATUS_ATIVA
from shared.evidence_config import CONFIRMADO, NAO_APLICAVEL

# Situacao de cada ocorrencia AVALIADA nesta execucao, para o reprocessamento encerrar o que
# deixou de existir. Linha nao avaliada (dado ausente, ambiguo, prazo ainda nao vencido) nao entra.
SITUACAO_ABERTA = 'ABERTA'
SITUACAO_RESOLVIDA = 'RESOLVIDA'


def _excecao_de_jornada(excecao):
    return excecao.get('papel_fonte') == 'jornada' and excecao.get('campo_logico') == 'status_resolucao'


def monitoring_source(fontes):
    # Une os papeis ja cadastrados da MESMA tabela. Exige instante de extracao.
    for source in fontes.get('checkout', []):
        if source.get('schema_fisico') != 'involves_bracell':
            continue
        mapping = dict(source['mapeamento_campos'])
        for role in ('checkin', 'colaborador'):
            for other in fontes.get(role, []):
                if (other['schema_fisico'], other['tabela_fisica']) == (source['schema_fisico'], source['tabela_fisica']):
                    mapping.update(other['mapeamento_campos'])
        if {'hora_entrada', 'hora_saida', 'colaborador', 'data', 'evolucao'} <= mapping.keys():
            return dict(source, mapeamento_campos=mapping, descricao='Involves')
    return None


def execute(engine, regra, fontes, provedor, leitor, inicio, fim, *, marca, operacao,
            criar=True, registrar=True, prefixo='pdoh_controle.'):
    from .regras_configuradas import _linha_logica, _nome, _dia, montar_achado, _eventos, fingerprint_ocorrencia
    from .findings import registrar_achado
    result = dict(regra=CHECKOUT, avaliadas=0, confirmadas=0, criadas=0, fallback=0, situacao={})
    situacao = result['situacao']
    with engine.connect() as connection:
        schedules = [dict(r) for r in connection.execute(text(
            f'SELECT * FROM {prefixo}{TABLE} WHERE configuracao_id=:id AND marca=:marca AND operacao=:operacao AND ativo=1'),
            dict(id=regra['configuracao_id'], marca=marca, operacao=operacao)).mappings()]
    if not schedules:
        return dict(result, motivo='Sem configuração de jornada ativa.')
    source = monitoring_source(fontes)
    if source is None:
        return dict(result, motivo='Monitoramento sem entrada, saída ou instante de extração mapeado.')
    mapping = source['mapeamento_campos']
    rows = [_linha_logica(row, mapping) for row in leitor(source, list(mapping.values()), mapping['data'], inicio, fim)]
    groups = defaultdict(list)
    for row in rows:
        groups[(_nome(row.get('colaborador')), _dia(row.get('data')))].append(row)
    proofs = []
    for (_, day), candidates in groups.items():
        if not day or not candidates[0].get('colaborador'):
            continue
        stamp = max(str(r.get('evolucao') or '') for r in candidates)
        latest = [r for r in candidates if str(r.get('evolucao') or '') == stamp]
        comparable = [{k: r.get(k) for k in ('hora_entrada', 'hora_saida')} for r in latest]
        if any(r != comparable[0] for r in comparable):
            continue  # Ambiguidade nao comprova ausencia.
        row = latest[0]
        result['avaliadas'] += 1
        chave = fingerprint_ocorrencia(CHECKOUT, marca, operacao, row['colaborador'], day)
        if row.get('hora_saida') is not None and str(row['hora_saida']).strip():
            situacao[chave] = SITUACAO_RESOLVIDA  # checkout identificado: nao ha divergencia
            continue
        resolution = provedor._resolucao(row['colaborador'], day)
        status = (resolution or {}).get('status_resolucao')
        fallback = status in STATUS_COM_FALLBACK
        if status == 'RESOLVIDA':
            schedule = next((s for s in schedules if float(s['jornada']) == float(resolution.get('jornada_semanal') or 0)), None)
        elif fallback:
            schedule = fallback_schedule()
        else:
            continue
        if not checkout_due(schedule, row):
            continue
        # Reutiliza a avaliacao de excecoes. A condicao interna nao e editavel pelo usuario.
        # Com a jornada padrao aplicada, "Jornada nao resolvida" deixa de valer para este dia
        # (a jornada foi resolvida pelo fallback); as demais excecoes continuam valendo.
        excecoes = [e for e in regra.get('excecoes') or [] if not (fallback and _excecao_de_jornada(e))]
        operational = dict(regra, tempo_minimo_minutos=0, excecoes=excecoes, condicoes=[dict(tipo='CONDICAO', status=STATUS_ATIVA,
            papel_fonte='checkout', campo_logico='hora_saida', operador='IS NULL', valor_esperado=None)])
        proof = avaliar_regra(operational, row, provedor, colaborador=row['colaborador'], data=day,
                              fonte_rotulo='Involves', fonte_tabela=source['tabela_fisica'])
        if proof and proof['resultado'] == NAO_APLICAVEL:
            situacao[chave] = SITUACAO_RESOLVIDA  # excecao passou a valer (ex.: atestado lancado)
        if proof and proof['resultado'] == CONFIRMADO:
            situacao[chave] = SITUACAO_ABERTA
            origem = ORIGEM_FALLBACK if fallback else 'CONFIGURACAO'
            proof['configuracao_operacional'] = dict(id=schedule['id'], jornada=float(schedule['jornada']),
                hora_entrada_padrao=schedule['hora_entrada_padrao'], hora_saida_padrao=schedule['hora_saida_padrao'],
                origem=origem)
            proof['monitoramento'] = {key: str(row[key]) if row.get(key) is not None else None
                                     for key in ('hora_entrada', 'hora_saida', 'data', 'evolucao')}
            proof['esperado'] = f"Checkout registrado até a saída esperada às {schedule['hora_saida_padrao']}"
            proof['jornada_aplicada'] = float(schedule['jornada'])
            proof['horario_esperado'] = str(schedule['hora_saida_padrao'])[:5]
            if fallback:
                result['fallback'] += 1
                proof['jornada_origem'] = ORIGEM_FALLBACK
                proof['motivo_fallback'] = MOTIVO_FALLBACK
                proof['verificacoes'].append(dict(
                    criterio='jornada', rotulo='Jornada padrão (fallback)', atendido=True,
                    descricao=MOTIVO_FALLBACK, fonte=None, campo='status_resolucao', valor=status))
            proofs.append(proof)
    result['confirmadas'] = len(proofs)
    if criar and proofs and gera_oportunidade(regra, regra['tratamentos'])[0]:
        result['criadas'] = registrar_achado(engine, [montar_achado(regra, p, marca=marca, operacao=operacao,
                                                                  fonte=source) for p in proofs])
    _eventos(engine, registrar, 'INFO', 'JORNADA_MONITORAMENTO', 'Monitoramento operacional de checkout avaliado.',
             dict(marca=marca, operacao=operacao, fonte='Involves', campo='Último checkout',
                  ultima_atualizacao=max((str(r['evolucao']) for r in rows if r.get('evolucao')), default=None),
                  colaboradores_analisados=len({name for name, _ in groups if name}), motivo=None, **{k: v for k, v in result.items() if k != 'situacao'}))
    return result


def evidence_matches(connection, marca, operacao, proof):
    """Porta final: caminhos legados sem configuracao comprovada nao criam checkout."""
    if not isinstance(proof, dict):
        return False
    config, monitored = proof.get('configuracao_operacional'), proof.get('monitoramento')
    if not isinstance(config, dict) or not isinstance(monitored, dict):
        return False
    if config.get('origem') == ORIGEM_FALLBACK:
        # Jornada padrao: vale apenas se for identica a definicao em codigo.
        padrao = fallback_schedule()
        return (all(str(padrao[k]) == str(config.get(k)) for k in ('id', 'hora_entrada_padrao', 'hora_saida_padrao'))
                and float(padrao['jornada']) == float(config.get('jornada') or 0)
                and checkout_due(padrao, monitored))
    schedule = connection.execute(text(
        f'SELECT j.* FROM pdoh_controle.{TABLE} j JOIN pdoh_controle.regra_configuracao r '
        'ON r.configuracao_id=j.configuracao_id WHERE j.id=:id AND j.marca=:marca '
        'AND j.operacao=:operacao AND r.codigo_interno=:codigo AND j.ativo=1 FOR SHARE'),
        dict(id=config.get('id'), marca=marca, operacao=operacao, codigo=CHECKOUT)).mappings().first()
    return bool(schedule and all(str(schedule[k]) == str(config.get(k)) for k in
                                 ('hora_entrada_padrao', 'hora_saida_padrao'))
                and float(schedule['jornada']) == float(config.get('jornada') or 0)
                and checkout_due(schedule, monitored))
