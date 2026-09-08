import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bracell"))

from src.data_quality import analisar_dataframe  # noqa: E402
from src.identity import normalizar_identificador  # noqa: E402
from src.legacy_fallbacks import observar_fallback_jornada, observar_fallbacks_entrada  # noqa: E402
from src.observability import registrar_evento, registrar_oportunidades  # noqa: E402


class _EngineIndisponivel:
    def begin(self):
        raise RuntimeError("controle indisponivel para teste")


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
        self.assertTrue(
            {
                "CAMPO_OBRIGATORIO_VAZIO",
                "REGISTRO_DUPLICADO",
                "IDENTIFICACAO_COLABORADOR",
                "INCONSISTENCIA_HORARIO",
                "DATA_FORA_DO_PERIODO",
                "DADO_FORA_DO_PADRAO",
            }.issubset(tipos)
        )

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
