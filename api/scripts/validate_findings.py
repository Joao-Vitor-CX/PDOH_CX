"""Validacao real do roteamento, rollback integral e comparacao de hashes.

Somente o teste transacional cria execucao SINTETICA (nao executa pipeline), sempre
revertida. Catalogo real e historico existente sao apenas lidos. API usa reader.
"""
from contextlib import contextmanager, redirect_stdout
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'bracell'))

from fastapi.testclient import TestClient
from sqlalchemy import text
from api.app.config import Settings
from api.app.database import Database
from api.app.main import create_app
from api.scripts.validate_live import snapshot
from api.scripts.validate_fallback import local_admin, platina_snapshot
from src.findings import registrar_achado


def transactional_test(admin):
    identifier = 'BRACELL_VALIDACAO_ROTEAMENTO_' + uuid4().hex[:16]
    old = os.environ.get('PDOH_EXECUTION_ID')
    os.environ['PDOH_EXECUTION_ID'] = identifier
    expected = {'CHECKOUT_AUSENTE': 'OPORTUNIDADE', 'PDV_MESMO_NOME_IDS_DISTINTOS': 'ALERTA',
        'DATA_FORA_DO_PERIODO': 'TELEMETRIA', 'VALOR_SEM_PADRONIZACAO': 'ALERTA',
        'REGISTRO_DUPLICADO': 'TELEMETRIA', 'CAMPO_OBRIGATORIO_VAZIO': 'OPORTUNIDADE'}
    checks = {}
    try:
        with admin.connect() as c:
            transaction = c.begin()
            try:
                c.execute(text("INSERT INTO pdoh_controle.execucao (execution_id,marca,status_execucao,componente_atual) "
                    "VALUES (:id,'BRACELL','INICIADA','VALIDACAO')"), {'id': identifier})
                class Writer:
                    @contextmanager
                    def begin(self):
                        with c.begin_nested():
                            yield c
                items = [dict(marca='BRACELL', tipo_problema=kind, origem='TESTE_TRANSACIONAL', tabela_origem='fixture',
                    descricao_detalhada='Teste transacional revertido', severidade='ALTA', evidencia={'sintetico': True}) for kind in expected]
                with redirect_stdout(io.StringIO()):
                    assert registrar_achado(Writer(), items) == 6
                    assert registrar_achado(Writer(), items) == 0
                routes = c.execute(text("SELECT tipo_problema,classificacao,destino,registro_id FROM pdoh_controle.achado_roteamento WHERE execution_id=:id"), {'id': identifier}).mappings().all()
                assert {r['tipo_problema']:r['classificacao'] for r in routes} == expected
                for table in ('oportunidade','alerta','execucao_evento','oportunidade_historico','notificacao_outbox'):
                    quantity = c.execute(text('SELECT COUNT(*) FROM pdoh_controle.'+table+' WHERE execution_id=:id'), {'id': identifier}).scalar_one()
                    assert quantity == 2, (table, quantity)
                    checks[table] = quantity
                checks['achado_roteamento'] = len(routes)
                checks['rotas'] = [dict(r) for r in routes]
            finally:
                transaction.rollback()
            assert c.execute(text('SELECT COUNT(*) FROM pdoh_controle.execucao WHERE execution_id=:id'), {'id': identifier}).scalar_one() == 0
        checks['rollback_confirmado'] = True
        return checks
    finally:
        if old is None:
            os.environ.pop('PDOH_EXECUTION_ID', None)
        else:
            os.environ['PDOH_EXECUTION_ID'] = old


def main():
    settings = replace(Settings.load(), host='127.0.0.1', port=3307)
    database = Database(settings)
    database.initialize()
    admin = local_admin()
    try:
        before = snapshot(database)
        platina_before = platina_snapshot(admin)
        tests = transactional_test(admin)
        results = {}
        with TestClient(create_app(settings, database)) as client:
            client.headers['Authorization'] = 'Bearer '+settings.token
            for path, classification in [('oportunidades','OPORTUNIDADE'),('alertas','ALERTA'),('telemetria','TELEMETRIA')]:
                response = client.get('/api/v2/'+path, params={'tamanho': 3})
                assert response.status_code == 200, response.text
                page = response.json()
                assert all(item['classificacao'] == classification for item in page['items'])
                fresh = client.get('/api/v2/'+path, params={'incluir_legado': False}).json()
                assert fresh['total'] == 0
                results[path] = {'total': page['total'], 'novos': fresh['total'], 'http': response.status_code}
            after = snapshot(database)
        platina_after = platina_snapshot(admin)
        assert before == after, 'Dados de controle divergiram; verificar atividade concorrente.'
        assert platina_before == platina_after
        print(json.dumps({'teste_mysql': tests, 'api': results, 'controle_antes': before, 'controle_depois': after,
            'platina_antes': platina_before, 'platina_depois': platina_after, 'historico_preservado': True}, ensure_ascii=False, default=str))
    finally:
        database.close()
        admin.dispose()


if __name__ == '__main__':
    main()
