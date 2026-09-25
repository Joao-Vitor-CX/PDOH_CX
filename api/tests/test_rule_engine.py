"""Executor de regras: o motor so faz o que a configuracao manda.

A regra usada aqui e' a HORAS_AUSENTES exatamente como sera cadastrada (condicao, tempo
minimo e as quatro excecoes), com valores reais observados na origem BRACELL. Nenhum teste
acessa banco: `shared.rule_engine` e' puro.
"""
from datetime import time, timedelta
import unittest

from shared.evidence_config import CONFIRMADO, INDISPONIVEL, NAO_APLICAVEL
from shared.rule_engine import (
    REGRA_INATIVA, REGRA_NAO_CADASTRADA, REGRA_SEM_GERACAO, SEM_REGISTRO, ConfiguracaoInvalida,
    TIPO_BOOLEANO, TIPO_DURACAO, TIPO_HORA, TIPO_NUMERO, TIPO_PERCENTUAL, TIPO_TEXTO,
    avaliar_regra, codigos_liberados, comparar, descrever_condicao, gera_oportunidade, operadores_do_tipo,
    rotulo_do_papel, segundos, texto_normalizado, validar_valor,
)

ABONAVEIS = ['FÉRIAS', 'FERIADO', 'FOLGA', 'SEM SISTEMA', 'LICENÇA PATERNIDADE', 'CASAMENTO']


def excecao(ordem, nome, papel, campo, operador, valor, status='ATIVA'):
    return dict(tipo='BLOQUEIO', ordem=ordem, papel_fonte=papel, campo_logico=campo,
                operador=operador, valor_esperado=valor, descricao=nome, status=status)


def regra_horas_ausentes(tempo_minimo=0, **status):
    return dict(
        codigo_interno='HORAS_AUSENTES', nome_regra='Horas ausentes', tempo_minimo_minutos=tempo_minimo,
        condicoes=[dict(tipo='CONDICAO', ordem=1, papel_fonte='pdoh', campo_logico='horas_nao_registradas',
                        operador='MAIOR_QUE', valor_esperado='00:00', descricao='', status='ATIVA')],
        excecoes=[
            excecao(1, 'Atestado', 'colaborador', 'afastado', 'CONTEM', 'ATESTADO', status.get('atestado', 'ATIVA')),
            excecao(2, 'Afastamento', 'colaborador', 'afastado', 'EM_LISTA', ABONAVEIS, status.get('afastamento', 'ATIVA')),
            excecao(3, 'Sem jornada', 'jornada', 'status_resolucao', 'DIFERENTE_DE', 'RESOLVIDA', status.get('jornada', 'ATIVA')),
            excecao(4, 'Sem roteiro', 'colaborador', 'tem_roteiro', 'IGUAL_A', False, status.get('roteiro', 'ATIVA')),
        ])


def provedor_de(**valores):
    """Provedor de valores para as excecoes. Padrao: dia normal, sem nenhuma excecao."""
    base = {('colaborador', 'afastado'): None, ('colaborador', 'tem_roteiro'): 'Sim',
            ('jornada', 'status_resolucao'): 'RESOLVIDA'}
    base.update({tuple(chave.split('.')): valor for chave, valor in valores.items()})

    def provedor(excecao_, colaborador, data):
        return base.get((excecao_['papel_fonte'], excecao_['campo_logico']), SEM_REGISTRO)
    provedor.jornada_origem = lambda colaborador, data: 'INVOLVES'
    return provedor


def avaliar(linha, provedor=None, regra=None):
    return avaliar_regra(regra or regra_horas_ausentes(), linha, provedor or provedor_de(),
                         colaborador='ANA', data='2026-09-03',
                         fonte_rotulo='PDOH Platina',
                         fonte_tabela='exclusivo_bracell_platina_relatorio_pdoh')


