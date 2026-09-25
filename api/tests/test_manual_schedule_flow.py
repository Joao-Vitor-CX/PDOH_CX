"""Configuração manual -> fallback real -> executor/dispatcher/API, somente SQLite em memória."""
from contextlib import redirect_stdout
from datetime import date
import io
import json
import os
import unittest
from unittest.mock import patch
from sqlalchemy import select
from api.tests.test_operational_schedule import ScheduleApiTest
from api.tests.test_findings import SQLiteWriter
from api.tests.test_regras_configuradas import Motor
from shared.journey import resolve
from shared.treatment_catalog import montar_regra
from src.operational_schedule import execute
from src.regras_configuradas import carregar_regras, ProvedorDeExcecoes


class ManualScheduleFlowTest(ScheduleApiTest):
    def test_manual_44_fallback_generation_and_notification_api(self):
        # JSON controlado, nunca cadastra colaborador ou altera fonte real.
        sample = json.loads('{"colaborador":"COLABORADOR TESTE 44H","jornada":44,"hora_entrada":"08:00","hora_saida":null}')
        with self.db.engine.begin() as c:
            c.execute(self.db.tables['jornada_consolidada'].delete())
        body = self.body(sample['jornada'])
        schedule = {**body['jornadas'][0], 'nome_jornada': 'Manual 44H', 'intervalo': '01:00', 'origem_configuracao': 'MANUAL'}
        # A regra já existe quando a configuração manual é adicionada via PATCH.
        response = self.client.post(self.url, json={**body, 'jornadas': []})
        self.assertEqual(200, response.status_code, response.text)
        rule_id = response.json()['regra']['configuracao_id']
        def rule_snapshot():
            with self.db.engine.connect() as c:
                return {name: [dict(r) for r in c.execute(select(self.db.tables[name])).mappings()]
                        for name in ('regra_configuracao', 'regra_condicao_configuracao', 'regra_tratamento_configuracao')}
        before = rule_snapshot()
        response = self.client.patch('/api/v2/configuracoes/regras/CHECKOUT_AUSENTE?marca=BRACELL&operacao=EXCLUSIVA',
                                     json={'usuario': body['usuario'], 'motivo': body['motivo'], 'jornadas': [schedule]})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(before, rule_snapshot(), 'Adicionar jornada não pode criar ou modificar regras, condições ou tratamentos.')
        self.assertEqual(rule_id, response.json()['regra']['configuracao_id'])
        saved = response.json()['regra']['jornadas'][0]
        self.assertFalse(saved['disponivel'])
        self.assertEqual(('MANUAL', '01:00'), (saved['origem_configuracao'], saved['intervalo']))
        self.db.insert('regra_tratativa', **montar_regra('CHECKOUT_AUSENTE'))
        self.db.insert('execucao', execution_id='manual-run', marca='BRACELL', status_execucao='INICIADA',
                       periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 1))
        person = dict(id='manual-person', usuario='manual-person', nome_colaborador=sample['colaborador'],
                      usuario_ativo='Sim', perfil='PROMOTOR EXCLUSIVO', data_dimensao='2026-09-01', data_evolucao='2026-09-02')
        configs = [dict(tabela=table, prioridade=i, campo_horas='horas', campo_perfil='perfil', campo_jornada='jornada')
                   for i, table in enumerate(('principal', 'secundaria'), 1)]
        resolutions = resolve({'principal': [{**person, 'horas': None}], 'secundaria': [{**person, 'horas': '44H'}]},
                              configs, brand='BRACELL', operation='EXCLUSIVA', profiles=['PROMOTOR EXCLUSIVO'], as_of='2026-09-01')
        self.assertEqual(('RESOLVIDA', 44, 'secundaria'),
                         (resolutions[0]['status_resolucao'], resolutions[0]['jornada_semanal'], resolutions[0]['fonte']))
        row = {k: sample[k] for k in ('colaborador', 'hora_entrada', 'hora_saida')}
        row.update(data='2026-09-01', evolucao='2026-09-02 05:00:00')
        sources = {'checkout': [dict(fonte_id='fixture', schema_fisico='involves_bracell', tabela_fisica='status_day',
                                   mapeamento_campos={k: k for k in row})]}
        reader = lambda *args: [dict(row)]
        provider = ProvedorDeExcecoes(sources, reader, lambda day: resolutions, '2026-09-01', '2026-09-01')
        rule = next(r for r in carregar_regras(self.db.engine, 'BRACELL', 'EXCLUSIVA', prefixo='') if r['codigo_interno'] == 'CHECKOUT_AUSENTE')
        motor = Motor(self.db, SQLiteWriter(self.db.engine))
        with patch.dict(os.environ, {'PDOH_EXECUTION_ID': 'manual-run'}), redirect_stdout(io.StringIO()):
            result = execute(motor, rule, sources, provider, reader, '2026-09-01', '2026-09-01',
                             marca='BRACELL', operacao='EXCLUSIVA', registrar=False, prefixo='')
            again = execute(motor, rule, sources, provider, reader, '2026-09-01', '2026-09-01',
                            marca='BRACELL', operacao='EXCLUSIVA', registrar=False, prefixo='')
        self.assertEqual(1, result['criadas'])
        self.assertEqual(0, again['criadas'])
        with self.db.engine.begin() as c:
            opportunity = dict(c.execute(select(self.db.tables['oportunidade'])).mappings().one())
            proof = opportunity['evidencia']['comprovacao']
            self.assertEqual('19:00', proof['configuracao_operacional']['hora_saida_padrao'])
            self.assertIsNone(proof['monitoramento']['hora_saida'])
            self.assertEqual('MEDIA', opportunity['severidade'])
            table = self.db.tables['execucao']
            c.execute(table.update().where(table.c.execution_id == 'manual-run').values(status_execucao='CONCLUIDA'))
        params = dict(marca='BRACELL', operacao='EXCLUSIVA', periodo='automatico')
        summary = self.client.get('/api/v2/findings/resumo', params=params)
        self.assertEqual(200, summary.status_code, summary.text)
        params.update(periodo='personalizado', periodo_inicio=summary.json()['periodo']['inicio'], periodo_fim=summary.json()['periodo']['fim'])
        groups = self.client.get('/api/v2/oportunidades/resumo', params=params)
        self.assertEqual(200, groups.status_code, groups.text)
        self.assertEqual(1, groups.json()['total'])
        group = groups.json()['items'][0]
        self.assertEqual('CHECKOUT_AUSENTE', group['tipo_problema'])
        evidence = self.client.get('/api/v2/oportunidades/' + group['grupo_id'] + '/evidencias', params=params)
        self.assertEqual(200, evidence.status_code, evidence.text)
        if os.environ.get('EXPORT_MANUAL_FLOW') == '1':
            print('MANUAL_FLOW=' + json.dumps(dict(summary=summary.json(), groups=groups.json(), evidence=evidence.json(),
                result=result, fallback=resolutions[0]['fonte'], schedule=saved), ensure_ascii=False, default=str))


if __name__ == '__main__':
    unittest.main()
