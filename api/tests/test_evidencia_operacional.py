"""Camada de evidencia: nenhuma oportunidade sem comprovacao da origem.

Exercita o motor puro (`shared.evidence_engine`) e o endpoint de leitura. Nenhum teste
toca MySQL, Docker ou a esteira; as fontes oficiais sao fixtures sinteticas.
"""
from datetime import date, datetime
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.app.config import Settings
from api.app.main import create_app
from api.tests.test_api import FixtureDatabase
from shared.evidence_config import (
    CONFIRMADO, INDISPONIVEL, JORNADA_FALLBACK, JORNADA_INVOLVES, JORNADA_RAW,
    NAO_APLICAVEL, matriz_de_linhas, regras_de_linhas,
)
from shared.evidence_engine import avaliar, deve_gerar_oportunidade, origem_da_jornada

SEGUNDA, SABADO = date(2026, 8, 31), date(2026, 9, 5)
ABONAVEIS = ['FÉRIAS', 'FERIADO', 'FOLGA']

FONTES = [
    dict(marca='BRACELL', operacao='EXCLUSIVA', papel='status_day',
         tabela='status_day_operacao_bracell',
         campos={'colaborador': 'colaborador', 'data': 'dia_referencia', 'roteiro': 'tem_roteiro',
                 'entrada': 'primeiro_checkin', 'saida': 'ultimo_checkout', 'afastamento': 'afastado'}),
    dict(marca='BRACELL', operacao='EXCLUSIVA', papel='colaborador',
         tabela='colaboradores_ativos_bracell',
         campos={'colaborador': 'nome_colaborador', 'ativo': 'usuario_ativo', 'jornada': 'nome_pai'}),
    dict(marca='BRACELL', operacao='EXCLUSIVA', papel='checkin',
         tabela='relatorio_checkin_bracell',
         campos={'colaborador': 'colaborador', 'data': 'data_roteiro', 'saida': 'hora_saida'}),
]
REGRAS = [
    dict(marca='BRACELL', operacao='EXCLUSIVA', tipo_problema='CHECKIN_ENTRADA_AUSENTE',
         papel='status_day', campo='primeiro_checkin', valor_esperado='Entrada registrada no dia trabalhado',
         criterios=['colaborador_vigente', 'dia_trabalhado', 'jornada_resolvida', 'sem_abono'],
         papeis_apoio=['colaborador']),
    dict(marca='BRACELL', operacao='EXCLUSIVA', tipo_problema='CHECKOUT_AUSENTE',
         papel='checkin', campo='hora_saida', valor_esperado='Check-out real apos a entrada registrada',
         criterios=['colaborador_vigente', 'dia_trabalhado', 'houve_entrada', 'sem_abono'],
         papeis_apoio=['status_day']),
]


def matriz():
    return matriz_de_linhas(FONTES)[('BRACELL', 'EXCLUSIVA')]


def regras():
    return regras_de_linhas(REGRAS)


def jornada(**extras):
    base = dict(colaborador='ANA', vigente=True, elegivel=True, jornada_semanal=44.0,
                fonte='colaboradores_ativos_bracell', campo='nome_pai', perfil='PROMOTOR EXCLUSIVO')
    base.update(extras)
    return base


def status(**extras):
    base = dict(colaborador='ANA', dia_referencia=SEGUNDA, tem_roteiro='Sim',
                primeiro_checkin=None, ultimo_checkout=None, afastado=None)
    base.update(extras)
    return base


def achado(tipo='CHECKIN_ENTRADA_AUSENTE', **extras):
    base = dict(tipo_problema=tipo, marca='BRACELL', colaborador='ANA', data_referencia=SEGUNDA,
                tabela_origem='status_day_operacao_bracell',
                evidencia={'campo_esperado': 'primeiro_checkin', 'valor_encontrado': '(ausente)',
                           'valor_esperado': 'Entrada registrada'})
    base.update(extras)
    return base


