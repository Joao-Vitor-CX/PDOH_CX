"""Dados sintéticos em memória, sinks substituídos; nunca chama ETL/processador/banco."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from pandas.testing import assert_frame_equal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bracell'))
from src.legacy_fallbacks import observar_fallbacks_entrada
from src.data_quality import observar_qualidade
from src.de_para import resolver_de_para
from api.app.research import assess_field


class OperationalControlledTest(unittest.TestCase):
    def test_checkout_with_checkin_and_without_checkin(self):
        frame = pd.DataFrame([
            dict(colaborador='Com check-in', hora_saida=None, tipo_checkin='Checkin Manual', checkout_sistema=None, checkout_registrado=None, data_roteiro='2026-09-01'),
            dict(colaborador='Sem check-in', hora_saida=None, tipo_checkin='Sem Checkin', checkout_sistema=None, checkout_registrado=None, data_roteiro='2026-09-01'),
        ])
        original, opportunities, fallbacks = frame.copy(deep=True), [], []
        # Com a origem disponivel, a comprovacao roda; sem ela nada vira oportunidade
        # (coberto em test_checkout_sem_origem_nao_gera_oportunidade).
        with patch('src.evidence_context.comprovar_e_registrar', side_effect=lambda _e, _s, rows, **kw: opportunities.extend(rows)), patch('src.legacy_fallbacks.registrar_fallback', side_effect=lambda _, **kw: fallbacks.append(kw)), patch('src.legacy_fallbacks.registrar_evento'):
            observar_fallbacks_entrada(object(), frame, 'checkin', source_engine=object())
        assert_frame_equal(original, frame)
        self.assertEqual(['Com check-in'], [row['colaborador'] for row in opportunities])
        self.assertEqual('CHECKOUT_AUSENTE', opportunities[0]['tipo_problema'])
        self.assertEqual('23:59:00', opportunities[0]['evidencia']['fallback_valor'])
        self.assertTrue(opportunities[0]['evidencia']['fallback_usado'])
        self.assertEqual(2, len(fallbacks)) # observação do legado é distinta da regra de negócio

    def test_checkout_sem_origem_nao_gera_oportunidade(self):
        """Sem fonte para comprovar entrada, roteiro e abono, nao ha cobranca."""
        frame = pd.DataFrame([
            dict(colaborador='Com check-in', hora_saida=None, tipo_checkin='Checkin Manual',
                 checkout_sistema=None, checkout_registrado=None, data_roteiro='2026-09-01'),
        ])
        opportunities, events = [], []
        with patch('src.legacy_fallbacks.registrar_achado', side_effect=lambda _, rows: opportunities.extend(rows)), patch('src.legacy_fallbacks.registrar_fallback'), patch('src.legacy_fallbacks.registrar_evento', side_effect=lambda _, **kw: events.append(kw)):
            observar_fallbacks_entrada(object(), frame, 'checkin')
        self.assertEqual([], opportunities)
        self.assertEqual('ALERTA', next(e for e in events if e['codigo'] == 'COMPROVACAO_SEM_ORIGEM')['nivel'])

    def test_status_day_usa_o_snapshot_mais_recente_do_dia(self):
        """`data_evolucao` e a data da extracao: o snapshot do proprio dia vem incompleto.

        Antes da correcao, a divergencia entre extracoes marcava o par como ambiguo e o
        dia inteiro virava "evidencia indisponivel" — 227 de 297 pares reais perdidos.
        """
        from src.evidence_context import carregar_status_day
        from shared.evidence_config import matriz_de_linhas

        linhas = [
            # Extracao do proprio dia: a entrada ainda nao tinha sido registrada.
            dict(colaborador='ANA', dia_referencia='2026-09-01', tem_roteiro='Sim',
                 primeiro_checkin=None, ultimo_checkout=None, afastado=None,
                 data_evolucao='2026-09-01'),
            # Extracoes seguintes ja trazem o horario real e concordam entre si.
            dict(colaborador='ANA', dia_referencia='2026-09-01', tem_roteiro='Sim',
                 primeiro_checkin='2026-09-01 08:00:52', ultimo_checkout='2026-09-01 18:22:25',
                 afastado=None, data_evolucao='2026-09-02'),
            dict(colaborador='ANA', dia_referencia='2026-09-01', tem_roteiro='Sim',
                 primeiro_checkin='2026-09-01 08:00:52', ultimo_checkout='2026-09-01 18:22:25',
                 afastado=None, data_evolucao='2026-09-03'),
        ]

        class _Conexao:
            def execute(self, *_a, **_k):
                class R:
                    def mappings(self): return self
                    def all(self): return linhas
                return R()
            def __enter__(self): return self
            def __exit__(self, *_a): return False

        class _Engine:
            def connect(self): return _Conexao()

        matriz = matriz_de_linhas([dict(
            marca='BRACELL', operacao='EXCLUSIVA', papel='status_day',
            tabela='status_day_operacao_bracell',
            campos={'colaborador': 'colaborador', 'data': 'dia_referencia', 'roteiro': 'tem_roteiro',
                    'entrada': 'primeiro_checkin', 'saida': 'ultimo_checkout',
                    'afastamento': 'afastado', 'evolucao': 'data_evolucao'})])[('BRACELL', 'EXCLUSIVA')]

        indice = carregar_status_day(_Engine(), matriz)
        registro = indice[('ANA', '2026-09-01')]
        self.assertIsNotNone(registro, 'snapshot antigo nao pode invalidar o par')
        self.assertEqual('2026-09-01 08:00:52', registro['primeiro_checkin'])
        self.assertEqual('2026-09-03', registro['data_evolucao'])

    def test_divergencia_dentro_da_mesma_extracao_continua_ambigua(self):
        """Duas verdades na MESMA extracao nao viram prova: o par fica indisponivel."""
        from src.evidence_context import carregar_status_day
        from shared.evidence_config import matriz_de_linhas

        linhas = [
            dict(colaborador='ANA', dia_referencia='2026-09-01', tem_roteiro='Sim',
                 primeiro_checkin=None, data_evolucao='2026-09-02'),
            dict(colaborador='ANA', dia_referencia='2026-09-01', tem_roteiro='Nao',
                 primeiro_checkin='2026-09-01 08:00:52', data_evolucao='2026-09-02'),
        ]

        class _Conexao:
            def execute(self, *_a, **_k):
                class R:
                    def mappings(self): return self
                    def all(self): return linhas
                return R()
            def __enter__(self): return self
            def __exit__(self, *_a): return False

        class _Engine:
            def connect(self): return _Conexao()

        matriz = matriz_de_linhas([dict(
            marca='BRACELL', operacao='EXCLUSIVA', papel='status_day',
            tabela='status_day_operacao_bracell',
            campos={'colaborador': 'colaborador', 'data': 'dia_referencia', 'roteiro': 'tem_roteiro',
                    'entrada': 'primeiro_checkin', 'evolucao': 'data_evolucao'})])[('BRACELL', 'EXCLUSIVA')]

        self.assertIsNone(carregar_status_day(_Engine(), matriz)[('ANA', '2026-09-01')])

    def test_ceara_normalizes_to_ce_and_xyz_alert_is_retained(self):
        mapping = [dict(valor_origem='Ceara', valor_padronizado='CE')]
        with patch('src.de_para.carregar_de_para', return_value=mapping):
            self.assertEqual('CE', resolver_de_para(object(), 'CADASTRO', 'estado', 'Ceará')['valor_padronizado'])
        frame = pd.DataFrame([dict(colaborador='Pessoa teste', data_visita='2026-09-01', estado=value) for value in ('Ceará', 'XYZ')])
        original, rows = frame.copy(deep=True), []
        with patch('src.data_quality.carregar_de_para', return_value=mapping), patch('src.data_quality.registrar_achado', side_effect=lambda _, data: rows.extend(data)), patch('src.data_quality.registrar_evento'):
            observar_qualidade(object(), frame, 'gerencial_de_visitas', 'gerencial_visitas_bracell')
        self.assertEqual(['XYZ'], [row['evidencia']['valor'] for row in rows if row['tipo_problema']=='DADO_FORA_DO_PADRAO'])
        assert_frame_equal(original, frame)

    def test_research_nulls_required_vs_optional_and_preserved_input(self):
        frame = pd.DataFrame([
            dict(id=1, responsavel=None, data_solicitacao='2026-09-01', data_expiracao='2026-09-05', status='Pendente', data_conclusao=None),
            dict(id=2, responsavel='Pessoa teste', data_solicitacao='2026-09-01', data_expiracao='2026-09-05', status='Pendente', data_conclusao=None),
        ])
        original, rows = frame.copy(deep=True), []
        with patch('src.legacy_fallbacks.registrar_achado', side_effect=lambda _, data: rows.extend(data)), patch('src.legacy_fallbacks.registrar_fallback'), patch('src.legacy_fallbacks.registrar_evento'):
            observar_fallbacks_entrada(object(), frame, 'pesquisas')
        self.assertEqual(1, len(rows))
        self.assertEqual(['responsavel'], rows[0]['evidencia']['campo_esperado'])
        assert_frame_equal(original, frame)

    def test_field_impact_is_contextual_not_every_null_an_opportunity(self):
        for field in ('responsavel', 'status', 'data_expiracao', 'data_solicitacao'):
            self.assertEqual('OPORTUNIDADE', assess_field(field)['classificacao_sugerida'])
        self.assertEqual('ALERTA', assess_field('id')['classificacao_sugerida'])
        self.assertEqual('TELEMETRIA', assess_field('data_conclusao', 'Pendente')['classificacao_sugerida'])
        self.assertEqual('OPORTUNIDADE', assess_field('data_conclusao', 'Respondida')['classificacao_sugerida'])
        self.assertEqual('ALERTA', assess_field('campo_desconhecido')['classificacao_sugerida'])
