from contextlib import contextmanager
from datetime import date, datetime
from typing import get_args
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Column, Date, DateTime, Integer, JSON, MetaData, String, Table, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from api.app.config import Settings
from api.app.database import TABLE_MODELS, validate_grants
from api.app.main import create_app


# Tabelas cuja identidade e' composta no MySQL. Sem isso o fixture marcaria so a
# primeira coluna como PK e recusaria linhas legitimas (duas fontes da mesma marca).
CHAVES_COMPOSTAS = {
    'configuracao_operacao': ('marca', 'operacao'),
    'configuracao_evidencia': ('marca', 'operacao', 'papel'),
    'configuracao_evidencia_regra': ('marca', 'operacao', 'tipo_problema'),
}


class FixtureDatabase:
    """Somente SQLite em memoria; nenhum acesso a Docker/MySQL nestes testes."""
    def __init__(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.metadata = MetaData()
        types = {str: String, int: Integer, bool: Boolean, date: Date, datetime: DateTime}
        self.tables = {}
        for name, model in TABLE_MODELS.items():
            columns = []
            chave = CHAVES_COMPOSTAS.get(name)
            for key, field in model.model_fields.items():
                annotation = get_args(field.annotation)[0] if get_args(field.annotation) else field.annotation
                options = {}
                if key in {'registrado_em', 'identificada_em', 'atualizada_em', 'ocorrido_em'}:
                    options['server_default'] = text('CURRENT_TIMESTAMP')
                principal = key in chave if chave else not columns
                columns.append(Column(key, types.get(annotation, JSON), primary_key=principal, **options))
            self.tables[name] = Table(name, self.metadata, *columns)
        self.metadata.create_all(self.engine)

    def insert(self, name, **overrides):
        defaults = {str: "referencia", int: 0, bool: False, date: date(2026, 9, 1), datetime: datetime(2026, 9, 15, 10)}
        data = {}
        for key, field in TABLE_MODELS[name].model_fields.items():
            args = get_args(field.annotation)
            data[key] = None if type(None) in args else defaults.get(field.annotation)
            if key == 'operacao':
                data[key] = 'EXCLUSIVA'
        data.update(overrides)
        with self.engine.begin() as conn:
            conn.execute(self.tables[name].insert(), data)

    def ativar_regra(self, tipo, marca='BRACELL', operacao='EXCLUSIVA', *, status='ATIVA',
                     geracao_automatica=True, gera=True):
        """Cadastra a regra configuravel que autoriza `tipo` a aparecer como oportunidade.

        Sem ela a fila nao mostra o tipo (regra inexistente). Os parametros permitem montar
        os demais estados: `status='INATIVA'`, `geracao_automatica=False` ou `gera=False`.
        """
        identificador = f'cfg:{marca}:{operacao}:{tipo}'
        self.insert('regra_configuracao', configuracao_id=identificador, marca=marca, operacao=operacao,
                    nome_regra=tipo, codigo_interno=tipo, categoria='Jornada', status=status,
                    prioridade=1, tempo_minimo_minutos=0, descricao='Regra de teste',
                    comportamento_esperado='Regra de teste', regra_catalogo_id=None,
                    geracao_automatica_ativa=geracao_automatica, usuario_alteracao='teste')
        self.insert('regra_tratamento_configuracao', tratamento_id='trt:' + identificador,
                    configuracao_id=identificador, resultado='CONFIRMADO', acao_recomendada='Agir',
                    destino='OPORTUNIDADE', gera_oportunidade=gera, status='ATIVO',
                    usuario_alteracao='teste')

    def initialize(self):
        pass

    def close(self):
        self.engine.dispose()

    @contextmanager
    def connection(self):
        with self.engine.begin() as conn:
            yield conn


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        self.db.insert("execucao", execution_id="e1", marca="BRACELL", periodo_inicio=date(2026, 8, 31), periodo_fim=date(2026, 9, 5), status_execucao="CONCLUIDA_COM_ALERTAS")
        self.db.insert("execucao", execution_id="e2", marca="OUTRA", periodo_inicio=date(2026, 9, 7), periodo_fim=date(2026, 9, 12), status_execucao="FALHA_TECNICA")
        self.db.insert("execucao", execution_id="e3", marca="BRACELL", status_execucao="INICIADA")
        self.db.insert("regra_tratativa", regra_id="r1", tipo_problema="TIPO", status_regra="ATIVA", prioridade=10)
        self.db.insert("regra_tratativa", regra_id="r2", marca="BRACELL", tipo_problema="OUTRO", status_regra="INATIVA", prioridade=20)
        self.db.insert("oportunidade", oportunidade_id="o1", execution_id="e1", marca="BRACELL", regra_id="r1", tipo_problema="TIPO", status_oportunidade="ABERTA", evidencia={"campo_origem": "jornada_trabalho", "valor_origem": "CX"})
        self.db.insert("oportunidade", oportunidade_id="o2", execution_id="e1", marca="BRACELL", tipo_problema="OUTRO", status_oportunidade="RESOLVIDA")
        self.db.insert("oportunidade", oportunidade_id="o3", execution_id="e2", marca="OUTRA", tipo_problema="TIPO", status_oportunidade="ABERTA")
        self.db.insert("oportunidade_historico", id=1, oportunidade_id="o1", execution_id="e1", status_novo="ABERTA", acao="IDENTIFICADA")
        self.db.insert("oportunidade_historico", id=2, oportunidade_id="o1", execution_id="e1", status_novo="ABERTA", acao="REVISAO", responsavel="Revisor teste")
        self.db.insert("de_para", de_para_id="d1", processo="JORNADA", status="ATIVO")
        self.db.insert("de_para_historico", id=1, de_para_id="d1", acao="CRIADO", status_novo="ATIVO")
        self.db.insert("execucao_etapa", id=1, execution_id="e1", contexto={"ok": True})
        self.db.insert("execucao_fonte", id=1, execution_id="e1")
        self.db.insert("saida_linhagem", id=1, execution_id="e1")
        self.db.insert("colaborador_identidade", colaborador_id_interno="c1", marca="BRACELL")
        self.db.insert("identificador_entidade", identificador_id="p1", identificador_interno="pdv1", marca="BRACELL", tipo_entidade="PDV", status="ATIVO")
        self.settings = Settings(token="t" * 40)
        self.client = TestClient(create_app(self.settings, self.db))
        self.client.__enter__()
        self.client.headers["Authorization"] = "Bearer " + self.settings.token

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def get(self, path, **params):
        r = self.client.get("/api/v1" + path, params=params)
        self.assertEqual(200, r.status_code, r.text)
        return r.json()

    def test_dashboard_counts_do_not_multiply_execution_join(self):
        result = self.get("/dashboard")
        self.assertEqual(3, result["total_execucoes"])
        self.assertEqual(3, result["quantidade_oportunidades"])
        result = self.get("/dashboard", marca="BRACELL", status="CONCLUIDA_COM_ALERTAS")
        self.assertEqual(1, result["total_execucoes"])
        self.assertEqual(2, result["quantidade_oportunidades"])

    def test_dashboard_periods_paginate_without_changing_totals(self):
        first = self.get("/dashboard", tamanho=1)
        second = self.get("/dashboard", tamanho=1, pagina=2)
        self.assertEqual(3, first["marcas_periodos"]["total"])
        self.assertNotEqual(first["marcas_periodos"]["items"], second["marcas_periodos"]["items"])
        self.assertEqual(first["total_execucoes"], second["total_execucoes"])

    def test_period_overlap_inclusive_and_null_period_excluded(self):
        result = self.get("/execucoes", periodo_inicio="2026-09-05", periodo_fim="2026-09-07")
        self.assertEqual({"e1", "e2"}, {x["execution_id"] for x in result["items"]})
        self.assertEqual(1, self.get("/execucoes", periodo_fim="2026-09-05")["total"])

    def test_combined_filters_and_database_status(self):
        result = self.get("/oportunidades", marca="BRACELL", tipo="TIPO", status="ABERTA", regra="r1", periodo_inicio="2026-09-01", periodo_fim="2026-09-02")
        self.assertEqual(["o1"], [x["oportunidade_id"] for x in result["items"]])
        self.assertEqual(1, self.get("/execucoes", status="INICIADA")["total"])

    def test_stable_pagination_and_empty_page(self):
        first = self.get("/oportunidades", tamanho=1)
        second = self.get("/oportunidades", tamanho=1, pagina=2)
        self.assertEqual(3, first["total"])
        self.assertNotEqual(first["items"], second["items"])
        self.assertEqual([], self.get("/oportunidades", pagina=10)["items"])

    def test_detail_preserves_missing_links_and_current_rule(self):
        detail = self.get("/oportunidades/o1")
        self.assertEqual("e1", detail["execucao"]["execution_id"])
        self.assertEqual("r1", detail["regra_atual"]["regra_id"])
        self.assertEqual("Revisor teste", detail["ultima_tratativa"]["responsavel"])
        self.assertIsNone(detail["identidade_colaborador"])
        self.assertIsNone(self.get("/oportunidades/o2")["regra_atual"])
        self.assertEqual("CX", detail["evidencia"]["valor_origem"])

    def test_history_order_empty_and_missing_parent(self):
        self.assertEqual([1, 2], [x["id"] for x in self.get("/oportunidades/o1/historico")["items"]])
        self.assertEqual(0, self.get("/oportunidades/o2/historico")["total"])
        self.assertEqual(404, self.client.get("/api/v1/oportunidades/missing/historico").status_code)
        self.assertEqual(1, self.get("/de-para/d1/historico")["total"])

    def test_catalog_global_rules_and_filters(self):
        self.assertEqual(2, self.get("/regras", marca="BRACELL")["total"])
        self.assertEqual(1, self.get("/regras", marca="BRACELL", incluir_globais="false")["total"])
        self.assertEqual(1, self.get("/regras", status="ATIVA", tipo="TIPO")["total"])
        self.assertEqual(0, self.get("/de-para", processo="PERFIL")["total"])
        self.assertEqual(1, self.get("/de-para", processo="JORNADA", status="ATIVO")["total"])

    def test_trace_routes(self):
        self.assertEqual(1, self.get("/execucoes/e1")["quantidade_saidas"])
        for suffix in ("etapas", "fontes", "linhagem"):
            self.assertEqual(1, self.get("/execucoes/e1/" + suffix)["total"])
        self.assertEqual("c1", self.get("/colaboradores/c1")["colaborador_id_interno"])
        self.assertEqual(1, self.get("/entidades", tipo_entidade="PDV")["total"])
        self.assertEqual("pdv1", self.get("/entidades/p1")["identificador_interno"])

    def test_invalid_queries_are_rejected(self):
        for params in ({"pagina": 0}, {"tamanho": 201}, {"periodo_inicio": "ontem"}, {"periodo_inicio": "2026-09-12", "periodo_fim": "2026-09-01"}, {"sttaus": "ABERTA"}):
            self.assertEqual(422, self.client.get("/api/v1/oportunidades", params=params).status_code)

    def test_sql_injection_is_a_literal_value(self):
        self.assertEqual(0, self.get("/oportunidades", marca="' OR 1=1 --")["total"])
        self.assertEqual(0, self.get("/regras", tipo="'; DROP TABLE execucao; --")["total"])
        self.assertEqual(3, self.get("/execucoes")["total"])

    def test_authentication_mutations_and_cache(self):
        self.assertEqual("no-store", self.client.get("/api/v1/dashboard").headers["Cache-Control"])
        for method in ("post", "put", "patch", "delete"):
            self.assertEqual(405, getattr(self.client, method)("/api/v1/oportunidades").status_code)
        self.client.headers.pop("Authorization")
        self.assertEqual(401, self.client.get("/api/v1/dashboard").status_code)
        self.assertEqual(401, self.client.get("/api/v1/dashboard", headers={"Authorization": "Bearer invalido"}).status_code)

    def test_database_failure_is_not_exposed(self):
        with patch.object(self.db, "connection", side_effect=OperationalError("secret sql", {}, Exception("secret password"))):
            result = self.client.get("/api/v1/dashboard")
            self.assertEqual(503, result.status_code)
            self.assertNotIn("secret", result.text)

    def test_openapi_has_typed_responses_and_only_the_documented_writes(self):
        """Consulta = GET. Excecoes conhecidas: a simulacao (POST, nao grava) e a criacao/edicao
        auditada de regras (POST/PATCH, conta propria de minimo privilegio). Qualquer outra
        escrita quebra aqui."""
        schema = self.client.get("/openapi.json").json()
        self.assertIn("OpportunityDetail", schema["components"]["schemas"])
        for path, operations in schema["paths"].items():
            if path in {"/api/fallback/simular", "/api/v1/fallback/simular"}:
                expected = {"post"}
            elif path == "/api/v2/configuracoes/regras":
                expected = {"post"}
            elif path == "/api/v2/configuracoes/regras/{codigo}":
                expected = {"patch"}
            else:
                expected = {"get"}
            self.assertEqual(expected, set(operations), path)

    def test_grants_reject_writer_role_and_grant_option(self):
        validate_grants(["GRANT USAGE ON *.* TO 'reader'@'%'", "GRANT SELECT ON `pdoh_controle`.* TO 'reader'@'%'"])
        for grant in ("GRANT SELECT, INSERT ON `pdoh_controle`.* TO 'writer'@'%'", "GRANT `role`@`%` TO `reader`@`%`", "GRANT USAGE ON *.* TO 'reader'@'%' WITH GRANT OPTION", "GRANT SELECT ON `pdoh_controle`.* TO 'reader'@'%' WITH GRANT OPTION", "GRANT SELECT ON *.* TO 'reader'@'%'"):
            with self.assertRaises(RuntimeError):
                validate_grants([grant])


if __name__ == "__main__":
    unittest.main()
