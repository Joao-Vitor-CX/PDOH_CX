"""Regras de oportunidade CONFIGURADAS: da configuracao a fila, sem regra de negocio no codigo.

    Configuracao -> regra ativa -> motor valida -> criterios atendidos -> oportunidade criada

Usa o executor e o dispatcher REAIS sobre SQLite em memoria; nenhum acesso a MySQL, a Platina
real ou a origem. Os quatro cenarios obrigatorios estao nomeados `test_cenario_N_*`.
"""
from contextlib import redirect_stdout
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import text

from api.app.config import Settings
from api.app.main import create_app
from api.tests.test_api import FixtureDatabase
from api.tests.test_findings import SQLiteWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bracell'))
from src.findings import registrar_achado
from src.regras_configuradas import (
    carregar_fontes, carregar_regras, executar_regras, fonte_primaria, montar_achado,
)

MARCA, OPERACAO = 'BRACELL', 'EXCLUSIVA'
PLATINA = 'exclusivo_bracell_platina_relatorio_pdoh'
STATUS_DAY = 'status_day_operacao_bracell'
DIA = date(2026, 9, 1)
PERIODO = (date(2026, 8, 31), date(2026, 9, 5))


class Motor:
    """Engine minimo: leitura pelo SQLite e escrita pelo adaptador MySQL -> SQLite."""

    def __init__(self, db, writer):
        self.engine, self.writer = db.engine, writer

    def connect(self):
        return self.engine.connect()

    def begin(self):
        return self.writer.begin()


class RegrasConfiguradasTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        self.writer = SQLiteWriter(self.db.engine)
        self.motor = Motor(self.db, self.writer)
        self.db.insert('execucao', execution_id='new-run', marca=MARCA, status_execucao='INICIADA',
                       periodo_inicio=PERIODO[0], periodo_fim=PERIODO[1])
        self.env = patch.dict(os.environ, {'PDOH_EXECUTION_ID': 'new-run', 'PDOH_COMPONENTE': 'TESTE'})
        self.env.start()
        self.leituras = []
        self.dados = {PLATINA: [], STATUS_DAY: []}
        self.jornadas = {}
        self.catalogar()

    def tearDown(self):
        self.env.stop()
        self.db.close()

    # ------------------------------------------------------------------ montagem
    def catalogar(self, tipo='HORAS_AUSENTES'):
        """Catalogo de tratativas (classificacao/impacto/acao): NAO libera nada por si so."""
        self.db.insert('regra_tratativa', regra_id=tipo, marca=MARCA, tipo_problema=tipo,
                       classificacao='OPORTUNIDADE', status_regra='ATIVA', prioridade=10,
                       severidade_padrao='MEDIA', impacto_negocio='Horas não registradas',
                       acao_recomendada='Validar com o colaborador', responsavel_padrao='Lider da operacao')

    def fontes(self):
        self.db.insert('fonte_semantica_configuracao', fonte_id='f-pdoh', marca=MARCA, operacao=OPERACAO,
                       papel='pdoh', tipo='PRINCIPAL', prioridade=1, schema_fisico='produtos_platina',
                       tabela_fisica=PLATINA, status='MAPEADA', descricao='PDOH Platina',
                       usuario_alteracao='teste',
                       mapeamento_campos={'data': 'data', 'colaborador': 'colaborador',
                                          'horas_nao_registradas': 'horas_nao_registradas'})
        self.db.insert('fonte_semantica_configuracao', fonte_id='f-status', marca=MARCA, operacao=OPERACAO,
                       papel='colaborador', tipo='ALTERNATIVA', prioridade=2, schema_fisico='involves_bracell',
                       tabela_fisica=STATUS_DAY, status='MAPEADA', descricao='Status do dia',
                       usuario_alteracao='teste',
                       mapeamento_campos={'data': 'dia_referencia', 'colaborador': 'colaborador',
                                          'afastado': 'afastado', 'tem_roteiro': 'tem_roteiro',
                                          'evolucao': 'data_evolucao'})

    def condicao(self, configuracao, identificador, tipo, ordem, papel, campo, operador, valor, descricao,
                 status='ATIVA'):
        self.db.insert('regra_condicao_configuracao', condicao_id=f'{configuracao}:{identificador}',
                       configuracao_id=configuracao, tipo=tipo, ordem=ordem, papel_fonte=papel,
                       campo_logico=campo, operador=operador, valor_esperado=valor, descricao=descricao,
                       status=status, usuario_alteracao='teste')

    def cadastrar(self, *, status='ATIVA', geracao=True, gera=True, tempo_minimo=0, excecoes=None):
        """HORAS_AUSENTES como esta cadastrada: condicao + as 4 excecoes da tela."""
        self.fontes()
        self.db.ativar_regra('HORAS_AUSENTES', status=status, geracao_automatica=geracao, gera=gera)
        configuracao = f'cfg:{MARCA}:{OPERACAO}:HORAS_AUSENTES'
        if tempo_minimo:
            with self.db.engine.begin() as conexao:
                conexao.execute(text('UPDATE regra_configuracao SET tempo_minimo_minutos=:t '
                                     'WHERE configuracao_id=:c'), dict(t=tempo_minimo, c=configuracao))
        self.condicao(configuracao, 'c1', 'CONDICAO', 1, 'pdoh', 'horas_nao_registradas', 'MAIOR_QUE', '00:00',
                      'Horas não registradas maior que 00:00')
        ativas = excecoes or {'Atestado', 'Afastamento', 'Sem jornada', 'Sem roteiro'}
        for ordem, (nome, papel, campo, operador, valor) in enumerate([
                ('Atestado', 'colaborador', 'afastado', 'CONTEM', 'ATESTADO'),
                ('Afastamento', 'colaborador', 'afastado', 'EM_LISTA', ['FERIADO', 'FOLGA']),
                ('Sem jornada', 'jornada', 'status_resolucao', 'DIFERENTE_DE', 'RESOLVIDA'),
                ('Sem roteiro', 'colaborador', 'tem_roteiro', 'IGUAL_A', False)], start=1):
            self.condicao(configuracao, f'e{ordem}', 'BLOQUEIO', ordem, papel, campo, operador, valor, nome,
                          status='ATIVA' if nome in ativas else 'INATIVA')

    def platina(self, colaborador='ANA', dia=DIA, horas=timedelta(minutes=30)):
        self.dados[PLATINA].append(dict(colaborador=colaborador, data=dia, horas_nao_registradas=horas))

    def dia(self, colaborador='ANA', dia=DIA, *, afastado=None, roteiro='Sim', evolucao=date(2026, 9, 6)):
        self.dados[STATUS_DAY].append(dict(colaborador=colaborador, dia_referencia=dia, afastado=afastado,
                                           tem_roteiro=roteiro, data_evolucao=evolucao))

    def jornada(self, colaborador='ANA', status='RESOLVIDA'):
        self.jornadas[colaborador] = status

    def cenario_normal(self, colaborador='ANA', horas=timedelta(minutes=30)):
        self.platina(colaborador, horas=horas)
        self.dia(colaborador)
        self.jornada(colaborador)

    def leitor(self, fonte, colunas, coluna_data, inicio, fim):
        self.leituras.append(fonte['tabela_fisica'])
        return [dict(linha) for linha in self.dados[fonte['tabela_fisica']]]

    def resolver_jornada(self, dia):
        return [dict(colaborador=nome, status_resolucao=status) for nome, status in self.jornadas.items()]

    def executar(self, **kwargs):
        opcoes = dict(periodo_inicio=PERIODO[0], periodo_fim=PERIODO[1], prefixo='',
                      leitor=self.leitor, resolver_jornada=self.resolver_jornada)
        opcoes.update(kwargs)
        with redirect_stdout(io.StringIO()):
            return executar_regras(self.motor, None, **opcoes)

    # ------------------------------------------------------------------ consultas
    def oportunidades(self):
        with self.db.connection() as c:
            return [dict(l._mapping) for l in c.execute(text(
                'SELECT * FROM oportunidade ORDER BY colaborador, data_referencia'))]

    def eventos(self, codigo=None):
        consulta = 'SELECT codigo, nivel, categoria, contexto FROM execucao_evento'
        params = {}
        if codigo:
            consulta += ' WHERE codigo=:codigo'
            params['codigo'] = codigo
        with self.db.connection() as c:
            linhas = [dict(l._mapping) for l in c.execute(text(consulta + ' ORDER BY id'), params)]
        for linha in linhas:
            if isinstance(linha['contexto'], str):
                linha['contexto'] = json.loads(linha['contexto'])
        return linhas

    def despachar(self, colaborador='ANA', tipo='HORAS_AUSENTES'):
        """Achado comprovado vindo de QUALQUER detector: o dispatcher tem que barrar sozinho."""
        achado = dict(tipo_problema=tipo, marca=MARCA, colaborador=colaborador, origem='TESTE',
                      tabela_origem='fixture', descricao_detalhada='Achado sintetico', severidade='MEDIA',
                      data_referencia=DIA, evidencia={'campo': 'horas_nao_registradas', 'comprovacao': dict(
                          resultado='confirmado', regra=tipo, fonte='PDOH Platina', campo='horas_nao_registradas',
                          jornada_origem='INVOLVES', justificativa=False, atestado=False, motivo=None,
                          verificacoes=[])})
        with redirect_stdout(io.StringIO()):
            return registrar_achado(self.writer, [achado])

    # ================================================================== 4 cenarios obrigatorios
    def test_cenario_1_regra_ativa_e_condicao_atendida_cria_oportunidade(self):
        self.cadastrar()
        self.cenario_normal(horas=timedelta(minutes=30))
        resumo = self.executar()

        regra = resumo['regras'][0]
        self.assertEqual((1, 1, 1), (regra['avaliadas'], regra['confirmadas'], regra['criadas']))
        (oportunidade,) = self.oportunidades()
        self.assertEqual(('HORAS_AUSENTES', 'ANA', 'exclusivo_bracell_platina_relatorio_pdoh'),
                         (oportunidade['tipo_problema'], oportunidade['colaborador'], oportunidade['tabela_origem']))
        evidencia = json.loads(oportunidade['evidencia']) if isinstance(oportunidade['evidencia'], str) \
            else oportunidade['evidencia']
        prova = evidencia['comprovacao']
        # Auditoria: regra, configuracao usada, tabela, campo, valor encontrado e resultado.
        self.assertEqual('confirmado', prova['resultado'])
        self.assertEqual('Oportunidade gerada', prova['resultado_regra'])
        self.assertEqual(('PDOH Platina', PLATINA, 'horas_nao_registradas', '00:30:00'),
                         (prova['fonte'], prova['fonte_tabela'], prova['campo'], prova['encontrado']))
        self.assertEqual(0, prova['configuracao_utilizada']['tempo_minimo_minutos'])
        self.assertEqual({'Atestado', 'Afastamento', 'Sem jornada', 'Sem roteiro'},
                         {e['nome'] for e in prova['configuracao_utilizada']['excecoes'] if e['ativa']})
        self.assertEqual(4, sum(1 for v in prova['verificacoes'] if v['criterio'] == 'excecao'))
        self.assertTrue(self.eventos('REGRA_EXECUTADA'))

    def test_cenario_2_regra_inexistente_nao_cria_oportunidade(self):
        # Sem nenhuma linha de configuracao o executor nao tem o que rodar...
        self.cenario_normal()
        resumo = self.executar()
        self.assertEqual([], resumo['regras'])
        self.assertEqual(0, len(self.oportunidades()))
        self.assertEqual([], self.leituras)
        # ...e, mesmo que um detector produza um achado comprovado, a porta final recusa.
        self.assertEqual(0, self.despachar())
        self.assertEqual(0, len(self.oportunidades()))
        (evento,) = self.eventos('REGRA_NAO_CADASTRADA')
        self.assertEqual(1, evento['contexto']['total'])
        self.assertEqual('HORAS_AUSENTES', evento['contexto']['tipo_problema'])

    def test_cenario_3_regra_inativa_nao_cria_oportunidade(self):
        self.cadastrar(status='INATIVA', geracao=False)
        self.cenario_normal()
        resumo = self.executar()
        self.assertEqual(['HORAS_AUSENTES'], resumo['ignoradas'])
        self.assertEqual([], resumo['regras'])
        self.assertEqual([], self.leituras)           # nem le a fonte: regra desligada nao gasta consulta
        self.assertEqual(0, len(self.oportunidades()))
        self.assertEqual(0, self.despachar())
        self.assertEqual(0, len(self.oportunidades()))
        self.assertEqual(1, len(self.eventos('REGRA_INATIVA')))

    def test_cenario_3b_status_ativa_com_geracao_desligada_tambem_e_inativa(self):
        self.cadastrar(status='ATIVA', geracao=False)
        self.cenario_normal()
        self.assertEqual(['HORAS_AUSENTES'], self.executar()['ignoradas'])
        self.assertEqual(0, self.despachar())
        self.assertEqual(1, len(self.eventos('REGRA_INATIVA')))

    def test_cenario_4_dados_insuficientes_nao_cria_e_registra_indisponibilidade(self):
        self.cadastrar()
        self.platina('ANA', horas=None)                    # campo sem valor na Platina
        self.platina('BIA', horas=timedelta(minutes=40))   # tem valor, mas a fonte das excecoes nao tem o dia
        self.dia('ANA')
        self.jornada('ANA')
        self.jornada('BIA')
        resumo = self.executar()

        regra = resumo['regras'][0]
        self.assertEqual((2, 0, 0), (regra['indisponiveis'], regra['confirmadas'], regra['criadas']))
        self.assertEqual(0, len(self.oportunidades()))
        (evento,) = self.eventos('REGRA_DADOS_INDISPONIVEIS')
        self.assertEqual('ALERTA', evento['nivel'])
        self.assertEqual(2, evento['contexto']['total'])
        self.assertEqual({'ANA', 'BIA'}, {a['colaborador'] for a in evento['contexto']['amostra']})
        self.assertTrue(all(a['motivo'] for a in evento['contexto']['amostra']))

    def test_cenario_4b_sem_origem_a_jornada_fica_indisponivel_e_nao_gera(self):
        self.cadastrar()
        self.cenario_normal()
        resumo = self.executar(resolver_jornada=lambda dia: None)   # origem somente leitura fora do ar
        self.assertEqual((1, 0), (resumo['regras'][0]['indisponiveis'], resumo['regras'][0]['criadas']))
        self.assertEqual(0, len(self.oportunidades()))
        self.assertEqual(1, len(self.eventos('REGRA_DADOS_INDISPONIVEIS')))

    # ================================================================== o motor segue a configuracao
    def test_excecao_aplicada_nao_gera_e_e_registrada(self):
        self.cadastrar()
        self.platina('ANA')
        self.dia('ANA', afastado='CX - ATESTADO MÉDICO 3 DIAS')
        self.jornada('ANA')
        regra = self.executar()['regras'][0]
        self.assertEqual((1, 0, 0), (regra['nao_aplicaveis'], regra['confirmadas'], regra['criadas']))
        self.assertEqual(0, len(self.oportunidades()))
        (evento,) = self.eventos('REGRA_EXCECAO_APLICADA')
        self.assertIn('Atestado', list(evento['contexto']['motivos'])[0])

    def test_cada_excecao_configurada_barra_o_seu_caso(self):
        casos = {'Afastamento': dict(afastado='FERIADO'), 'Sem roteiro': dict(roteiro='Não')}
        for nome, extras in casos.items():
            with self.subTest(excecao=nome):
                self.setUp()
                self.cadastrar()
                self.platina('ANA')
                self.dia('ANA', **extras)
                self.jornada('ANA')
                regra = self.executar()['regras'][0]
                self.assertEqual((1, 0), (regra['nao_aplicaveis'], regra['criadas']), nome)
                self.assertIn(nome, list(regra['motivos_nao_aplicaveis'])[0])
                self.tearDown()
        with self.subTest(excecao='Sem jornada'):
            self.setUp()
            self.cadastrar()
            self.platina('ANA')
            self.dia('ANA')
            self.jornada('ANA', status='NAO_ENCONTRADA')
            regra = self.executar()['regras'][0]
            self.assertEqual((1, 0), (regra['nao_aplicaveis'], regra['criadas']))
            self.tearDown()

    def test_excecao_desmarcada_na_configuracao_deixa_de_barrar(self):
        """"Atestado" desmarcado na tela: o mesmo dia passa a gerar, e a prova mostra isso."""
        self.cadastrar(excecoes={'Afastamento', 'Sem jornada', 'Sem roteiro'})
        self.platina('ANA')
        self.dia('ANA', afastado='CX - ATESTADO MÉDICO 3 DIAS')
        self.jornada('ANA')
        self.assertEqual(1, self.executar()['regras'][0]['criadas'])
        prova = json.loads(self.oportunidades()[0]['evidencia'])['comprovacao']
        atestado = next(e for e in prova['configuracao_utilizada']['excecoes'] if e['nome'] == 'Atestado')
        self.assertFalse(atestado['ativa'])

    def test_tempo_minimo_vem_da_configuracao(self):
        self.cadastrar(tempo_minimo=30)
        self.cenario_normal('ANA', horas=timedelta(minutes=20))     # abaixo: nem e' candidata
        self.cenario_normal('BIA', horas=timedelta(minutes=45))     # acima: gera
        regra = self.executar()['regras'][0]
        self.assertEqual((1, 1), (regra['candidatas'], regra['criadas']))
        (oportunidade,) = self.oportunidades()
        self.assertEqual('BIA', oportunidade['colaborador'])
        prova = json.loads(oportunidade['evidencia'])['comprovacao']
        self.assertEqual((30, '00:45:00'), (prova['configuracao_utilizada']['tempo_minimo_minutos'],
                                            prova['encontrado']))

    def test_valor_da_condicao_vem_da_configuracao(self):
        """Nao ha limite no codigo: trocar o valor na configuracao muda quem e' candidato."""
        self.cadastrar()
        with self.db.engine.begin() as conexao:
            conexao.execute(text("UPDATE regra_condicao_configuracao SET valor_esperado='\"01:00\"' "
                                 "WHERE tipo='CONDICAO'"))
        self.cenario_normal('ANA', horas=timedelta(minutes=30))
        self.cenario_normal('BIA', horas=timedelta(hours=2))
        self.executar()
        self.assertEqual(['BIA'], [o['colaborador'] for o in self.oportunidades()])

    def test_regra_sem_geracao_confirma_mas_nao_cria(self):
        self.cadastrar(gera=False)
        self.cenario_normal()
        regra = self.executar()['regras'][0]
        self.assertEqual((1, 0, False), (regra['confirmadas'], regra['criadas'], regra['gera_oportunidade']))
        self.assertEqual(0, len(self.oportunidades()))
        self.assertEqual(1, len(self.eventos('REGRA_SEM_GERACAO')))

    def test_ensaio_nao_grava_nada(self):
        self.cadastrar()
        self.cenario_normal()
        regra = self.executar(criar=False, registrar=False)['regras'][0]
        self.assertEqual((1, 0), (regra['confirmadas'], regra['criadas']))
        self.assertEqual(0, len(self.oportunidades()))
        self.assertEqual([], self.eventos())

    def test_reexecucao_na_mesma_execucao_nao_duplica(self):
        self.cadastrar()
        self.cenario_normal()
        self.assertEqual(1, self.executar()['regras'][0]['criadas'])
        self.assertEqual(0, self.executar()['regras'][0]['criadas'])
        self.assertEqual(1, len(self.oportunidades()))

    def test_regra_que_cruza_fontes_e_registrada_como_sem_executor(self):
        self.cadastrar()
        configuracao = f'cfg:{MARCA}:{OPERACAO}:HORAS_AUSENTES'
        self.condicao(configuracao, 'c2', 'CONDICAO', 2, 'checkin', 'hora_entrada', 'IS NOT NULL', None,
                      'Entrada registrada')
        self.cenario_normal()
        resumo = self.executar()
        self.assertEqual([], resumo['regras'])
        self.assertEqual('HORAS_AUSENTES', resumo['sem_executor'][0]['regra'])
        self.assertEqual(0, len(self.oportunidades()))
        self.assertEqual(1, len(self.eventos('REGRA_SEM_EXECUTOR_GENERICO')))

    def test_falha_de_leitura_nao_derruba_a_esteira(self):
        self.cadastrar()
        self.cenario_normal()

        def quebrado(*_):
            raise RuntimeError('fonte fora do ar')
        resumo = self.executar(leitor=quebrado)
        self.assertEqual([], resumo['regras'])
        self.assertIn('fonte fora do ar', resumo['erros'][0]['erro'])
        self.assertEqual(0, len(self.oportunidades()))
        self.assertEqual(1, len(self.eventos('REGRAS_CONFIGURADAS_INDISPONIVEL')))

    # ================================================================== leitura de fontes
    def test_status_day_vale_pela_extracao_mais_recente(self):
        """O snapshot do proprio dia costuma vir incompleto: vale a extracao posterior."""
        self.cadastrar()
        self.platina('ANA')
        self.dia('ANA', afastado='CX - ATESTADO MÉDICO 3 DIAS', evolucao=date(2026, 9, 1))
        self.dia('ANA', afastado=None, evolucao=date(2026, 9, 6))
        self.jornada('ANA')
        self.assertEqual(1, self.executar()['regras'][0]['criadas'])

    def test_divergencia_na_mesma_extracao_e_ambiguidade_indisponivel(self):
        self.cadastrar()
        self.platina('ANA')
        self.dia('ANA', afastado=None)
        self.dia('ANA', afastado='FERIADO')
        self.jornada('ANA')
        regra = self.executar()['regras'][0]
        self.assertEqual((1, 0), (regra['indisponiveis'], regra['criadas']))

    def test_nomes_com_caixa_e_espacos_diferentes_sao_a_mesma_pessoa(self):
        self.cadastrar()
        self.platina('ANA  MARIA')
        self.dia('ana maria')
        self.jornada('ANA  MARIA')
        self.assertEqual(1, self.executar()['regras'][0]['criadas'])

    def test_fonte_primaria_e_a_do_papel_da_condicao(self):
        self.cadastrar()
        (regra,) = carregar_regras(self.motor, MARCA, OPERACAO, '')
        fonte, motivo = fonte_primaria(regra, carregar_fontes(self.motor, MARCA, OPERACAO, ''))
        self.assertIsNone(motivo)
        self.assertEqual(PLATINA, fonte['tabela_fisica'])
        self.assertEqual('PDOH Platina', fonte['descricao'])

    def test_fingerprint_e_deterministico_por_regra_colaborador_e_dia(self):
        self.cadastrar()
        (regra,) = carregar_regras(self.motor, MARCA, OPERACAO, '')
        fonte = carregar_fontes(self.motor, MARCA, OPERACAO, '')['pdoh'][0]
        prova = dict(colaborador='ANA', data='2026-09-01', campo='horas_nao_registradas', esperado='x',
                     encontrado='00:30:00', fonte='PDOH Platina')

        def achado(**extras):
            return montar_achado(regra, {**prova, **extras}, marca=MARCA, operacao=OPERACAO, fonte=fonte)
        self.assertEqual(achado()['fingerprint'], achado(encontrado='00:45:00')['fingerprint'])
        self.assertEqual(achado()['fingerprint'], achado(colaborador='ana')['fingerprint'])
        self.assertNotEqual(achado()['fingerprint'], achado(data='2026-09-02')['fingerprint'])

    # ================================================================== a fila reflete so o que esta ativo
    def test_fila_da_api_mostra_a_oportunidade_da_regra_ativa_e_some_ao_desativar(self):
        self.cadastrar()
        self.cenario_normal()
        self.executar()
        clock = patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 9))
        clock.start()
        self.addCleanup(clock.stop)
        client = TestClient(create_app(Settings(token='x' * 40), self.db))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)      # fecha o SQLite so' no fim do teste
        client.headers['Authorization'] = 'Bearer ' + 'x' * 40
        pagina = client.get('/api/v2/oportunidades', params=dict(incluir_legado=False))
        self.assertEqual(200, pagina.status_code, pagina.text)
        self.assertEqual(['HORAS_AUSENTES'], [i['tipo_problema'] for i in pagina.json()['items']])

        # Desativar a regra tira a oportunidade da fila; o registro historico permanece.
        with self.db.engine.begin() as conexao:
            conexao.execute(text("UPDATE regra_configuracao SET status='INATIVA', "
                                 "geracao_automatica_ativa=0 WHERE codigo_interno='HORAS_AUSENTES'"))
        pagina = client.get('/api/v2/oportunidades', params=dict(incluir_legado=False))
        self.assertEqual(0, pagina.json()['total'])
        self.assertEqual(1, len(self.oportunidades()))

    # ================================================================== fase 2: reprocessamento
    def nova_execucao(self, execution_id):
        """Reprocessamento = nova execucao operacional sobre a mesma janela."""
        self.db.insert('execucao', execution_id=execution_id, marca=MARCA, status_execucao='INICIADA',
                       periodo_inicio=PERIODO[0], periodo_fim=PERIODO[1])
        os.environ['PDOH_EXECUTION_ID'] = execution_id

    def historico(self):
        with self.db.connection() as c:
            return [dict(l._mapping) for l in c.execute(text(
                'SELECT oportunidade_id, execution_id, status_anterior, status_novo, acao FROM oportunidade_historico '
                'ORDER BY id'))]

    def fila(self, **params):
        clock = patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 24))
        clock.start()
        self.addCleanup(clock.stop)
        client = TestClient(create_app(Settings(token='x' * 40), self.db))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        client.headers['Authorization'] = 'Bearer ' + 'x' * 40
        resposta = client.get('/api/v2/oportunidades/resumo', params=dict(
            marca=MARCA, periodo='personalizado', periodo_inicio=str(PERIODO[0]), periodo_fim=str(PERIODO[1]),
            **params))
        self.assertEqual(200, resposta.status_code, resposta.text)
        return resposta.json()

    def test_reprocessamento_encerra_ocorrencia_corrigida_com_historico(self):
        self.cadastrar()
        self.cenario_normal('ANA')
        self.cenario_normal('BIA')
        self.executar()
        self.assertEqual({'ANA', 'BIA'}, {g['colaborador'] for g in self.fila()['items']})

        # ANA corrigiu o apontamento (horas zeradas); BIA continua com divergência.
        self.nova_execucao('run-2')
        self.dados[PLATINA] = [dict(colaborador='ANA', data=DIA, horas_nao_registradas=timedelta(0)),
                               dict(colaborador='BIA', data=DIA, horas_nao_registradas=timedelta(minutes=30))]
        regra = self.executar(reconciliar=True)['regras'][0]
        self.assertEqual(1, regra['encerradas'])
        self.assertNotIn('situacao', regra)
        estados = {(o['colaborador'], o['execution_id']): o['status_oportunidade'] for o in self.oportunidades()}
        self.assertEqual({('ANA', 'new-run'): 'ENCERRADA', ('BIA', 'new-run'): 'ABERTA',
                          ('BIA', 'run-2'): 'ABERTA'}, estados)
        encerramento = [h for h in self.historico() if h['acao'] == 'ENCERRADA_REPROCESSAMENTO']
        self.assertEqual([('run-2', 'ABERTA', 'ENCERRADA')],
                         [(h['execution_id'], h['status_anterior'], h['status_novo']) for h in encerramento])
        self.assertEqual(1, len(self.eventos('REPROCESSAMENTO_ENCERRAMENTO')))
        # A Central deixa de mostrar ANA; BIA segue com UMA ocorrência (sem duplicar por execução).
        (grupo,) = self.fila()['items']
        self.assertEqual(('BIA', 1), (grupo['colaborador'], grupo['quantidade']))

    def test_reprocessamento_nao_encerra_o_que_nao_foi_reavaliado(self):
        """Dado ausente na nova leitura não prova correção: a ocorrência continua aberta."""
        self.cadastrar()
        self.cenario_normal('ANA')
        self.executar()
        self.nova_execucao('run-2')
        self.dados[PLATINA] = []
        self.assertEqual(0, self.executar(reconciliar=True)['regras'][0]['encerradas'])
        self.assertEqual(['ABERTA'], [o['status_oportunidade'] for o in self.oportunidades()])

    def test_ensaio_e_execucao_normal_nunca_encerram(self):
        self.cadastrar()
        self.cenario_normal('ANA')
        self.executar()
        self.nova_execucao('run-2')
        self.dados[PLATINA] = [dict(colaborador='ANA', data=DIA, horas_nao_registradas=timedelta(0))]
        self.assertNotIn('encerradas', self.executar(reconciliar=True, criar=False, registrar=False)['regras'][0])
        self.assertNotIn('encerradas', self.executar()['regras'][0])
        self.assertEqual(['ABERTA'], [o['status_oportunidade'] for o in self.oportunidades()])

    # ================================================================== fase 2: checkout + fallback
    VISITAS = 'gerencial_checkin_checkout_bracell'

    def cadastrar_checkout(self, *, jornada_ativa=True):
        from api.tests.test_operational_schedule import add_tables
        from shared.operational_schedule import TABLE
        add_tables(self.db)
        self.fontes()
        self.catalogar('CHECKOUT_AUSENTE')
        self.db.ativar_regra('CHECKOUT_AUSENTE')
        configuracao = f'cfg:{MARCA}:{OPERACAO}:CHECKOUT_AUSENTE'
        with self.db.engine.begin() as c:
            c.execute(self.db.tables[TABLE].insert().values(
                id='j44', configuracao_id=configuracao, marca=MARCA, operacao=OPERACAO, jornada=44,
                hora_entrada_padrao='08:00:00', hora_saida_padrao='18:00:00', ativo=jornada_ativa))
        for papel in ('checkout', 'checkin', 'colaborador'):
            self.db.insert('fonte_semantica_configuracao', fonte_id=f'f-{papel}-visitas', marca=MARCA,
                           operacao=OPERACAO, papel=papel, tipo='PRINCIPAL', prioridade=1,
                           schema_fisico='involves_bracell', tabela_fisica=self.VISITAS, status='MAPEADA',
                           descricao='Involves', usuario_alteracao='teste',
                           mapeamento_campos={'colaborador': 'colaborador', 'data': 'data', 'evolucao': 'evolucao',
                                              'hora_entrada': 'hora_entrada', 'hora_saida': 'hora_saida'})
        # Mesmas exceções que a tela copia de HORAS_AUSENTES, inclusive "Jornada não resolvida".
        for ordem, (nome, papel, campo, operador, valor) in enumerate([
                ('Atestado', 'colaborador', 'afastado', 'CONTEM', 'ATESTADO'),
                ('Sem jornada', 'jornada', 'status_resolucao', 'DIFERENTE_DE', 'RESOLVIDA')], start=1):
            self.condicao(configuracao, f'e{ordem}', 'BLOQUEIO', ordem, papel, campo, operador, valor, nome)
        self.dados[self.VISITAS] = []

    def visita(self, colaborador, *, saida=None, dia=DIA):
        self.dados[self.VISITAS].append(dict(colaborador=colaborador, data=dia, hora_entrada='08:03:00',
                                             hora_saida=saida, evolucao='2026-09-02 05:00:00'))

    def prova_checkout(self, colaborador):
        (oportunidade,) = [o for o in self.oportunidades()
                           if o['colaborador'] == colaborador and o['tipo_problema'] == 'CHECKOUT_AUSENTE']
        evidencia = oportunidade['evidencia']
        return json.loads(evidencia) if isinstance(evidencia, str) else evidencia

    def test_checkout_sem_jornada_na_origem_usa_fallback_44h_rastreavel(self):
        self.cadastrar_checkout()
        self.visita('BIA')
        self.dia('BIA')
        self.jornada('BIA', 'NAO_ENCONTRADA')
        regra = self.executar()['regras'][0]
        self.assertEqual((1, 1, 1), (regra['confirmadas'], regra['criadas'], regra['fallback']))
        evidencia = self.prova_checkout('BIA')
        prova = evidencia['comprovacao']
        self.assertTrue(evidencia['fallback_usado'])
        self.assertEqual('FALLBACK', prova['jornada_origem'])
        self.assertEqual(dict(id='JORNADA_PADRAO_44H', jornada=44.0, hora_entrada_padrao='08:00:00',
                              hora_saida_padrao='19:00:00', origem='FALLBACK'), prova['configuracao_operacional'])
        self.assertEqual((44.0, '19:00'), (prova['jornada_aplicada'], prova['horario_esperado']))
        self.assertIn('jornada padrão 44H', prova['motivo_fallback'])
        self.assertEqual(('BIA', '2026-09-01', 'CHECKOUT_AUSENTE'), (prova['colaborador'], prova['data'], prova['regra']))
        rotulos = [v['rotulo'] for v in prova['verificacoes']]
        self.assertIn('Jornada padrão (fallback)', rotulos)
        self.assertIn('Exceção: Atestado', rotulos)
        self.assertNotIn('Exceção: Sem jornada', rotulos)

    def test_checkout_com_jornada_resolvida_segue_a_configuracao_sem_fallback(self):
        self.cadastrar_checkout()
        self.visita('ANA')
        self.dia('ANA')
        self.resolver_jornada = lambda dia: [dict(colaborador='ANA', status_resolucao='RESOLVIDA', jornada_semanal=44)]
        regra = self.executar(resolver_jornada=self.resolver_jornada)['regras'][0]
        self.assertEqual((1, 0), (regra['criadas'], regra['fallback']))
        evidencia = self.prova_checkout('ANA')
        self.assertFalse(evidencia['fallback_usado'])
        self.assertEqual(('j44', '18:00:00', 'CONFIGURACAO'), tuple(
            evidencia['comprovacao']['configuracao_operacional'][k] for k in ('id', 'hora_saida_padrao', 'origem')))

    def test_fallback_so_quando_a_jornada_nao_foi_encontrada(self):
        self.cadastrar_checkout()
        for nome, status in (('FORA', 'FORA_ESCOPO'), ('CONF', 'CONFLITO'), ('INC', 'RESOLUCAO_INCOMPLETA')):
            self.visita(nome)
            self.dia(nome)
            self.jornada(nome, status)
        self.visita('SEMCADASTRO')          # nem aparece no cadastro de jornada
        self.dia('SEMCADASTRO')
        regra = self.executar()['regras'][0]
        self.assertEqual((0, 0), (regra['criadas'], regra['fallback']))
        self.assertEqual([], self.oportunidades())

    def test_fallback_nao_anula_as_demais_excecoes(self):
        self.cadastrar_checkout()
        self.visita('BIA')
        self.dia('BIA', afastado='CX - ATESTADO MÉDICO')
        self.jornada('BIA', 'NAO_ENCONTRADA')
        self.assertEqual(0, self.executar()['regras'][0]['criadas'])

    def test_porta_final_recusa_fallback_diferente_do_padrao(self):
        from src.operational_schedule import evidence_matches
        prova = dict(configuracao_operacional=dict(id='JORNADA_PADRAO_44H', jornada=44.0, origem='FALLBACK',
                                                   hora_entrada_padrao='08:00:00', hora_saida_padrao='19:00:00'),
                     monitoramento=dict(hora_entrada='08:03:00', hora_saida=None, data='2026-09-01',
                                        evolucao='2026-09-02 05:00:00'))
        self.assertTrue(evidence_matches(None, MARCA, OPERACAO, prova))
        adulterada = dict(prova, configuracao_operacional=dict(prova['configuracao_operacional'],
                                                               hora_saida_padrao='12:00:00'))
        self.assertFalse(evidence_matches(None, MARCA, OPERACAO, adulterada))
        com_saida = dict(prova, monitoramento=dict(prova['monitoramento'], hora_saida='18:40:00'))
        self.assertFalse(evidence_matches(None, MARCA, OPERACAO, com_saida))

    def test_ciclo_checkout_aberto_corrigido_encerrado_e_reaberto(self):
        """Cenário 1: CHECKOUT_AUSENTE aberto. Cenário 2: checkout lançado -> encerrado e fora da Central."""
        self.cadastrar_checkout()
        self.visita('BIA')
        self.dia('BIA')
        self.jornada('BIA', 'NAO_ENCONTRADA')
        self.executar()
        (grupo,) = self.fila(tipo='CHECKOUT_AUSENTE')['items']
        self.assertEqual(('BIA', 'ABERTA', 'FALLBACK', 1), (grupo['colaborador'], grupo['status_operacional'],
                                                          grupo['validacao']['jornada_origem'], grupo['quantidade']))

        # Reprocessar sem correção: nada novo na Central, nada encerrado.
        self.nova_execucao('run-2')
        self.assertEqual(0, self.executar(reconciliar=True)['regras'][0]['encerradas'])
        (grupo,) = self.fila(tipo='CHECKOUT_AUSENTE')['items']
        self.assertEqual(1, grupo['quantidade'])

        # Checkout identificado na nova extração.
        self.nova_execucao('run-3')
        self.dados[self.VISITAS] = []
        self.visita('BIA', saida='18:40:00')
        regra = self.executar(reconciliar=True)['regras'][0]
        self.assertEqual((0, 2), (regra['criadas'], regra['encerradas']))   # as duas gravações anteriores
        self.assertEqual({'ENCERRADA'}, {o['status_oportunidade'] for o in self.oportunidades()})
        self.assertEqual([], self.fila(tipo='CHECKOUT_AUSENTE')['items'])

        # Se a divergência voltar, uma nova gravação aberta traz a oportunidade de volta.
        self.nova_execucao('run-4')
        self.dados[self.VISITAS] = []
        self.visita('BIA')
        self.executar(reconciliar=True)
        (grupo,) = self.fila(tipo='CHECKOUT_AUSENTE')['items']
        self.assertEqual(('BIA', 1), (grupo['colaborador'], grupo['quantidade']))


if __name__ == '__main__':
    unittest.main()