class OperadoresTest(unittest.TestCase):
    def test_duracao_compara_por_tempo_e_nao_por_texto(self):
        self.assertTrue(comparar('MAIOR_QUE', '00:32:19', '00:00', 'duracao'))
        self.assertFalse(comparar('MAIOR_QUE', '00:00:00', '00:00', 'duracao'))
        self.assertTrue(comparar('MAIOR_IGUAL', '00:30:00', '00:30', 'duracao'))
        self.assertTrue(comparar('MENOR_QUE', '00:09:59', '00:10', 'duracao'))
        # "10:00" > "9:59" como tempo, embora o contrario como texto.
        self.assertTrue(comparar('MAIOR_QUE', '10:00:00', '9:59', 'duracao'))

    def test_time_do_mysql_chega_como_timedelta_e_como_time(self):
        self.assertTrue(comparar('MAIOR_QUE', timedelta(minutes=32, seconds=19), '00:00', 'duracao'))
        self.assertTrue(comparar('MAIOR_QUE', time(0, 32, 19), '00:00', 'duracao'))
        self.assertEqual(90000, segundos(timedelta(hours=25)))      # TIME passa de 24h

    def test_ordem_contra_valor_ausente_e_desconhecida_nao_falsa(self):
        """A ausencia nao prova que o valor e' pequeno: nao pode virar 'condicao nao atendida'."""
        self.assertIsNone(comparar('MAIOR_QUE', None, '00:00', 'duracao'))
        self.assertIsNone(comparar('MAIOR_QUE', '', '00:00', 'duracao'))
        self.assertIsNone(comparar('MAIOR_QUE', 'texto qualquer', '00:00', 'duracao'))

    def test_texto_ignora_acento_caixa_e_espaco(self):
        self.assertEqual('licenca paternidade', texto_normalizado('  LICENÇA   Paternidade '))
        self.assertTrue(comparar('CONTEM', 'CX - ATESTADO MÉDICO 3 DIAS', 'atestado'))
        self.assertTrue(comparar('EM_LISTA', 'ferias', ABONAVEIS))
        self.assertTrue(comparar('EM_LISTA', 'FERIADO', ABONAVEIS))

    def test_contem_e_lista_sobre_campo_vazio_sao_falsos(self):
        self.assertFalse(comparar('CONTEM', None, 'ATESTADO'))
        self.assertFalse(comparar('EM_LISTA', '', ABONAVEIS))

    def test_falta_nao_justificada_nao_e_atestado_nem_afastamento(self):
        self.assertFalse(comparar('CONTEM', 'FALTA NÃO JUSTIFICADA', 'ATESTADO'))
        self.assertFalse(comparar('EM_LISTA', 'FALTA NÃO JUSTIFICADA', ABONAVEIS))

    def test_booleano_aceita_sim_nao_da_origem(self):
        self.assertTrue(comparar('IGUAL_A', 'Não', False))
        self.assertFalse(comparar('IGUAL_A', 'Sim', False))
        self.assertTrue(comparar('DIFERENTE_DE', 'Sim', False))

    def test_vazio_e_nao_vazio(self):
        self.assertTrue(comparar('IS NULL', None, None))
        self.assertTrue(comparar('IS NULL', '  ', None))
        self.assertTrue(comparar('IS NOT NULL', '08:00:00', None))

    def test_menor_que_campo_compara_dois_instantes_da_mesma_linha(self):
        self.assertTrue(comparar('MENOR_QUE_CAMPO', '2026-09-01 08:00:00', None, None, outro='2026-09-01 09:00:00'))
        self.assertIsNone(comparar('MENOR_QUE_CAMPO', '2026-09-01 08:00:00', None, None, outro=None))

    def test_operador_desconhecido_e_erro_de_configuracao(self):
        with self.assertRaises(ConfiguracaoInvalida):
            comparar('PARECIDO_COM', 'a', 'b')


