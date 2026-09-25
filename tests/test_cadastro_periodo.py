"""Cadastro historico: a semana usa o cadastro vigente nela, nao o do dia da execucao."""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bracell'))
from src.data_loader import cadastro_do_periodo, deduplicar_pesquisas  # noqa: E402


def linha(nome, dimensao, *, ativo='Sim', horas=None, jornada='CX - JORNADA PADRAO'):
    evolucao = (pd.Timestamp(dimensao) + pd.Timedelta(days=1)).strftime('%Y-%m-%d')
    return dict(nome_colaborador=nome, usuario_ativo=ativo, nome_pai=horas, jornada_trabalho=jornada,
                perfil_acesso='PROMOTOR EXCLUSIVO', data_dimensao=dimensao, data_evolucao=evolucao)


def cadastro(*registros):
    return pd.DataFrame(list(registros))


class CadastroDoPeriodoTest(unittest.TestCase):
    def setUp(self):
        dias = pd.date_range('2026-08-30', '2026-09-23').strftime('%Y-%m-%d')
        registros = []
        for dia in dias:
            # ANA: ativa o tempo todo, 44H.
            registros.append(linha('ANA', dia, horas='44'))
            # GIZELDA: ativa ate 02/09, depois sai do cadastro.
            if dia <= '2026-09-02':
                registros.append(linha('GIZELDA', dia, horas='44'))
            # CAMILA: sem horas na epoca; 24H so' a partir de 08/09.
            registros.append(linha('CAMILA', dia, horas='24' if dia >= '2026-09-08' else None,
                                   jornada='CX - INTERMITENTE 24H' if dia >= '2026-09-08' else 'CX - JORNADA PADRAO'))
            # MARIA: so' entra em 22/09.
            if dia >= '2026-09-22':
                registros.append(linha('MARIA', dia, horas=None))
            # BETO: inativo no cadastro durante a semana.
            registros.append(linha('BETO', dia, horas='44', ativo='Sim' if dia >= '2026-09-10' else 'Nao'))
        self.df = cadastro(*registros)

    def test_semana_usa_quem_estava_ativo_nela(self):
        resultado, vigencia = cadastro_do_periodo(self.df, '2026-08-31', '2026-09-05')
        self.assertEqual({'ANA', 'CAMILA', 'GIZELDA'}, set(resultado['nome_colaborador']))
        self.assertEqual('PERIODO', vigencia['modo'])
        self.assertEqual('2026-09-01', vigencia['extracoes']['2026-08-31'])      # extracao do proprio dia

    def test_jornada_e_a_da_epoca_nao_a_atual(self):
        resultado, _ = cadastro_do_periodo(self.df, '2026-08-31', '2026-09-05')
        camila = resultado.set_index('nome_colaborador').loc['CAMILA']
        self.assertTrue(pd.isna(camila['nome_pai']))                              # processador aplica o 44H padrao
        self.assertEqual('CX - JORNADA PADRAO', camila['jornada_trabalho'])

    def test_quem_saiu_no_meio_da_semana_usa_o_registro_do_ultimo_dia_ativo(self):
        resultado, _ = cadastro_do_periodo(self.df, '2026-08-31', '2026-09-05')
        gizelda = resultado.set_index('nome_colaborador').loc['GIZELDA']
        self.assertEqual(pd.Timestamp('2026-09-02'), gizelda['data_dimensao'])

    def test_sem_periodo_mantem_o_comportamento_anterior(self):
        resultado, vigencia = cadastro_do_periodo(self.df)
        self.assertEqual('EXTRACAO_MAIS_RECENTE', vigencia['modo'])
        self.assertEqual({'ANA', 'CAMILA', 'MARIA', 'BETO'}, set(resultado['nome_colaborador']))
        self.assertEqual('24', resultado.set_index('nome_colaborador').loc['CAMILA', 'nome_pai'])

    def test_semana_corrente_equivale_ao_cadastro_mais_recente(self):
        corrente, _ = cadastro_do_periodo(self.df, '2026-09-21', '2026-09-23')
        atual, _ = cadastro_do_periodo(self.df)
        self.assertEqual(set(atual['nome_colaborador']), set(corrente['nome_colaborador']))


class PesquisaUnicaTest(unittest.TestCase):
    def test_mesma_pesquisa_em_varias_extracoes_conta_uma_vez_na_versao_mais_recente(self):
        df = pd.DataFrame([
            dict(id=1, status='Pendente', data_evolucao='2026-09-02'),
            dict(id=1, status='Respondida', data_evolucao='2026-09-04'),
            dict(id=2, status='Pendente', data_evolucao='2026-09-02'),
        ])
        resultado = deduplicar_pesquisas(df)
        self.assertEqual(2, len(resultado))
        self.assertEqual('Respondida', resultado.set_index('id').loc[1, 'status'])

    def test_sem_id_nao_altera(self):
        df = pd.DataFrame([dict(status='A'), dict(status='A')])
        self.assertEqual(2, len(deduplicar_pesquisas(df)))


if __name__ == '__main__':
    unittest.main()


class VinculoDoDiaTest(unittest.TestCase):
    def test_so_grava_colaborador_x_dia_com_vinculo(self):
        from src.alch import filtrar_vinculo_do_dia
        df = pd.DataFrame([
            dict(colaborador='GIZELDA', data='2026-09-02'), dict(colaborador='GIZELDA', data='2026-09-03'),
            dict(colaborador='ana ', data='2026-09-03'), dict(colaborador='ZE', data='2026-09-20')])
        ativos = {'2026-09-02': {'GIZELDA', 'ANA'}, '2026-09-03': {'ANA'}}
        resultado, removidas = filtrar_vinculo_do_dia(df, ativos)
        self.assertEqual([('GIZELDA', '2026-09-02'), ('ana ', '2026-09-03'), ('ZE', '2026-09-20')],
                         list(zip(resultado['colaborador'], resultado['data'])))   # 20/09 sem cadastro conhecido: mantido
        self.assertEqual([('GIZELDA', '2026-09-03')], removidas)

    def test_sem_vigencia_nada_muda(self):
        from src.alch import filtrar_vinculo_do_dia
        df = pd.DataFrame([dict(colaborador='A', data='2026-09-03')])
        self.assertEqual((1, []), (len(filtrar_vinculo_do_dia(df, {})[0]), filtrar_vinculo_do_dia(df, {})[1]))

    def test_cadastro_do_periodo_informa_ativos_por_dia(self):
        base = CadastroDoPeriodoTest('test_semana_usa_quem_estava_ativo_nela')
        base.setUp()
        _, vigencia = cadastro_do_periodo(base.df, '2026-08-31', '2026-09-05')
        self.assertIn('GIZELDA', vigencia['ativos_por_dia']['2026-09-02'])
        self.assertNotIn('GIZELDA', vigencia['ativos_por_dia']['2026-09-03'])
        self.assertNotIn('MARIA', set().union(*vigencia['ativos_por_dia'].values()))
