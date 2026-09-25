"""Contrato observador -> parametros persistidos -> SQLite -> HTTP, sem MySQL.

Execute com PDOH_TEST_OBSERVER_PYTHON apontando ao Python com pandas quando os
runtimes de API e processamento forem distintos. Nao importa/executa a ETL.
"""
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import unittest

from api.tests import test_api


class CadastralContractTest(unittest.TestCase):
    get = test_api.ApiTest.get
    setUp = test_api.ApiTest.setUp
    tearDown = test_api.ApiTest.tearDown

    def test_uf_identity_and_counts_preserve_execution_history(self):
        self.db.insert("regra_tratativa", regra_id="uf", tipo_problema="CADASTRO_UF_AUSENTE", classificacao="ALERTA")
        for identifier, execution, user, count in (("u1", "e1", "a", 10), ("u2", "e3", "a", 10), ("u3", "e1", "b", 1)):
            self.db.insert("oportunidade", oportunidade_id=identifier, execution_id=execution,
                marca="BRACELL", colaborador="Mesmo nome", regra_id="uf", tipo_problema="CADASTRO_UF_AUSENTE",
                evidencia=dict(versao_regra=1, campo="UF", quantidade_ocorrencias=count,
                    identidade_origem=dict(criterio="USUARIO_ORIGEM", valor=user)))
        all_runs = self.get("/alertas", campo="UF")
        self.assertEqual(2, all_runs["total"])
        self.assertEqual(21, all_runs["total_ocorrencias"])
        self.assertEqual(3, all_runs["total_registros"])
        one_run = self.get("/alertas", campo="UF", execution_id="e1")
        self.assertEqual(11, one_run["total_ocorrencias"])
        self.assertEqual(2, one_run["total_registros"])

    def test_legacy_or_malformed_counts_do_not_inflate_occurrences(self):
        from api.app.alerts import occurrence_count
        base = dict(tipo_problema="CADASTRO_UF_AUSENTE", classificacao="ALERTA")
        for count in (None, True, -1, 0, "10", 1.5):
            self.assertEqual(1, occurrence_count(dict(base, evidencia=dict(versao_regra=1, campo="UF", quantidade_ocorrencias=count))))
        self.assertEqual(1, occurrence_count(dict(base, tipo_problema="PESQUISA_CAMPOS_NULOS",
            evidencia=dict(versao_regra=1, campo="UF", quantidade_ocorrencias=100))))

    @unittest.skipUnless(os.environ.get("PDOH_TEST_OBSERVER_PYTHON"), "Informe o runtime isolado do observador com pandas")
    def test_generated_source_through_persistence_and_api(self):
        root = Path(__file__).resolve().parents[2]
        process = subprocess.run([os.environ["PDOH_TEST_OBSERVER_PYTHON"],
            str(root / "tests/test_alertas_cadastrais.py"), "--emit-fixture"],
            cwd=root, capture_output=True, text=True, check=True, timeout=30)
        payload = json.loads(process.stdout)
        self.db.insert("regra_tratativa", **payload["regra"], titulo="UF nao preenchida")
        ids = set()
        for item in payload["registros"]:
            ids.add(item["alerta_id"])
            self.db.insert("alerta", alerta_id=item["alerta_id"], execution_id="e1",
                marca=item["marca"], colaborador=item["colaborador"], tipo_problema=item["tipo"],
                regra_id=item["regra_id"], data_referencia=date.fromisoformat(item["data"]),
                origem=item["origem"], tabela_origem=item["tabela"], status_alerta="ABERTA",
                evidencia=json.loads(item["evidencia"]))
            self.db.insert("achado_roteamento", achado_id=item["achado_id"], execution_id="e1",
                marca=item["marca"], tipo_problema=item["tipo"], fingerprint=item["fingerprint"],
                regra_id=item["regra_id"], classificacao="ALERTA", destino="alerta", registro_id=item["alerta_id"],
                regra_snapshot=json.loads(item["snapshot"]))
        result = self.client.get("/api/v2/alertas", params={"marca": "BRACELL", "execution_id": "e1", "incluir_legado": False})
        self.assertEqual(200, result.status_code, result.text)
        page = result.json()
        self.assertEqual(3, page["total"])
        self.assertEqual(ids, {x["id"] for x in page["items"]})
        self.assertEqual(12, sum(x["evidencia"]["quantidade_ocorrencias"] for x in page["items"]))
        self.assertTrue(all(x["classificacao"] == "ALERTA" and x["origem_registro"] == "ALERTA" for x in page["items"]))
        operation = self.client.get("/api/v2/oportunidades", params={"incluir_legado": False}).json()
        self.assertEqual(0, operation["total"])
