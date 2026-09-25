"""Periodo padrao do painel: abre em dados reais sem esconder a escolha do usuario.

Motivo: a Platina so tem 31/08 a 05/09. Em 21/09 a "semana anterior" (14/09 a 19/09) e' uma
janela sem linhas, e o painel inteiro mostrava "Aguardando fonte oficial" na entrada. O modo
`automatico` usa a semana mais recente com dados; qualquer periodo escolhido continua sendo
respeitado, inclusive quando esta vazio -- nesse caso a API informa o que a fonte cobre.
"""
from datetime import date
import unittest
from unittest.mock import patch

# Modulo (nao a classe): o loader do unittest coleta TestCase importado no namespace.
from api.tests import test_pdoh_platform as _suite

SEGUNDA_PROCESSADA, SABADO_PROCESSADO = '2026-08-31', '2026-09-05'


class PeriodoAutomaticoTest(unittest.TestCase):
    # Reaproveita as fixtures da suite do PDOH sem herdar (e reexecutar) os testes dela.
    setUp, tearDown = _suite.PdohPlatformTest.setUp, _suite.PdohPlatformTest.tearDown
    platina, linha = _suite.PdohPlatformTest.platina, _suite.PdohPlatformTest.linha
    semana, get = _suite.PdohPlatformTest.semana, _suite.PdohPlatformTest.get

    @staticmethod
    def relogio(dia):
        return patch('api.app.findings_repository.hoje_local', return_value=dia)

    # ------------------------------------------------------------------ PDOH (Platina)
    def test_automatico_abre_na_semana_mais_recente_com_dados(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=2 * 3600)
        with self.relogio(date(2026, 9, 21)):        # segunda-feira; semana anterior = 14/09-19/09
            resumo = self.get('pdoh/resumo', marca='BRACELL', periodo='automatico')
        self.assertTrue(resumo['disponivel'])
        self.assertTrue(resumo['periodo_automatico'])
        self.assertEqual({'inicio': SEGUNDA_PROCESSADA, 'fim': SABADO_PROCESSADO}, resumo['periodo'])
        self.assertEqual(50.0, resumo['pdoh']['valor'])
        self.assertEqual(SEGUNDA_PROCESSADA, resumo['cobertura']['disponivel_de'])
        self.assertEqual(SABADO_PROCESSADO, resumo['cobertura']['disponivel_ate'])

    def test_periodo_explicito_vazio_nao_e_substituido_e_informa_o_que_a_fonte_cobre(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=2 * 3600)
        with self.relogio(date(2026, 9, 21)):
            resumo = self.get('pdoh/resumo', marca='BRACELL', periodo='semana')
        self.assertFalse(resumo['disponivel'])
        self.assertFalse(resumo['periodo_automatico'])
        self.assertEqual({'inicio': '2026-09-14', 'fim': '2026-09-19'}, resumo['periodo'])
        self.assertIsNone(resumo['pdoh'])
        self.assertEqual('Não há registros oficiais do PDOH no período selecionado.', resumo['motivo'])
        # E' isso que permite a tela dizer "ha dados de 31/08 a 05/09" em vez de "aguardando".
        self.assertEqual(0, resumo['cobertura']['registros_no_periodo'])
        self.assertEqual(SEGUNDA_PROCESSADA, resumo['cobertura']['disponivel_de'])
        self.assertEqual(SABADO_PROCESSADO, resumo['cobertura']['disponivel_ate'])

    def test_semana_parcial_mais_recente_e_a_semana_operacional_inteira(self):
        """Dados ate a quarta-feira: a janela continua sendo segunda a sabado."""
        tabela = self.platina()
        for dia in (date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 9)):
            self.linha(tabela, 'ANA', dia, 3600)
        with self.relogio(date(2026, 9, 21)):
            resumo = self.get('pdoh/resumo', marca='BRACELL', periodo='automatico')
        self.assertEqual({'inicio': '2026-09-07', 'fim': '2026-09-12'}, resumo['periodo'])
        self.assertEqual(3, resumo['cobertura']['dias_no_periodo'])

    def test_automatico_sem_dados_cai_no_padrao_documentado_sem_inventar_janela(self):
        self.platina()                                # fonte acessivel, porem vazia
        with self.relogio(date(2026, 9, 21)):
            resumo = self.get('pdoh/resumo', marca='BRACELL', periodo='automatico')
        self.assertFalse(resumo['disponivel'])
        self.assertFalse(resumo['periodo_automatico'])
        self.assertEqual({'inicio': '2026-09-14', 'fim': '2026-09-19'}, resumo['periodo'])
        self.assertIsNone(resumo['cobertura']['disponivel_ate'])

    def test_automatico_sem_fonte_da_marca_explica_o_motivo(self):
        self.platina('BRACELL')
        with self.relogio(date(2026, 9, 21)):
            resumo = self.get('pdoh/resumo', marca='TANGARA', periodo='automatico')
        self.assertFalse(resumo['disponivel'])
        self.assertEqual('Não há fonte oficial do PDOH acessível para esta marca.', resumo['motivo'])
        self.assertFalse(resumo['cobertura']['acessivel'])

    def test_composicao_evolucao_e_colaborador_usam_a_mesma_janela_automatica(self):
        from api.app.pdoh_repository import codificar_colaborador
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=2 * 3600)
        esperado = {'inicio': SEGUNDA_PROCESSADA, 'fim': SABADO_PROCESSADO}
        with self.relogio(date(2026, 9, 21)):
            composicao = self.get('pdoh/composicao', marca='BRACELL', periodo='automatico')
            evolucao = self.get('pdoh/evolucao', marca='BRACELL', periodo='automatico')
            individual = self.get('pdoh/colaborador/' + codificar_colaborador('BRACELL', 'ANA'),
                                  marca='BRACELL', periodo='automatico')
        self.assertEqual(esperado, composicao['periodo'])
        self.assertEqual(esperado, evolucao['periodo'])
        self.assertEqual(esperado, individual['periodo'])
        self.assertTrue(composicao['disponivel'] and evolucao['disponivel'] and individual['disponivel'])
        self.assertEqual(50.0, individual['pdoh']['valor'])

    def test_filtros_de_colaborador_e_estado_continuam_valendo_na_janela_automatica(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=3 * 3600, estado='CE')
        self.semana(tabela, 'BRUNO', produtividade=1 * 3600, estado='PI')
        with self.relogio(date(2026, 9, 21)):
            geral = self.get('pdoh/resumo', marca='BRACELL', periodo='automatico')
            so_ce = self.get('pdoh/resumo', marca='BRACELL', periodo='automatico', estado='CE')
            so_bruno = self.get('pdoh/resumo', marca='BRACELL', periodo='automatico', colaborador='BRUNO')
        self.assertEqual(50.0, geral['pdoh']['valor'])
        self.assertEqual(75.0, so_ce['pdoh']['valor'])
        self.assertEqual(25.0, so_bruno['pdoh']['valor'])

    # ------------------------------------------------------------------ fila operacional
    def test_fila_automatica_usa_a_ultima_execucao_com_dados_e_ignora_falha_e_validacao(self):
        # A base ja tem uma execucao CONCLUIDA de 31/08 a 05/09. As duas abaixo sao POSTERIORES e
        # nao podem ser escolhidas: uma falhou (nao produziu dado) e a outra e' de validacao.
        self.db.insert('execucao', execution_id='falhou', marca='BRACELL', status_execucao='FALHA_TECNICA',
                       periodo_inicio=date(2026, 9, 7), periodo_fim=date(2026, 9, 12))
        self.db.insert('execucao', execution_id='validacao', marca='BRACELL', status_execucao='CONCLUIDA',
                       periodo_inicio=date(2099, 12, 31), periodo_fim=date(2099, 12, 31))
        self.db.insert('execucao_contexto', execution_id='validacao', marca='BRACELL',
                       finalidade='VALIDACAO', justificativa='teste')
        with self.relogio(date(2026, 9, 21)):
            resumo = self.get('findings/resumo', marca='BRACELL', periodo='automatico')
            fila = self.get('oportunidades/resumo', marca='BRACELL', periodo='automatico')
        self.assertEqual({'inicio': SEGUNDA_PROCESSADA, 'fim': SABADO_PROCESSADO}, resumo['periodo'])
        self.assertEqual(0, fila['total'])          # janela resolvida sem erro, mesmo sem achados

    def test_fila_automatica_sem_nenhuma_execucao_boa_cai_na_semana_anterior(self):
        with self.db.engine.begin() as conexao:
            conexao.exec_driver_sql("UPDATE execucao SET status_execucao='FALHA_TECNICA'")
        with self.relogio(date(2026, 9, 21)):
            resumo = self.get('findings/resumo', marca='BRACELL', periodo='automatico')
        self.assertEqual({'inicio': '2026-09-14', 'fim': '2026-09-19'}, resumo['periodo'])


if __name__ == '__main__':
    unittest.main()
