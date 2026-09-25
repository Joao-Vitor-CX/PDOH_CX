from datetime import date
import unittest
from unittest.mock import patch

from api.tests import test_api


class AlertTest(unittest.TestCase):
    get = test_api.ApiTest.get
    tearDown = test_api.ApiTest.tearDown

    def setUp(self):
        test_api.ApiTest.setUp(self)
        self.db.insert('regra_tratativa', regra_id='alert', tipo_problema='CADASTRO', classificacao='ALERTA', titulo='Cadastro incompleto')
        self.db.insert('regra_tratativa', regra_id='tele', tipo_problema='TECNICO', classificacao='TELEMETRIA')
        self.db.insert('regra_tratativa', regra_id='oper', tipo_problema='OPERACIONAL', classificacao='OPORTUNIDADE')
        for i, field in enumerate(['estado', 'estado', 'estado', 'cidade']):
            self.db.insert('oportunidade', oportunidade_id=f'a{i}', execution_id='e1', marca='BRACELL', regra_id='alert', tipo_problema='CADASTRO', colaborador='Pessoa teste', colaborador_id_interno='same', data_referencia=date(2026, 9, i+1), evidencia={'campo':field}, status_oportunidade='ABERTA')
        self.db.insert('oportunidade', oportunidade_id='t1', execution_id='e1', regra_id='tele', tipo_problema='TECNICO', colaborador='Pessoa teste')
        self.db.insert('oportunidade', oportunidade_id='p1', execution_id='e1', regra_id='oper', tipo_problema='OPERACIONAL')

    def test_only_alerts_and_collaborator_field_consolidation(self):
        result = self.get('/alertas')
        self.assertEqual(1, result['total'])
        self.assertEqual(4, result['total_ocorrencias'])
        group = result['items'][0]
        self.assertEqual('ALERTA', group['classificacao'])
        self.assertEqual({'estado':3, 'cidade':1}, {field['campo']:field['quantidade_ocorrencias'] for field in group['campos']})
        self.assertEqual(4, group['quantidade_ocorrencias'])
        records = self.get('/alertas/' + group['chave_grupo'] + '/registros', tamanho=2)
        self.assertEqual(4, records['total'])
        self.assertEqual(2, len(records['items']))
        self.assertTrue(all(record['classificacao'] == 'ALERTA' for record in records['items']))
        self.assertEqual(422, self.client.get('/api/v1/alertas?classificacao=TELEMETRIA').status_code)

    def test_classification_filter_is_catalog_not_action_or_type_guess(self):
        result = self.get('/oportunidades', classificacao='ALERTA')
        self.assertEqual(4, result['total'])
        self.assertEqual(1, self.get('/oportunidades', classificacao='TELEMETRIA')['total'])
        self.assertIsNone(self.get('/oportunidades/o2')['classificacao'])

    def test_field_filter_and_no_merge_across_brands_or_identities(self):
        self.db.insert('oportunidade', oportunidade_id='other', execution_id='e2', marca='OUTRA', regra_id='alert', tipo_problema='CADASTRO', colaborador='Pessoa teste', colaborador_id_interno='same', evidencia={'campo':'estado'})
        self.db.insert('oportunidade', oportunidade_id='homonym', execution_id='e1', marca='BRACELL', regra_id='alert', tipo_problema='CADASTRO', colaborador='Pessoa teste', colaborador_id_interno='different', evidencia={'campo':'estado'})
        result = self.get('/alertas', campo='estado')
        self.assertEqual(3, result['total'])
        self.assertEqual(5, result['total_ocorrencias'])
        self.assertEqual(4, self.get('/alertas', campo='estado', marca='BRACELL')['total_ocorrencias'])

    def test_null_identity_never_merges_all_unknown_people(self):
        for i in range(2):
            self.db.insert('oportunidade', oportunidade_id=f'n{i}', execution_id='e1', marca='BRACELL', regra_id='alert', tipo_problema='CADASTRO', evidencia={'campo_esperado':['responsavel','status','status']})
        result = self.get('/alertas', campo='responsavel')
        self.assertEqual(2, result['total'])
        self.assertTrue(all(row['criterio_agrupamento']=='REGISTRO_SEM_IDENTIDADE' for row in result['items']))
        self.assertEqual(0, self.get('/alertas', campo='inexistente')['total'])

    def test_stable_pages_limit_no_silent_truncation_and_read_only(self):
        before = self.get('/oportunidades')['total']
        first = self.get('/alertas', tamanho=1)
        self.assertEqual(first, self.get('/alertas', tamanho=1))
        self.assertEqual([], self.get('/alertas', pagina=100)['items'])
        with patch('api.app.alerts.MAX_ALERT_RECORDS', 2):
            self.assertEqual(422, self.client.get('/api/v1/alertas').status_code)
        self.assertEqual(before, self.get('/oportunidades')['total'])
        for method in ('post','put','patch','delete'):
            self.assertEqual(405, getattr(self.client, method)('/api/v1/alertas').status_code)
