import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bracell"))

from src.data_quality import analisar_dataframe, observar_qualidade  # noqa: E402
from src.observability import evidencia_padrao  # noqa: E402
from src.database import criar_engine, validar_comando_somente_leitura  # noqa: E402
from src.identity import normalizar_identificador, observar_identidades_entidades  # noqa: E402
from src.de_para import (  # noqa: E402
    bootstrap_de_para,
    observar_padronizacao,
    resolver_de_para,
)
from src.legacy_fallbacks import observar_fallback_jornada, observar_fallbacks_entrada  # noqa: E402
from src.observability import (  # noqa: E402
    carregar_regras_tratativa,
    finalizar_execucao,
    registrar_evento,
    registrar_oportunidades,
    resolver_tratativa,
)
from run_observado import _LogSeguro, _snapshot_sem_lideres, _criterio_lider  # noqa: E402


class _EngineIndisponivel:
    def begin(self):
        raise RuntimeError("controle indisponivel para teste")


class _ConexaoCaptura:
    def __init__(self):
        self.comando = None
        self.parametros = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, comando, parametros):
        self.comando = str(comando)
        self.parametros = parametros


class _EngineCaptura:
    def __init__(self):
        self.conexao = _ConexaoCaptura()

    def begin(self):
        return self.conexao


class _Resultado:
    """Resultado minimo compativel com o uso do modulo (INSERT/SELECT)."""

    rowcount = 1
    lastrowid = 1
    row = None
    rows = ()

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return list(self.rows)


class _ConexaoMulti:
    def __init__(self, regra="ativa"):
        self.execucoes = []
        # Regra CONFIGURAVEL da oportunidade: "ativa", "inativa" ou None (nao cadastrada).
        self.regra = regra

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, comando, parametros=None):
        self.execucoes.append((str(comando), parametros))
        result = _Resultado()
        if "SELECT marca,status_execucao" in str(comando):
            result.row = {"marca": "BRACELL", "status_execucao": "INICIADA"}
        if "FROM pdoh_controle.regra_configuracao" in str(comando) and self.regra:
            ativa = self.regra == "ativa"
            result.row = {"configuracao_id": "CFG", "status": "ATIVA" if ativa else "INATIVA",
                          "geracao_automatica_ativa": 1 if ativa else 0}
        if "FROM pdoh_controle.regra_tratamento_configuracao" in str(comando):
            result.rows = [{"resultado": "CONFIRMADO", "gera_oportunidade": 1, "status": "ATIVO"}]
        return result


class _EngineMulti:
    def __init__(self, regra="ativa"):
        self.conexao = _ConexaoMulti(regra)

    def begin(self):
        return self.conexao

    def connect(self):
        return self.conexao


class _EngineConnectIndisponivel:
    def connect(self):
        raise RuntimeError("origem/controle indisponivel para teste")


