"""Camada v2.1 (PDOH Platform): consolidacao oficial, nunca estimativa.

A Platina sintetica usada aqui reproduz o formato real (TIME por colaborador/dia) para
que a razao de somas do processador seja exercitada de ponta a ponta. Nenhum teste
acessa MySQL, Docker ou o pipeline.
"""
from datetime import date, datetime, timedelta
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import JSON, Column, Date, DateTime, Integer, MetaData, Numeric, String, Table

from api.app.config import Settings
from api.app.main import create_app
from api.app.pdoh_repository import (
    PESOS_EFETIVIDADE, _segundos, codificar_colaborador, janela_anterior,
)
from api.tests.test_api import FixtureDatabase

SEGUNDA, SABADO = date(2026, 8, 31), date(2026, 9, 5)


def hhmmss(segundos):
    return f'{segundos // 3600:02d}:{segundos % 3600 // 60:02d}:{segundos % 60:02d}'


class PdohPlatformTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        self.db.insert('execucao', execution_id='execucao-restrita-1', marca='BRACELL', status_execucao='CONCLUIDA',
                       periodo_inicio=SEGUNDA, periodo_fim=SABADO)
        self.client = TestClient(create_app(Settings(token='x' * 40), self.db))
        self.client.__enter__()
        self.client.headers['Authorization'] = 'Bearer ' + 'x' * 40
        # Relogio fixo: a semana fechada padrao e' 2026-08-31 (seg) a 2026-09-05 (sab).
        self.clock = patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 9))
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.client.__exit__(None, None, None)

    # ------------------------------------------------------------------ fixtures
    def platina(self, marca='BRACELL', nome=None):
        tabela = Table(f'platina_{marca.lower()}', MetaData(),
                       Column('colaborador', String), Column('estado', String),
                       Column('data', Date), Column('nome_do_dia', String),
                       Column('produtividade', String), Column('ocio', String),
                       Column('deslocamento', String), Column('horas_nao_registradas', String),
                       Column('horas_programadas', String),
                       Column('primeiro_checkin', String), Column('ultimo_checkout', String),
                       Column('visitas_diarias', Integer), Column('visitas_diarias_realizadas', Integer),
                       Column('pesquisas_diarias', Integer), Column('pesquisas_diarias_realizadas', Integer),
                       Column('percentual_produtividade', Numeric), Column('percentual_visitas', Numeric),
                       Column('percentual_pesquisas', Numeric), Column('percentual_efetividade', Numeric))
        tabela.create(self.db.engine)
        self.db.tables[f'platina_pdoh:{marca}'] = tabela
        return tabela

    def linha(self, tabela, colaborador, dia, produtividade, programadas=14400, ocio=0,
              deslocamento=0, nao_registradas=0, visitas=(2, 2), pesquisas=(10, 5), estado='SP'):
        with self.db.engine.begin() as conexao:
            conexao.execute(tabela.insert(), dict(
                colaborador=colaborador, estado=estado, data=dia, nome_do_dia='SEGUNDA',
                produtividade=hhmmss(produtividade), ocio=hhmmss(ocio),
                deslocamento=hhmmss(deslocamento), horas_nao_registradas=hhmmss(nao_registradas),
                horas_programadas=hhmmss(programadas),
                primeiro_checkin='08:00:00', ultimo_checkout='12:00:00',
                visitas_diarias=visitas[0], visitas_diarias_realizadas=visitas[1],
                pesquisas_diarias=pesquisas[0], pesquisas_diarias_realizadas=pesquisas[1],
                percentual_produtividade=(produtividade / programadas) if programadas else 0,
                percentual_visitas=(visitas[1] / visitas[0]) if visitas[0] else 0,
                percentual_pesquisas=(pesquisas[1] / pesquisas[0]) if pesquisas[0] else 0,
                percentual_efetividade=0))

    def semana(self, tabela, colaborador, produtividade, **extras):
        for offset in range(6):
            self.linha(tabela, colaborador, SEGUNDA + timedelta(days=offset), produtividade, **extras)

    def get(self, path, **params):
        resposta = self.client.get('/api/v2/' + path, params=params)
        self.assertEqual(200, resposta.status_code, resposta.text)
        return resposta.json()

    # ------------------------------------------------------------------ 1. disponivel
    def test_pdoh_disponivel_devolve_a_razao_de_somas_do_processador(self):
        tabela = self.platina()
        # 4h programadas/dia. Um colaborador entrega 3h, o outro 1h => 4h de 8h = 50%.
        self.semana(tabela, 'ANA', produtividade=3 * 3600)
        self.semana(tabela, 'BRUNO', produtividade=1 * 3600)

        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertTrue(resumo['disponivel'])
        self.assertIsNone(resumo['motivo'])
        self.assertEqual('PLATINA', resumo['fonte'])
        self.assertEqual('percentual_produtividade', resumo['indicador'])
        self.assertEqual(50.0, resumo['pdoh']['valor'])
        self.assertEqual('%', resumo['pdoh']['unidade'])
        # Media simples dos percentuais daria o mesmo aqui; a razao de somas e' o que muda
        # quando as horas programadas diferem -- coberto em test_razao_de_somas...
        self.assertEqual(50.0, resumo['percentual'])          # contrato ja consumido pelo painel
        self.assertEqual({'registros_no_periodo': 12, 'colaboradores_no_periodo': 2,
                          'dias_no_periodo': 6},
                         {chave: resumo['cobertura'][chave] for chave in
                          ('registros_no_periodo', 'colaboradores_no_periodo', 'dias_no_periodo')})

    def test_razao_de_somas_e_nao_media_de_percentuais(self):
        """Jornadas desiguais separam as duas regras: so a oficial pondera por hora."""
        tabela = self.platina()
        # ANA: 8h programadas, 8h produtivas (100%). BRUNO: 2h programadas, 0h (0%).
        self.semana(tabela, 'ANA', produtividade=8 * 3600, programadas=8 * 3600)
        self.semana(tabela, 'BRUNO', produtividade=0, programadas=2 * 3600)
        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertEqual(80.0, resumo['pdoh']['valor'])   # 48h / 60h, regra do processador
        self.assertNotEqual(50.0, resumo['pdoh']['valor'])  # media simples seria 50%

    def test_efetividade_usa_os_pesos_oficiais_quarenta_trinta_trinta(self):
        tabela = self.platina()
        # produtividade 50%, visitas 100%, pesquisas 50% => (50*40 + 100*30 + 50*30)/100 = 65
        self.semana(tabela, 'ANA', produtividade=2 * 3600, visitas=(2, 2), pesquisas=(10, 5))
        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertEqual({'produtividade': 40.0, 'visitas': 30.0, 'pesquisas': 30.0},
                         PESOS_EFETIVIDADE)
        self.assertEqual(65.0, resumo['efetividade']['valor'])

    def test_variacao_compara_com_a_semana_operacional_anterior(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=2 * 3600)                     # 50%
        for offset in range(6):                                                # semana anterior
            self.linha(tabela, 'ANA', SEGUNDA - timedelta(days=7 - offset), 1 * 3600)   # 25%
        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertEqual(25.0, resumo['pdoh']['variacao_periodo_anterior'])
        self.assertEqual(25.0, resumo['variacao_periodo_anterior'])

    def test_janela_anterior_da_semana_operacional_recua_sete_dias(self):
        self.assertEqual((date(2026, 8, 24), date(2026, 8, 29)), janela_anterior(SEGUNDA, SABADO))
        # Janela arbitraria recua o proprio tamanho, sem alinhar em semana.
        self.assertEqual((date(2026, 9, 1), date(2026, 9, 3)),
                         janela_anterior(date(2026, 9, 4), date(2026, 9, 6)))

    # ------------------------------------------------------------------ 2. indisponivel
    def test_indisponivel_nunca_publica_valor_zero_nem_estimado(self):
        sem_marca = self.get('pdoh/resumo')
        self.assertFalse(sem_marca['disponivel'])
        self.assertIsNone(sem_marca['pdoh'])
        self.assertIsNone(sem_marca['percentual'])
        self.assertIsNone(sem_marca['composicao'])
        self.assertIn('informe a marca', sem_marca['motivo'])

        tabela = self.platina()
        vazio = self.get('pdoh/resumo', marca='BRACELL')
        self.assertFalse(vazio['disponivel'])
        self.assertEqual('Não há registros oficiais do PDOH no período selecionado.', vazio['motivo'])

        # Linhas existem, mas sem horas programadas nao ha base: motivo, nunca 0%.
        self.semana(tabela, 'ANA', produtividade=0, programadas=0)
        sem_jornada = self.get('pdoh/resumo', marca='BRACELL')
        self.assertFalse(sem_jornada['disponivel'])
        self.assertIsNone(sem_jornada['pdoh'])
        self.assertIn('horas programadas', sem_jornada['motivo'])

    def test_meta_nao_e_inventada_quando_nao_ha_cadastro(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=2 * 3600)
        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertIsNone(resumo['pdoh']['meta'])
        self.assertIn('Não há meta de PDOH cadastrada', resumo['pdoh']['motivo_meta'])

    def test_oportunidades_nunca_alimentam_o_indicador(self):
        """Fila operacional cheia e Platina vazia continua indisponivel."""
        self.platina()
        self.db.insert('regra_tratativa', regra_id='r1', marca='BRACELL', tipo_problema='CHECKOUT_AUSENTE',
                       classificacao='OPORTUNIDADE', status_regra='ATIVA', prioridade=10)
        for indice in range(5):
            self.db.insert('oportunidade', oportunidade_id=f'o{indice}', execution_id='execucao-restrita-1', marca='BRACELL',
                           regra_id='r1', tipo_problema='CHECKOUT_AUSENTE', status_oportunidade='ABERTA',
                           colaborador='ANA', data_referencia=SEGUNDA, fingerprint=f'f{indice}')
        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertFalse(resumo['disponivel'])
        self.assertIsNone(resumo['percentual'])

    # ------------------------------------------------------------------ 3. composicao
    def test_composicao_bate_com_a_fonte_oficial_e_com_o_resumo(self):
        tabela = self.platina()
        # 4h programadas: 2h produtivas, 1h ocio, 0,5h deslocamento, 0,5h nao registradas.
        self.semana(tabela, 'ANA', produtividade=2 * 3600, ocio=3600,
                    deslocamento=1800, nao_registradas=1800)
        composicao = self.get('pdoh/composicao', marca='BRACELL')
        self.assertTrue(composicao['disponivel'])
        self.assertEqual('PLATINA', composicao['fonte'])
        self.assertEqual(50.0, composicao['produtividade']['valor'])
        self.assertEqual(25.0, composicao['ocio']['valor'])
        self.assertEqual(12.5, composicao['deslocamento']['valor'])
        self.assertEqual(12.5, composicao['horas_nao_registradas']['valor'])
        # O somatorio fecha a jornada programada: nada foi estimado nem sobrou.
        self.assertEqual(100.0, sum(composicao[parte]['valor'] for parte in
                                    ('produtividade', 'ocio', 'deslocamento', 'horas_nao_registradas')))
        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertEqual(composicao['produtividade'], resumo['composicao']['produtividade'])
        self.assertEqual(composicao['ocio'], resumo['indicadores']['ocio'])

    def test_composicao_indisponivel_traz_motivo_e_nenhum_indicador(self):
        self.platina()
        composicao = self.get('pdoh/composicao', marca='BRACELL')
        self.assertFalse(composicao['disponivel'])
        self.assertIsNone(composicao['produtividade'])
        self.assertIsNone(composicao['ocio'])
        self.assertEqual('Não há registros oficiais do PDOH no período selecionado.',
                         composicao['motivo'])

    # ------------------------------------------------------------------ evolucao
    def test_evolucao_entrega_um_ponto_por_dia_na_ordem_da_janela(self):
        tabela = self.platina()
        for offset in range(6):
            self.linha(tabela, 'ANA', SEGUNDA + timedelta(days=offset), (offset + 1) * 1800)
        evolucao = self.get('pdoh/evolucao', marca='BRACELL')
        self.assertTrue(evolucao['disponivel'])
        self.assertEqual('dia', evolucao['granularidade'])
        self.assertEqual([str(SEGUNDA + timedelta(days=offset)) for offset in range(6)],
                         [ponto['periodo'] for ponto in evolucao['pontos']])
        self.assertEqual([12.5, 25.0, 37.5, 50.0, 62.5, 75.0],
                         [ponto['pdoh'] for ponto in evolucao['pontos']])
        # O resumo publica a mesma serie no formato consumido pelo grafico.
        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertEqual([ponto['pdoh'] for ponto in evolucao['pontos']],
                         [ponto['percentual'] for ponto in resumo['evolucao']])

    def test_evolucao_semanal_agrupa_de_segunda_a_sabado(self):
        tabela = self.platina()
        for offset in range(6):
            self.linha(tabela, 'ANA', SEGUNDA - timedelta(days=7 - offset), 1 * 3600)   # 25%
            self.linha(tabela, 'ANA', SEGUNDA + timedelta(days=offset), 3 * 3600)       # 75%
        evolucao = self.get('pdoh/evolucao', marca='BRACELL', granularidade='semana',
                            periodo='personalizado', periodo_inicio='2026-08-24',
                            periodo_fim='2026-09-05')
        self.assertEqual(['2026-08-24', '2026-08-31'], [p['periodo'] for p in evolucao['pontos']])
        self.assertEqual([25.0, 75.0], [p['pdoh'] for p in evolucao['pontos']])
        # Domingo (30/08) nao entra em nenhuma janela operacional.
        self.assertTrue(all(date.fromisoformat(p['fim']).weekday() == 5 for p in evolucao['pontos']))

    def test_evolucao_sem_dado_oficial_nao_devolve_serie_vazia_silenciosa(self):
        self.platina()
        evolucao = self.get('pdoh/evolucao', marca='BRACELL')
        self.assertFalse(evolucao['disponivel'])
        self.assertEqual([], evolucao['pontos'])
        self.assertEqual('Não há registros oficiais do PDOH no período selecionado.',
                         evolucao['motivo'])

    # ------------------------------------------------------------------ 4. colaborador
    def test_colaborador_devolve_somente_os_dados_daquele_colaborador(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=3 * 3600)      # 75%
        self.semana(tabela, 'BRUNO', produtividade=1 * 3600)    # 25%

        identificador = codificar_colaborador('BRACELL', 'ANA')
        ana = self.get(f'pdoh/colaborador/{identificador}', marca='BRACELL')
        self.assertTrue(ana['disponivel'])
        self.assertEqual('ANA', ana['colaborador']['nome'])
        self.assertEqual(75.0, ana['pdoh']['valor'])
        self.assertEqual(75.0, ana['composicao']['produtividade']['valor'])
        self.assertEqual(6, ana['dias_no_periodo'])
        # O consolidado da marca (50%) nao vaza para a visao individual.
        self.assertNotEqual(self.get('pdoh/resumo', marca='BRACELL')['pdoh']['valor'],
                            ana['pdoh']['valor'])

        bruno = self.get('pdoh/colaborador/' + codificar_colaborador('BRACELL', 'BRUNO'), marca='BRACELL')
        self.assertEqual(25.0, bruno['pdoh']['valor'])

    def test_colaborador_nao_expoe_uuid_fingerprint_nem_execution_id(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=3 * 3600)
        self.db.insert('regra_tratativa', regra_id='r1', marca='BRACELL', tipo_problema='CHECKOUT_AUSENTE',
                       classificacao='OPORTUNIDADE', status_regra='ATIVA', prioridade=10,
                       titulo_exibicao='Checkout não registrado', impacto_negocio='Tempo em loja',
                       acao_recomendada='Validar a saída com o colaborador', severidade_padrao='MEDIA',
                       responsavel_padrao='Líder da operação')
        self.db.ativar_regra('CHECKOUT_AUSENTE')   # a fila so mostra regra ativa
        self.db.insert('oportunidade', oportunidade_id='11111111-1111-1111-1111-111111111111',
                       execution_id='execucao-restrita-1', marca='BRACELL', regra_id='r1', tipo_problema='CHECKOUT_AUSENTE',
                       status_oportunidade='ABERTA', colaborador='ANA', data_referencia=SEGUNDA,
                       fingerprint='fp-secreto', severidade='MEDIA')

        resposta = self.client.get('/api/v2/pdoh/colaborador/' + codificar_colaborador('BRACELL', 'ANA'),
                                   params={'marca': 'BRACELL'})
        corpo = resposta.text
        for proibido in ('11111111-1111-1111-1111-111111111111', 'fp-secreto',
                         'execucao-restrita-1', 'fingerprint', 'execution_id', 'oportunidade_id'):
            self.assertNotIn(proibido, corpo)
        impactadores = resposta.json()['impactadores']
        self.assertEqual([{'regra': 'CHECKOUT_AUSENTE', 'titulo': 'Checkout não registrado',
                           'quantidade': 1, 'impacto': 'Tempo em loja',
                           'acao_recomendada': 'Validar a saída com o colaborador',
                           'severidade': 'MEDIA'}], impactadores)

    def test_colaborador_aceita_o_id_interno_da_identidade_sem_devolve_lo(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=3 * 3600)
        self.db.insert('colaborador_identidade', colaborador_id_interno='uuid-interno-1',
                       marca='BRACELL', nome_referencia='ANA')
        resposta = self.get('pdoh/colaborador/uuid-interno-1', marca='BRACELL')
        self.assertEqual('ANA', resposta['colaborador']['nome'])
        self.assertEqual(75.0, resposta['pdoh']['valor'])
        self.assertNotEqual('uuid-interno-1', resposta['colaborador']['id'])
        self.assertEqual(codificar_colaborador('BRACELL', 'ANA'), resposta['colaborador']['id'])

    def test_colaborador_sem_registro_na_fonte_nao_inventa_indicador(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=3 * 3600)
        ausente = self.get('pdoh/colaborador/' + codificar_colaborador('BRACELL', 'CARLOS'), marca='BRACELL')
        self.assertFalse(ausente['disponivel'])
        self.assertIsNone(ausente['pdoh'])
        self.assertEqual([], ausente['impactadores'])

    # ------------------------------------------------------------------ 5. periodo
    def test_periodo_padrao_e_a_semana_fechada_de_segunda_a_sabado(self):
        tabela = self.platina()
        self.semana(tabela, 'ANA', produtividade=2 * 3600)
        self.linha(tabela, 'ANA', date(2026, 9, 6), 4 * 3600)   # domingo: fora da operacao
        resumo = self.get('pdoh/resumo', marca='BRACELL')
        self.assertEqual({'inicio': '2026-08-31', 'fim': '2026-09-05'}, resumo['periodo'])
        self.assertEqual(0, date.fromisoformat(resumo['periodo']['inicio']).weekday())
        self.assertEqual(5, date.fromisoformat(resumo['periodo']['fim']).weekday())
        self.assertEqual(6, resumo['cobertura']['dias_no_periodo'])   # domingo nao entrou
        self.assertEqual(50.0, resumo['pdoh']['valor'])               # domingo nao alterou o valor

    def test_periodo_personalizado_exige_as_duas_datas(self):
        resposta = self.client.get('/api/v2/pdoh/resumo',
                                   params={'marca': 'BRACELL', 'periodo': 'personalizado'})
        self.assertEqual(422, resposta.status_code)

    # ------------------------------------------------------------------ 6. marca
    def test_marca_nao_mistura_operacoes(self):
        bracell = self.platina('BRACELL')
        flora = self.platina('FLORA')
        self.semana(bracell, 'ANA', produtividade=3 * 3600)     # 75%
        self.semana(flora, 'ANA', produtividade=1 * 3600)       # 25%

        self.assertEqual(75.0, self.get('pdoh/resumo', marca='BRACELL')['pdoh']['valor'])
        self.assertEqual(25.0, self.get('pdoh/resumo', marca='FLORA')['pdoh']['valor'])
        # Mesmo nome em duas operacoes: cada visao individual le a sua propria fonte.
        self.assertEqual(75.0, self.get('pdoh/colaborador/' + codificar_colaborador('BRACELL', 'ANA'),
                                        marca='BRACELL')['pdoh']['valor'])
        self.assertEqual(25.0, self.get('pdoh/colaborador/' + codificar_colaborador('FLORA', 'ANA'),
                                        marca='FLORA')['pdoh']['valor'])

    def test_marca_desconhecida_responde_indisponivel_sem_cair_em_outra_fonte(self):
        self.platina('BRACELL')
        tangara = self.get('pdoh/resumo', marca='TANGARA')
        self.assertFalse(tangara['disponivel'])
        self.assertEqual('Não há fonte oficial do PDOH acessível para esta marca.', tangara['motivo'])
        self.assertIsNone(tangara['cobertura']['tabela'])

    def test_resumo_expoe_linhas_diarias_e_filtra_colaborador_estado_sem_recalculo_no_cliente(self):
        tabela = self.platina()
        self.linha(tabela, 'ANA', SEGUNDA, 3 * 3600, estado='SP')
        self.linha(tabela, 'BRUNO', SEGUNDA, 1 * 3600, estado='BA')
        self.db.insert('fallback_evento', fallback_id='fallback-jornada-ana',
                       execution_id='execucao-restrita-1', componente='PDOH',
                       etapa='PROCESSAMENTO_PDOH', codigo='JORNADA_PADRAO_44H',
                       motivo='Jornada ausente', severidade='ALTA',
                       contexto={'colaborador': 'ANA'})

        resumo = self.get('pdoh/resumo', marca='BRACELL', colaborador='ana', estado='SP',
                          periodo='personalizado', periodo_inicio=SEGUNDA, periodo_fim=SEGUNDA)
        self.assertEqual(75.0, resumo['percentual'])
        self.assertEqual(1, resumo['detalhes']['total'])
        linha = resumo['detalhes']['items'][0]
        self.assertEqual(('ANA', 'SP', '2026-08-31'),
                         (linha['colaborador'], linha['estado'], linha['data']))
        self.assertEqual('03:00:00', linha['produtividade'])
        self.assertEqual(0.75, linha['percentuais']['produtividade'])
        self.assertEqual('08:00:00', linha['primeiro_checkin'])
        # Sem resolucao oficial gravada: o evento do processador aparece a parte e nao vira
        # "fallback de jornada" decidido pela resolucao.
        self.assertIsNone(linha['jornada']['houve_fallback'])
        self.assertTrue(linha['jornada']['fallback_processador_pdoh'])
        self.assertEqual('JORNADA_PADRAO_44H', linha['jornada']['origem_fallback'])
        self.assertIn('platina', linha['origem_dado'])
        self.assertEqual(['ANA', 'BRUNO'], resumo['filtros_disponiveis']['colaboradores'])
        self.assertEqual(['BA', 'SP'], resumo['filtros_disponiveis']['estados'])

    # ------------------------------------------------------------------ jornada por linha
    def resolucoes(self, *linhas):
        tabela = Table('jornada_consolidada', MetaData(),
                       Column('resolucao_id', String, primary_key=True), Column('marca', String),
                       Column('colaborador', String), Column('data_referencia', Date), Column('fonte', String),
                       Column('campo', String), Column('status_resolucao', String), Column('jornada_semanal', Numeric),
                       Column('elegivel', Integer), Column('vigente', Integer), Column('evidencia', JSON),
                       Column('registrado_em', DateTime))
        tabela.create(self.db.engine)
        self.db.tables['jornada_consolidada'] = tabela
        with self.db.engine.begin() as conexao:
            for i, linha in enumerate(linhas):
                conexao.execute(tabela.insert(), dict(dict(
                    resolucao_id=str(i), marca='BRACELL', fonte=None, campo=None, jornada_semanal=None,
                    elegivel=1, vigente=1, evidencia={}, registrado_em=datetime(2026, 9, 1, 8)), **linha))

    def test_jornada_da_linha_vem_da_resolucao_oficial_da_data(self):
        tabela = self.platina()
        for nome in ('ANA', 'BIA', 'CAIO', 'DITO', 'EVA'):
            self.linha(tabela, nome, SEGUNDA + timedelta(days=1), 3600)
        involves = dict(fonte='colaboradores_ativos_bracell', campo='nome_pai', status_resolucao='RESOLVIDA')
        self.resolucoes(
            dict(colaborador='ANA', data_referencia=SEGUNDA, jornada_semanal=36, **involves),
            # Versao posterior a data da linha nao vale para ela.
            dict(colaborador='ANA', data_referencia=SABADO, jornada_semanal=24, **involves),
            dict(colaborador='BIA', data_referencia=SEGUNDA, status_resolucao='NAO_ENCONTRADA'),
            # Lacuna preenchida pela versao posterior da mesma fonte.
            dict(colaborador='CAIO', data_referencia=SEGUNDA, jornada_semanal=44, evidencia=dict(
                preenchimento_posterior=dict(data_referencia='2026-09-08')), **involves),
            dict(colaborador='DITO', data_referencia=SEGUNDA, status_resolucao='FORA_ESCOPO', elegivel=0))
        self.db.insert('fallback_evento', fallback_id='proc-eva', execution_id='execucao-restrita-1',
                       componente='PDOH', etapa='PROCESSAMENTO_PDOH', codigo='JORNADA_PADRAO_44H',
                       motivo='Jornada ausente', severidade='ALTA', contexto={'colaborador': 'EVA'})
        itens = {i['colaborador']: i['jornada'] for i in self.get(
            'pdoh/resumo', marca='BRACELL', periodo='personalizado', periodo_inicio=SEGUNDA,
            periodo_fim=SABADO)['detalhes']['items']}
        self.assertEqual(('36H', 'INVOLVES', False, 'RESOLVIDA', '2026-08-31'), tuple(
            itens['ANA'][k] for k in ('jornada_aplicada', 'origem', 'houve_fallback', 'status_resolucao', 'data_resolucao')))
        self.assertIn('colaboradores_ativos_bracell.nome_pai', itens['ANA']['fonte'])
        self.assertEqual(('44H', 'FALLBACK', True, 'JORNADA_PADRAO_44H'), tuple(
            itens['BIA'][k] for k in ('jornada_aplicada', 'origem', 'houve_fallback', 'origem_fallback')))
        self.assertIn('jornada padrão 44H', itens['BIA']['motivo'])
        self.assertEqual(('44H', False), (itens['CAIO']['jornada_aplicada'], itens['CAIO']['houve_fallback']))
        self.assertIn('2026-09-08', itens['CAIO']['motivo'])
        self.assertEqual((None, False), (itens['DITO']['jornada_aplicada'], itens['DITO']['houve_fallback']))
        # Sem cadastro na data: nada de fallback de jornada; o do processador PDOH aparece a parte.
        self.assertEqual((None, None, True), tuple(
            itens['EVA'][k] for k in ('jornada_aplicada', 'houve_fallback', 'fallback_processador_pdoh')))

    def test_periodos_de_validacao_sao_resolvidos_no_backend(self):
        self.platina()
        esperados = {
            'hoje': ('2026-09-09', '2026-09-09'),
            'ontem': ('2026-09-08', '2026-09-08'),
            'ultimos_7_dias': ('2026-09-03', '2026-09-09'),
            'ultimos_30_dias': ('2026-08-11', '2026-09-09'),
            'tres_meses': ('2026-06-01', '2026-08-31'),
            'doze_meses': ('2025-09-01', '2026-08-31'),
        }
        for modo, (inicio, fim) in esperados.items():
            with self.subTest(modo=modo):
                self.assertEqual({'inicio': inicio, 'fim': fim},
                                 self.get('pdoh/resumo', marca='BRACELL', periodo=modo)['periodo'])
        relativo = self.get('pdoh/resumo', marca='BRACELL', periodo='relativo',
                            periodo_quantidade=2, periodo_unidade='semanas')
        self.assertEqual({'inicio': '2026-08-27', 'fim': '2026-09-09'}, relativo['periodo'])

    # ------------------------------------------------------------------ configuracao
    def test_configuracao_operacao_e_somente_leitura_e_publica_os_parametros_oficiais(self):
        self.db.insert('configuracao_operacao', marca='BRACELL', operacao='EXCLUSIVA',
                       descricao='Operacao exclusiva Bracell',
                       fontes_jornada=[{'tabela': 'raw_colaboradores', 'prioridade': 2,
                                        'campo_jornada': 'jornada_de_trabalho'},
                                       {'tabela': 'colaboradores_ativos', 'prioridade': 1,
                                        'campo_jornada': 'jornada_trabalho'}],
                       perfis_operacionais=['PROMOTOR EXCLUSIVO', 'LIDER EXCLUSIVO'],
                       atualizado_em=datetime(2026, 9, 18, 8, 14))
        self.db.insert('regra_fallback_config', id='fb1', marca='BRACELL', regra='CHECKOUT',
                       escopo='MARCA', chave='hora_saida', valor_fallback='23:59',
                       vigencia_inicio=date(2026, 1, 1), status='ATIVO')
        self.db.insert('regra_tratativa', regra_id='r1', marca='BRACELL', tipo_problema='CHECKOUT_AUSENTE',
                       classificacao='OPORTUNIDADE', status_regra='ATIVA', prioridade=10,
                       titulo_exibicao='Checkout não registrado')
        self.db.insert('regra_configuracao', configuracao_id='cfg1', marca='BRACELL',
                       operacao='EXCLUSIVA', nome_regra='Entrada não registrada',
                       codigo_interno='CHECKIN_ENTRADA_AUSENTE', categoria='Jornada',
                       status='EM_VALIDACAO', prioridade=1, geracao_automatica_ativa=False)
        self.db.insert('regra_condicao_configuracao', condicao_id='cond1',
                       configuracao_id='cfg1', tipo='CONDICAO', ordem=1, papel_fonte='checkin',
                       campo_logico='hora_entrada', operador='IS NULL', valor_esperado=None,
                       descricao='Entrada ausente.')
        self.db.insert('regra_tratamento_configuracao', tratamento_id='trat1',
                       configuracao_id='cfg1', resultado='CONFIRMADO',
                       destino='OPORTUNIDADE_FUTURA', gera_oportunidade=False)
        self.db.insert('fonte_semantica_configuracao', fonte_id='fonte1', marca='BRACELL',
                       operacao='EXCLUSIVA', papel='checkin', tipo='PRINCIPAL', prioridade=1,
                       schema_fisico='involves_bracell', tabela_fisica='relatorio_checkin_bracell',
                       mapeamento_campos={'hora_entrada': 'hora_entrada'}, status='MAPEADA')
        self.db.insert('jornada_prioridade_configuracao', etapa_id='etapa1', marca='BRACELL',
                       operacao='EXCLUSIVA', prioridade=1, origem_codigo='INVOLVES',
                       papel_fonte='jornada', fallback=False, status='EM_VALIDACAO',
                       aplicado_no_processamento=False)
        self.db.insert('governanca_configuracao_historico', id=1, marca='BRACELL',
                       operacao='EXCLUSIVA', entidade_tipo='REGRA', entidade_id='cfg1',
                       codigo_referencia='CHECKIN_ENTRADA_AUSENTE', acao='CADASTRO')

        config = self.get('configuracoes/operacao', marca='BRACELL')
        self.assertTrue(config['somente_leitura'])
        self.assertEqual('EXCLUSIVA', config['operacao'])
        # Fontes de jornada na ordem de prioridade que o pipeline respeita.
        self.assertEqual(['colaboradores_ativos', 'raw_colaboradores'],
                         [fonte['tabela'] for fonte in config['jornada']])
        self.assertEqual(['PROMOTOR EXCLUSIVO', 'LIDER EXCLUSIVO'], config['perfis_operacionais'])
        self.assertEqual('23:59', config['fallback'][0]['valor_fallback'])
        self.assertEqual('Checkout não registrado', config['regras'][0]['titulo'])
        self.assertEqual('CHECKIN_ENTRADA_AUSENTE', config['regras_governanca'][0]['codigo_interno'])
        self.assertFalse(config['regras_governanca'][0]['geracao_automatica_ativa'])
        self.assertEqual('checkin', config['regras_governanca'][0]['condicoes'][0]['papel_fonte'])
        self.assertFalse(config['regras_governanca'][0]['tratativas'][0]['gera_oportunidade'])
        self.assertEqual('relatorio_checkin_bracell', config['fontes_semanticas'][0]['tabela_fisica'])
        self.assertFalse(config['prioridade_jornada'][0]['aplicado_no_processamento'])
        self.assertEqual('CADASTRO', config['historico_governanca'][0]['acao'])
        parametros = config['parametros']
        self.assertEqual({'produtividade': 40.0, 'visitas': 30.0, 'pesquisas': 30.0},
                         parametros['pesos_efetividade'])
        self.assertEqual('SUM(produtividade) / SUM(horas_programadas)', parametros['formula_pdoh'])
        self.assertIn('segunda a sabado', parametros['semana_operacional'])
        self.assertIsNone(parametros['meta_pdoh'])

    def test_configuracao_nao_aceita_escrita(self):
        for metodo in (self.client.post, self.client.put, self.client.patch, self.client.delete):
            self.assertIn(metodo('/api/v2/configuracoes/operacao').status_code, (404, 405))

    # ------------------------------------------------------------------ unidades
    def test_conversao_de_tempo_cobre_time_timedelta_texto_e_nulo(self):
        self.assertEqual(0, _segundos(None))
        self.assertEqual(3661, _segundos('01:01:01'))
        self.assertEqual(3661, _segundos(timedelta(hours=1, minutes=1, seconds=1)))
        self.assertEqual(90000, _segundos(timedelta(hours=25)))    # TIME do MySQL passa de 24h
        self.assertEqual(0, _segundos(''))
        self.assertEqual(0, _segundos('nao-e-tempo'))
        self.assertEqual(-3600, _segundos('-01:00:00'))


if __name__ == '__main__':
    unittest.main()
