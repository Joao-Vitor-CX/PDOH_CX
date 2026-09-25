"""Fixtures sinteticas; nenhuma conexao externa ou execucao de ETL."""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bracell"))
from src.cadastral_alerts import avaliar_uf_ausente, TIPO_UF_AUSENTE
from src.data_quality import analisar_dataframe, observar_qualidade
from shared.treatment_catalog import CLASSIFICACAO_POR_TIPO, REGRAS_PADRAO


def row(**changes):
    value = dict(nome_colaborador="Pessoa A", usuario="usuario-a", usuario_ativo="sim",
        uf=None, data_dimensao="2026-09-01", data_evolucao="2026-09-10",
        perfil_acesso="PROMOTOR EXCLUSIVO")
    value.update(changes)
    return value


def fixture():
    return pd.DataFrame([row() for _ in range(10)] + [
        row(nome_colaborador="Pessoa B", usuario="usuario-b", uf=" "),
        row(nome_colaborador="Pessoa C", usuario="usuario-c", uf=""),
        row(nome_colaborador="Valido", usuario="valido", uf="CE"),
        row(nome_colaborador="Inativo", usuario="inativo", usuario_ativo="nao"),
    ])


RULE = dict(regra_id="regra-uf-teste", tipo_problema=TIPO_UF_AUSENTE, marca="BRACELL",
    classificacao="ALERTA", status_regra="ATIVA")


class Result:
    rowcount = 1
    lastrowid = 1
    row = None

    def mappings(self):
        return self

    def first(self):
        return self.row


class Sink:
    """Captura os parametros do INSERT real, inclusive historico; sem executar SQL."""
    def __init__(self):
        self.calls = []

    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, parameters):
        self.calls.append((str(statement), parameters.copy()))
        result = Result()
        if "SELECT marca,status_execucao" in str(statement):
            result.row = {"marca": "BRACELL", "status_execucao": "INICIADA"}
        return result


def persisted_fixture():
    engine = Sink()
    with patch.dict("os.environ", {"PDOH_EXECUTION_ID": "UF_TEST"}), patch("src.findings.resolver_classificacao", return_value=RULE), redirect_stdout(io.StringIO()):
        count = observar_qualidade(engine, fixture(), "colaboradores", "colaboradores_ativos_bracell")
    inserts = [params for sql, params in engine.calls if sql.startswith("INSERT INTO pdoh_controle.alerta ")]
    histories = [params for sql, params in engine.calls if sql.startswith("INSERT INTO pdoh_controle.oportunidade_historico ")]
    assert count == len(inserts) == 3
    assert len(histories) == 0
    return dict(regra=RULE, registros=inserts, historicos=histories)