class ObservabilidadeTest(unittest.TestCase):
    def test_qualidade_identifica_problemas_sem_mutar_dataframe(self):
        dataframe = pd.DataFrame(
            [
                {
                    "colaborador": "Ana",
                    "data_roteiro": "2026-09-01",
                    "hora_entrada": "2026-09-01 10:00:00",
                    "hora_saida": "2026-09-01 09:00:00",
                    "estado": "SP",
                },
                {
                    "colaborador": "Ana",
                    "data_roteiro": "2026-09-01",
                    "hora_entrada": "2026-09-01 10:00:00",
                    "hora_saida": "2026-09-01 09:00:00",
                    "estado": "SP",
                },
                {
                    "colaborador": " Bob ",
                    "data_roteiro": "2026-08-01",
                    "hora_entrada": None,
                    "hora_saida": None,
                    "estado": "Sao Paulo",
                },
            ]
        )
        original = dataframe.copy(deep=True)

        oportunidades = analisar_dataframe(
            dataframe,
            "checkin",
            "relatorio_checkin_bracell",
            periodo_inicio="2026-09-01",
            periodo_fim="2026-09-06",
        )

        assert_frame_equal(original, dataframe, check_exact=True)
        tipos = {item["tipo_problema"] for item in oportunidades}
        # Cenarios operacionais/telemetria continuam sendo detectados por analisar_dataframe.
        self.assertTrue(
            {
                "CAMPO_OBRIGATORIO_VAZIO",
                "INCONSISTENCIA_HORARIO",
                "DATA_FORA_DO_PERIODO",  # ainda detectado; observar_qualidade o roteia p/ telemetria
            }.issubset(tipos)
        )
        # Geracao descontinuada: nao aparecem mais.
        self.assertNotIn("REGISTRO_DUPLICADO", tipos)
        self.assertNotIn("IDENTIFICACAO_COLABORADOR", tipos)

    def test_identidade_normaliza_apenas_na_camada_sombra(self):
        self.assertEqual("JOAO DA SILVA", normalizar_identificador("  João  da Silva "))
        self.assertNotEqual(
            normalizar_identificador("João"),
            normalizar_identificador("João Silva"),
        )

    def test_falha_da_observabilidade_nao_propaga(self):
        saida = io.StringIO()
        with redirect_stdout(saida):
            registrar_evento(
                _EngineIndisponivel(),
                nivel="INFO",
                categoria="TESTE",
                codigo="TESTE_FAIL_OPEN",
                mensagem="evento de teste",
            )
            total = registrar_oportunidades(
                _EngineIndisponivel(),
                [
                    {
                        "origem": "TESTE",
                        "tabela_origem": "teste",
                        "tipo_problema": "TESTE",
                        "descricao_detalhada": "teste",
                        "severidade": "BAIXA",
                    }
                ],
            )
        self.assertEqual(0, total)
        self.assertIn("OBSERVABILIDADE_INDISPONIVEL", saida.getvalue())

    def test_conexao_recusa_host_externo_antes_de_criar_engine(self):
        saida = io.StringIO()
        with (
            patch.dict(os.environ, {"PDOH_DB_HOST": "mysql-producao.exemplo"}),
            patch("src.database.create_engine") as construtor,
            redirect_stderr(saida),
        ):
            with self.assertRaisesRegex(RuntimeError, "nao esta autorizado"):
                criar_engine()
        construtor.assert_not_called()
        self.assertIn("CONEXAO_BANCO_NAO_AUTORIZADA", saida.getvalue())

    def test_conexao_aceita_somente_hosts_locais_previstos(self):
        with patch("src.database.create_engine") as construtor:
            for host in ("mysql", "localhost", "127.0.0.1", "MYSQL"):
                with patch.dict(
                    os.environ,
                    {
                        "PDOH_DB_HOST": host,
                        "PDOH_DB_USER": "pdoh_cx_app",
                        "PDOH_DB_PASSWORD": "segredo_local_de_teste",
                    },
                ):
                    criar_engine()
        self.assertEqual(4, construtor.call_count)

    def test_origem_aceita_exclusivamente_comandos_de_leitura(self):
        for comando in (
            "SELECT * FROM status_day_operacao_bracell",
            "SHOW TABLES",
            "DESCRIBE colaboradores_ativos_bracell",
            "EXPLAIN SELECT 1",
        ):
            validar_comando_somente_leitura(comando)

        for comando in (
            "INSERT INTO origem VALUES (1)",
            "UPDATE origem SET valor = 1",
            "DELETE FROM origem",
            "TRUNCATE TABLE origem",
            "ALTER TABLE origem ADD COLUMN valor INT",
            "DROP TABLE origem",
            "CREATE TABLE origem (valor INT)",
            "SELECT 1; DELETE FROM origem",
            "SELECT * FROM origem FOR UPDATE",
            "SELECT * FROM origem INTO OUTFILE '/tmp/origem.csv'",
        ):
            with self.assertRaisesRegex(RuntimeError, "exclusivamente"):
                validar_comando_somente_leitura(comando)

    def test_arquivo_de_log_indisponivel_nao_lanca_excecao(self):
        # Um arquivo real usado como se fosse diretorio provoca FileExistsError
        # antes de qualquer escrita e exercita a degradacao fail-open.
        bloqueador = Path(__file__).resolve()
        log = _LogSeguro(bloqueador / "execucao.log")
        self.assertFalse(log.disponivel)
        log.write("nao deve interromper")
        log.flush()
        log.close()

    def test_finalizacao_registra_o_orquestrador_como_componente_atual(self):
        engine = _EngineCaptura()
        resumo = {
            "status_execucao": "INICIADA",
            "houve_persistencia": 0,
            "total_alertas": 0,
            "total_fallbacks": 0,
        }
        with (
            patch("src.observability.obter_resumo_execucao", return_value=resumo),
            patch.dict(os.environ, {"PDOH_EXECUTION_ID": "TESTE", "PDOH_COMPONENTE": "ORQUESTRADOR"}),
        ):
            status = finalizar_execucao(engine)

        self.assertEqual("CONCLUIDA_SEM_RESULTADO", status)
        self.assertIn("componente_atual = :componente", engine.conexao.comando)
        self.assertEqual("ORQUESTRADOR", engine.conexao.parametros["componente"])

    def test_detector_de_fallback_nao_muta_e_reconhece_defaults_legados(self):
        checkin = pd.DataFrame(
            [{"colaborador": "Ana", "data_roteiro": "2026-09-01", "hora_saida": None}]
        )
        checkin_original = checkin.copy(deep=True)
        with patch("src.legacy_fallbacks.registrar_fallback") as registrar:
            total = observar_fallbacks_entrada(object(), checkin, "checkin")
        self.assertEqual(1, total)
        self.assertEqual("HORA_SAIDA_PADRAO_2359", registrar.call_args.kwargs["codigo"])
        assert_frame_equal(checkin_original, checkin, check_exact=True)

        colaboradores = pd.DataFrame(
            [
                {
                    "nome_colaborador": "Ana",
                    "perfil_acesso": "PROMOTOR EXCLUSIVO",
                    "nome_pai": None,
                }
            ]
        )
        colaboradores_original = colaboradores.copy(deep=True)
        with patch("src.legacy_fallbacks.registrar_fallback") as registrar:
            total = observar_fallback_jornada(object(), colaboradores)
        self.assertEqual(1, total)
        self.assertEqual("JORNADA_PADRAO_44H", registrar.call_args.kwargs["codigo"])
        assert_frame_equal(colaboradores_original, colaboradores, check_exact=True)

    def test_processadores_nao_usam_identidade_ou_qualidade_no_calculo(self):
        manifesto = __import__("json").loads(
            (ROOT / "manifesto_replicacao.json").read_text(encoding="utf-8")
        )
        for relativo in manifesto["arquivos"]:
            if not relativo.endswith(".py"):
                continue
            codigo = (ROOT / relativo).read_text(encoding="utf-8").lower()
            self.assertNotIn("colaborador_id_interno", codigo, relativo)
            self.assertNotIn("data_quality", codigo, relativo)
            self.assertNotIn("observability", codigo, relativo)

    def test_resolver_e_carregar_regras_nao_dependem_do_engine(self):
        # Catalogo em codigo (shared.treatment_catalog): nao ha mais I/O a falhar, entao
        # um engine indisponivel nao impede a resolucao de um tipo_problema conhecido.
        regra = resolver_tratativa(_EngineConnectIndisponivel(), "SEM_LIDERES_NO_PERIODO")
        self.assertIsNotNone(regra)
        self.assertEqual("SEM_LIDERES_NO_PERIODO", regra["tipo_problema"])
        self.assertIsNone(resolver_tratativa(_EngineConnectIndisponivel(), "TIPO_INEXISTENTE"))
        self.assertTrue(carregar_regras_tratativa(_EngineConnectIndisponivel()))

    def test_registrar_oportunidade_persiste_regra_id(self):
        engine = _EngineMulti()
        with patch.dict(os.environ, {"PDOH_EXECUTION_ID": "TESTE_REGRA"}), patch("src.findings.resolver_classificacao", return_value={"regra_id": "RID-TESTE", "classificacao": "OPORTUNIDADE", "impacto_negocio": "Impacto", "acao_recomendada": "Conferir", "responsavel_padrao": "Lider"}):
            inseridas = registrar_oportunidades(
                engine,
                [{
                    "tipo_problema": "SEM_LIDERES_NO_PERIODO",
                    "origem": "INVOLVES_BRACELL",
                    "tabela_origem": "colaboradores_ativos_bracell",
                    "regra_id": "RID-TESTE",
                    "colaborador": "Pessoa teste",
                    "descricao_detalhada": "teste",
                    "severidade": "BAIXA",
                    # Toda oportunidade exige comprovacao confirmada e regra configurada e ativa.
                    "evidencia": {"comprovacao": {"resultado": "confirmado"}},
                }],
            )
        self.assertEqual(1, inseridas)
        insercao = next(
            (c, p) for c, p in engine.conexao.execucoes if "INSERT INTO pdoh_controle.oportunidade (" in c
        )
        self.assertIn("regra_id", insercao[0])
        self.assertEqual("RID-TESTE", insercao[1]["regra_id"])

    def test_snapshot_sem_lideres_fail_open_sem_origem(self):
        # Sem credenciais de origem, a pre-checagem degrada para "nao pular".
        with patch("run_observado.criar_engine_origem", side_effect=RuntimeError("sem origem")):
            self.assertFalse(_snapshot_sem_lideres("LIDER EXCLUSIVO"))

    def test_identidade_pdv_prioriza_id_e_detecta_inconsistencias(self):
        dfs = {
            "gerencial_de_visitas": pd.DataFrame(
                [
                    {"id_pdv": 10, "codigo_pdv": None, "cnpj_pdv": None, "ponto_venda": "LOJA CENTRO"},
                    {"id_pdv": 10, "codigo_pdv": None, "cnpj_pdv": None, "ponto_venda": "LOJA CENTRO"},
                    {"id_pdv": 20, "codigo_pdv": None, "cnpj_pdv": None, "ponto_venda": "LOJA CENTRO"},
                    {"id_pdv": 30, "codigo_pdv": None, "cnpj_pdv": None, "ponto_venda": "LOJA NORTE"},
                    {"id_pdv": 30, "codigo_pdv": None, "cnpj_pdv": None, "ponto_venda": "LOJA NORTE II"},
                ]
            ),
            "checkin": pd.DataFrame([{"cod_pdv": None, "ponto_venda": "LOJA SEM CODIGO"}]),
        }
        capturadas = []
        engine = _EngineMulti()
        with (
            patch("src.identity.registrar_achado", side_effect=lambda e, ops: capturadas.extend(ops)),
            patch("src.identity.resolver_tratativa", return_value=None),
            patch.dict(os.environ, {"PDOH_EXECUTION_ID": "TESTE_PDV"}),
        ):
            total = observar_identidades_entidades(engine, dfs)

        self.assertGreaterEqual(total, 4)  # 3 PDVs por id + PDV por nome + MARCA
        tipos = {o["tipo_problema"] for o in capturadas}
        self.assertIn("PDV_MESMO_NOME_IDS_DISTINTOS", tipos)
        self.assertIn("PDV_NOME_DIVERGENTE_MESMO_ID", tipos)
        self.assertIn("PDV_SEM_IDENTIFICADOR", tipos)

        inserts = [
            p for c, p in engine.conexao.execucoes
            if "INSERT INTO pdoh_controle.identificador_entidade (" in c
        ]
        chaves = {d["chave"] for lista in inserts for d in lista}
        self.assertIn("ID:10", chaves)      # prioriza id_pdv
        self.assertIn("MARCA:BRACELL", chaves)

    def test_regra_id_resolvido_centralmente(self):
        engine = _EngineMulti()
        with (
            patch("src.findings.resolver_classificacao", return_value={"regra_id": "R-CENTRAL", "classificacao": "OPORTUNIDADE", "impacto_negocio": "Impacto", "acao_recomendada": "Conferir", "responsavel_padrao": "Lider"}),
            patch.dict(os.environ, {"PDOH_EXECUTION_ID": "T_CENTRAL"}),
        ):
            registrar_oportunidades(
                engine,
                [{
                    "tipo_problema": "CAMPO_OBRIGATORIO_VAZIO",
                    "origem": "INVOLVES_BRACELL",
                    "tabela_origem": "colaboradores_ativos_bracell",
                    "descricao_detalhada": "d",
                    "colaborador": "Pessoa teste",
                    "severidade": "ALTA",
                    # A comprovacao chega da esteira; sem ela o dispatcher recusa a
                    # oportunidade (coberto em test_dispatcher_exige_comprovacao).
                    "evidencia": {"campo": "UF", "comprovacao": {"resultado": "confirmado"}},
                }],
            )
        insercao = next(
            p for c, p in engine.conexao.execucoes if "INSERT INTO pdoh_controle.oportunidade (" in c
        )
        self.assertEqual("R-CENTRAL", insercao["regra_id"])

    def test_dispatcher_exige_comprovacao_para_oportunidade(self):
        """Sem o selo do motor de evidencias nao ha INSERT na fila operacional."""
        engine = _EngineMulti()
        with (
            patch("src.findings.resolver_classificacao", return_value={
                "regra_id": "R-CENTRAL", "classificacao": "OPORTUNIDADE", "severidade_padrao": "ALTA",
                "impacto_negocio": "Jornada", "acao_recomendada": "Validar",
                "responsavel_padrao": "Lider", "tratamento_esperado": "t"}),
            patch.dict(os.environ, {"PDOH_EXECUTION_ID": "T_SEM_PROVA"}),
        ):
            registrar_oportunidades(engine, [{
                "tipo_problema": "CHECKOUT_AUSENTE",
                "origem": "INVOLVES_BRACELL",
                "tabela_origem": "relatorio_checkin_bracell",
                "descricao_detalhada": "d",
                "colaborador": "Pessoa teste",
                "severidade": "ALTA",
                "evidencia": {"campo_esperado": "hora_saida"},
            }])
        comandos = [c for c, _ in engine.conexao.execucoes]
        self.assertFalse(any("INSERT INTO pdoh_controle.oportunidade (" in c for c in comandos))
        self.assertTrue(any("ACHADO_SEM_EVIDENCIA_CONFIRMADA" in c for c in comandos))

    def _despachar_oportunidade_comprovada(self, regra):
        engine = _EngineMulti(regra)
        with (
            patch("src.findings.resolver_classificacao", return_value={
                "regra_id": "R-CFG", "classificacao": "OPORTUNIDADE", "severidade_padrao": "MEDIA",
                "impacto_negocio": "Horas não registradas", "acao_recomendada": "Validar",
                "responsavel_padrao": "Lider", "tratamento_esperado": "t"}),
            patch.dict(os.environ, {"PDOH_EXECUTION_ID": "T_PORTA"}),
        ):
            inseridas = registrar_oportunidades(engine, [{
                "tipo_problema": "HORAS_AUSENTES", "origem": "PDOH_PLATINA",
                "tabela_origem": "exclusivo_bracell_platina_relatorio_pdoh",
                "descricao_detalhada": "d", "colaborador": "Pessoa teste", "severidade": "MEDIA",
                "evidencia": {"campo_esperado": "horas_nao_registradas", "comprovacao": {"resultado": "confirmado"}},
            }])
        return inseridas, engine.conexao.execucoes

    def test_dispatcher_so_cria_oportunidade_de_regra_cadastrada_ativa_e_configurada(self):
        """Configuracao -> regra ativa -> criterios atendidos -> oportunidade."""
        inseridas, execucoes = self._despachar_oportunidade_comprovada("ativa")
        self.assertEqual(1, inseridas)
        self.assertTrue(any("INSERT INTO pdoh_controle.oportunidade (" in c for c, _ in execucoes))

    def test_dispatcher_recusa_regra_inexistente_e_inativa_e_registra_o_motivo(self):
        for regra, codigo in ((None, "REGRA_NAO_CADASTRADA"), ("inativa", "REGRA_INATIVA")):
            with self.subTest(regra=regra):
                inseridas, execucoes = self._despachar_oportunidade_comprovada(regra)
                self.assertEqual(0, inseridas)
                self.assertFalse(any("INSERT INTO pdoh_controle.oportunidade (" in c for c, _ in execucoes))
                self.assertFalse(any("INSERT INTO pdoh_controle.achado_roteamento" in c for c, _ in execucoes))
                # O achado nao some em silencio: vira evento de governanca com o motivo.
                eventos = [p for c, p in execucoes if "INSERT INTO pdoh_controle.execucao_evento" in c and p]
                self.assertEqual([codigo], [p["codigo"] for p in eventos])

    def test_falha_parametrizacao_quando_cenario_sem_regra(self):
        engine = _EngineMulti()
        with (
            patch("src.findings.resolver_classificacao", return_value=None),
            patch.dict(os.environ, {"PDOH_EXECUTION_ID": "T_FP"}),
        ):
            registrar_oportunidades(
                engine,
                [{
                    "tipo_problema": "COLABORADOR_SEM_CLASSIFICACAO",
                    "origem": "INVOLVES_BRACELL",
                    "tabela_origem": "colaboradores_ativos_bracell",
                    "descricao_detalhada": "d",
                    "severidade": "MEDIA",
                }],
            )
        tipos = [p["tipo"] for c, p in engine.conexao.execucoes if "INSERT INTO pdoh_controle.oportunidade (" in c]
        self.assertEqual([], tipos)
        self.assertTrue(any("CLASSIFICACAO_NAO_RESOLVIDA" in c for c, _ in engine.conexao.execucoes))

    def test_colaborador_sem_classificacao_detectado(self):
        df = pd.DataFrame(
            [
                {"nome_colaborador": "A", "usuario_ativo": "Sim", "data_evolucao": "2026-09-01",
                 "perfil_acesso": "PROMOTOR EXCLUSIVO", "data_dimensao": "2026-09-01"},
                {"nome_colaborador": "B", "usuario_ativo": "Sim", "data_evolucao": "2026-09-01",
                 "perfil_acesso": None, "data_dimensao": "2026-09-01"},
                {"nome_colaborador": "C", "usuario_ativo": "Sim", "data_evolucao": "2026-09-01",
                 "perfil_acesso": "PERFIL DESCONHECIDO", "data_dimensao": "2026-09-01"},
            ]
        )
        ops = analisar_dataframe(df, "colaboradores", "colaboradores_ativos_bracell")
        sem_classificacao = [o for o in ops if o["tipo_problema"] == "COLABORADOR_SEM_CLASSIFICACAO"]
        self.assertEqual(2, len(sem_classificacao))  # B (vazio) e C (fora do dominio)

    def test_jornada_nao_encontrada_gera_oportunidade(self):
        colaboradores = pd.DataFrame(
            [
                {"nome_colaborador": "Ana", "perfil_acesso": "PROMOTOR EXCLUSIVO", "nome_pai": None},
                {"nome_colaborador": "Bia", "perfil_acesso": "PROMOTOR EXCLUSIVO", "nome_pai": "44"},
            ]
        )
        capturadas = []
        with (
            patch("src.legacy_fallbacks.registrar_fallback"),
            patch("src.legacy_fallbacks.registrar_achado", side_effect=lambda e, ops: capturadas.extend(ops)),
            patch("src.legacy_fallbacks.obter_componente", return_value="PROMOTORES"),
        ):
            observar_fallback_jornada(object(), colaboradores)
        tipos = {o["tipo_problema"] for o in capturadas}
        self.assertNotIn("JORNADA_NAO_ENCONTRADA", tipos)  # Falta de fonte completa nao comprova ausencia.

    def test_criterio_lider_default_e_override(self):
        script = "lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py"
        with patch("run_observado.resolver_tratativa", return_value=None):
            self.assertEqual("LIDER EXCLUSIVO", _criterio_lider(object(), script))
        with patch(
            "run_observado.resolver_tratativa",
            return_value={"regra_identificacao": '{"%s": "SUPERVISOR"}' % script},
        ):
            self.assertEqual("SUPERVISOR", _criterio_lider(object(), script))
        self.assertIsNone(_criterio_lider(object(), "pdoh_bracell.py"))

    def test_resolver_de_para_encontra_e_normaliza(self):
        mapeamentos = [{"valor_origem": "CX - JORNADA PADRÃO", "valor_padronizado": "JORNADA PADRAO", "marca": None}]
        with patch("src.de_para.carregar_de_para", return_value=mapeamentos):
            achado = resolver_de_para(object(), "JORNADA", "jornada_trabalho", "cx - jornada padrao")
            self.assertIsNotNone(achado)
            self.assertEqual("JORNADA PADRAO", achado["valor_padronizado"])
            self.assertIsNone(resolver_de_para(object(), "JORNADA", "jornada_trabalho", "CX - OUTRA"))

    def test_observar_padronizacao_registra_nao_mapeados(self):
        dfs = {
            "colaboradores": pd.DataFrame(
                [
                    {"jornada_trabalho": "CX - JORNADA PADRÃO", "perfil_acesso": "PROMOTOR EXCLUSIVO"},
                    {"jornada_trabalho": "CX - NOVA JORNADA", "perfil_acesso": "PROMOTOR EXCLUSIVO"},
                ]
            )
        }

        def fake_carregar(engine, processo, campo, marca="BRACELL"):
            if processo == "JORNADA":
                return [{"valor_origem": "CX - JORNADA PADRÃO"}]
            if processo == "PERFIL":
                return [{"valor_origem": "PROMOTOR EXCLUSIVO"}]
            return []

        capturadas = []
        with (
            patch("src.de_para.carregar_de_para", side_effect=fake_carregar),
            patch("src.de_para.registrar_achado", side_effect=lambda e, ops: capturadas.extend(ops)),
            patch("src.de_para.registrar_evento"),
        ):
            nao_mapeados = observar_padronizacao(object(), dfs)

        self.assertEqual(1, nao_mapeados)
        tipos = {o["tipo_problema"] for o in capturadas}
        self.assertIn("VALOR_SEM_PADRONIZACAO", tipos)
        valores = {o["evidencia"]["valor_origem"] for o in capturadas}
        self.assertIn("CX - NOVA JORNADA", valores)

    def test_bootstrap_de_para_fail_open(self):
        with patch("src.de_para.registrar_evento"):
            self.assertEqual(0, bootstrap_de_para(_EngineIndisponivel()))

    def test_data_fora_do_periodo_vira_telemetria_nao_oportunidade(self):
        df = pd.DataFrame([
            {"colaborador": "Ana", "data_roteiro": "2025-01-01", "hora_entrada": "2025-01-01 08:00:00",
             "hora_saida": "2025-01-01 17:00:00", "estado": "SP"},
        ])
        ops_registradas, eventos = [], []
        with (
            patch("src.data_quality.registrar_achado", side_effect=lambda e, ops: ops_registradas.extend(ops)),
            patch("src.data_quality.registrar_evento", side_effect=lambda e, **kw: eventos.append(kw)),
        ):
            observar_qualidade(object(), df, "checkin", "relatorio_checkin_bracell",
                               periodo_inicio="2026-09-01", periodo_fim="2026-09-05")
        tipos_ops = {o["tipo_problema"] for o in ops_registradas}
        codigos_ev = {ev.get("codigo") for ev in eventos}
        self.assertIn("DATA_FORA_DO_PERIODO", tipos_ops)  # detector envia ao dispatcher
        self.assertNotIn("DATA_FORA_DO_PERIODO", codigos_ev)  # produtor nao escolhe destino
        self.assertNotIn("REGISTRO_DUPLICADO", tipos_ops)
        self.assertNotIn("IDENTIFICACAO_COLABORADOR", tipos_ops)

    def test_checkout_ausente_so_com_checkin_sem_alterar_fallback(self):
        df = pd.DataFrame([
            # Ana: check-in feito, sem checkout -> gera (2 ocorrencias, mesmo dia)
            {"colaborador": "Ana", "data_roteiro": "2026-09-01", "hora_saida": None, "tipo_checkin": "Checkin GPS", "checkout_sistema": None, "checkout_registrado": None},
            {"colaborador": "Ana", "data_roteiro": "2026-09-01", "hora_saida": None, "tipo_checkin": "Checkin Manual", "checkout_sistema": None, "checkout_registrado": None},
            # Bob: Sem Checkin -> NAO gera (nao houve visita/check-in)
            {"colaborador": "Bob", "data_roteiro": "2026-09-02", "hora_saida": None, "tipo_checkin": "Sem Checkin", "checkout_sistema": None, "checkout_registrado": None},
            # Cid: check-in, mas checkout pelo sistema -> NAO gera (checkout existe)
            {"colaborador": "Cid", "data_roteiro": "2026-09-03", "hora_saida": None, "tipo_checkin": "Checkin GPS", "checkout_sistema": "2026-09-03 18:00:00", "checkout_registrado": None},
            # Dan: tem hora_saida -> NAO gera (nem fallback)
            {"colaborador": "Dan", "data_roteiro": "2026-09-04", "hora_saida": "18:00:00", "tipo_checkin": "Checkin GPS", "checkout_sistema": None, "checkout_registrado": None},
        ])
        ops, fallbacks, eventos = [], [], []
        with (
            patch("src.evidence_context.comprovar_e_registrar",
                  side_effect=lambda e, s, o, **kw: ops.extend(o)),
            patch("src.legacy_fallbacks.registrar_fallback", side_effect=lambda e, **kw: fallbacks.append(kw)),
            patch("src.legacy_fallbacks.registrar_evento", side_effect=lambda e, **kw: eventos.append(kw)),
        ):
            observar_fallbacks_entrada(object(), df, "checkin", source_engine=object())
        checkout = [o for o in ops if o["tipo_problema"] == "CHECKOUT_AUSENTE"]
        self.assertEqual(1, len(checkout))  # so Ana (Sem Checkin e checkout_sistema excluidos)
        ev = checkout[0]["evidencia"]
        self.assertTrue(ev["fallback_usado"])
        self.assertEqual("23:59:00", ev["fallback_valor"])
        self.assertEqual(2, ev["ocorrencias"])
        # Fallback legado permanece registrado para TODO hora_saida nulo (Ana x2, Bob, Cid).
        self.assertTrue(any(f.get("codigo") == "HORA_SAIDA_PADRAO_2359" for f in fallbacks))

    def test_checkout_ausente_sem_origem_nao_vira_oportunidade_sem_prova(self):
        """Sem a origem aberta nao ha como comprovar entrada, roteiro nem abono."""
        df = pd.DataFrame([
            {"colaborador": "Ana", "data_roteiro": "2026-09-01", "hora_saida": None,
             "tipo_checkin": "Checkin GPS", "checkout_sistema": None, "checkout_registrado": None},
        ])
        ops, eventos = [], []
        with (
            patch("src.legacy_fallbacks.registrar_achado", side_effect=lambda e, o: ops.extend(o)),
            patch("src.legacy_fallbacks.registrar_fallback"),
            patch("src.legacy_fallbacks.registrar_evento", side_effect=lambda e, **kw: eventos.append(kw)),
        ):
            observar_fallbacks_entrada(object(), df, "checkin")
        self.assertEqual([], ops)
        alerta = next(ev for ev in eventos if ev.get("codigo") == "COMPROVACAO_SEM_ORIGEM")
        self.assertEqual("ALERTA", alerta["nivel"])
        self.assertEqual(1, alerta["contexto"]["achados_descartados"])

    def test_classificacao_por_tipo_mapeamento(self):
        from shared.treatment_catalog import CLASSIFICACAO_POR_TIPO as C
        for tipo in ("JORNADA_NAO_ENCONTRADA", "CHECKOUT_AUSENTE"):
            self.assertEqual("OPORTUNIDADE", C[tipo], tipo)
        self.assertEqual('CONFIGURACAO', C['FALHA_PARAMETRIZACAO'])
        for tipo in ("CAMPO_OBRIGATORIO_VAZIO", "DATA_HORA_INVALIDA", "DADO_FORA_DO_PADRAO", "VALOR_SEM_PADRONIZACAO", "DIVERGENCIA_CADASTRAL",
                     "PDV_SEM_IDENTIFICADOR", "PDV_NOME_DIVERGENTE_MESMO_ID", "COLABORADOR_SEM_CLASSIFICACAO"):
            self.assertEqual("ALERTA", C[tipo], tipo)
        for tipo in ("REGISTRO_DUPLICADO", "DATA_FORA_DO_PERIODO", "VOLUME_OPORTUNIDADES_TRUNCADO",
                     "IDENTIFICACAO_COLABORADOR"):
            self.assertEqual("TELEMETRIA", C[tipo], tipo)

    def test_estado_de_para_remove_fora_do_padrao_mapeado(self):
        df = pd.DataFrame([
            {"colaborador": "Ana", "data_visita": "2026-09-01", "estado": "Pará"},
            {"colaborador": "Bob", "data_visita": "2026-09-01", "estado": "Xyzland"},
        ])
        ops = []
        with (
            patch("src.data_quality.registrar_achado", side_effect=lambda e, o: ops.extend(o)),
            patch("src.data_quality.registrar_evento"),
            patch("src.data_quality.carregar_de_para", return_value=[{"valor_origem": "Para"}]),
        ):
            observar_qualidade(object(), df, "gerencial_de_visitas", "gerencial_visitas_bracell")
        valores = {o["evidencia"].get("valor") for o in ops if o["tipo_problema"] == "DADO_FORA_DO_PADRAO"}
        self.assertNotIn("Pará", valores)   # mapeado no De/Para -> nao gera
        self.assertIn("Xyzland", valores)    # nao mapeado -> permanece

    def test_pesquisa_campos_nulos_somente_obrigatorios(self):
        df = pd.DataFrame([
            {"id": 1, "responsavel": None, "data_solicitacao": "2026-09-01", "data_expiracao": "2026-09-05",
             "status": "Pendente", "data_conclusao": None},
            {"id": 2, "responsavel": "Ana", "data_solicitacao": "2026-09-01", "data_expiracao": "2026-09-05",
             "status": "Pendente", "data_conclusao": None},
        ])
        ops = []
        with (
            patch("src.legacy_fallbacks.registrar_achado", side_effect=lambda e, o: ops.extend(o)),
            patch("src.legacy_fallbacks.registrar_fallback"),
        ):
            observar_fallbacks_entrada(object(), df, "pesquisas")
        pcn = [o for o in ops if o["tipo_problema"] == "PESQUISA_CAMPOS_NULOS"]
        self.assertEqual(1, len(pcn))  # so id=1 (responsavel obrigatorio nulo); data_conclusao opcional NAO conta
        self.assertIn("responsavel", pcn[0]["evidencia"]["campo_esperado"])
        self.assertTrue(pcn[0]["evidencia"]["fallback_usado"])
        self.assertEqual("1999-01-01", pcn[0]["evidencia"]["fallback_valor"])

    def test_evidencia_padrao_formato(self):
        ev = evidencia_padrao(campo_esperado="hora_saida", valor_encontrado="(ausente)",
                              fallback_usado=True, fallback_valor="23:59:00", origem="relatorio_checkin_bracell")
        self.assertTrue(ev["fallback_usado"])
        self.assertEqual("23:59:00", ev["fallback_valor"])
        self.assertEqual("hora_saida", ev["campo_esperado"])
        semfb = evidencia_padrao(campo_esperado="perfil_acesso")
        self.assertFalse(semfb["fallback_usado"])

    def test_schema_lateral_cobre_aceite_e_compose_migra_volume_existente(self):
        ddl = (ROOT / "docker/mysql/migrations/002_observabilidade.sql").read_text(
            encoding="utf-8"
        ).lower()
        for tabela in (
            "execucao",
            "execucao_etapa",
            "execucao_evento",
            "fallback_evento",
            "colaborador_identidade",
            "colaborador_alias",
            "oportunidade",
            "oportunidade_historico",
            "notificacao_outbox",
            "saida_linhagem",
        ):
            self.assertIn(f"create table if not exists pdoh_controle.{tabela}", ddl)
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("  migrate:", compose)
        self.assertIn("service_completed_successfully", compose)
        self.assertIn('profiles: ["pipeline"]', compose)
        self.assertIn("fallback_id", ddl)
        trecho_pipeline = compose.split("  pipeline:", 1)[1].split("volumes:", 1)[0]
        self.assertIn("condition: service_healthy", trecho_pipeline)
        self.assertNotIn("service_completed_successfully", trecho_pipeline)

    def test_runtime_tem_permissoes_minimas_no_controle(self):
        script = (ROOT / "docker/mysql/scripts/run-migrations.sh").read_text(
            encoding="utf-8"
        ).lower()
        self.assertIn(
            "grant select, insert, update on pdoh_controle.* to '$pdoh_db_user'@'%'",
            script,
        )
        self.assertNotIn("grant all privileges", script)
        self.assertIn(
            "grant create, alter, drop, index, references on produtos_platina.* "
            "to '$pdoh_migration_user'@'%'",
            script,
        )

    def test_processadores_continuam_protegidos_pelo_manifesto(self):
        # A verificacao detalhada de SHA fica no contrato de replicacao. Este
        # teste explicita o limite arquitetural da nova camada.
        runner = (ROOT / "bracell/run_observado.py").read_text(encoding="utf-8")
        for script in (
            "pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
            "lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
        ):
            self.assertIn(script, runner)
        self.assertIn("subprocess.Popen", runner)


if __name__ == "__main__":
    unittest.main()
