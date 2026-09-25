from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import Table, Column, String, Float, Boolean, DateTime, text
from api.tests.test_api import FixtureDatabase
from api.tests.test_rule_admin import cadastrar_horas_ausentes, FixtureRuleWriter, TOKEN, CORPO
from api.app.config import Settings
from api.app.main import create_app
from shared.operational_schedule import TABLE, checkout_due


def add_tables(db):
    db.tables[TABLE] = Table(TABLE, db.metadata,
        Column('id', String, primary_key=True), Column('configuracao_id', String), Column('marca', String),
        Column('operacao', String), Column('jornada', Float), Column('hora_entrada_padrao', String),
        Column('hora_saida_padrao', String), Column('ativo', Boolean), Column('usuario_alteracao', String),
        Column('nome_jornada', String), Column('intervalo', String),
        Column('origem_configuracao', String, server_default='CADASTRO_OPERACIONAL'),
        Column('criada_em', DateTime, server_default=text('CURRENT_TIMESTAMP')),
        Column('atualizada_em', DateTime, server_default=text('CURRENT_TIMESTAMP')))
    db.tables['jornada_consolidada'] = Table('jornada_consolidada', db.metadata,
        Column('resolucao_id', String, primary_key=True), Column('marca', String), Column('operacao', String),
        Column('colaborador_chave', String), Column('jornada_semanal', Float), Column('elegivel', Boolean),
        Column('vigente', Boolean), Column('status_resolucao', String), Column('registrado_em', DateTime))
    db.metadata.create_all(db.engine)
    with db.engine.begin() as c:
        for hour in (44, 36, 24):
            c.execute(db.tables['jornada_consolidada'].insert().values(resolucao_id=str(hour),
                marca='BRACELL', operacao='EXCLUSIVA', colaborador_chave=str(hour), jornada_semanal=hour,
                elegivel=True, vigente=True, status_resolucao='RESOLVIDA', registrado_em=datetime(2026, 9, 22)))


class ScheduleApiTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        self.addCleanup(self.db.close)
        add_tables(self.db)
        cadastrar_horas_ausentes(self.db)
        self.client = TestClient(create_app(Settings(token=TOKEN), self.db, FixtureRuleWriter(self.db)))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.headers['Authorization'] = 'Bearer ' + TOKEN
        self.url = '/api/v2/configuracoes/regras?marca=BRACELL&operacao=EXCLUSIVA'

    def body(self, hours=44):
        return dict(**CORPO, nome_regra='Check-out ausente', descricao='Ausência após a jornada',
                    tipo_oportunidade='CHECKOUT_AUSENTE', papel_fonte='checkout', campo_logico='hora_saida',
                    operador='IS NULL', status='ATIVA', jornadas=[dict(jornada=hours,
                    ativo=True, hora_entrada_padrao='08:00', hora_saida_padrao='19:00')])

    def test_create_read_update_atomic_and_isolated(self):
        response = self.client.post(self.url, json=self.body())
        self.assertEqual(200, response.status_code, response.text)
        rule = response.json()['regra']
        self.assertEqual('JORNADA', rule['modelo_configuracao'])
        self.assertEqual([44, 36, 24], [s['jornada'] for s in rule['jornadas']])
        self.assertEqual('19:00', rule['jornadas'][0]['hora_saida_padrao'])
        self.assertIsNone(rule['monitoramento']['ultima_atualizacao'])
        url = '/api/v2/configuracoes/regras/CHECKOUT_AUSENTE?marca=BRACELL&operacao=EXCLUSIVA'
        config = self.body()['jornadas'][0]
        changed = {**config, 'hora_saida_padrao': '18:00'}
        response = self.client.patch(url, json={**CORPO, 'jornadas': [changed]})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual('18:00', response.json()['regra']['jornadas'][0]['hora_saida_padrao'])
        rejected = self.client.patch(url, json={**CORPO, 'nome_regra': 'Não deve salvar', 'jornadas': [{**changed, 'jornada': 40}]})
        self.assertEqual(422, rejected.status_code)
        rejected = self.client.patch(url, json={**CORPO, 'condicoes': [{'ordem': 1, 'operador': 'MAIOR_QUE', 'valor': '19:00'}]})
        self.assertEqual(422, rejected.status_code)
        config = self.client.get('/api/v2/configuracoes/operacao?marca=BRACELL').json()
        current = next(r for r in config['regras_governanca'] if r['codigo_interno'] == 'CHECKOUT_AUSENTE')
        self.assertEqual('Check-out ausente', current['nome_regra'])
        self.assertTrue(any(h['entidade_tipo'] == 'JORNADA_OPERACAO' for h in config['historico_governanca']))
        self.assertEqual(409, self.client.post(self.url, json=self.body()).status_code)

    def test_invalid_hours_and_duplicate_journeys(self):
        for update in ({'hora_saida_padrao': '25:00'}, {'hora_saida_padrao': None}, {'hora_saida_padrao': '08:00'}, {'jornada': 40}):
            body = self.body()
            body['jornadas'][0].update(update)
            self.assertEqual(422, self.client.post(self.url, json=body).status_code)
        body = self.body()
        body['jornadas'] *= 2
        self.assertEqual(422, self.client.post(self.url, json=body).status_code)

    def test_manual_persistence_edit_and_scope(self):
        body = self.body(40)
        body['jornadas'][0].update(nome_jornada='Equipe 40H', intervalo='01:00', origem_configuracao='MANUAL')
        response = self.client.post(self.url, json=body)
        self.assertEqual(200, response.status_code, response.text)
        schedules = response.json()['regra']['jornadas']
        manual = next(s for s in schedules if s['jornada'] == 40)
        self.assertFalse(manual['disponivel'])
        self.assertEqual('MANUAL', manual['origem_configuracao'])
        self.assertEqual('01:00', manual['intervalo'])
        self.assertEqual(3, len([s for s in schedules if s['origem_configuracao'] == 'CADASTRO_OPERACIONAL']))
        edit = {k: v for k, v in manual.items() if k != 'disponivel'}
        edit.update(jornada=42, nome_jornada='Equipe 42H', intervalo='00:30')
        url = '/api/v2/configuracoes/regras/CHECKOUT_AUSENTE?marca=BRACELL&operacao=EXCLUSIVA'
        response = self.client.patch(url, json={**CORPO, 'jornadas': [edit]})
        self.assertEqual(200, response.status_code, response.text)
        saved = next(s for s in response.json()['regra']['jornadas'] if s['id'] == manual['id'])
        self.assertEqual((42, 'Equipe 42H', '00:30'), (saved['jornada'], saved['nome_jornada'], saved['intervalo']))
        config = self.client.get('/api/v2/configuracoes/operacao?marca=BRACELL').json()
        self.assertEqual(saved, next(s for r in config['regras_governanca'] if r['codigo_interno'] == 'CHECKOUT_AUSENTE' for s in r['jornadas'] if s['id'] == manual['id']))
        for invalid in ({'id': 'outra-regra'}, {'origem_configuracao': 'CADASTRO_OPERACIONAL'}, {'nome_jornada': ' '}, {'intervalo': '25:00'}):
            response = self.client.patch(url, json={**CORPO, 'jornadas': [{**edit, **invalid}]})
            self.assertEqual(422, response.status_code, response.text)
        other_url = url.replace('CHECKOUT_AUSENTE', 'HORAS_AUSENTES')
        self.assertEqual(422, self.client.patch(other_url, json={**CORPO, 'jornadas': [edit]}).status_code)

    def test_operational_journey_saves_interval_and_is_reopened(self):
        # Cenario 1/2 do modal: jornada da operacao recebe horarios e intervalo; reabrir mantem.
        url = '/api/v2/configuracoes/regras/CHECKOUT_AUSENTE?marca=BRACELL&operacao=EXCLUSIVA'
        self.assertEqual(200, self.client.post(self.url, json=self.body()).status_code)
        edit = dict(jornada=36, nome_jornada='Jornada 36h', origem_configuracao='CADASTRO_OPERACIONAL', intervalo='01:00',
                    hora_entrada_padrao='08:00', hora_saida_padrao='16:00', ativo=False)
        response = self.client.patch(url, json={**CORPO, 'jornadas': [edit]})
        self.assertEqual(200, response.status_code, response.text)
        config = self.client.get('/api/v2/configuracoes/operacao?marca=BRACELL').json()
        rule = next(r for r in config['regras_governanca'] if r['codigo_interno'] == 'CHECKOUT_AUSENTE')
        saved = next(s for s in rule['jornadas'] if s['jornada'] == 36)
        self.assertEqual(('08:00', '16:00', '01:00', 'CADASTRO_OPERACIONAL', False), tuple(
            saved[k] for k in ('hora_entrada_padrao', 'hora_saida_padrao', 'intervalo', 'origem_configuracao', 'ativo')))

    def test_missing_journey_columns_refuse_instead_of_silently_dropping(self):
        # Base sem a migracao 019: gravar intervalo "com sucesso" e perde-lo seria so' alteracao visual.
        self.assertEqual(200, self.client.post(self.url, json=self.body()).status_code)
        tabela = self.db.tables[TABLE]
        self.db.tables[TABLE] = Table(TABLE + '_sem_019', self.db.metadata,
            *[Column(c.name, c.type, primary_key=c.primary_key) for c in tabela.c
              if c.name not in ('nome_jornada', 'intervalo', 'origem_configuracao')])
        self.db.metadata.create_all(self.db.engine)
        url = '/api/v2/configuracoes/regras/CHECKOUT_AUSENTE?marca=BRACELL&operacao=EXCLUSIVA'
        edit = dict(jornada=44, intervalo='01:00', hora_entrada_padrao='08:00', hora_saida_padrao='19:00', ativo=True)
        response = self.client.patch(url, json={**CORPO, 'jornadas': [edit]})
        self.assertEqual(503, response.status_code, response.text)
        self.assertIn('019', response.json()['detail'])

    def test_rule_exposes_engine_default_journey_for_missing_hours(self):
        self.assertEqual(200, self.client.post(self.url, json=self.body()).status_code)
        config = self.client.get('/api/v2/configuracoes/operacao?marca=BRACELL').json()
        rule = next(r for r in config['regras_governanca'] if r['codigo_interno'] == 'CHECKOUT_AUSENTE')
        self.assertEqual(dict(jornada=44.0, hora_entrada_padrao='08:00', hora_saida_padrao='19:00', origem='CODIGO'),
                         rule['jornada_padrao'])

    def test_manual_duplicate_is_atomic(self):
        body = self.body()
        self.assertEqual(200, self.client.post(self.url, json=body).status_code)
        manual = dict(jornada=40, nome_jornada='Manual', intervalo='01:00', origem_configuracao='MANUAL',
                      ativo=True, hora_entrada_padrao='08:00', hora_saida_padrao='19:00')
        url = '/api/v2/configuracoes/regras/CHECKOUT_AUSENTE?marca=BRACELL&operacao=EXCLUSIVA'
        self.assertEqual(200, self.client.patch(url, json={**CORPO, 'jornadas': [manual]}).status_code)
        config = self.client.get('/api/v2/configuracoes/operacao?marca=BRACELL').json()
        schedules = next(r['jornadas'] for r in config['regras_governanca'] if r['codigo_interno'] == 'CHECKOUT_AUSENTE')
        saved = next(s for s in schedules if s['jornada'] == 40)
        invalid = {**manual, 'id': saved['id'], 'jornada': 44}
        self.assertEqual(422, self.client.patch(url, json={**CORPO, 'jornadas': [invalid]}).status_code)