class HorasAusentesTest(unittest.TestCase):
    # ------------------------------------------------------- Cenario 1: condicao atendida
    def test_condicao_atendida_sem_excecao_confirma_e_explica_a_origem(self):
        prova = avaliar({'horas_nao_registradas': '00:32:19'})
        self.assertEqual(CONFIRMADO, prova['resultado'])
        self.assertIsNone(prova['motivo'])
        self.assertEqual('Oportunidade gerada', prova['resultado_regra'])
        # Rastreabilidade: regra, fonte, campo, esperado, encontrado e configuracao usada.
        self.assertEqual('HORAS_AUSENTES', prova['regra'])
        self.assertEqual('PDOH Platina', prova['fonte'])
        self.assertEqual('exclusivo_bracell_platina_relatorio_pdoh', prova['fonte_tabela'])
        self.assertEqual('horas_nao_registradas', prova['campo'])
        self.assertEqual('Horas não registradas maior que 00:00', prova['esperado'])
        self.assertEqual('00:32:19', prova['encontrado'])
        self.assertEqual('INVOLVES', prova['jornada_origem'])
        configuracao = prova['configuracao_utilizada']
        self.assertEqual(0, configuracao['tempo_minimo_minutos'])
        self.assertEqual('Horas não registradas maior que 00:00', configuracao['condicoes'][0]['descricao'])
        self.assertEqual(['Atestado', 'Afastamento', 'Sem jornada', 'Sem roteiro'],
                         [e['nome'] for e in configuracao['excecoes']])
        self.assertTrue(all(e['ativa'] for e in configuracao['excecoes']))

    def test_toda_verificacao_carrega_criterio_rotulo_e_estado(self):
        prova = avaliar({'horas_nao_registradas': '00:32:19'})
        self.assertEqual(['condicao'] + ['excecao'] * 4, [v['criterio'] for v in prova['verificacoes']])
        self.assertEqual(['Condição da regra', 'Exceção: Atestado', 'Exceção: Afastamento',
                          'Exceção: Sem jornada', 'Exceção: Sem roteiro'],
                         [v['rotulo'] for v in prova['verificacoes']])
        self.assertTrue(all(v['atendido'] is True for v in prova['verificacoes']))

    def test_condicao_nao_atendida_nao_e_candidata(self):
        self.assertIsNone(avaliar({'horas_nao_registradas': '00:00:00'}))
        self.assertIsNone(avaliar({'horas_nao_registradas': timedelta(0)}))

    # ------------------------------------------------------- tempo minimo
    def test_tempo_minimo_e_a_tolerancia_configurada(self):
        regra = regra_horas_ausentes(tempo_minimo=30)
        self.assertIsNone(avaliar({'horas_nao_registradas': '00:29:59'}, regra=regra))
        prova = avaliar({'horas_nao_registradas': '00:30:00'}, regra=regra)
        self.assertEqual(CONFIRMADO, prova['resultado'])
        self.assertEqual(30, prova['configuracao_utilizada']['tempo_minimo_minutos'])
        self.assertIn('Tempo mínimo', [v['rotulo'] for v in prova['verificacoes']])

    def test_tempo_minimo_zero_nao_cria_criterio_extra(self):
        prova = avaliar({'horas_nao_registradas': '00:00:01'})
        self.assertNotIn('tempo_minimo', [v['criterio'] for v in prova['verificacoes']])

    # ------------------------------------------------------- excecoes
    def test_atestado_impede_e_diz_qual_foi_o_registro(self):
        prova = avaliar({'horas_nao_registradas': '02:10:00'},
                        provedor_de(**{'colaborador.afastado': 'CX - ATESTADO MÉDICO 3 DIAS'}))
        self.assertEqual(NAO_APLICAVEL, prova['resultado'])
        self.assertEqual('Exceção aplicada: Atestado (CX - ATESTADO MÉDICO 3 DIAS)', prova['motivo'])

    def test_afastamento_da_lista_oficial_impede(self):
        prova = avaliar({'horas_nao_registradas': '04:00:00'},
                        provedor_de(**{'colaborador.afastado': 'FERIADO'}))
        self.assertEqual(NAO_APLICAVEL, prova['resultado'])
        self.assertIn('Afastamento', prova['motivo'])

    def test_falta_nao_justificada_nao_e_excecao_e_continua_sendo_oportunidade(self):
        prova = avaliar({'horas_nao_registradas': '04:00:00'},
                        provedor_de(**{'colaborador.afastado': 'FALTA NÃO JUSTIFICADA'}))
        self.assertEqual(CONFIRMADO, prova['resultado'])

    def test_sem_roteiro_impede(self):
        prova = avaliar({'horas_nao_registradas': '01:00:00'},
                        provedor_de(**{'colaborador.tem_roteiro': 'Não'}))
        self.assertEqual(NAO_APLICAVEL, prova['resultado'])
        self.assertIn('Sem roteiro', prova['motivo'])

    def test_sem_jornada_impede(self):
        prova = avaliar({'horas_nao_registradas': '01:00:00'},
                        provedor_de(**{'jornada.status_resolucao': 'NAO_ENCONTRADA'}))
        self.assertEqual(NAO_APLICAVEL, prova['resultado'])
        self.assertIn('Sem jornada', prova['motivo'])

    def test_excecao_desligada_na_configuracao_e_ignorada(self):
        """O usuario desmarcou 'Atestado': o mesmo dia passa a gerar oportunidade."""
        provedor = provedor_de(**{'colaborador.afastado': 'CX - ATESTADO MÉDICO 3 DIAS'})
        com = avaliar({'horas_nao_registradas': '02:10:00'}, provedor)
        sem = avaliar({'horas_nao_registradas': '02:10:00'}, provedor,
                      regra_horas_ausentes(atestado='INATIVA'))
        self.assertEqual(NAO_APLICAVEL, com['resultado'])
        self.assertEqual(CONFIRMADO, sem['resultado'])
        self.assertFalse(sem['configuracao_utilizada']['excecoes'][0]['ativa'])
        self.assertEqual(3, len([v for v in sem['verificacoes'] if v['criterio'] == 'excecao']))

    # ------------------------------------------------------- Cenario 4: dados insuficientes
    def test_registro_da_excecao_nao_localizado_e_indisponivel_nunca_confirmado(self):
        def sem_status_day(excecao_, colaborador, data):
            return SEM_REGISTRO if excecao_['papel_fonte'] == 'colaborador' else 'RESOLVIDA'
        prova = avaliar({'horas_nao_registradas': '01:00:00'}, sem_status_day)
        self.assertEqual(INDISPONIVEL, prova['resultado'])
        self.assertIn('Atestado', prova['motivo'])
        self.assertEqual('Dados insuficientes; nenhuma oportunidade foi criada', prova['resultado_regra'])
        naoverificaveis = [v for v in prova['verificacoes'] if v['atendido'] is None]
        self.assertEqual(3, len(naoverificaveis))             # atestado, afastamento e roteiro

    def test_campo_da_condicao_sem_valor_e_indisponivel(self):
        prova = avaliar({'horas_nao_registradas': None})
        self.assertEqual(INDISPONIVEL, prova['resultado'])
        self.assertEqual('Horas não registradas sem valor na fonte oficial', prova['motivo'])

    def test_excecao_aplicada_tem_precedencia_sobre_dado_ausente_de_outra(self):
        """Se uma excecao ja barra, faltar dado para outra nao muda a decisao."""
        def misto(excecao_, colaborador, data):
            if excecao_['campo_logico'] == 'afastado':
                return 'FERIADO'
            return SEM_REGISTRO
        self.assertEqual(NAO_APLICAVEL, avaliar({'horas_nao_registradas': '01:00:00'}, misto)['resultado'])

    def test_regra_sem_condicao_ativa_e_configuracao_invalida(self):
        regra = regra_horas_ausentes()
        regra['condicoes'][0]['status'] = 'INATIVA'
        with self.assertRaises(ConfiguracaoInvalida):
            avaliar({'horas_nao_registradas': '01:00:00'}, regra=regra)

    def test_descricao_da_condicao_le_como_negocio(self):
        condicao = regra_horas_ausentes()['condicoes'][0]
        self.assertEqual('Horas não registradas maior que 00:00', descrever_condicao(condicao))
        self.assertEqual('Afastamento ou atestado está vazio', descrever_condicao(
            dict(papel_fonte='colaborador', campo_logico='afastado', operador='IS NULL')))


