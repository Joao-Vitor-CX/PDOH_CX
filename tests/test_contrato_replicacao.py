import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContratoReplicacaoTest(unittest.TestCase):
    def test_regras_e_bases_replicadas_permanecem_inalteradas(self):
        manifesto = json.loads(
            (ROOT / "manifesto_replicacao.json").read_text(encoding="utf-8")
        )
        for caminho_relativo, hash_esperado in manifesto["arquivos"].items():
            caminho = ROOT / caminho_relativo
            self.assertTrue(caminho.is_file(), caminho_relativo)
            hash_atual = hashlib.sha256(caminho.read_bytes()).hexdigest()
            self.assertEqual(hash_esperado, hash_atual, caminho_relativo)

    def test_data_loader_usa_origem_local_e_as_cinco_tabelas(self):
        codigo = (ROOT / "bracell/src/data_loader.py").read_text(encoding="utf-8")
        self.assertIn('"database": "involves_bracell"', codigo)
        self.assertNotIn("involves_exclusivos", codigo)
        self.assertNotIn("137.184.232.133", codigo)
        tabelas = {
            "status_day_operacao_bracell",
            "colaboradores_ativos_bracell",
            "relatorio_checkin_bracell",
            "gerencial_visitas_bracell",
            "painel_pesquisas_bracell",
        }
        for tabela in tabelas:
            self.assertEqual(1, codigo.count(f"'{tabela}'"), tabela)

    def test_persistencia_e_temporaria_ficam_na_platina(self):
        codigo = (ROOT / "bracell/src/alch.py").read_text(encoding="utf-8")
        self.assertIn(
            'NOME_TABELA = "produtos_platina.'
            'exclusivo_bracell_platina_relatorio_pdoh"',
            codigo,
        )
        self.assertIn('SCHEMA_TEMPORARIO = "produtos_platina"', codigo)

    def test_codigo_ativo_nao_consulta_nem_persiste_em_gold(self):
        for caminho in (ROOT / "bracell").rglob("*.py"):
            codigo_ativo = "\n".join(
                linha
                for linha in caminho.read_text(encoding="utf-8").splitlines()
                if not linha.lstrip().startswith("#")
            ).lower()
            self.assertNotIn("exclusivo_bracell_gold", codigo_ativo, str(caminho))

    def test_sql_cria_somente_os_objetos_desta_fase(self):
        sql = (ROOT / "docker/mysql/init/001_bancos_e_tabelas.sql").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn("create database if not exists involves_bracell", sql)
        self.assertIn("create database if not exists produtos_platina", sql)
        tabelas = (
            "status_day_operacao_bracell",
            "colaboradores_ativos_bracell",
            "relatorio_checkin_bracell",
            "gerencial_visitas_bracell",
            "painel_pesquisas_bracell",
            "exclusivo_bracell_platina_relatorio_pdoh",
        )
        for tabela in tabelas:
            self.assertEqual(1, sql.count(f"create table if not exists " + (
                "produtos_platina." if tabela.startswith("exclusivo_")
                else "involves_bracell."
            ) + tabela), tabela)
        self.assertNotIn("involves_exclusivos", sql)
        self.assertNotIn("gold", sql)

    def test_usuario_da_aplicacao_nao_escreve_na_origem(self):
        sql = (ROOT / "docker/mysql/init/001_bancos_e_tabelas.sql").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn(
            "grant select on involves_bracell.* to 'pdoh_cx_app'@'%'", sql
        )
        self.assertIn(
            "grant all privileges on produtos_platina.* to 'pdoh_cx_app'@'%'", sql
        )

    def test_compose_declara_backend_mysql_healthcheck_e_volume(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("  mysql:", compose)
        self.assertIn("  backend:", compose)
        self.assertIn("healthcheck:", compose)
        self.assertIn("pdoh_cx_mysql_data", compose)
        self.assertIn('PDOH_DB_HOST: mysql', compose)

    def test_healthcheck_e_somente_leitura(self):
        codigo = (ROOT / "bracell/src/healthcheck.py").read_text(
            encoding="utf-8"
        ).upper()
        self.assertIn("SELECT COUNT(*)", codigo)
        for operacao in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP TABLE"):
            self.assertNotIn(operacao, codigo)


if __name__ == "__main__":
    unittest.main()