class CheckoutDecisionTest(unittest.TestCase):
    def setUp(self):
        self.schedule = dict(ativo=True, hora_entrada_padrao='08:00', hora_saida_padrao='19:00')
        self.row = dict(data='2026-09-01', hora_entrada='08:03:00', hora_saida=None, evolucao='2026-09-02 05:00:00')

    def test_config_required_and_real_value_preserved(self):
        original = dict(self.row)
        self.assertFalse(checkout_due(None, self.row))
        self.assertFalse(checkout_due({**self.schedule, 'ativo': False}, self.row))
        self.assertTrue(checkout_due(self.schedule, self.row))
        self.assertEqual(original, self.row)
        self.assertFalse(checkout_due(self.schedule, {**self.row, 'hora_saida': '18:45:00'}))

    def test_incomplete_and_early_monitoring_blocked(self):
        for changes in ({'hora_entrada': None}, {'evolucao': None}, {'evolucao': '2026-09-01 18:59:59'}, {'hora_entrada': 'invalida'}):
            self.assertFalse(checkout_due(self.schedule, {**self.row, **changes}))
        self.assertFalse(checkout_due(self.schedule, self.row, datetime(2026, 9, 1, 18)))

    def test_overnight(self):
        schedule = dict(ativo=True, hora_entrada_padrao='22:00', hora_saida_padrao='06:00')
        self.assertFalse(checkout_due(schedule, self.row))
        self.assertTrue(checkout_due(schedule, {**self.row, 'evolucao': '2026-09-02 06:01:00'}))

    def test_mysql_time_and_different_schedules(self):
        row = {**self.row, 'hora_entrada': timedelta(hours=8), 'evolucao': '2026-09-01 17:00:00'}
        self.assertFalse(checkout_due(self.schedule, row))
        self.assertTrue(checkout_due({**self.schedule, 'hora_saida_padrao': '16:00'}, row))
        self.assertTrue(checkout_due({**self.schedule, 'hora_saida_padrao': '12:00'}, row))

    def test_executor_uses_real_source_and_resolved_journey(self):
        from src.operational_schedule import execute
        from src.regras_configuradas import ProvedorDeExcecoes
        db = FixtureDatabase()
        self.addCleanup(db.close)
        add_tables(db)
        with db.engine.begin() as c:
            c.execute(db.tables[TABLE].insert().values(id='s', configuracao_id='r', marca='BRACELL', operacao='EXCLUSIVA', jornada=44, **self.schedule))
        mapping = {k: k for k in ('data', 'colaborador', 'hora_entrada', 'hora_saida', 'evolucao')}
        source = dict(fonte_id='f', schema_fisico='involves_bracell', tabela_fisica='status_day', mapeamento_campos=mapping)
        sources = {'checkout': [source]}
        rows = [{**self.row, 'colaborador': 'Pessoa'}]
        reader = lambda *args: rows
        resolver = lambda day: [dict(colaborador='Pessoa', status_resolucao='RESOLVIDA', jornada_semanal=44)]
        provider = ProvedorDeExcecoes(sources, reader, resolver, '2026-09-01', '2026-09-01')
        rule = dict(configuracao_id='r', codigo_interno='CHECKOUT_AUSENTE', nome_regra='Checkout', status='ATIVA', geracao_automatica_ativa=True,
                    excecoes=[], tratamentos=[dict(resultado='CONFIRMADO', status='ATIVO', gera_oportunidade=True)])
        with patch('src.findings.registrar_achado', return_value=1) as persist:
            result = execute(db.engine, rule, sources, provider, reader, '2026-09-01', '2026-09-01', marca='BRACELL', operacao='EXCLUSIVA', registrar=False, prefixo='')
        self.assertEqual(1, result['criadas'])
        proof = persist.call_args.args[1][0]['evidencia']['comprovacao']
        self.assertEqual('19:00', proof['configuracao_operacional']['hora_saida_padrao'])
        self.assertIsNone(proof['monitoramento']['hora_saida'])
        self.assertEqual('confirmado', proof['resultado'])


if __name__ == '__main__':
    unittest.main()
