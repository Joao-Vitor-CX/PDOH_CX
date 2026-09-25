"""Resolucao oficial de jornada: vale a jornada VIGENTE NA DATA; versao posterior nunca preenche o passado."""
import unittest

from shared.journey import resolve

CONFIGS = [
    dict(tabela='colaboradores_ativos_bracell', prioridade=1, campo_horas='nome_pai',
         campo_perfil='perfil_acesso', campo_jornada='jornada_trabalho'),
    dict(tabela='raw_exclusivo_bracell_colaboradores_ativos', prioridade=2, campo_horas='nome_do_pai',
         campo_perfil='perfil_de_acesso', campo_jornada='jornada_de_trabalho'),
]
PERFIS = ['PROMOTOR EXCLUSIVO']


def cadastro(usuario, dimensao, horas, *, ativo='Sim', perfil='PROMOTOR EXCLUSIVO'):
    return dict(id=usuario, usuario=usuario, nome_colaborador=f'PESSOA {usuario}', usuario_ativo=ativo,
                perfil_acesso=perfil, nome_pai=horas, jornada_trabalho='CX - JORNADA PADRAO',
                data_dimensao=dimensao, data_evolucao=dimensao)


def resolver(linhas, as_of='2026-09-02'):
    fontes = {'colaboradores_ativos_bracell': linhas, 'raw_exclusivo_bracell_colaboradores_ativos': []}
    return {r['colaborador_chave']: r for r in resolve(fontes, CONFIGS, brand='BRACELL', operation='EXCLUSIVA',
                                                       profiles=PERFIS, as_of=as_of)}


class JornadaDaEpocaTest(unittest.TestCase):
    def test_jornada_vigente_na_data_vale_mesmo_que_mude_depois(self):
        r = resolver([cadastro('1', '2026-09-01', '44'), cadastro('1', '2026-09-15', '24')])['1']
        self.assertEqual(('RESOLVIDA', 44.0, '2026-09-01'), (r['status_resolucao'], r['jornada_semanal'], r['data_referencia']))

    def test_lacuna_na_data_nao_e_preenchida_por_versao_posterior(self):
        # Caso CAMILA: sem horas na epoca, 24H so' em 08/09 -> na semana vale o fallback (NAO_ENCONTRADA).
        r = resolver([cadastro('1', '2026-09-01', None), cadastro('1', '2026-09-08', '24')])['1']
        self.assertEqual(('NAO_ENCONTRADA', None), (r['status_resolucao'], r['jornada_semanal']))
        self.assertNotIn('preenchimento_posterior', r['evidencia'])
        self.assertEqual(['2026-09-01'], [f['data_referencia'] for f in r['evidencia']['fontes_verificadas']])

    def test_colaborador_que_so_entra_depois_nao_existe_no_passado(self):
        self.assertEqual({}, resolver([cadastro('9', '2026-09-22', '44')]))

    def test_inativo_ou_fora_do_perfil_fica_fora_de_escopo(self):
        self.assertEqual('FORA_ESCOPO', resolver([cadastro('1', '2026-09-01', '44', ativo='Nao')])['1']['status_resolucao'])
        self.assertEqual('FORA_ESCOPO', resolver([cadastro('1', '2026-09-01', '44', perfil='GESTOR')])['1']['status_resolucao'])


if __name__ == '__main__':
    unittest.main()
