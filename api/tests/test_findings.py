"""Dispatcher real + SQL sintetico SQLite + API v2. Nunca acessa MySQL/pipeline."""
from contextlib import contextmanager, redirect_stdout
from datetime import date, datetime
import io
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from api.app.config import Settings
from api.app.main import create_app
from api.tests.test_api import FixtureDatabase

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bracell'))
from src.findings import campos_da_evidencia, grupo_operacional, registrar_achado


class SQLiteWriter:
    """Somente adapta sintaxe MySQL de binds/lock; executa INSERT/SELECT reais em memoria."""
    def __init__(self, engine):
        self.engine = engine
        self.statements = []

    @contextmanager
    def begin(self):
        with self.engine.begin() as connection:
            owner = self
            class Connection:
                def execute(self, statement, params=None):
                    sql = str(statement)
                    owner.statements.append(sql)
                    sql = (sql.replace('pdoh_controle.', '').replace(' FOR UPDATE', '').replace(' FOR SHARE', '')
                              .replace('INSERT IGNORE INTO', 'INSERT OR IGNORE INTO'))
                    sql = re.sub(r'CAST\((:[a-z_]+) AS JSON\)', r'\1', sql)
                    return connection.execute(text(sql), params or {})
            yield Connection()


class FindingsTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        with self.db.engine.begin() as c:
            c.execute(text('CREATE TABLE configuracao_jornada_operacao (id TEXT PRIMARY KEY, configuracao_id TEXT, '
                           'marca TEXT, operacao TEXT, jornada REAL, hora_entrada_padrao TEXT, hora_saida_padrao TEXT, ativo INTEGER)'))
        self.db.insert('execucao', execution_id='new-run', marca='BRACELL', status_execucao='INICIADA',
            periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5))
        self.writer = SQLiteWriter(self.db.engine)
        self.client = TestClient(create_app(Settings(token='x' * 40), self.db))
        self.client.__enter__()
        self.client.headers['Authorization'] = 'Bearer ' + 'x' * 40
        self.env = patch.dict(os.environ, {'PDOH_EXECUTION_ID': 'new-run'})
        self.env.start()
        # Relogio fixo: semana fechada padrao = 2026-08-31..2026-09-06 (cobre os fixtures).
        self.clock = patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 9))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.env.stop()
        self.client.__exit__(None, None, None)

    def rule(self, kind, classification, brand='BRACELL', identifier=None, *, ativar=True, **extras):
        # Oportunidade so existe com regra CONFIGURAVEL ativa; `ativar=False` reproduz "regra
        # cadastrada no catalogo, mas nao configurada" (nada deve ser criado).
        if ativar and 'OPORTUNIDADE' in (classification, extras.get('classificacao_excecao')):
            self.db.ativar_regra(kind, brand)
            if kind == 'CHECKOUT_AUSENTE':
                with self.db.engine.begin() as c:
                    c.execute(text('INSERT INTO configuracao_jornada_operacao VALUES '
                        "('schedule',:id,:brand,'EXCLUSIVA',44,'08:00','19:00',1)"),
                        dict(id=f'cfg:{brand}:EXCLUSIVA:{kind}', brand=brand))
        extras.setdefault('severidade_padrao', 'MEDIA')
        extras.setdefault('impacto_negocio', 'Tempo operacional')
        extras.setdefault('acao_recomendada', 'Validar o registro na origem')
        extras.setdefault('responsavel_padrao', 'Lider da operacao')
        self.db.insert('regra_tratativa', regra_id=identifier or kind, marca=brand,
            tipo_problema=kind, classificacao=classification, status_regra='ATIVA', prioridade=10, **extras)

    def comprovacao(self, resultado='confirmado'):
        """Selo que o motor de evidencias carimba antes do achado chegar ao dispatcher."""
        return dict(resultado=resultado, regra='CHECKOUT_AUSENTE', fonte='relatorio_checkin_bracell',
                    configuracao_operacional=dict(id='schedule', jornada=44, hora_entrada_padrao='08:00', hora_saida_padrao='19:00'),
                    monitoramento=dict(data='2026-09-01', hora_entrada='08:03:00', hora_saida=None, evolucao='2026-09-02 05:00:00'),
                    campo='hora_saida', jornada_origem='INVOLVES', justificativa=False, atestado=False,
                    motivo=None if resultado == 'confirmado' else 'Sem comprovação na fonte oficial.',
                    verificacoes=[])

    def finding(self, kind='CHECKOUT_AUSENTE', *, sem_prova=False, **extras):
        """Achado ja comprovado, como a esteira o entrega apos o motor de evidencias.

        `sem_prova=True` reproduz o caminho antigo, que o dispatcher agora recusa.
        """
        base = dict(tipo_problema=kind, marca='BRACELL', colaborador='Colaborador teste', origem='TEST', tabela_origem='fixture',
                    descricao_detalhada='Achado sintetico', severidade='MEDIA', evidencia={'campo': 'UF'})
        base.update(extras)
        if not sem_prova and isinstance(base.get('evidencia'), dict):
            base['evidencia'] = {**base['evidencia'], 'comprovacao': self.comprovacao()}
        return base

    def dispatch(self, items):
        with redirect_stdout(io.StringIO()):
            return registrar_achado(self.writer, items)

    def count(self, table):
        with self.db.connection() as c:
            return c.execute(text('SELECT COUNT(*) FROM '+table)).scalar_one()

    def page(self, path, **params):
        response = self.client.get('/api/v2/'+path, params=params)
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_six_required_types_catalog_routes_and_api_no_mixing(self):
        catalog = {'CHECKOUT_AUSENTE': 'OPORTUNIDADE', 'PDV_MESMO_NOME_IDS_DISTINTOS': 'ALERTA',
            'DATA_FORA_DO_PERIODO': 'TELEMETRIA', 'VALOR_SEM_PADRONIZACAO': 'ALERTA',
            'REGISTRO_DUPLICADO': 'TELEMETRIA', 'CAMPO_OBRIGATORIO_VAZIO': 'OPORTUNIDADE'}
        for kind, classification in catalog.items():
            self.rule(kind, classification)
        self.assertEqual(6, self.dispatch([self.finding(k) for k in catalog]))
        for table in ('oportunidade', 'alerta', 'execucao_evento'):
            self.assertEqual(2, self.count(table))
        self.assertEqual(2, self.count('oportunidade_historico'))
        self.assertEqual(6, self.count('achado_roteamento'))
        for endpoint, classification in [('oportunidades','OPORTUNIDADE'), ('alertas','ALERTA'), ('telemetria','TELEMETRIA')]:
            result = self.page(endpoint, incluir_legado=False)
            self.assertEqual(2, result['total'])
            self.assertEqual({classification}, {r['classificacao'] for r in result['items']})
            self.assertTrue(all(r['regra_snapshot']['classificacao'] == classification for r in result['items']))
        self.assertTrue(any('FROM pdoh_controle.regra_tratativa' in s for s in self.writer.statements))

    def test_dispatcher_recusa_oportunidade_sem_comprovacao(self):
        """Ultima linha de defesa: mesmo que um detector escape, nao ha fila sem prova."""
        for kind in ('CHECKOUT_AUSENTE', 'CHECKIN_ENTRADA_AUSENTE', 'INCONSISTENCIA_HORARIO'):
            self.rule(kind, 'OPORTUNIDADE')
        sem_prova = [self.finding(kind, sem_prova=True) for kind in
                     ('CHECKOUT_AUSENTE', 'CHECKIN_ENTRADA_AUSENTE', 'INCONSISTENCIA_HORARIO')]
        self.assertEqual(0, self.dispatch(sem_prova))
        self.assertEqual(0, self.count('oportunidade'))
        self.assertEqual(0, self.count('achado_roteamento'))
        # O achado nao some: vira evento de governanca com o motivo.
        with self.db.connection() as c:
            eventos = [dict(row._mapping) for row in c.execute(text(
                "SELECT codigo, categoria FROM execucao_evento WHERE categoria='EVIDENCIA'"))]
        self.assertEqual(3, len(eventos))
        self.assertEqual({'ACHADO_SEM_EVIDENCIA_CONFIRMADA'}, {e['codigo'] for e in eventos})

    def test_dispatcher_aceita_o_mesmo_achado_quando_a_prova_chega(self):
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE')
        self.assertEqual(0, self.dispatch([self.finding('CHECKOUT_AUSENTE', sem_prova=True)]))
        self.assertEqual(1, self.dispatch([self.finding('CHECKOUT_AUSENTE')]))
        self.assertEqual(1, self.count('oportunidade'))

    def test_comprovacao_nao_confirmada_tambem_e_recusada(self):
        """`nao_aplicavel` e `indisponivel` sao decisoes explicitas, nao aprovacoes."""
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE')
        for resultado in ('nao_aplicavel', 'indisponivel'):
            achado = self.finding('CHECKOUT_AUSENTE', sem_prova=True)
            achado['evidencia'] = {**achado['evidencia'], 'comprovacao': self.comprovacao(resultado)}
            self.assertEqual(0, self.dispatch([achado]), resultado)
        self.assertEqual(0, self.count('oportunidade'))

    def test_producer_cannot_force_classification_or_rule_id(self):
        self.rule('NOVO_TIPO_NAO_HARDCODED', 'ALERTA')
        item = self.finding('NOVO_TIPO_NAO_HARDCODED', classificacao='OPORTUNIDADE', regra_id='forged')
        before = json.dumps(item, sort_keys=True)
        self.assertEqual(1, self.dispatch(item))
        self.assertEqual(0, self.count('oportunidade'))
        self.assertEqual(1, self.count('alerta'))
        self.assertEqual(before, json.dumps(item, sort_keys=True))

    def test_no_active_rule_or_invalid_class_never_creates_opportunity(self):
        self.rule('CONFIG', 'CONFIG')
        self.assertEqual(0, self.dispatch([self.finding('UNKNOWN'), self.finding('CONFIG')]))
        self.assertEqual(0, self.count('oportunidade'))
        self.assertEqual(0, self.count('alerta'))
        self.assertEqual(2, self.count('execucao_evento'))
        self.assertEqual(2, self.page('telemetria')['total']) # erros de roteamento sao eventos tecnicos

    def test_specific_brand_then_global_and_never_other_brand(self):
        self.rule('K', 'TELEMETRIA', brand=None, identifier='global')
        self.rule('K', 'ALERTA', identifier='bracell')
        self.rule('K', 'OPORTUNIDADE', brand='FLORA', identifier='flora')
        self.assertEqual(1, self.dispatch(self.finding('K')))
        self.assertEqual(1, self.page('alertas', marca='BRACELL')['total'])
        self.assertEqual(0, self.page('alertas', marca='FLORA')['total'])
        self.db.insert('execucao', execution_id='flora-run', marca='FLORA', status_execucao='INICIADA',
            periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5))
        with patch.dict(os.environ, {'PDOH_EXECUTION_ID': 'flora-run'}):
            item = self.finding('K'); item['marca'] = 'FLORA'
            self.assertEqual(1, self.dispatch(item))
        self.assertEqual(1, self.page('oportunidades', marca='FLORA')['total'])
        self.assertEqual(0, self.page('oportunidades', marca='BRACELL')['total'])
        self.rule('GLOBAL_ONLY', 'TELEMETRIA', brand=None)
        self.assertEqual(1, self.dispatch(self.finding('GLOBAL_ONLY')))

    def test_ambiguous_global_rules_are_diagnostic_only(self):
        self.rule('K', 'ALERTA', brand=None, identifier='g1')
        self.rule('K', 'OPORTUNIDADE', brand=None, identifier='g2')
        self.assertEqual(0, self.dispatch(self.finding('K')))
        self.assertEqual(0, self.count('achado_roteamento'))

    def test_duplicate_and_later_catalog_change_do_not_reroute_or_reclassify(self):
        self.rule('K', 'ALERTA')
        item = self.finding('K')
        self.assertEqual(1, self.dispatch(item))
        with self.db.engine.begin() as c:
            c.execute(self.db.tables['regra_tratativa'].update().values(classificacao='OPORTUNIDADE'))
        self.assertEqual(0, self.dispatch(item))
        self.assertEqual(1, self.count('alerta'))
        self.assertEqual(0, self.count('oportunidade'))
        self.assertEqual(1, self.page('alertas')['total'])
        self.assertEqual(0, self.page('oportunidades')['total'])

    def test_batch_rollback_and_brand_mismatch_do_not_leak_rows(self):
        self.rule('K', 'ALERTA')
        wrong = self.finding('K'); wrong['marca'] = 'FLORA'
        self.assertEqual(0, self.dispatch([self.finding('K'), wrong]))
        self.assertEqual(0, self.count('alerta'))
        self.assertEqual(0, self.count('achado_roteamento'))

    def test_closed_execution_does_not_receive_new_rows(self):
        self.rule('K', 'ALERTA')
        with self.db.engine.begin() as c:
            c.execute(self.db.tables['execucao'].update().values(status_execucao='CONCLUIDA'))
        self.assertEqual(0, self.dispatch(self.finding('K')))
        self.assertEqual(0, self.count('alerta'))

    def test_legacy_is_read_without_migration_and_filters_paginate(self):
        self.rule('K', 'ALERTA')
        self.db.insert('oportunidade', oportunidade_id='legacy', execution_id='new-run', marca='BRACELL', regra_id='K', tipo_problema='K')
        self.assertEqual(1, self.dispatch(self.finding('K')))
        self.assertEqual(2, self.page('alertas')['total'])
        self.assertEqual(1, self.page('alertas', incluir_legado=False)['total'])
        self.assertEqual(1, self.count('oportunidade'))
        self.assertEqual(0, self.count('oportunidade_historico'))
        first = self.page('alertas', tamanho=1)
        second = self.page('alertas', tamanho=1, pagina=2)
        self.assertNotEqual(first['items'][0]['origem_registro'], second['items'][0]['origem_registro'])
        self.assertEqual(0, self.page('alertas', tipo='OTHER')['total'])
        self.assertEqual(0, self.page('alertas', marca="' OR 1=1 --")['total'])
        self.assertEqual(0, self.page('alertas', periodo_inicio='2030-01-01')['total'])

    def test_api_auth_read_only_and_snapshot(self):
        self.rule('K', 'ALERTA'); self.dispatch(self.finding('K'))
        with self.db.connection() as c:
            before = {n: [dict(r) for r in c.execute(select(t)).mappings()] for n,t in self.db.tables.items()}
        self.page('alertas')
        with self.db.connection() as c:
            after = {n: [dict(r) for r in c.execute(select(t)).mappings()] for n,t in self.db.tables.items()}
        self.assertEqual(before, after)
        self.assertEqual(405, self.client.post('/api/v2/alertas', json={}).status_code)
        self.assertEqual(422, self.client.get('/api/v2/alertas?classificacao=OPORTUNIDADE').status_code)
        self.client.headers.pop('Authorization')
        self.assertEqual(401, self.client.get('/api/v2/telemetria').status_code)


    # ---- Filtros operacionais v2: severidade, colaborador, periodo e resumo ----

    def test_filtro_severidade_usa_catalogo_e_nao_valor_do_registro(self):
        self.rule('OP_ALTA', 'OPORTUNIDADE', identifier='op_alta', severidade_padrao='ALTA')
        self.rule('OP_MEDIA', 'OPORTUNIDADE', identifier='op_media', severidade_padrao='MEDIA')
        # O registro grava BAIXA, mas o catalogo diz ALTA -> visao e filtro seguem o catalogo.
        self.assertEqual(2, self.dispatch([
            self.finding('OP_ALTA', severidade='BAIXA', data_referencia='2026-09-02'),
            self.finding('OP_MEDIA', severidade='BAIXA', data_referencia='2026-09-03')]))
        alta = self.page('oportunidades', severidade='ALTA')
        self.assertEqual(1, alta['total'])
        self.assertEqual('ALTA', alta['items'][0]['severidade'])
        self.assertEqual('OP_ALTA', alta['items'][0]['tipo_problema'])
        self.assertEqual(1, self.page('oportunidades', severidade='MEDIA')['total'])
        self.assertEqual(0, self.page('oportunidades', severidade='CRITICA')['total'])

    def test_filtro_colaborador_por_nome_ou_id_interno(self):
        self.rule('OP', 'OPORTUNIDADE')
        self.db.insert('colaborador_identidade', colaborador_id_interno='id-123', marca='BRACELL')
        self.db.insert('colaborador_identidade', colaborador_id_interno='id-999', marca='BRACELL')
        self.assertEqual(2, self.dispatch([
            self.finding('OP', colaborador='Joao Silva', colaborador_id_interno='id-123', data_referencia='2026-09-02'),
            self.finding('OP', colaborador='Maria Souza', colaborador_id_interno='id-999', data_referencia='2026-09-03')]))
        por_nome = self.page('oportunidades', colaborador='joao')
        self.assertEqual(1, por_nome['total'])
        self.assertEqual('Joao Silva', por_nome['items'][0]['colaborador'])
        por_id = self.page('oportunidades', colaborador='id-999')
        self.assertEqual(1, por_id['total'])
        self.assertEqual('Maria Souza', por_id['items'][0]['colaborador'])
        self.assertEqual(0, self.page('oportunidades', colaborador='inexistente')['total'])

    def test_filtro_periodo_nao_retorna_fora_da_janela(self):
        self.rule('OP', 'OPORTUNIDADE')
        self.assertEqual(1, self.dispatch(self.finding('OP')))
        dentro = self.page('oportunidades', periodo_inicio='2026-08-31', periodo_fim='2026-09-06')
        self.assertEqual(1, dentro['total'])
        fora = self.page('oportunidades', periodo_inicio='2026-10-01', periodo_fim='2026-10-31')
        self.assertEqual(0, fora['total'])

    def test_periodo_padrao_segunda_abre_semana_anterior_seg_a_sab(self):
        with patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 14)):  # segunda-feira
            resumo = self.client.get('/api/v2/findings/resumo').json()
        self.assertEqual('2026-09-07', resumo['periodo']['inicio'])   # segunda anterior
        self.assertEqual('2026-09-12', resumo['periodo']['fim'])      # sabado anterior
        # Domingo nunca entra na janela operacional.
        self.assertEqual(5, date.fromisoformat(resumo['periodo']['fim']).weekday())

    def test_classificacao_resolve_por_tipo_quando_nao_ha_regra_id(self):
        """Historico sem regra_id continua classificado pelo catalogo (tipo + marca)."""
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE', severidade_padrao='ALTA',
                  tratamento_esperado='Corrigir o check-out na origem')
        self.db.insert('oportunidade', oportunidade_id='sem-regra', execution_id='new-run',
            marca='BRACELL', tipo_problema='CHECKOUT_AUSENTE', regra_id=None, severidade='BAIXA')
        page = self.page('oportunidades')
        self.assertEqual(1, page['total'])
        item = page['items'][0]
        self.assertEqual('CATALOGO_POR_TIPO_MARCA', item['criterio_classificacao'])
        self.assertEqual('OPORTUNIDADE', item['classificacao'])
        self.assertEqual('ALTA', item['severidade'])
        self.assertEqual('Corrigir o check-out na origem', item['tratativa'])
        self.assertEqual('CHECKOUT_AUSENTE', item['regra_id'])
        self.assertEqual(0, self.page('alertas')['total'])

    def test_excecao_por_origem_separa_mesma_regra_em_duas_classificacoes(self):
        """INCONSISTENCIA_HORARIO: telemetria em pesquisas, oportunidade em check-in."""
        self.rule('INCONSISTENCIA_HORARIO', 'TELEMETRIA',
                  origem_excecao='relatorio_checkin_bracell', classificacao_excecao='OPORTUNIDADE')
        for identifier, origem in (('pesq', 'painel_pesquisas_bracell'), ('chk', 'relatorio_checkin_bracell')):
            self.db.insert('oportunidade', oportunidade_id=identifier, execution_id='new-run',
                marca='BRACELL', tipo_problema='INCONSISTENCIA_HORARIO', regra_id=None, tabela_origem=origem)
        operacional = self.page('oportunidades')
        self.assertEqual(1, operacional['total'])
        self.assertEqual('chk', operacional['items'][0]['id'])
        tecnico = self.page('telemetria')
        self.assertEqual(1, tecnico['total'])
        self.assertEqual('pesq', tecnico['items'][0]['id'])
        self.assertEqual(0, self.page('alertas')['total'])

    def test_registro_sem_regra_no_catalogo_nao_vaza_para_nenhum_endpoint(self):
        self.db.insert('oportunidade', oportunidade_id='orfao', execution_id='new-run',
            marca='BRACELL', tipo_problema='TIPO_INEXISTENTE', regra_id=None)
        for endpoint in ('oportunidades', 'alertas', 'telemetria'):
            self.assertEqual(0, self.page(endpoint)['total'])

    def test_periodo_mensal_retorna_mes_fechado(self):
        with patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 17)):
            resumo = self.client.get('/api/v2/findings/resumo', params={'periodo': 'mes'}).json()
        self.assertEqual('2026-08-01', resumo['periodo']['inicio'])
        self.assertEqual('2026-08-31', resumo['periodo']['fim'])

    def test_resumo_bate_com_consultas_individuais(self):
        for kind, classe, sev in [('OP_A', 'OPORTUNIDADE', 'ALTA'), ('OP_M', 'OPORTUNIDADE', 'MEDIA'),
                                   ('AL', 'ALERTA', 'MEDIA'), ('TL', 'TELEMETRIA', 'MEDIA')]:
            self.rule(kind, classe, identifier=kind.lower(), severidade_padrao=sev)
        self.assertEqual(4, self.dispatch([self.finding('OP_A'), self.finding('OP_M'),
                                           self.finding('AL'), self.finding('TL')]))
        resumo = self.client.get('/api/v2/findings/resumo').json()
        self.assertEqual(self.page('oportunidades')['total'], resumo['oportunidades']['total'])
        self.assertEqual(self.page('alertas')['total'], resumo['alertas']['total'])
        self.assertEqual(self.page('telemetria')['total'], resumo['telemetria']['total'])
        self.assertEqual(2, resumo['oportunidades']['total'])
        self.assertEqual(1, resumo['oportunidades']['alta'])
        self.assertEqual(1, resumo['oportunidades']['media'])
        self.assertEqual(resumo['oportunidades']['total'],
            resumo['oportunidades']['critica'] + resumo['oportunidades']['alta']
            + resumo['oportunidades']['media'] + resumo['oportunidades']['baixa'])


    # ---- Camada de resumo operacional: agrupamento, dedup e ciclo de vida ----

    def ocorrencia(self, identifier, **extras):
        """Linha historica em `oportunidade` (sem passar pelo dispatcher)."""
        base = dict(oportunidade_id=identifier, execution_id='new-run', marca='BRACELL',
                    tipo_problema='CHECKOUT_AUSENTE', regra_id=None, colaborador='Joao Silva',
                    colaborador_id_interno=None, tabela_origem='relatorio_checkin_bracell',
                    fingerprint='fp-' + identifier, data_referencia=date(2026, 9, 1),
                    severidade='MEDIA', status_oportunidade='ABERTA')
        base.update(extras)
        self.db.insert('oportunidade', **base)

    def grupos(self, **params):
        return self.page('oportunidades/resumo', **params)

    def test_resumo_agrupa_por_regra_colaborador_e_nao_conta_repeticao_de_execucao(self):
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE', titulo='Check-out nao registrado',
                  severidade_padrao='MEDIA', tratamento_esperado='Corrigir o check-out na origem')
        # Mesmo achado regravado por 3 execucoes + 2 dias distintos do mesmo colaborador.
        for execucao in ('r1', 'r2', 'r3'):
            self.db.insert('execucao', execution_id=execucao, marca='BRACELL', status_execucao='CONCLUIDA',
                periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5))
            self.ocorrencia(f'a-{execucao}', execution_id=execucao, fingerprint='fp-dia1')
            self.ocorrencia(f'b-{execucao}', execution_id=execucao, fingerprint='fp-dia2',
                            data_referencia=date(2026, 9, 2))
        self.ocorrencia('outro', fingerprint='fp-maria', colaborador='Maria Souza')

        pagina = self.grupos()
        self.assertEqual(2, pagina['total'])                      # 7 linhas -> 2 cards
        joao = next(g for g in pagina['items'] if g['colaborador'] == 'Joao Silva')
        self.assertEqual(2, joao['quantidade'])                   # COUNT(DISTINCT fingerprint)
        self.assertEqual(6, joao['registros_historicos'])         # COUNT(*) preservado
        self.assertEqual(2, joao['dias_afetados'])
        self.assertEqual('2026-09-01', joao['primeira_ocorrencia'])
        self.assertEqual('2026-09-02', joao['ultima_ocorrencia'])
        self.assertEqual('Check-out nao registrado', joao['titulo'])
        # `tratamento_esperado` e' legado tecnico; o card usa o impacto de
        # negocio cadastrado no catalogo.
        self.assertEqual('Tempo operacional', joao['impacto'])
        self.assertEqual('ABERTA', joao['status_operacional'])
        # O card nao carrega identificador tecnico.
        self.assertNotIn('oportunidade_id', joao)
        self.assertNotIn('fingerprint', joao)

    def test_detalhes_do_grupo_expoem_ocorrencias_e_ids_tecnicos(self):
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE', titulo='Check-out nao registrado')
        for execucao in ('r1', 'r2'):
            self.db.insert('execucao', execution_id=execucao, marca='BRACELL', status_execucao='CONCLUIDA',
                periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5))
            self.ocorrencia(f'x-{execucao}', execution_id=execucao, fingerprint='fp-unico')
        grupo_id = self.grupos()['items'][0]['grupo_id']
        detalhe = self.page(f'oportunidades/{grupo_id}/detalhes')
        self.assertEqual('Joao Silva', detalhe['colaborador'])
        self.assertEqual(1, detalhe['quantidade'])
        self.assertEqual(1, detalhe['ocorrencias']['total'])
        ocorrencia = detalhe['ocorrencias']['items'][0]
        self.assertEqual(2, ocorrencia['repeticoes'])             # regravada em 2 execucoes
        self.assertEqual('fp-unico', ocorrencia['fingerprint'])
        self.assertIn(ocorrencia['execution_id'], {'r1', 'r2'})
        self.assertEqual(404, self.client.get('/api/v2/oportunidades/nao-e-um-grupo/detalhes').status_code)

    def test_resolvida_sai_da_fila_e_reabre_com_ocorrencia_posterior(self):
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE')
        self.ocorrencia('o1', identificada_em=datetime(2026, 9, 2, 8))
        grupo_id = self.grupos()['items'][0]['grupo_id']

        self.db.insert('oportunidade_grupo_status', grupo_id=grupo_id, marca='BRACELL',
            tipo_problema='CHECKOUT_AUSENTE', colaborador='Joao Silva', colaborador_id_interno=None,
            status_operacional='RESOLVIDA', resolvido_em=datetime(2026, 9, 3, 12), responsavel='Lider')
        self.assertEqual(0, self.grupos()['total'])                       # sai da fila aberta
        encerradas = self.grupos(incluir_encerradas=True)
        self.assertEqual(1, encerradas['total'])                          # segue no historico
        self.assertEqual('RESOLVIDA', encerradas['items'][0]['status_operacional'])

        # Nova ocorrencia identificada depois da resolucao reabre o grupo.
        self.ocorrencia('o2', fingerprint='fp-novo', identificada_em=datetime(2026, 9, 4, 9))
        fila = self.grupos()
        self.assertEqual(1, fila['total'])
        self.assertEqual('REABERTA', fila['items'][0]['status_operacional'])

    def test_resumo_so_traz_oportunidade_e_respeita_filtros(self):
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE', severidade_padrao='ALTA')
        self.rule('PESQUISA_CAMPOS_NULOS', 'TELEMETRIA', identifier='pesq')
        self.ocorrencia('op')
        self.ocorrencia('tel', tipo_problema='PESQUISA_CAMPOS_NULOS', fingerprint='fp-tel')
        self.assertEqual(1, self.grupos()['total'])                       # telemetria fora
        self.assertEqual(1, self.grupos(severidade='ALTA')['total'])
        self.assertEqual(0, self.grupos(severidade='BAIXA')['total'])
        self.assertEqual(1, self.grupos(colaborador='joao')['total'])
        self.assertEqual(0, self.grupos(colaborador='ninguem')['total'])
        self.assertEqual(0, self.grupos(periodo_inicio='2030-01-01')['total'])


    # ---- Contrato operacional definitivo: contexto, catalogo, alertas, notificacao, PDOH ----

    def test_um_problema_por_regra_colaborador_e_campo_repeticao_e_so_contador(self):
        self.rule('CAMPO_OBRIGATORIO_VAZIO', 'OPORTUNIDADE')
        for execucao in ('r1', 'r2', 'r3'):
            self.db.insert('execucao', execution_id=execucao, marca='BRACELL', status_execucao='CONCLUIDA',
                periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5))
            for dia in range(1, 6):   # mesmo problema em 5 dias, regravado por 3 execucoes
                self.ocorrencia(f'ent-{execucao}-{dia}', execution_id=execucao,
                    tipo_problema='CAMPO_OBRIGATORIO_VAZIO', fingerprint=f'fp-entrada-{dia}',
                    data_referencia=date(2026, 9, dia), evidencia={'campo': 'hora_entrada'})
        # Mesmo colaborador e mesma regra, OUTRO campo: e' outro problema.
        self.ocorrencia('saida', tipo_problema='CAMPO_OBRIGATORIO_VAZIO', fingerprint='fp-saida',
                        evidencia={'campo': 'hora_saida'})
        pagina = self.grupos()
        self.assertEqual(2, pagina['total'])
        entrada = next(g for g in pagina['items'] if g['campo'] == 'hora_entrada')
        self.assertEqual(5, entrada['quantidade'])               # 15 regravacoes -> 5 ocorrencias
        self.assertEqual(15, entrada['registros_historicos'])
        self.assertEqual(('2026-09-01', '2026-09-05'), (entrada['primeira_ocorrencia'], entrada['ultima_ocorrencia']))
        self.assertEqual('relatorio_checkin_bracell', entrada['origem'])
        saida = next(g for g in pagina['items'] if g['campo'] == 'hora_saida')
        self.assertNotEqual(entrada['grupo_id'], saida['grupo_id'])
        detalhe = self.page(f"oportunidades/{entrada['grupo_id']}/detalhes")
        self.assertEqual(5, detalhe['ocorrencias']['total'])     # o outro campo nao vaza
        self.assertTrue(all(o['repeticoes'] == 3 for o in detalhe['ocorrencias']['items']))

    def test_titulo_impacto_e_acao_vem_do_catalogo_sem_invencao(self):
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE', titulo='CHECKOUT_AUSENTE',
                  titulo_exibicao='Checkout não registrado', impacto_negocio='Tempo em loja',
                  acao_recomendada='Validar ausência de checkout e orientar registro correto.')
        self.rule('SEM_TEXTO', 'OPORTUNIDADE', identifier='sem-texto', tratamento_esperado='Tratativa tecnica',
                  impacto_negocio=None, acao_recomendada=None)
        self.ocorrencia('com')
        self.ocorrencia('sem', tipo_problema='SEM_TEXTO', fingerprint='fp-sem', colaborador='Maria')
        cards = {g['tipo_problema']: g for g in self.grupos()['items']}
        self.assertEqual('Checkout não registrado', cards['CHECKOUT_AUSENTE']['titulo'])
        self.assertEqual('Tempo em loja', cards['CHECKOUT_AUSENTE']['impacto'])
        self.assertEqual('Validar ausência de checkout e orientar registro correto.',
                         cards['CHECKOUT_AUSENTE']['acao_recomendada'])
        self.assertNotIn('SEM_TEXTO', cards)  # Sem impacto e acao nao pode entrar na fila do lider.
        self.assertEqual('SEM_TEXTO', self.page('alertas/resumo')['items'][0]['tipo_problema'])

    def test_textos_de_excecao_acompanham_a_classificacao_da_origem(self):
        """Mesmo tipo: jornada no check-in (oportunidade), cadastro em pesquisas (alerta)."""
        self.rule('CAMPO_OBRIGATORIO_VAZIO', 'OPORTUNIDADE', titulo_exibicao='Campo obrigatório não preenchido',
                  impacto_negocio='Jornada', acao_recomendada='Orientar o colaborador.',
                  origem_excecao='painel_pesquisas_bracell', classificacao_excecao='ALERTA',
                  impacto_negocio_excecao='Qualidade cadastral',
                  acao_recomendada_excecao='Completar o campo obrigatório da pesquisa.')
        self.ocorrencia('chk', tipo_problema='CAMPO_OBRIGATORIO_VAZIO', fingerprint='fp-chk',
                        evidencia={'campo': 'hora_entrada'})
        self.ocorrencia('pesq', tipo_problema='CAMPO_OBRIGATORIO_VAZIO', fingerprint='fp-pesq', colaborador=None,
                        tabela_origem='painel_pesquisas_bracell', evidencia={'campo': 'responsavel'})
        self.assertEqual([('Jornada', 'Orientar o colaborador.')],
                         [(g['impacto'], g['acao_recomendada']) for g in self.grupos()['items']])
        self.assertEqual([('Qualidade cadastral', 'Completar o campo obrigatório da pesquisa.')],
                         [(g['impacto'], g['acao_recomendada']) for g in self.page('alertas/resumo')['items']])

    def test_pesquisas_sem_responsavel_e_telemetria_e_nao_herda_acao_operacional(self):
        from api.app.findings_repository import _textos_de_negocio
        self.rule('CAMPO_OBRIGATORIO_VAZIO', 'OPORTUNIDADE', impacto_negocio='Jornada',
                  acao_recomendada='Orientar o colaborador.', origem_excecao='painel_pesquisas_bracell',
                  classificacao_excecao='TELEMETRIA', impacto_negocio_excecao='Sem impacto operacional',
                  acao_recomendada_excecao=None)
        self.ocorrencia('chk', tipo_problema='CAMPO_OBRIGATORIO_VAZIO', fingerprint='fp-chk',
                        evidencia={'campo': 'hora_entrada'})
        self.ocorrencia('pesq', tipo_problema='CAMPO_OBRIGATORIO_VAZIO', fingerprint='fp-pesq', colaborador=None,
                        tabela_origem='painel_pesquisas_bracell', evidencia={'campo': 'responsavel'})
        self.assertEqual(['hora_entrada'], [g['campo'] for g in self.grupos()['items']])  # so check-in na fila
        self.assertEqual(0, self.page('alertas/resumo')['total'])                        # nao e' alerta
        self.assertEqual(['pesq'], [t['id'] for t in self.page('telemetria')['items']])  # e' telemetria
        regra = dict(impacto_negocio='Jornada', acao_recomendada='Orientar o colaborador.',
                     origem_excecao='painel_pesquisas_bracell', impacto_negocio_excecao='Sem impacto operacional',
                     acao_recomendada_excecao=None)
        textos = _textos_de_negocio(regra, 'CAMPO_OBRIGATORIO_VAZIO', 'painel_pesquisas_bracell')
        self.assertEqual(('Sem impacto operacional', None), (textos['impacto'], textos['acao_recomendada']))

    def test_configuracao_sai_da_fila_sem_notificar_e_segue_registrada(self):
        """Cadastro da marca/periodo nao e' problema de pessoa: governanca, nao fila."""
        self.notificacoes()
        self.rule('SEM_LIDERES_NO_PERIODO', 'CONFIGURACAO', severidade_padrao='ALTA')
        self.db.insert('oportunidade', oportunidade_id='legado-config', execution_id='new-run',
            marca='BRACELL', tipo_problema='SEM_LIDERES_NO_PERIODO', regra_id=None, colaborador=None,
            tabela_origem='colaboradores_ativos_bracell', fingerprint='fp-config')
        for endpoint in ('oportunidades/resumo', 'alertas/resumo', 'telemetria', 'oportunidades'):
            self.assertEqual(0, self.page(endpoint)['total'], endpoint)

        self.assertEqual(1, self.dispatch(self.finding('SEM_LIDERES_NO_PERIODO', severidade='ALTA')))
        self.assertEqual(0, self.count('oportunidade') - 1)      # so a linha legada inserida acima
        self.assertEqual(0, self.count('notificacao_outbox'))    # nunca notifica
        with self.db.connection() as c:
            categoria = c.execute(text("SELECT categoria FROM execucao_evento "
                                       "WHERE codigo='SEM_LIDERES_NO_PERIODO'")).scalar_one()
        self.assertEqual('CONFIGURACAO', categoria)              # preservada para governanca
        self.assertEqual(0, self.page('telemetria')['total'])    # e nao polui telemetria

    def test_resumo_de_alertas_consolida_problemas_e_categorias_cobrem_todos_os_grupos(self):
        self.rule('CADASTRO_UF_AUSENTE', 'ALERTA', titulo_exibicao='UF não preenchida')
        self.rule('DADO_FORA_DO_PADRAO', 'ALERTA', identifier='fora')
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE', identifier='chk')
        uf = lambda n: {'versao_regra': 1, 'campo': 'UF', 'quantidade_ocorrencias': n}
        for execucao in ('r1', 'r2'):   # o mesmo alerta regravado em duas execucoes
            self.db.insert('execucao', execution_id=execucao, marca='BRACELL', status_execucao='CONCLUIDA',
                periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5))
            self.ocorrencia(f'uf-joao-{execucao}', execution_id=execucao, tipo_problema='CADASTRO_UF_AUSENTE',
                            fingerprint='fp-uf-joao', tabela_origem='colaboradores_ativos_bracell', evidencia=uf(10))
        self.ocorrencia('uf-maria', tipo_problema='CADASTRO_UF_AUSENTE', fingerprint='fp-uf-maria',
                        colaborador='Maria', tabela_origem='colaboradores_ativos_bracell', evidencia=uf(2))
        for campo in ('estado', 'cidade'):
            self.ocorrencia(f'fora-{campo}', tipo_problema='DADO_FORA_DO_PADRAO', fingerprint=f'fp-{campo}',
                            tabela_origem='colaboradores_ativos_bracell', evidencia={'campo': campo})
        self.ocorrencia('op', fingerprint='fp-op')   # oportunidade nunca entra em alertas

        pagina = self.page('alertas/resumo', tamanho=1)
        self.assertEqual(4, pagina['total'])                     # 6 linhas historicas -> 4 problemas
        self.assertEqual(1, len(pagina['items']))
        resumo = pagina['resumo']
        self.assertEqual(4, resumo['grupos'])                    # resumo cobre todos, nao so a pagina
        self.assertEqual(4, resumo['alertas'])
        self.assertEqual(10 + 2 + 1 + 1, resumo['ocorrencias_acumuladas'])
        self.assertEqual(2, resumo['colaboradores_afetados'])
        categorias = {c['tipo_problema']: c for c in resumo['por_regra']}
        self.assertEqual(2, categorias['CADASTRO_UF_AUSENTE']['colaboradores_afetados'])
        self.assertEqual(12, categorias['CADASTRO_UF_AUSENTE']['ocorrencias_acumuladas'])
        self.assertEqual('UF não preenchida', categorias['CADASTRO_UF_AUSENTE']['titulo'])
        self.assertEqual(2, categorias['DADO_FORA_DO_PADRAO']['grupos'])  # estado e cidade separados
        self.assertNotIn('CHECKOUT_AUSENTE', categorias)
        joao = self.page('alertas/resumo', colaborador='joao')['items']
        self.assertEqual([1], [g['quantidade_alertas'] for g in joao if g['tipo_problema'] == 'CADASTRO_UF_AUSENTE'])

    def notificacoes(self):
        with self.db.engine.begin() as c:
            c.execute(text('CREATE TABLE IF NOT EXISTS notificacao_outbox (notificacao_id TEXT PRIMARY KEY, '
                           'execution_id TEXT, oportunidade_id TEXT, tipo_notificacao TEXT, prioridade INTEGER, '
                           'status_notificacao TEXT, dedupe_key TEXT UNIQUE, payload TEXT)'))

    def test_problema_aberto_gera_uma_unica_notificacao_mesmo_repetindo(self):
        self.notificacoes()
        self.rule('CHECKOUT_AUSENTE', 'OPORTUNIDADE', severidade_padrao='ALTA')
        item = lambda dia, campo='hora_saida': self.finding(
            severidade='ALTA', colaborador='Joao Silva', tabela_origem='relatorio_checkin_bracell',
            data_referencia=f'2026-09-0{dia}', evidencia={'campo_esperado': campo})
        # A comprovacao viaja na evidencia; ela nao altera a chave do problema operacional.
        self.assertEqual(3, self.dispatch([item(1), item(2), item(3)]))   # 3 dias do mesmo problema
        self.db.insert('execucao', execution_id='run-2', marca='BRACELL', status_execucao='INICIADA',
            periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5))
        with patch.dict(os.environ, {'PDOH_EXECUTION_ID': 'run-2'}):
            self.assertEqual(2, self.dispatch([item(4), item(1)]))          # reprocessamento + novo dia
        self.assertEqual(5, self.count('oportunidade'))                     # historico preserva os eventos
        self.assertEqual(1, self.count('notificacao_outbox'))               # um problema -> uma notificacao
        self.dispatch(item(5, campo='hora_entrada'))                        # outro campo = outro problema
        self.assertEqual(2, self.count('notificacao_outbox'))

        # A notificacao aponta para o mesmo card da fila.
        with self.db.connection() as c:
            payloads = [json.loads(row[0]) for row in c.execute(text('SELECT payload FROM notificacao_outbox'))]
        cards = {g['grupo_id'] for g in self.grupos()['items']}
        self.assertEqual(cards, {p['grupo_id'] for p in payloads})

    def test_chave_de_grupo_identica_entre_pipeline_e_api(self):
        from api.app.findings_repository import campo_do_registro, codificar_grupo
        for evidencia in ({'campo': 'hora_entrada'}, {'campo_esperado': ['b', 'a']}, None, 'nao-json', {},
                          {'campo_inicio': 'hora_entrada', 'campo_fim': 'hora_saida'}, {'coluna': 'uf'}):
            self.assertEqual('+'.join(campos_da_evidencia(evidencia)), campo_do_registro(evidencia))
            self.assertEqual(
                grupo_operacional('BRACELL', 'T', 'id-1', 'Nome', 'origem', evidencia),
                codificar_grupo('BRACELL', 'T', 'id-1', 'Nome', 'origem', campo_do_registro(evidencia)))

    def test_pdoh_sem_fonte_oficial_nunca_devolve_numero(self):
        semana = self.page('pdoh/resumo')
        self.assertFalse(semana['disponivel'])
        self.assertIsNone(semana['percentual'])
        self.assertIsNone(semana['pdoh'])
        self.assertIn('informe a marca', semana['motivo'])
        sem_fonte = self.page('pdoh/resumo', marca='FLORA')
        self.assertEqual('Não há fonte oficial do PDOH acessível para esta marca.', sem_fonte['motivo'])
        self.assertFalse(sem_fonte['cobertura']['acessivel'])

    def test_grants_aceitam_somente_a_tabela_oficial_do_pdoh(self):
        from api.app.database import validate_grants
        validate_grants(["GRANT USAGE ON *.* TO `r`@`%`", "GRANT SELECT ON `pdoh_controle`.* TO `r`@`%`",
                         "GRANT SELECT ON `produtos_platina`.`exclusivo_bracell_platina_relatorio_pdoh` TO `r`@`%`"])
        for proibido in ("GRANT SELECT ON `produtos_platina`.* TO `r`@`%`",
                         "GRANT SELECT ON `produtos_platina`.`outra_tabela` TO `r`@`%`",
                         "GRANT SELECT, INSERT ON `produtos_platina`.`exclusivo_bracell_platina_relatorio_pdoh` TO `r`@`%`",
                         "GRANT SELECT ON `produtos_platina`.`exclusivo_bracell_platina_relatorio_pdoh` TO `r`@`%` WITH GRANT OPTION"):
            with self.assertRaises(RuntimeError):
                validate_grants(["GRANT SELECT ON `pdoh_controle`.* TO `r`@`%`", proibido])


if __name__ == '__main__':
    unittest.main()
