"""Dados sinteticos em SQLite em memoria; API deve emitir apenas SELECT."""
from datetime import date, datetime
import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import event, select

from api.app.config import Settings
from api.app.main import create_app
from api.tests.test_api import FixtureDatabase


class FallbackTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        self.db.insert("execucao", execution_id="exec-real", marca="BRACELL", componente_atual="ORQUESTRADOR",
                       periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5),
                       status_execucao="CONCLUIDA_COM_ALERTAS", iniciado_em=datetime(2026, 9, 6))
        self.observation("o1", "Ana", "2026-09-01", ["1", "2"], 2)
        self.observation("o2", "Ana", "2026-09-02", ["3"], 1)
        self.observation("o3", "Bia", "2026-09-02", ["4", "5"], 2)
        self.client = TestClient(create_app(Settings(token="x" * 40), self.db))
        self.client.__enter__()
        self.client.headers["Authorization"] = "Bearer " + "x" * 40

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def observation(self, identifier, person, day, refs, count, **overrides):
        data = dict(oportunidade_id=identifier, execution_id="exec-real", marca="BRACELL", colaborador=person,
            data_referencia=date.fromisoformat(day), tabela_origem="relatorio_checkin_bracell",
            tipo_problema="CHECKOUT_AUSENTE", evidencia={"campo_esperado": "hora_saida", "fallback_usado": True,
            "fallback_valor": "23:59:00", "ocorrencias": count, "registro_afetado": refs})
        data.update(overrides)
        self.db.insert("oportunidade", **data)

    def config(self, identifier="brand", **overrides):
        data = dict(id=identifier, marca="BRACELL", regra="CHECKOUT_AUSENTE", escopo="MARCA", chave="*",
                    valor_fallback="19:00", vigencia_inicio=date(2026, 9, 1), vigencia_fim=None,
                    status="ATIVO", usuario_alteracao="test")
        data.update(overrides)
        self.db.insert("regra_fallback_config", **data)

    def resolve(self, **params):
        return self.client.get("/api/v1/fallback/resolver", params={"marca": "BRACELL", "data_referencia": "2026-09-17", **params})

    def simulate(self, **params):
        return self.client.post("/api/fallback/simular", json={"regra": "CHECKOUT_AUSENTE", "marca": "BRACELL", "novo_valor": "18:00", **params})

    def snapshot(self):
        with self.db.connection() as c:
            return {name: sorted(json.dumps(dict(r), sort_keys=True, default=str) for r in c.execute(select(table)).mappings())
                    for name, table in self.db.tables.items()}

    def test_default_without_configuration(self):
        result = self.resolve()
        self.assertEqual(200, result.status_code)
        self.assertEqual(("DEFAULT", "23:59", False), tuple(result.json()[k] for k in ("origem", "valor", "aplicado_no_processador")))

    def test_leader_priority_and_brand_fallback(self):
        self.config()
        self.config("leader", escopo="LIDER", chave="lider-1", valor_fallback="18:00")
        self.assertEqual("18:00", self.resolve(lider_id="lider-1").json()["valor"])
        self.assertEqual("LIDER", self.resolve(lider_id="lider-1").json()["origem"])
        self.assertEqual("19:00", self.resolve(lider_id="lider-2").json()["valor"])
        self.assertEqual("MARCA", self.resolve().json()["origem"])
        self.assertEqual("23:59", self.resolve(marca="OUTRA", lider_id="lider-1").json()["valor"])

    def test_expiry_future_inactive_and_inclusive_boundaries(self):
        self.config()
        self.config("leader", escopo="LIDER", chave="l1", valor_fallback="18:00", vigencia_fim=date(2026, 9, 16))
        self.assertEqual("19:00", self.resolve(lider_id="l1").json()["valor"])
        for day in ("2026-09-01", "2026-09-16"):
            self.assertEqual("18:00", self.resolve(lider_id="l1", data_referencia=day).json()["valor"])
        self.assertEqual("23:59", self.resolve(data_referencia="2026-08-31").json()["valor"])
        self.config("inactive", escopo="LIDER", chave="l2", status="INATIVO")
        self.assertEqual("MARCA", self.resolve(lider_id="l2").json()["origem"])

    def test_expired_brand_returns_default(self):
        self.config(vigencia_fim=date(2026, 9, 16))
        self.assertEqual("DEFAULT", self.resolve().json()["origem"])

    def test_ambiguous_configuration_is_conflict_not_random(self):
        self.config()
        self.config("overlap", vigencia_inicio=date(2026, 9, 10))
        self.assertEqual(409, self.resolve().status_code)

    def test_simulation_counts_occurrences_not_opportunity_rows_and_no_writes(self):
        before = self.snapshot()
        statements = []
        def guard(_c, _cu, statement, _p, _ctx, _many):
            statements.append(statement)
            self.assertTrue(statement.lstrip().upper().startswith("SELECT"), statement)
        event.listen(self.db.engine, "before_cursor_execute", guard)
        try:
            response = self.simulate()
        finally:
            event.remove(self.db.engine, "before_cursor_execute", guard)
        self.assertEqual(200, response.status_code, response.text)
        result = response.json()
        self.assertEqual((5, 2, 3), (result["registros_afetados"], result["colaboradores_afetados"], result["grupos_observados"]))
        self.assertEqual(("2026-09-01", "2026-09-05"), (result["periodo_inicio"], result["periodo_fim"]))
        self.assertFalse(result["dados_alterados"])
        self.assertFalse(result["pdoh_recalculado"])
        self.assertTrue(statements)
        self.assertEqual(before, self.snapshot())

    def test_configuration_never_changes_effective_processor_value(self):
        self.config(valor_fallback="17:00")
        result = self.simulate().json()
        self.assertEqual("23:59", result["fallback_atual"])
        self.assertEqual("17:00", result["configuracao_marca"]["valor"])

    def test_same_value_has_zero_changed_records(self):
        result = self.simulate(novo_valor="23:59").json()
        self.assertEqual((5, 0, 0), (result["registros_identificados"], result["registros_afetados"], result["colaboradores_afetados"]))

    def test_period_filter_and_no_evidence_not_zero(self):
        result = self.simulate(periodo_inicio="2026-09-02", periodo_fim="2026-09-02")
        self.assertEqual(3, result.json()["registros_afetados"])
        self.assertEqual(409, self.simulate(periodo_inicio="2026-09-03").status_code)
        self.assertEqual(404, self.simulate(marca="OUTRA").status_code)
        self.assertEqual(404, self.simulate(execution_id="missing").status_code)

    def test_duplicate_evidence_is_not_double_counted(self):
        self.observation("duplicate", "Ana", "2026-09-01", ["2", "1"], 2)
        result = self.simulate().json()
        self.assertEqual(5, result["registros_afetados"])
        self.assertEqual(1, result["evidencias_duplicadas_desconsideradas"])

    def test_ambiguous_groups_and_bad_evidence_are_rejected(self):
        self.observation("ambiguous", "Ana", "2026-09-01", ["6"], 1)
        self.assertEqual(409, self.simulate().status_code)

    def test_null_date_missing_count_and_wrong_fallback_are_rejected(self):
        for override in ({"data_referencia": None}, {"evidencia": {}}, {"evidencia": {"fallback_valor": "18:00"}}):
            with self.subTest(override=override):
                self.observation("bad", "Cris", "2026-09-03", ["6"], 1, **override)
                self.assertEqual(409, self.simulate().status_code)
                with self.db.engine.begin() as c:
                    c.execute(self.db.tables["oportunidade"].delete().where(self.db.tables["oportunidade"].c.oportunidade_id == "bad"))

    def test_sampled_indices_use_explicit_count(self):
        self.observation("sampled", "Cris", "2026-09-03", list(map(str, range(10, 30))), 50)
        result = self.simulate().json()
        self.assertEqual(55, result["registros_afetados"])
        self.assertTrue(any("amostrais" in x for x in result["avisos"]))

    def test_newer_run_without_evidence_is_not_reported_as_zero(self):
        self.db.insert("execucao", execution_id="new-empty", marca="BRACELL", componente_atual="ORQUESTRADOR",
            periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5), status_execucao="CONCLUIDA",
            iniciado_em=datetime(2026, 9, 9))
        self.assertEqual("exec-real", self.simulate().json()["execution_id"])
        self.assertEqual(409, self.simulate(execution_id="new-empty").status_code)

    def test_reused_source_index_across_people_is_ambiguous(self):
        self.observation("overlap", "Cris", "2026-09-03", ["1"], 1)
        self.assertEqual(409, self.simulate().status_code)

    def test_null_collaborator_is_not_a_fictitious_person(self):
        self.observation("anonymous", None, "2026-09-03", ["6"], 1)
        result = self.simulate().json()
        self.assertEqual(6, result["registros_afetados"])
        self.assertEqual(2, result["colaboradores_afetados"])
        self.assertEqual(1, result["grupos_sem_colaborador"])

    def test_truncation_is_disclosed(self):
        self.db.insert("execucao_evento", id=1, execution_id="exec-real", codigo="VOLUME_OPORTUNIDADES_TRUNCADO")
        self.assertTrue(any("truncamento" in x for x in self.simulate().json()["avisos"]))

    def test_homonyms_with_different_ids_are_not_merged(self):
        self.observation("h1", "Homonomo", "2026-09-03", ["6"], 1, colaborador_id_interno="id1")
        self.observation("h2", "Homonomo", "2026-09-04", ["7"], 1, colaborador_id_interno="id2")
        self.assertEqual(409, self.simulate().status_code)

    def test_sql_injection_is_only_a_brand_literal(self):
        self.assertEqual(404, self.simulate(marca="' OR 1=1 --").status_code)
        self.assertEqual(5, self.simulate().json()["registros_afetados"])

    def test_simulation_excludes_synthetic_and_repeated_executions(self):
        for identifier in ("exec-old", "BRACELL_VALIDACAO_TEST"):
            self.db.insert("execucao", execution_id=identifier, marca="BRACELL", componente_atual="ORQUESTRADOR",
                periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5), status_execucao="CONCLUIDA",
                iniciado_em=datetime(2026, 9, 1) if identifier == "exec-old" else datetime(2026, 9, 9))
            self.observation(identifier, "Outra pessoa", "2026-09-01", ["999"], 500, execution_id=identifier)
        self.assertEqual("exec-real", self.simulate().json()["execution_id"])
        self.assertEqual(5, self.simulate().json()["registros_afetados"])
        self.assertEqual(404, self.simulate(execution_id="BRACELL_VALIDACAO_TEST").status_code)

    def test_validation_auth_alias_and_cors(self):
        for params in ({"novo_valor": "24:00"}, {"novo_valor": "8:00"}, {"novo_valor": "18:00:00"},
                       {"regra": "OUTRA"}, {"marca": " "}, {"aplicar": True}, {"lider_id": "l1"},
                       {"periodo_inicio": "2026-10-01", "periodo_fim": "2026-09-01"}):
            self.assertEqual(422, self.simulate(**params).status_code, params)
        payload = {"regra": "CHECKOUT_AUSENTE", "marca": "BRACELL", "novo_valor": "18:00"}
        self.assertEqual(200, self.client.post("/api/v1/fallback/simular", json=payload).status_code)
        cors = self.client.options("/api/fallback/simular", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
        self.assertEqual(200, cors.status_code)
        for method in ("put", "patch", "delete"):
            self.assertEqual(405, getattr(self.client, method)("/api/fallback/simular").status_code)
        self.client.headers.pop("Authorization")
        self.assertEqual(401, self.simulate().status_code)
        self.assertEqual(401, self.resolve().status_code)


if __name__ == "__main__":
    unittest.main()