class CadastralTest(unittest.TestCase):
    def test_three_groups_twelve_occurrences_input_unchanged(self):
        frame = fixture()
        before = frame.copy(deep=True)
        result = avaliar_uf_ausente(frame)
        self.assertEqual(3, len(result["alertas"]))
        self.assertEqual([1, 1, 10], sorted(item["evidencia"]["quantidade_ocorrencias"] for item in result["alertas"]))
        for item in result["alertas"]:
            self.assertEqual("ALERTA", item["evidencia"]["classificacao"])
            self.assertEqual("QUALIDADE_CADASTRAL", item["evidencia"]["categoria"])
            self.assertEqual("UF", item["evidencia"]["campo"])
            self.assertEqual("Atualizar cadastro na origem", item["evidencia"]["tratativa"])
        assert_frame_equal(before, frame)

    def test_valid_inactive_unknown_and_other_brand_are_excluded(self):
        frame = pd.DataFrame([row(uf="CE"), row(usuario_ativo="nao"), row(usuario_ativo=None), row(usuario_ativo="talvez"), row(marca="OUTRA")])
        self.assertEqual([], avaliar_uf_ausente(frame)["alertas"])
        self.assertEqual([], avaliar_uf_ausente(fixture(), marca="OUTRA")["alertas"])
        self.assertEqual([], avaliar_uf_ausente(fixture(), tabela_origem="pesquisas")["alertas"])

    def test_snapshot_and_latest_reference_prevent_stale_alerts(self):
        for correction in (dict(uf="SP"), dict(usuario_ativo="nao")):
            frame = pd.DataFrame([row(data_evolucao="2026-09-01"), row(), row(data_dimensao="2026-09-02", **correction)])
            self.assertEqual([], avaliar_uf_ausente(frame)["alertas"])

    def test_alias_estado_missing_schema_empty_source(self):
        state = fixture().rename(columns={"uf": "estado"})
        result = avaliar_uf_ausente(state, tabela_origem="raw_exclusivo_bracell_colaboradores_ativos")
        self.assertEqual(3, len(result["alertas"]))
        self.assertEqual([], avaliar_uf_ausente(state.assign(uf="CE"))["alertas"])
        self.assertEqual("COLUNAS_INSUFICIENTES", avaliar_uf_ausente(state.drop(columns="estado"))["diagnostico"]["motivo"])
        self.assertEqual("FONTE_VAZIA", avaliar_uf_ausente(state.iloc[:0])["diagnostico"]["motivo"])

    def test_same_name_different_users_never_merges(self):
        frame = pd.DataFrame([row(usuario="a"), row(usuario="b")])
        self.assertEqual(2, len(avaliar_uf_ausente(frame)["alertas"]))
        unknown = pd.DataFrame([row(usuario=None, nome_colaborador=None)] * 2)
        self.assertEqual(2, len(avaliar_uf_ausente(unknown)["alertas"]))

    def test_stable_fingerprint_and_limit_is_on_groups_not_occurrences(self):
        frame = fixture()
        first = avaliar_uf_ausente(frame)["alertas"]
        second = avaliar_uf_ausente(frame.iloc[::-1])["alertas"]
        self.assertEqual([item["fingerprint"] for item in first], [item["fingerprint"] for item in second])
        with patch.dict("os.environ", {"PDOH_OBS_MAX_EVIDENCIAS_POR_REGRA": "1"}):
            findings = analisar_dataframe(frame.iloc[:10], "colaboradores", "colaboradores_ativos_bracell")
        uf = [item for item in findings if item["tipo_problema"] == TIPO_UF_AUSENTE]
        self.assertEqual(1, len(uf))
        self.assertEqual(10, uf[0]["evidencia"]["quantidade_ocorrencias"])

    def test_detector_delegates_destination_without_own_rule_resolution(self):
        with patch("src.data_quality.registrar_achado", return_value=3) as sink:
            observar_qualidade(object(), fixture(), "colaboradores", "colaboradores_ativos_bracell")
        self.assertEqual(3, len(sink.call_args.args[1]))
        self.assertTrue(all(row["tipo_problema"] == TIPO_UF_AUSENTE for row in sink.call_args.args[1]))

    def test_persistence_contract_links_alert_rule_and_history_once_per_group(self):
        payload = persisted_fixture()
        self.assertEqual(3, len(payload["registros"]))
        self.assertTrue(all(item["regra_id"] == RULE["regra_id"] for item in payload["registros"]))
        self.assertEqual(12, sum(json.loads(item["evidencia"])["quantidade_ocorrencias"] for item in payload["registros"]))
        self.assertEqual("ALERTA", CLASSIFICACAO_POR_TIPO[TIPO_UF_AUSENTE])
        # Sem impacto comprovado no PDOH: sai da visao operacional e nunca e' oportunidade.
        self.assertEqual("TELEMETRIA", CLASSIFICACAO_POR_TIPO["PESQUISA_CAMPOS_NULOS"])
        self.assertEqual(1, sum(rule["tipo_problema"] == TIPO_UF_AUSENTE for rule in REGRAS_PADRAO))


if __name__ == "__main__":
    if "--emit-fixture" in sys.argv:
        print(json.dumps(persisted_fixture(), ensure_ascii=True, default=str))
    else:
        unittest.main()
