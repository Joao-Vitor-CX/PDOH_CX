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

    def test_data_loader_separa_origem_do_destino_e_usa_as_cinco_tabelas(self):
        codigo = (ROOT / "bracell/src/data_loader.py").read_text(encoding="utf-8")
        self.assertIn('"database": "involves_bracell"', codigo)
        self.assertNotIn("involves_exclusivos", codigo)
        self.assertNotIn("137.184.232.133", codigo)
        self.assertIn("engine_origem = criar_engine_origem()", codigo)
        self.assertIn("pd.read_sql(query, engine_origem)", codigo)
        self.assertIn("return dataframes, engine_local", codigo)
        tabelas = {
            "status_day_operacao_bracell",
            "colaboradores_ativos_bracell",
            "relatorio_checkin_bracell",
            "gerencial_visitas_bracell",
            "painel_pesquisas_bracell",
        }
        for tabela in tabelas:
            self.assertEqual(1, codigo.count(f"'{tabela}'"), tabela)

    def test_camada_parametrizacao_reutiliza_controle_sem_alterar_processadores(self):
        # Migracao: cria regra_tratativa e adiciona campos aditivos, de forma
        # idempotente (PREPARE) e sem semear dados (conta de migracao so tem DDL).
        migracao = (ROOT / "docker/mysql/migrations/004_parametrizacao_tratativas.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS pdoh_controle.regra_tratativa", migracao)
        self.assertIn("ADD COLUMN regra_id", migracao)
        self.assertIn("fk_oportunidade_regra", migracao)
        self.assertIn("ADD COLUMN responsavel", migracao)
        self.assertIn("PREPARE stmt FROM @sql", migracao)
        self.assertNotIn("INSERT INTO pdoh_controle.regra_tratativa", migracao)

        # Observabilidade: funcoes de consulta e persistencia do regra_id (catalogo
        # de regras agora vive em codigo, shared/treatment_catalog.py -- sem seed).
        obs = (ROOT / "bracell/src/observability.py").read_text(encoding="utf-8")
        for fn in ("def resolver_tratativa", "def carregar_regras_tratativa"):
            self.assertIn(fn, obs)
        dispatcher = (ROOT / "bracell/src/findings.py").read_text(encoding="utf-8")
        self.assertIn("tipo_problema,regra_id,", dispatcher)

        # Orquestrador (nao travado): pre-checagem preventiva de lideres.
        orq = (ROOT / "bracell/run_observado.py").read_text(encoding="utf-8")
        self.assertIn("FILTRO_LIDER_POR_SCRIPT", orq)
        self.assertIn("def _snapshot_sem_lideres", orq)
        self.assertIn("SEM_LIDERES_NO_PERIODO", orq)

        # Os processadores travados permanecem sem qualquer gancho de controle.
        for proc in (
            "bracell/lideres_pdoh_bracell.py",
            "bracell/lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
        ):
            codigo_proc = (ROOT / proc).read_text(encoding="utf-8")
            self.assertNotIn("SEM_LIDERES_NO_PERIODO", codigo_proc, proc)
            self.assertNotIn("resolver_tratativa", codigo_proc, proc)

    def test_identidade_entidade_e_camada_shadow_sem_tocar_processadores(self):
        # Migracao 005: tabelas genericas de identidade, idempotentes e sem seed.
        migracao = (ROOT / "docker/mysql/migrations/005_identificador_entidade.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS pdoh_controle.identificador_entidade", migracao)
        self.assertIn("identificador_entidade_alias", migracao)
        self.assertIn("uk_entidade_marca_tipo_chave", migracao)
        self.assertNotIn("INSERT INTO pdoh_controle.identificador_entidade", migracao)

        # Observador de identidade de PDV/MARCA (shadow) e prioridade de chave.
        ident = (ROOT / "bracell/src/identity.py").read_text(encoding="utf-8")
        self.assertIn("def observar_identidades_entidades", ident)
        self.assertIn("FONTES_PDV", ident)
        self.assertIn("id_pdv", ident)

        # Ligado no data_loader (nao travado), como camada complementar.
        loader = (ROOT / "bracell/src/data_loader.py").read_text(encoding="utf-8")
        self.assertIn("observar_identidades_entidades(engine_local, dataframes)", loader)

        # Processadores travados nao referenciam a identidade de entidades.
        for proc in (
            "bracell/pdoh_bracell.py",
            "bracell/pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
            "bracell/lideres_pdoh_bracell.py",
            "bracell/lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
        ):
            codigo_proc = (ROOT / proc).read_text(encoding="utf-8")
            self.assertNotIn("identificador_entidade", codigo_proc, proc)
            self.assertNotIn("observar_identidades_entidades", codigo_proc, proc)

    def test_expansao_qualidade_e_autonomia_regras(self):
        obs = (ROOT / "bracell/src/observability.py").read_text(encoding="utf-8")
        self.assertIn("def registrar_achado", obs)
        # Catalogo de tipo_problema vive em shared/treatment_catalog.py (ex-tabela
        # regra_tratativa); observability.py so' consome via import.
        catalogo = (ROOT / "shared/treatment_catalog.py").read_text(encoding="utf-8")
        for tipo in ("FALHA_PARAMETRIZACAO", "CRITERIO_LIDER", "COLUNA_OBRIGATORIA_AUSENTE", "REGISTRO_DUPLICADO"):
            self.assertIn(tipo, catalogo)

        dq = (ROOT / "bracell/src/data_quality.py").read_text(encoding="utf-8")
        self.assertIn("PERFIS_CONHECIDOS", dq)
        self.assertIn("COLABORADOR_SEM_CLASSIFICACAO", dq)

        lf = (ROOT / "bracell/src/legacy_fallbacks.py").read_text(encoding="utf-8")
        self.assertIn("JORNADA_NAO_ENCONTRADA", lf)

        orq = (ROOT / "bracell/run_observado.py").read_text(encoding="utf-8")
        self.assertIn("def _criterio_lider", orq)
        self.assertIn("CRITERIO_LIDER", orq)

        # Nada disso vaza para os processadores travados.
        for proc in (
            "bracell/pdoh_bracell.py",
            "bracell/pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
            "bracell/lideres_pdoh_bracell.py",
            "bracell/lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
        ):
            codigo_proc = (ROOT / proc).read_text(encoding="utf-8")
            self.assertNotIn("FALHA_PARAMETRIZACAO", codigo_proc, proc)
            self.assertNotIn("_criterio_lider", codigo_proc, proc)
            self.assertNotIn("COLABORADOR_SEM_CLASSIFICACAO", codigo_proc, proc)

    def test_de_para_camada_shadow_sem_tocar_processadores(self):
        migracao = (ROOT / "docker/mysql/migrations/006_de_para.sql").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS pdoh_controle.de_para", migracao)
        self.assertIn("de_para_historico", migracao)
        self.assertIn("uk_de_para", migracao)
        self.assertNotIn("INSERT INTO pdoh_controle.de_para", migracao)

        dp = (ROOT / "bracell/src/de_para.py").read_text(encoding="utf-8")
        for fn in ("def resolver_de_para", "def carregar_de_para", "def bootstrap_de_para", "def observar_padronizacao"):
            self.assertIn(fn, dp)
        self.assertIn("VALOR_SEM_PADRONIZACAO", dp)

        loader = (ROOT / "bracell/src/data_loader.py").read_text(encoding="utf-8")
        self.assertIn("observar_padronizacao(engine_local, dataframes)", loader)

        orq = (ROOT / "bracell/run_observado.py").read_text(encoding="utf-8")
        self.assertIn("bootstrap_de_para(engine)", orq)

        catalogo = (ROOT / "shared/treatment_catalog.py").read_text(encoding="utf-8")
        self.assertIn("VALOR_SEM_PADRONIZACAO", catalogo)

        for proc in (
            "bracell/pdoh_bracell.py",
            "bracell/pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
            "bracell/lideres_pdoh_bracell.py",
            "bracell/lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
        ):
            codigo_proc = (ROOT / proc).read_text(encoding="utf-8")
            self.assertNotIn("de_para", codigo_proc, proc)
            self.assertNotIn("observar_padronizacao", codigo_proc, proc)

    def test_assertividade_oportunidades_camada_shadow(self):
        obs = (ROOT / "bracell/src/observability.py").read_text(encoding="utf-8")
        self.assertIn("def evidencia_padrao", obs)
        catalogo = (ROOT / "shared/treatment_catalog.py").read_text(encoding="utf-8")
        for tipo in ("CHECKOUT_AUSENTE", "PESQUISA_CAMPOS_NULOS"):
            self.assertIn(tipo, catalogo)

        dq = (ROOT / "bracell/src/data_quality.py").read_text(encoding="utf-8")
        # Geracao de REGISTRO_DUPLICADO/IDENTIFICACAO_COLABORADOR descontinuada.
        self.assertNotIn('tipo="REGISTRO_DUPLICADO"', dq)
        self.assertNotIn('tipo="IDENTIFICACAO_COLABORADOR"', dq)
        self.assertNotIn("TIPOS_TELEMETRIA", dq)
        self.assertIn("registrar_achado", dq)

        lf = (ROOT / "bracell/src/legacy_fallbacks.py").read_text(encoding="utf-8")
        self.assertIn("CHECKOUT_AUSENTE", lf)
        self.assertIn("PESQUISA_CAMPOS_NULOS", lf)
        # Fallbacks legados inalterados (codigos e valores preservados).
        self.assertIn("HORA_SAIDA_PADRAO_2359", lf)
        self.assertIn("23:59:00", lf)
        self.assertIn("PESQUISA_NULOS_DATA_PADRAO_1999", lf)

        # Nada disso vaza para os processadores travados.
        for proc in (
            "bracell/pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
            "bracell/lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
        ):
            codigo_proc = (ROOT / proc).read_text(encoding="utf-8")
            self.assertNotIn("CHECKOUT_AUSENTE", codigo_proc, proc)
            self.assertNotIn("PESQUISA_CAMPOS_NULOS", codigo_proc, proc)

    def test_classificacao_de_para_estado_camada_shadow(self):
        mig = (ROOT / "docker/mysql/migrations/007_classificacao_oportunidade.sql").read_text(encoding="utf-8")
        for col in ("classificacao", "titulo", "severidade_padrao"):
            self.assertIn(col, mig)
        self.assertIn("PREPARE stmt FROM @sql", mig)

        obs = (ROOT / "bracell/src/observability.py").read_text(encoding="utf-8")
        self.assertIn("def resolver_classificacao", obs)
        catalogo = (ROOT / "shared/treatment_catalog.py").read_text(encoding="utf-8")
        self.assertIn("CLASSIFICACAO_POR_TIPO", catalogo)

        dp = (ROOT / "bracell/src/de_para.py").read_text(encoding="utf-8")
        self.assertIn("_ESTADOS_BR", dp)
        self.assertIn('"processo": "CADASTRO"', dp)

        dq = (ROOT / "bracell/src/data_quality.py").read_text(encoding="utf-8")
        self.assertIn("carregar_de_para", dq)  # gate de estado/uf

        lf = (ROOT / "bracell/src/legacy_fallbacks.py").read_text(encoding="utf-8")
        self.assertIn("tipo_com_checkin", lf)  # CHECKOUT_AUSENTE estrito

        # Processadores travados inalterados.
        for proc in (
            "bracell/pdoh_bracell.py",
            "bracell/lideres_pdoh_bracell.py",
        ):
            codigo_proc = (ROOT / proc).read_text(encoding="utf-8")
            self.assertNotIn("CLASSIFICACAO_POR_TIPO", codigo_proc, proc)

    def test_persistencia_direta_fica_na_platina_sem_ddl_no_runtime(self):
        codigo = (ROOT / "bracell/src/alch.py").read_text(encoding="utf-8")
        self.assertIn(
            'NOME_TABELA = "produtos_platina.'
            'exclusivo_bracell_platina_relatorio_pdoh"',
            codigo,
        )
        self.assertIn("ON DUPLICATE KEY UPDATE", codigo)
        self.assertNotIn("SCHEMA_TEMPORARIO", codigo)
        self.assertNotIn("df.to_sql(", codigo)
        self.assertNotIn("DROP TABLE", codigo.upper())
        validacao = (ROOT / "bracell/src/validate_persistence.py").read_text(
            encoding="utf-8"
        ).upper()
        self.assertNotIn("DELETE FROM", validacao)

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
        script = (ROOT / "docker/mysql/scripts/run-migrations.sh").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn(
            "grant select on involves_bracell.* to '$pdoh_db_user'@'%'", script
        )
        self.assertIn(
            "grant select, insert, update on produtos_platina.* to '$pdoh_db_user'@'%'",
            script,
        )
        self.assertNotIn("grant all privileges", script)

    def test_compose_declara_backend_mysql_healthcheck_e_volume(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("  mysql:", compose)
        self.assertIn("  backend:", compose)
        self.assertIn("healthcheck:", compose)
        self.assertIn("pdoh_cx_mysql_data", compose)
        self.assertIn('PDOH_DB_HOST: mysql', compose)
        self.assertIn('127.0.0.1:${PDOH_MYSQL_PORT:-3307}:3306', compose)
        self.assertIn("internal: true", compose)
        self.assertNotIn("pdoh_cx_dev", compose)
        self.assertNotIn("pdoh_cx_root_dev", compose)
        trecho_backend = compose.split("  backend:", 1)[1].split("  pipeline:", 1)[0]
        trecho_pipeline = compose.split("  pipeline:", 1)[1].split("\nvolumes:", 1)[0]
        self.assertNotIn("PDOH_SOURCE_DB_HOST", trecho_backend)
        self.assertIn("PDOH_SOURCE_DB_HOST", trecho_pipeline)
        self.assertIn("pdoh_cx_source_egress", trecho_pipeline)

    def test_backend_executa_sem_root_e_segredos_ficam_fora_da_imagem(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        database = (ROOT / "bracell/src/database.py").read_text(encoding="utf-8")
        init_sql = (ROOT / "docker/mysql/init/001_bancos_e_tabelas.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("USER 10001:10001", dockerfile)
        self.assertIn(".env", dockerignore.splitlines())
        self.assertIn(".env", gitignore.splitlines())
        self.assertNotIn("pdoh_cx_dev", database)
        self.assertNotIn("IDENTIFIED BY", init_sql.upper())

    def test_healthcheck_e_somente_leitura(self):
        codigo = (ROOT / "bracell/src/healthcheck.py").read_text(
            encoding="utf-8"
        ).upper()
        self.assertIn("SELECT COUNT(*)", codigo)
        for operacao in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP TABLE"):
            self.assertNotIn(operacao, codigo)


if __name__ == "__main__":
    unittest.main()