class PortaDeDecisaoTest(unittest.TestCase):
    """Uma unica definicao de "regra ativa" para a esteira e para a API."""
    ATIVA = dict(configuracao_id='r1', marca='BRACELL', operacao='EXCLUSIVA', codigo_interno='HORAS_AUSENTES',
                 status='ATIVA', geracao_automatica_ativa=True)
    GERA = [dict(resultado='CONFIRMADO', gera_oportunidade=True, status='ATIVO')]

    def test_regra_inexistente(self):
        self.assertEqual((False, REGRA_NAO_CADASTRADA), gera_oportunidade(None, self.GERA))

    def test_regra_inativa(self):
        self.assertEqual((False, REGRA_INATIVA), gera_oportunidade({**self.ATIVA, 'status': 'INATIVA'}, self.GERA))
        # Status ATIVA com geracao automatica desligada tambem nao gera.
        self.assertEqual((False, REGRA_INATIVA),
                         gera_oportunidade({**self.ATIVA, 'geracao_automatica_ativa': False}, self.GERA))
        self.assertEqual((False, REGRA_INATIVA), gera_oportunidade({**self.ATIVA, 'status': 'EM_VALIDACAO'}, self.GERA))

    def test_regra_ativa_com_geracao_desligada_analisa_mas_nao_gera(self):
        desligada = [dict(resultado='CONFIRMADO', gera_oportunidade=False, status='ATIVO')]
        self.assertEqual((False, REGRA_SEM_GERACAO), gera_oportunidade(self.ATIVA, desligada))
        self.assertEqual((False, REGRA_SEM_GERACAO), gera_oportunidade(self.ATIVA, []))
        # A tratativa de OUTRO resultado nao autoriza a geracao.
        outro = [dict(resultado='NAO_APLICAVEL', gera_oportunidade=True, status='ATIVO')]
        self.assertEqual((False, REGRA_SEM_GERACAO), gera_oportunidade(self.ATIVA, outro))

    def test_regra_ativa_e_configurada_para_gerar(self):
        self.assertEqual((True, None), gera_oportunidade(self.ATIVA, self.GERA))

    def test_codigos_liberados_por_marca_e_operacao(self):
        regras = [self.ATIVA,
                  {**self.ATIVA, 'configuracao_id': 'r2', 'codigo_interno': 'CHECKOUT_AUSENTE', 'status': 'INATIVA'},
                  {**self.ATIVA, 'configuracao_id': 'r3', 'codigo_interno': 'OUTRA', 'marca': 'FLORA'}]
        tratamentos = [{**self.GERA[0], 'configuracao_id': cid} for cid in ('r1', 'r2', 'r3')]
        self.assertEqual({('BRACELL', 'EXCLUSIVA'): {'HORAS_AUSENTES'}, ('FLORA', 'EXCLUSIVA'): {'OUTRA'}},
                         codigos_liberados(regras, tratamentos))


