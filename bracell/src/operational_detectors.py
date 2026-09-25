"""Candidatos operacionais; somente o evidence_engine autoriza a fila."""
from shared.evidence_engine import _vazio


def detectar_entrada_ausente(dataframe, tabela='status_day_operacao_bracell', marca='BRACELL'):
    if 'primeiro_checkin' not in dataframe.columns:
        return []  # Coluna ausente é diagnóstico de schema, não ausência de entrada.
    candidatos = {}
    for row in dataframe.to_dict('records'):
        if not _vazio(row['primeiro_checkin']):
            continue
        nome, data = row.get('colaborador'), row.get('dia_referencia')
        chave = (str(nome), str(data)[:10])
        candidatos[chave] = dict(marca=marca, origem='INVOLVES', tabela_origem=tabela,
            colaborador=nome, data_referencia=data, tipo_problema='CHECKIN_ENTRADA_AUSENTE',
            severidade='MEDIA', descricao_detalhada='Entrada não registrada no dia previsto.',
            evidencia=dict(campo_esperado='primeiro_checkin', valor_esperado='Entrada registrada',
                           valor_encontrado='vazio', ocorrencias=1))
    return list(candidatos.values())


def observar_operacionais(engine, source_engine, dataframe, nome_tabela, **periodo):
    from .evidence_context import comprovar_e_registrar
    if nome_tabela == 'relatorio_de_operacao':
        candidatos = detectar_entrada_ausente(dataframe)
    elif nome_tabela == 'checkin':
        from .data_quality import analisar_dataframe
        candidatos = [a for a in analisar_dataframe(dataframe, nome_tabela, 'relatorio_checkin_bracell', **periodo)
                      if a['tipo_problema'] == 'INCONSISTENCIA_HORARIO']
    else:
        return 0
    return comprovar_e_registrar(engine, source_engine, candidatos, **periodo)
