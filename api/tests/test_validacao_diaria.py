"""Validacao diaria do PDOH: status de cada dia exposto pela API, sem tocar no calculo.

Regra (aprovada em 25/09/2026), na ordem:
1. justificativa do dia na Platina  -> DESCONSIDERADO (fora da analise, sem fallback);
2. sem visitas programadas e sem check-in -> SEM_ATIVIDADE_PREVISTA (fora da analise);
3. check-in sem checkout real (vazio ou o 23:59 do processador) -> CHECKOUT_ESQUECIDO
   (fallback aplicado: saida considerada pela jornada);
4. demais -> VALIDO.
"""
from datetime import date, datetime, timedelta
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table

from api.app.config import Settings
from api.app.main import create_app
from api.tests.test_api import FixtureDatabase

SEGUNDA, SABADO = date(2026, 8, 31), date(2026, 9, 5)
DIAS = ('seg', 'ter', 'qua', 'qui', 'sex', 'sab')


class ValidacaoDiariaTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        self.client = TestClient(create_app(Settings(token='x' * 40), self.db))
        self.client.__enter__()
        self.client.headers['Authorization'] = 'Bearer ' + 'x' * 40
        self.clock = patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 9))
        self.clock.start()
        self.tabela = Table('platina_bracell', MetaData(),
                            Column('colaborador', String), Column('estado', String), Column('data', Date),
                            Column('nome_do_dia', String), Column('produtividade', String),
                            Column('ocio', String), Column('deslocamento', String),
                            Column('horas_nao_registradas', String), Column('horas_programadas', String),
                            Column('primeiro_checkin', String), Column('ultimo_checkout', String),
                            Column('visitas_diarias', Integer), Column('visitas_diarias_realizadas', Integer),
                            Column('pesquisas_diarias', Integer), Column('pesquisas_diarias_realizadas', Integer),
                            Column('percentual_produtividade', Numeric), Column('percentual_visitas', Numeric),
                            Column('percentual_pesquisas', Numeric), Column('percentual_efetividade', Numeric),
                            *[Column(f'justificativas_{dia}', String) for dia in DIAS])
        self.tabela.create(self.db.engine)
        self.db.tables['platina_pdoh:BRACELL'] = self.tabela

    def tearDown(self):
        self.clock.stop()
        self.client.__exit__(None, None, None)

    def linha(self, colaborador, dia, checkin='08:00:00', checkout='17:00:00', visitas=2, **justificativas):
        with self.db.engine.begin() as conexao:
            conexao.execute(self.tabela.insert(), dict(
                colaborador=colaborador, estado='SP', data=dia, nome_do_dia='DIA',
                produtividade='03:00:00', ocio='00:00:00', deslocamento='00:00:00',
                horas_nao_registradas='00:00:00', horas_programadas='04:00:00',
                primeiro_checkin=checkin, ultimo_checkout=checkout,
                visitas_diarias=visitas, visitas_diarias_realizadas=visitas,
                pesquisas_diarias=0, pesquisas_diarias_realizadas=0,
                percentual_produtividade=0.75, percentual_visitas=1, percentual_pesquisas=0,
                percentual_efetividade=0,
                **{f'justificativas_{dia_semana}': texto for dia_semana, texto in justificativas.items()}))

    def resolucoes(self, *linhas):
        tabela = Table('jornada_consolidada', MetaData(),
                       Column('resolucao_id', String, primary_key=True), Column('marca', String),
                       Column('colaborador', String), Column('data_referencia', Date), Column('fonte', String),
                       Column('campo', String), Column('status_resolucao', String), Column('jornada_semanal', Numeric),
                       Column('elegivel', Integer), Column('vigente', Integer), Column('evidencia', JSON),
                       Column('registrado_em', DateTime))
        tabela.create(self.db.engine)
        self.db.tables['jornada_consolidada'] = tabela
        with self.db.engine.begin() as conexao:
            for i, linha in enumerate(linhas):
                conexao.execute(tabela.insert(), dict(dict(
                    resolucao_id=str(i), marca='BRACELL', fonte='colaboradores_ativos_bracell', campo='nome_pai',
                    jornada_semanal=None, elegivel=1, vigente=1, evidencia={},
                    registrado_em=datetime(2026, 9, 1, 8)), **linha))

    def jornadas(self, *linhas):
        tabela = Table('configuracao_jornada_operacao', MetaData(),
                       Column('id', String, primary_key=True), Column('configuracao_id', String),
                       Column('marca', String), Column('operacao', String), Column('jornada', Numeric),
                       Column('hora_entrada_padrao', String), Column('hora_saida_padrao', String),
                       Column('ativo', Boolean), Column('atualizada_em', DateTime))
        tabela.create(self.db.engine)
        self.db.tables['configuracao_jornada_operacao'] = tabela
        # Jornadas de outra regra nao definem a saida do checkout.
        self.db.ativar_regra('CHECKOUT_AUSENTE')
        self.db.ativar_regra('OUTRA_REGRA')
        with self.db.engine.begin() as conexao:
            conexao.execute(tabela.insert(), dict(
                id='outra', configuracao_id='cfg:BRACELL:EXCLUSIVA:OUTRA_REGRA', marca='BRACELL',
                operacao='EXCLUSIVA', jornada=36, hora_entrada_padrao='05:00', hora_saida_padrao='06:00',
                ativo=True, atualizada_em=datetime(2026, 9, 1)))
            for i, linha in enumerate(linhas):
                conexao.execute(tabela.insert(), dict(dict(
                    id=str(i), configuracao_id='cfg:BRACELL:EXCLUSIVA:CHECKOUT_AUSENTE', marca='BRACELL', operacao='EXCLUSIVA',
                    ativo=True, atualizada_em=datetime(2026, 9, 1)), **linha))

    def resumo(self, **params):
        resposta = self.client.get('/api/v2/pdoh/resumo', params=dict(
            dict(marca='BRACELL', periodo='personalizado', periodo_inicio=SEGUNDA, periodo_fim=SABADO), **params))
        self.assertEqual(200, resposta.status_code, resposta.text)
        return resposta.json()

    def por_colaborador(self, **params):
        return {i['colaborador']: i for i in self.resumo(**params)['detalhes']['items']}

    # ------------------------------------------------------------------ status por dia
    def test_justificativa_do_dia_desconsidera_sem_fallback(self):
        # Segunda-feira: vale a coluna justificativas_seg, mesmo sem checkout.
        self.linha('ANA', SEGUNDA, checkout=None, seg='CX - ATESTADO MÉDICO 3 DIAS')
        linha = self.por_colaborador()['ANA']
        self.assertEqual('CX - ATESTADO MÉDICO 3 DIAS', linha['justificativa'])
        self.assertEqual(('DESCONSIDERADO', False, False), tuple(
            linha['validacao'][k] for k in ('status', 'considerado', 'fallback_aplicado')))
        self.assertIsNone(linha['validacao']['saida_considerada'])
        self.assertIn('ATESTADO', linha['validacao']['motivo'])

    def test_justificativa_de_outro_dia_da_semana_nao_vale_para_a_linha(self):
        self.linha('ANA', SEGUNDA, ter='FERIADO')
        linha = self.por_colaborador()['ANA']
        self.assertIsNone(linha['justificativa'])
        self.assertEqual('VALIDO', linha['validacao']['status'])

    def test_sem_visitas_programadas_e_sem_checkin_e_sem_atividade_prevista(self):
        self.linha('ANA', SEGUNDA, checkin=None, checkout=None, visitas=0)
        validacao = self.por_colaborador()['ANA']['validacao']
        self.assertEqual(('SEM_ATIVIDADE_PREVISTA', False, False), tuple(
            validacao[k] for k in ('status', 'considerado', 'fallback_aplicado')))

    def test_ausencia_sem_justificativa_continua_valida_na_analise(self):
        self.linha('ANA', SEGUNDA, checkin=None, checkout=None, visitas=3)
        validacao = self.por_colaborador()['ANA']['validacao']
        self.assertEqual(('VALIDO', True, False), tuple(
            validacao[k] for k in ('status', 'considerado', 'fallback_aplicado')))
        self.assertIn('sem justificativa', validacao['motivo'])

    def test_entrada_e_saida_registradas_e_valido_sem_fallback(self):
        self.linha('ANA', SEGUNDA)
        validacao = self.por_colaborador()['ANA']['validacao']
        self.assertEqual(('VALIDO', True, False), tuple(
            validacao[k] for k in ('status', 'considerado', 'fallback_aplicado')))

    def test_checkin_sem_checkout_aplica_fallback_pela_jornada_configurada(self):
        self.linha('ANA', SEGUNDA, checkout=None)
        self.resolucoes(dict(colaborador='ANA', data_referencia=SEGUNDA, status_resolucao='RESOLVIDA',
                             jornada_semanal=36))
        self.jornadas(dict(jornada=44, hora_entrada_padrao='08:00', hora_saida_padrao='19:00'),
                      dict(jornada=36, hora_entrada_padrao='08:00', hora_saida_padrao='16:00'))
        validacao = self.por_colaborador()['ANA']['validacao']
        self.assertEqual(('CHECKOUT_ESQUECIDO', True, True, '16:00', 'CONFIGURACAO'), tuple(
            validacao[k] for k in ('status', 'considerado', 'fallback_aplicado', 'saida_considerada', 'origem_saida')))
        self.assertIn('08:00', validacao['motivo'])
        self.assertIn('36H', validacao['motivo'])

    def test_checkout_23_59_do_processador_nao_e_checkout_real(self):
        self.linha('ANA', SEGUNDA, checkout='23:59:00')
        self.assertEqual('CHECKOUT_ESQUECIDO', self.por_colaborador()['ANA']['validacao']['status'])

    def test_jornada_nao_encontrada_usa_a_saida_da_jornada_padrao(self):
        self.linha('ANA', SEGUNDA, checkout=None)
        self.resolucoes(dict(colaborador='ANA', data_referencia=SEGUNDA, status_resolucao='NAO_ENCONTRADA'))
        self.jornadas(dict(jornada=44, hora_entrada_padrao='07:00', hora_saida_padrao='18:00'))
        validacao = self.por_colaborador()['ANA']['validacao']
        # Mesma definicao do motor: jornada padrao em codigo (08:00-19:00), nao a configurada.
        self.assertEqual(('CHECKOUT_ESQUECIDO', '19:00', 'JORNADA_PADRAO'), tuple(
            validacao[k] for k in ('status', 'saida_considerada', 'origem_saida')))

    def test_jornada_sem_horario_configurado_nao_inventa_saida(self):
        self.linha('ANA', SEGUNDA, checkout=None)
        self.resolucoes(dict(colaborador='ANA', data_referencia=SEGUNDA, status_resolucao='RESOLVIDA',
                             jornada_semanal=24))
        validacao = self.por_colaborador()['ANA']['validacao']
        # Sem saida configurada o motor nao gera oportunidade: fallback nao foi aplicado.
        self.assertEqual(('CHECKOUT_ESQUECIDO', False, None, None), tuple(
            validacao[k] for k in ('status', 'fallback_aplicado', 'saida_considerada', 'origem_saida')))
        self.assertIn('sem horário', validacao['motivo'])

    def test_justificativa_prevalece_sobre_checkout_esquecido(self):
        self.linha('ANA', SEGUNDA, checkout=None, seg='FERIADO')
        validacao = self.por_colaborador()['ANA']['validacao']
        self.assertEqual(('DESCONSIDERADO', False), (validacao['status'], validacao['fallback_aplicado']))

    def test_platina_sem_colunas_de_justificativa_nao_quebra(self):
        tabela = Table('platina_antiga', MetaData(), *[Column(c.name, c.type) for c in self.tabela.c
                                                       if not c.name.startswith('justificativas_')])
        tabela.create(self.db.engine)
        self.db.tables['platina_pdoh:BRACELL'] = self.tabela = tabela
        self.linha('ANA', SEGUNDA)
        linha = self.por_colaborador()['ANA']
        self.assertIsNone(linha['justificativa'])
        self.assertEqual('VALIDO', linha['validacao']['status'])

    # ------------------------------------------------------------------ oportunidade gerada no dia
    def oportunidade(self, identificador, colaborador, dia, tipo='CHECKOUT_AUSENTE', status='ABERTA'):
        self.db.insert('oportunidade', oportunidade_id=identificador, execution_id='exec', marca='BRACELL',
                       colaborador=colaborador, data_referencia=dia, tipo_problema=tipo,
                       status_oportunidade=status, fingerprint=identificador)

    def test_dia_informa_se_gerou_oportunidade_de_checkout(self):
        self.linha('ANA', SEGUNDA, checkout=None)
        self.linha('BIA', SEGUNDA)
        self.linha('CAIO', SEGUNDA, checkout=None)
        self.linha('DITO', SEGUNDA)
        self.oportunidade('op-ana', ' ana ', SEGUNDA)
        # Horas ausentes nao e oportunidade (decisao de 25/09/2026); encerrada nao conta.
        self.oportunidade('op-bia', 'BIA', SEGUNDA, tipo='HORAS_AUSENTES')
        self.oportunidade('op-caio', 'CAIO', SEGUNDA, status='ENCERRADA')
        self.oportunidade('op-dito', 'DITO', SEGUNDA + timedelta(days=1))
        itens = self.por_colaborador()
        self.assertEqual({'ANA': True, 'BIA': False, 'CAIO': False, 'DITO': False},
                         {nome: itens[nome]['validacao']['gerou_oportunidade'] for nome in itens})
        self.assertEqual(1, self.resumo()['validacao']['oportunidades'])

    # ------------------------------------------------------------------ consolidado do periodo
    def test_consolidado_cobre_o_periodo_inteiro_e_nao_so_a_pagina(self):
        self.linha('ANA', SEGUNDA)
        self.linha('ANA', SEGUNDA + timedelta(days=1), checkout=None)
        self.linha('ANA', SEGUNDA + timedelta(days=2), qua='FERIADO')
        self.linha('BIA', SEGUNDA + timedelta(days=2), qua='FERIADO')
        self.linha('BIA', SEGUNDA + timedelta(days=3), checkin=None, checkout=None, visitas=0)
        self.linha('CAIO', SEGUNDA, checkout=None)
        self.resolucoes(dict(colaborador='CAIO', data_referencia=SEGUNDA, status_resolucao='NAO_ENCONTRADA'))
        resumo = self.resumo(pagina=1, tamanho=1)
        self.assertEqual(1, len(resumo['detalhes']['items']))
        # ANA terca: checkout esquecido sem jornada conhecida -> sem fallback; CAIO: jornada padrao.
        self.assertEqual(dict(dias=6, considerados=3, validos=1, checkout_esquecido=2, fallback_aplicado=1,
                              desconsiderados=2, sem_atividade_prevista=1, colaboradores=3, oportunidades=0,
                              justificativas={'FERIADO': 2}),
                         resumo['validacao'])

    def test_consolidado_respeita_o_filtro_de_colaborador(self):
        self.linha('ANA', SEGUNDA)
        self.linha('BIA', SEGUNDA, checkout=None)
        self.assertEqual((1, 0), tuple(self.resumo(colaborador='ANA')['validacao'][k]
                                       for k in ('dias', 'checkout_esquecido')))

    def test_validacao_nao_altera_o_pdoh(self):
        self.linha('ANA', SEGUNDA, seg='FERIADO')
        self.linha('ANA', SEGUNDA + timedelta(days=1), checkout=None)
        # 3h de 4h por dia nos dois dias: o dia justificado continua no calculo oficial.
        self.assertEqual(75.0, self.resumo()['percentual'])


if __name__ == '__main__':
    unittest.main()