class EdicaoDeCondicaoTest(unittest.TestCase):
    """O que a tela pode oferecer e gravar: so' o que o motor sabe interpretar depois."""

    def test_duracao_e_normalizada_para_hh_mm(self):
        self.assertEqual('00:30', validar_valor('MAIOR_QUE', TIPO_DURACAO, '0:30'))
        self.assertEqual('01:05', validar_valor('MAIOR_IGUAL', TIPO_DURACAO, ' 1:5 '))
        self.assertEqual('00:00:30', validar_valor('MAIOR_QUE', TIPO_DURACAO, '00:00:30'))
        self.assertEqual('00:00', validar_valor('MAIOR_QUE', TIPO_DURACAO, '00:00:00'))

    def test_duracao_invalida_e_recusada_com_mensagem_de_negocio(self):
        for invalido in ('', 'abc', '-01:00', '10', '00:75', 30, None):
            with self.subTest(valor=invalido), self.assertRaises(ConfiguracaoInvalida) as erro:
                validar_valor('MAIOR_QUE', TIPO_DURACAO, invalido)
            self.assertIn('HH:MM', str(erro.exception))

    def test_numero_booleano_lista_e_texto(self):
        self.assertEqual(5, validar_valor('MAIOR_QUE', TIPO_NUMERO, '5,0'))
        self.assertEqual(2.5, validar_valor('MENOR_QUE', TIPO_PERCENTUAL, '2,5'))
        self.assertIs(False, validar_valor('IGUAL_A', TIPO_BOOLEANO, 'Não'))
        self.assertIs(True, validar_valor('IGUAL_A', TIPO_BOOLEANO, 'sim'))
        self.assertEqual(['FERIADO', 'FOLGA'], validar_valor('EM_LISTA', TIPO_TEXTO, ' FERIADO, FOLGA ,'))
        self.assertEqual(['A'], validar_valor('EM_LISTA', TIPO_TEXTO, ['A', ' ']))
        self.assertEqual('ATESTADO', validar_valor('CONTEM', TIPO_TEXTO, ' ATESTADO '))
        for operador, tipo, invalido in (('MAIOR_QUE', TIPO_NUMERO, 'x'), ('IGUAL_A', TIPO_BOOLEANO, 'talvez'),
                                         ('CONTEM', TIPO_TEXTO, '  '), ('EM_LISTA', TIPO_TEXTO, ' , ')):
            with self.subTest(operador=operador, valor=invalido), self.assertRaises(ConfiguracaoInvalida):
                validar_valor(operador, tipo, invalido)

    def test_operador_sem_valor_ignora_o_valor_informado(self):
        self.assertIsNone(validar_valor('IS NULL', TIPO_TEXTO, 'qualquer'))
        self.assertIsNone(validar_valor('IS NOT NULL', TIPO_DURACAO, None))

    def test_valor_validado_e_o_que_o_motor_compara(self):
        """Ida e volta: o que a tela grava, a esteira entende."""
        valor = validar_valor('MAIOR_QUE', TIPO_DURACAO, '0:30')
        self.assertTrue(comparar('MAIOR_QUE', timedelta(minutes=45), valor, TIPO_DURACAO))
        self.assertFalse(comparar('MAIOR_QUE', timedelta(minutes=20), valor, TIPO_DURACAO))

    def test_operadores_oferecidos_dependem_do_tipo_do_campo(self):
        codigos = lambda tipo, atual=None: [o['codigo'] for o in operadores_do_tipo(tipo, atual)]
        self.assertEqual(['MAIOR_QUE', 'MAIOR_IGUAL', 'MENOR_QUE', 'MENOR_IGUAL', 'IGUAL_A', 'DIFERENTE_DE',
                          'IS NULL', 'IS NOT NULL'], codigos(TIPO_DURACAO))
        self.assertEqual(['IGUAL_A', 'DIFERENTE_DE'], codigos(TIPO_BOOLEANO))
        self.assertIn('EM_LISTA', codigos(TIPO_TEXTO))
        self.assertNotIn('MAIOR_QUE', codigos(TIPO_TEXTO))
        self.assertEqual('Maior que', operadores_do_tipo(TIPO_DURACAO)[0]['rotulo'])
        # Operador legado que a tela nao sabe editar: so' ele mesmo, nunca uma troca por outro.
        self.assertEqual(['MENOR_QUE_CAMPO'], codigos(TIPO_HORA, 'MENOR_QUE_CAMPO'))
        # Tipo desconhecido cai no conjunto de texto (o mais conservador).
        self.assertEqual(codigos(TIPO_TEXTO), codigos(None))

    def test_rotulos_de_papel_para_a_tela(self):
        self.assertEqual('PDOH Platina', rotulo_do_papel('pdoh'))
        self.assertEqual('Cadastro de colaboradores', rotulo_do_papel('colaborador'))
        self.assertEqual('Papel novo', rotulo_do_papel('papel_novo'))


if __name__ == '__main__':
    unittest.main()