class MotorDeEvidenciasTest(unittest.TestCase):
    def avaliar(self, contexto, item=None, tipo='CHECKIN_ENTRADA_AUSENTE'):
        return avaliar(item or achado(tipo), contexto, matriz(), regras())

    # ------------------------------------------------- nenhuma oportunidade sem evidência
    def test_evidencia_confirmada_carrega_origem_campo_esperado_e_encontrado(self):
        prova = self.avaliar(dict(status_day=status(), jornada=jornada(),
                                  justificativas_abonaveis=ABONAVEIS))
        self.assertEqual(CONFIRMADO, prova['resultado'])
        self.assertTrue(deve_gerar_oportunidade(prova))
        self.assertEqual('status_day_operacao_bracell', prova['fonte'])
        self.assertEqual('primeiro_checkin', prova['campo'])
        self.assertEqual('Entrada registrada no dia trabalhado', prova['esperado'])
        self.assertEqual('CHECKIN_ENTRADA_AUSENTE', prova['regra'])
        self.assertEqual('ANA', prova['colaborador'])
        self.assertIsNone(prova['motivo'])
        # Todo critério cadastrado foi efetivamente verificado, nenhum ficou em aberto.
        self.assertEqual(['colaborador_vigente', 'dia_trabalhado', 'jornada_resolvida', 'sem_abono', 'ocorrencia_na_fonte'],
                         [item['criterio'] for item in prova['verificacoes']])
        self.assertTrue(all(item['atendido'] for item in prova['verificacoes']))

    def test_sem_matriz_ou_sem_regra_nunca_vira_oportunidade(self):
        sem_matriz = avaliar(achado(), dict(status_day=status(), jornada=jornada()), None, regras())
        self.assertEqual(INDISPONIVEL, sem_matriz['resultado'])
        self.assertFalse(deve_gerar_oportunidade(sem_matriz))
        sem_regra = avaliar(achado('REGRA_INEXISTENTE'), dict(status_day=status(), jornada=jornada()),
                            matriz(), regras())
        self.assertEqual(INDISPONIVEL, sem_regra['resultado'])
        self.assertIn('regra de evidência', sem_regra['motivo'])

    def test_fonte_nao_consultada_e_indisponivel_e_nao_confirmado_por_omissao(self):
        prova = self.avaliar(dict(jornada=jornada()))          # sem a chave status_day
        self.assertEqual(INDISPONIVEL, prova['resultado'])
        self.assertIn('não foi consultada', prova['motivo'])
        self.assertFalse(deve_gerar_oportunidade(prova))

    def test_colaborador_sem_registro_no_dia_nao_gera_cobranca(self):
        prova = self.avaliar(dict(status_day=None, jornada=jornada()))
        self.assertEqual(INDISPONIVEL, prova['resultado'])
        self.assertIn('Não há registro do colaborador', prova['motivo'])

    # ------------------------------------------------- campo vazio não basta
    def test_campo_vazio_sozinho_nao_sustenta_oportunidade(self):
        """Sem roteiro no dia, a entrada ausente deixa de ser cobrança."""
        prova = self.avaliar(dict(status_day=status(tem_roteiro='Não', primeiro_checkin=None),
                                  jornada=jornada(), justificativas_abonaveis=ABONAVEIS))
        self.assertEqual(NAO_APLICAVEL, prova['resultado'])
        self.assertIn('sem roteiro', prova['motivo'].lower())
        self.assertFalse(deve_gerar_oportunidade(prova))

    def test_colaborador_fora_do_perfil_operacional_nao_gera_oportunidade(self):
        prova = self.avaliar(dict(status_day=status(), jornada=jornada(elegivel=False),
                                  justificativas_abonaveis=ABONAVEIS))
        self.assertEqual(NAO_APLICAVEL, prova['resultado'])
        self.assertIn('fora do perfil', prova['motivo'])

    # ------------------------------------------------- atestado impede falso positivo
    def test_justificativa_abonavel_impede_a_oportunidade(self):
        prova = self.avaliar(dict(status_day=status(afastado='FÉRIAS'), jornada=jornada(),
                                  justificativas_abonaveis=ABONAVEIS))
        self.assertEqual(NAO_APLICAVEL, prova['resultado'])
        self.assertTrue(prova['justificativa'])
        self.assertFalse(prova['atestado'])
        self.assertEqual('FÉRIAS', prova['ausencia_registrada'])
        self.assertFalse(deve_gerar_oportunidade(prova))

    def test_atestado_fora_da_lista_abonavel_tambem_impede(self):
        """Ausência que não está na lista continua bloqueando: é afastamento, não cobrança."""
        prova = self.avaliar(dict(status_day=status(afastado='ATESTADO MEDICO'), jornada=jornada(),
                                  justificativas_abonaveis=ABONAVEIS))
        self.assertEqual(NAO_APLICAVEL, prova['resultado'])
        self.assertTrue(prova['atestado'])
        self.assertFalse(prova['justificativa'])
        self.assertIn('atestado, afastamento ou justificativa', prova['motivo'].lower())

    def test_checkout_ausente_exige_entrada_registrada(self):
        item = achado('CHECKOUT_AUSENTE', tabela_origem='relatorio_checkin_bracell',
                      evidencia={'campo_esperado': 'hora_saida', 'valor_encontrado': '(ausente)'})
        registro = dict(colaborador='ANA', data_roteiro=SEGUNDA, hora_entrada='08:00:00',
                        hora_saida=None, checkout_sistema=None, checkout_registrado=None)
        com_entrada = self.avaliar(dict(status_day=status(primeiro_checkin='08:00:00'), jornada=jornada(),
                                        registros_origem=[registro],
                                        justificativas_abonaveis=ABONAVEIS), item)
        self.assertEqual(CONFIRMADO, com_entrada['resultado'])
        self.assertEqual('relatorio_checkin_bracell', com_entrada['fonte'])
        sem_entrada = self.avaliar(dict(status_day=status(primeiro_checkin=None), jornada=jornada(),
                                        justificativas_abonaveis=ABONAVEIS), item)
        self.assertEqual(NAO_APLICAVEL, sem_entrada['resultado'])
        self.assertIn('Sem entrada registrada', sem_entrada['motivo'])

    # ------------------------------------------------- jornada sempre tem origem
    def test_jornada_sempre_declara_a_origem_na_prioridade_acordada(self):
        self.assertEqual(JORNADA_INVOLVES, origem_da_jornada(jornada()))
        self.assertEqual(JORNADA_RAW, origem_da_jornada(
            jornada(fonte='raw_exclusivo_bracell_colaboradores_ativos')))
        self.assertEqual(JORNADA_FALLBACK, origem_da_jornada(jornada(jornada_origem='FALLBACK')))
        # Sem jornada resolvida a origem é explicitamente indisponível, nunca "Involves".
        self.assertEqual('INDISPONIVEL', origem_da_jornada(jornada(jornada_semanal=None, fonte=None)))
        self.assertEqual('INDISPONIVEL', origem_da_jornada({}))

    def test_jornada_nao_resolvida_torna_a_evidencia_indisponivel(self):
        prova = self.avaliar(dict(status_day=status(), jornada=jornada(jornada_semanal=None, fonte=None),
                                  justificativas_abonaveis=ABONAVEIS))
        self.assertEqual(INDISPONIVEL, prova['resultado'])
        self.assertIn('jornada', prova['motivo'].lower())
        self.assertEqual('INDISPONIVEL', prova['jornada_origem'])

    def test_toda_evidencia_confirmada_declara_a_origem_da_jornada(self):
        for origem, ajuste in ((JORNADA_INVOLVES, {}),
                               (JORNADA_RAW, dict(fonte='raw_exclusivo_bracell_colaboradores_ativos')),
                               (JORNADA_FALLBACK, dict(jornada_origem='FALLBACK'))):
            prova = self.avaliar(dict(status_day=status(), jornada=jornada(**ajuste),
                                      justificativas_abonaveis=ABONAVEIS))
            self.assertEqual(CONFIRMADO, prova['resultado'])
            self.assertEqual(origem, prova['jornada_origem'])

    # ------------------------------------------------- multimarca
    def test_a_mesma_inteligencia_atende_outra_marca_sem_codigo_novo(self):
        fontes = [dict(linha, marca='FLORA', tabela=linha['tabela'].replace('bracell', 'flora'))
                  for linha in FONTES]
        regras_flora = [dict(linha, marca='FLORA') for linha in REGRAS]
        matriz_flora = matriz_de_linhas(fontes)[('FLORA', 'EXCLUSIVA')]
        prova = avaliar(achado(), dict(status_day=status(), jornada=jornada(),
                                       justificativas_abonaveis=ABONAVEIS),
                        matriz_flora, regras_de_linhas(regras_flora))
        self.assertEqual(CONFIRMADO, prova['resultado'])
        self.assertEqual('status_day_operacao_flora', prova['fonte'])
        # Nenhuma marca alcança a matriz da outra.
        self.assertIsNone(matriz_de_linhas(fontes).get(('BRACELL', 'EXCLUSIVA')))

    def test_configuracao_incompleta_nunca_inventa_tabela(self):
        parcial = matriz_de_linhas([dict(marca='TANGARA', operacao='EXCLUSIVA', papel='status_day',
                                         tabela='', campos={})])
        self.assertEqual({}, parcial)


class EndpointDeEvidenciaTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        self.db.insert('execucao', execution_id='e1', marca='BRACELL', status_execucao='CONCLUIDA',
                       periodo_inicio=SEGUNDA, periodo_fim=SABADO)
        self.db.insert('regra_tratativa', regra_id='r1', marca='BRACELL',
                       tipo_problema='CHECKIN_ENTRADA_AUSENTE', classificacao='OPORTUNIDADE',
                       status_regra='ATIVA', prioridade=10, titulo_exibicao='Entrada não registrada',
                       impacto_negocio='Jornada', acao_recomendada='Validar o registro no Involves',
                       severidade_padrao='ALTA', responsavel_padrao='Líder da operação')
        self.db.ativar_regra('CHECKIN_ENTRADA_AUSENTE')   # a fila so mostra regra ativa
        for linha in FONTES:
            self.db.insert('configuracao_evidencia', **linha)
        for linha in REGRAS:
            self.db.insert('configuracao_evidencia_regra', **linha)
        self.client = TestClient(create_app(Settings(token='x' * 40), self.db))
        self.client.__enter__()
        self.client.headers['Authorization'] = 'Bearer ' + 'x' * 40
        self.clock = patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 9))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.client.__exit__(None, None, None)

    def oportunidade(self, identificador, evidencia):
        self.db.insert('oportunidade', oportunidade_id=identificador, execution_id='e1', marca='BRACELL',
                       regra_id='r1', tipo_problema='CHECKIN_ENTRADA_AUSENTE', status_oportunidade='ABERTA',
                       colaborador='ANA', colaborador_id_interno=None, data_referencia=SEGUNDA,
                       tabela_origem='status_day_operacao_bracell', origem='INVOLVES_BRACELL',
                       severidade='ALTA', fingerprint=identificador, evidencia=evidencia)

    def get(self, path, **params):
        resposta = self.client.get('/api/v2/' + path, params=params)
        self.assertEqual(200, resposta.status_code, resposta.text)
        return resposta.json()

    def grupo(self):
        pagina = self.get('oportunidades/resumo', marca='BRACELL')
        self.assertTrue(pagina['items'], 'fixture nao produziu card operacional')
        return pagina['items'][0]

    def comprovacao(self, **extras):
        base = dict(regra='CHECKIN_ENTRADA_AUSENTE', colaborador='ANA', data='2026-08-31',
                    fonte='status_day_operacao_bracell', campo='primeiro_checkin',
                    esperado='Entrada registrada no dia trabalhado', encontrado=None,
                    jornada_origem=JORNADA_INVOLVES, justificativa=False, atestado=False,
                    ausencia_registrada=None, resultado=CONFIRMADO, motivo=None,
                    verificacoes=[dict(criterio='dia_trabalhado', atendido=True,
                                       descricao='Dia com roteiro previsto na operação.',
                                       fonte='status_day_operacao_bracell', campo='tem_roteiro',
                                       valor='Sim')])
        base.update(extras)
        return base

    # ------------------------------------------------- card carrega a prova
    def test_card_operacional_traz_origem_campo_e_status_de_validacao(self):
        self.oportunidade('o1', {'campo_esperado': 'primeiro_checkin', 'valor_encontrado': '(ausente)',
                                 'comprovacao': self.comprovacao()})
        card = self.grupo()
        self.assertEqual('status_day_operacao_bracell', card['origem'])
        self.assertEqual('primeiro_checkin', card['campo'])
        self.assertEqual('primeiro_checkin', card['evidencia']['campo'])
        self.assertEqual('status_day_operacao_bracell', card['evidencia']['fonte'])
        self.assertEqual('Entrada registrada no dia trabalhado', card['evidencia']['valor_esperado'])
        self.assertEqual(CONFIRMADO, card['validacao']['resultado'])
        self.assertEqual('Confirmado na fonte oficial', card['validacao']['rotulo'])
        self.assertEqual(JORNADA_INVOLVES, card['validacao']['jornada_origem'])

    def test_achado_antigo_sem_comprovacao_e_declarado_indisponivel(self):
        self.oportunidade('o1', {'campo_esperado': 'primeiro_checkin', 'valor_encontrado': '(ausente)'})
        card = self.grupo()
        self.assertEqual(INDISPONIVEL, card['validacao']['resultado'])
        self.assertEqual('Evidência indisponível', card['validacao']['rotulo'])
        self.assertIn('antes da camada de comprovação', card['validacao']['motivo'])
        self.assertEqual('INDISPONIVEL', card['validacao']['jornada_origem'])

    # ------------------------------------------------- endpoint de evidências
    def test_endpoint_devolve_fonte_regra_criterios_e_tratativa(self):
        self.oportunidade('o1', {'campo_esperado': 'primeiro_checkin', 'valor_encontrado': '(ausente)',
                                 'comprovacao': self.comprovacao()})
        card = self.grupo()
        corpo = self.get(f"oportunidades/{card['grupo_id']}/evidencias", marca='BRACELL')

        self.assertEqual('CHECKIN_ENTRADA_AUSENTE', corpo['oportunidade']['regra'])
        self.assertEqual('Entrada não registrada', corpo['oportunidade']['titulo'])
        self.assertEqual('Jornada', corpo['oportunidade']['impacto'])
        self.assertEqual('ANA', corpo['oportunidade']['colaborador'])

        self.assertEqual(CONFIRMADO, corpo['validacao']['resultado'])
        self.assertEqual(JORNADA_INVOLVES, corpo['validacao']['jornada_origem'])
        self.assertFalse(corpo['validacao']['justificativa'])
        self.assertFalse(corpo['validacao']['atestado'])
        self.assertEqual(1, corpo['validacao']['ocorrencias_comprovadas'])

        self.assertEqual('status_day', corpo['fonte']['papel'])
        self.assertEqual('status_day_operacao_bracell', corpo['fonte']['tabela'])
        self.assertEqual('primeiro_checkin', corpo['fonte']['campo'])
        self.assertEqual(['colaborador_vigente', 'dia_trabalhado', 'jornada_resolvida', 'sem_abono'],
                         corpo['fonte']['criterios'])

        self.assertEqual([dict(fonte='status_day_operacao_bracell', campo='tem_roteiro',
                               valor_encontrado='Sim', valor_esperado='Dia com roteiro previsto na operação.',
                               validacao='dia_trabalhado', atendido=True)], corpo['evidencias'])
        self.assertEqual({'acao_recomendada': 'Validar o registro no Involves',
                          'responsavel': 'Líder da operação'}, corpo['tratamento'])
        ocorrencia = corpo['ocorrencias'][0]
        self.assertEqual('2026-08-31', ocorrencia['data'])
        self.assertEqual(CONFIRMADO, ocorrencia['resultado_validacao'])
        self.assertEqual('Validar o registro no Involves', ocorrencia['tratativa'])
        self.assertTrue({'regra', 'colaborador', 'data', 'resultado_validacao', 'fonte', 'campo',
                         'valor_esperado', 'valor_encontrado', 'motivo', 'impacto', 'tratativa'} <= ocorrencia.keys())

    def test_endpoint_sem_comprovacao_lista_os_criterios_que_faltaram(self):
        self.oportunidade('o1', {'campo_esperado': 'primeiro_checkin'})
        card = self.grupo()
        corpo = self.get(f"oportunidades/{card['grupo_id']}/evidencias", marca='BRACELL')
        self.assertEqual(INDISPONIVEL, corpo['validacao']['resultado'])
        self.assertEqual(0, corpo['validacao']['ocorrencias_comprovadas'])
        self.assertEqual(1, corpo['validacao']['ocorrencias_avaliadas'])
        # A regra continua visível: o líder vê o que seria necessário comprovar.
        self.assertEqual(['colaborador_vigente', 'dia_trabalhado', 'jornada_resolvida', 'sem_abono'],
                         [linha['validacao'] for linha in corpo['evidencias']])
        self.assertTrue(all(linha['atendido'] is None for linha in corpo['evidencias']))

    def test_evidencia_nunca_expoe_uuid_fingerprint_nem_execution_id(self):
        self.oportunidade('11111111-1111-1111-1111-111111111111',
                          {'campo_esperado': 'primeiro_checkin', 'comprovacao': self.comprovacao()})
        card = self.grupo()
        resposta = self.client.get(f"/api/v2/oportunidades/{card['grupo_id']}/evidencias",
                                   params={'marca': 'BRACELL'})
        corpo = resposta.text
        for proibido in ('11111111-1111-1111-1111-111111111111', 'fingerprint',
                         'execution_id', 'oportunidade_id', 'e1"'):
            self.assertNotIn(proibido, corpo)

    def test_grupo_de_outra_marca_nao_e_acessivel(self):
        self.oportunidade('o1', {'campo_esperado': 'primeiro_checkin', 'comprovacao': self.comprovacao()})
        card = self.grupo()
        resposta = self.client.get(f"/api/v2/oportunidades/{card['grupo_id']}/evidencias",
                                   params={'marca': 'FLORA'})
        self.assertEqual(404, resposta.status_code)

    # ------------------------------------------------- matriz publicada
    def test_matriz_de_origem_e_consultavel_e_nao_tem_tabela_por_marca(self):
        corpo = self.get('configuracoes/evidencias', marca='BRACELL')
        marca = corpo['marcas'][0]
        self.assertEqual('BRACELL', marca['marca'])
        self.assertEqual(['checkin', 'colaborador', 'status_day'],
                         sorted(fonte['papel'] for fonte in marca['fontes']))
        self.assertEqual(['CHECKIN_ENTRADA_AUSENTE', 'CHECKOUT_AUSENTE'],
                         [regra['tipo_problema'] for regra in marca['regras']])
        # Papel semântico é estável entre marcas; só o nome físico muda.
        status_day = next(f for f in marca['fontes'] if f['papel'] == 'status_day')
        self.assertEqual('status_day_operacao_bracell', status_day['tabela'])
        self.assertEqual('afastado', status_day['campos']['afastamento'])


if __name__ == '__main__':
    unittest.main()
