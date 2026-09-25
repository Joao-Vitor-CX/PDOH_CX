"""Edicao auditada de regras (PATCH) e o vocabulario de negocio da leitura.

SQLite em memoria; nenhum acesso a MySQL. A conta de escrita real e' coberta pelos testes das
travas (`validate_writer_grants`, `_SQL_PERMITIDO`) e pela verificacao no ambiente local.
"""
from contextlib import contextmanager, redirect_stdout
from datetime import date, datetime
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import MetaData, text

from api.app.config import Settings
from api.app.main import create_app
from api.app.rule_admin import (
    _SQL_PERMITIDO, COLUNAS_EDITAVEIS, refletir_colunas, validate_writer_grants,
)
from api.tests.test_api import FixtureDatabase
from api.tests.test_findings import SQLiteWriter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'bracell'))
from src.findings import registrar_achado

MARCA, OPERACAO, CODIGO = 'BRACELL', 'EXCLUSIVA', 'HORAS_AUSENTES'
CFG = f'cfg:{MARCA}:{OPERACAO}:{CODIGO}'
TOKEN = 'x' * 40
CORPO = dict(usuario='joao.vitor', motivo='Definição de negócio de 21/09/2026')


class FixtureRuleWriter:
    """Mesma superficie de `RuleWriter`, sobre o SQLite do fixture."""
    disponivel = True

    def __init__(self, db):
        self.db, self.tables = db, db.tables

    @contextmanager
    def begin(self):
        with self.db.engine.begin() as conexao:
            yield conexao

    def initialize(self):
        pass

    def close(self):
        pass


def cadastrar_horas_ausentes(db, *, status='ATIVA', geracao=True, gera=True):
    db.insert('configuracao_operacao', marca=MARCA, operacao=OPERACAO, descricao='Operacao exclusiva Bracell',
              fontes_jornada=[], perfis_operacionais=['PROMOTOR EXCLUSIVO'], atualizado_em=datetime(2026, 9, 18, 8))
    db.ativar_regra(CODIGO, status=status, geracao_automatica=geracao, gera=gera)
    db.insert('fonte_semantica_configuracao', fonte_id='f-pdoh', marca=MARCA, operacao=OPERACAO, papel='pdoh',
              tipo='PRINCIPAL', prioridade=1, schema_fisico='produtos_platina',
              tabela_fisica='exclusivo_bracell_platina_relatorio_pdoh', status='MAPEADA',
              descricao='PDOH Platina', usuario_alteracao='teste',
              mapeamento_campos={'data': 'data', 'colaborador': 'colaborador',
                                 'horas_nao_registradas': 'horas_nao_registradas'})

    def condicao(chave, tipo, ordem, papel, campo, operador, valor, nome, status='ATIVA'):
        db.insert('regra_condicao_configuracao', condicao_id=f'{CFG}:{chave}', configuracao_id=CFG, tipo=tipo,
                  ordem=ordem, papel_fonte=papel, campo_logico=campo, operador=operador, valor_esperado=valor,
                  descricao=nome, status=status, usuario_alteracao='teste')
    condicao('c1', 'CONDICAO', 1, 'pdoh', 'horas_nao_registradas', 'MAIOR_QUE', '00:00',
             'Horas não registradas maior que 00:00')
    for ordem, (nome, papel, campo, operador, valor) in enumerate([
            ('Atestado', 'colaborador', 'afastado', 'CONTEM', 'ATESTADO'),
            ('Afastamento', 'colaborador', 'afastado', 'EM_LISTA', ['FERIADO', 'FOLGA']),
            ('Sem jornada', 'jornada', 'status_resolucao', 'DIFERENTE_DE', 'RESOLVIDA'),
            ('Sem roteiro', 'colaborador', 'tem_roteiro', 'IGUAL_A', False)], start=1):
        condicao(f'e{ordem}', 'BLOQUEIO', ordem, papel, campo, operador, valor, nome)


class RuleAdminTest(unittest.TestCase):
    def setUp(self):
        self.db = FixtureDatabase()
        cadastrar_horas_ausentes(self.db)
        self.writer = FixtureRuleWriter(self.db)
        self.client = TestClient(create_app(Settings(token=TOKEN), self.db, self.writer))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.headers['Authorization'] = 'Bearer ' + TOKEN

    # ------------------------------------------------------------------ apoio
    def patch(self, corpo=None, codigo=CODIGO, **params):
        return self.client.patch(f'/api/v2/configuracoes/regras/{codigo}', json={**CORPO, **(corpo or {})},
                                 params={'marca': MARCA, 'operacao': OPERACAO, **params})

    def linha(self, tabela, **filtros):
        onde = ' AND '.join(f'{c}=:{c}' for c in filtros)
        with self.db.connection() as c:
            return [dict(r._mapping) for r in c.execute(text(f'SELECT * FROM {tabela} WHERE {onde}'), filtros)]

    def regra(self):
        return self.linha('regra_configuracao', codigo_interno=CODIGO)[0]

    def historico(self):
        with self.db.connection() as c:
            linhas = [dict(r._mapping) for r in c.execute(text(
                'SELECT * FROM governanca_configuracao_historico ORDER BY id'))]
        for linha in linhas:                       # SQLite devolve JSON como texto; no MySQL ja vem decodificado
            for campo in ('valor_anterior', 'valor_novo'):
                if isinstance(linha[campo], str):
                    linha[campo] = json.loads(linha[campo])
        return linhas

    def config(self):
        resposta = self.client.get('/api/v2/configuracoes/operacao', params={'marca': MARCA})
        self.assertEqual(200, resposta.status_code, resposta.text)
        return resposta.json()

    # ------------------------------------------------------------------ ativar / desativar
    def test_desativar_e_reativar_sincroniza_status_geracao_e_audita(self):
        resposta = self.patch(dict(status='INATIVA'))
        self.assertEqual(200, resposta.status_code, resposta.text)
        corpo = resposta.json()
        self.assertTrue(corpo['alterado'])
        self.assertEqual(('INATIVA', False, False, 'REGRA_INATIVA'),
                         (corpo['regra']['status'], corpo['regra']['ativa'],
                          corpo['regra']['gera_oportunidade'], corpo['regra']['motivo_sem_geracao']))
        self.assertEqual(('INATIVA', 0), (self.regra()['status'], int(self.regra()['geracao_automatica_ativa'])))
        (evento,) = self.historico()
        self.assertEqual(('REGRA', 'ALTERACAO', CODIGO, 'joao.vitor', CORPO['motivo']),
                         (evento['entidade_tipo'], evento['acao'], evento['codigo_referencia'],
                          evento['usuario'], evento['motivo']))
        self.assertEqual('ATIVA', evento['valor_anterior']['status'])
        self.assertEqual('INATIVA', evento['valor_novo']['status'])
        self.assertEqual('joao.vitor', self.regra()['usuario_alteracao'])

        corpo = self.patch(dict(status='ATIVA')).json()
        self.assertEqual((True, True, None), (corpo['regra']['ativa'], corpo['regra']['gera_oportunidade'],
                                              corpo['regra']['motivo_sem_geracao']))
        self.assertEqual(2, len(self.historico()))

    def test_gerar_oportunidade_liga_e_desliga_a_tratativa_confirmada(self):
        corpo = self.patch(dict(gerar_oportunidade=False)).json()
        self.assertEqual((True, False, 'REGRA_SEM_GERACAO'),
                         (corpo['regra']['ativa'], corpo['regra']['gera_oportunidade'],
                          corpo['regra']['motivo_sem_geracao']))
        (tratamento,) = self.linha('regra_tratamento_configuracao', configuracao_id=CFG)
        self.assertFalse(tratamento['gera_oportunidade'])
        self.assertEqual('TRATAMENTO', self.historico()[0]['entidade_tipo'])
        self.assertEqual(('TRATAMENTO', 'Gerar oportunidade', True, False),
                         tuple(corpo['alteracoes'][0][k] for k in ('entidade', 'campo', 'antes', 'depois')))

    def test_tempo_minimo_nome_e_descricao(self):
        corpo = self.patch(dict(tempo_minimo_minutos=30, nome_regra='Horas ausentes',
                                descricao='Horas sem registro no PDOH.')).json()
        self.assertEqual((30, 'Horas ausentes'), (corpo['regra']['tempo_minimo_minutos'],
                                                  corpo['regra']['nome_regra']))
        self.assertEqual(30, self.regra()['tempo_minimo_minutos'])
        campos = {a['campo']: (a['antes'], a['depois']) for a in corpo['alteracoes']}
        self.assertEqual((0, 30), campos['Tempo mínimo (minutos)'])
        (evento,) = self.historico()               # uma linha de historico por entidade, nao por campo
        self.assertEqual(30, evento['valor_novo']['tempo_minimo_minutos'])

    def test_excecoes_marcadas_e_desmarcadas(self):
        corpo = self.patch(dict(excecoes=[dict(ordem=1, ativa=False), dict(ordem=4, ativa=False)])).json()
        situacao = {e['descricao']: e['status'] for e in corpo['regra']['excecoes']}
        self.assertEqual({'Atestado': 'INATIVA', 'Afastamento': 'ATIVA', 'Sem jornada': 'ATIVA',
                          'Sem roteiro': 'INATIVA'}, situacao)
        self.assertEqual({'BLOQUEIO'}, {h['entidade_tipo'] for h in self.historico()})
        self.assertEqual(2, len(self.historico()))
        self.assertEqual({'EXCECAO'}, {a['entidade'] for a in corpo['alteracoes']})

    def test_valores_da_excecao_editados_com_historico(self):
        # Inclusao de uma justificativa (ex.: FTJ) na lista da excecao, pela mesma rota auditada.
        corpo = self.patch(dict(excecoes=[dict(ordem=2, ativa=True, valor=['FERIADO', 'FOLGA', ' FTJ '])])).json()
        linha = self.linha('regra_condicao_configuracao', condicao_id=CFG + ':e2')[0]
        valor = linha['valor_esperado']
        self.assertEqual(['FERIADO', 'FOLGA', 'FTJ'], json.loads(valor) if isinstance(valor, str) else valor)
        self.assertEqual('ATIVA', linha['status'])
        (evento,) = self.historico()
        self.assertEqual('BLOQUEIO', evento['entidade_tipo'])
        self.assertEqual([('EXCECAO', 'Valor')], [(a['entidade'], a['campo']) for a in corpo['alteracoes']])

    def test_valor_de_excecao_invalido_e_recusado_sem_aplicar(self):
        for valor in ([], 'FTJ', [''], [1, 2]):
            with self.subTest(valor=valor):
                resposta = self.patch(dict(excecoes=[dict(ordem=2, ativa=True, valor=valor)]))
                self.assertEqual(422, resposta.status_code)
        self.assertEqual([], self.historico())

    def test_condicao_e_normalizada_e_a_regra_continua_valida(self):
        corpo = self.patch(dict(condicoes=[dict(ordem=1, operador='MAIOR_IGUAL', valor='0:30')])).json()
        condicao = corpo['regra']['condicoes'][0]
        self.assertEqual(('MAIOR_IGUAL', '00:30', 'Maior ou igual a'),
                         (condicao['operador'], condicao['valor_esperado'], condicao['operador_rotulo']))
        self.assertEqual('Horas não registradas maior ou igual a 00:30', condicao['texto'])

    def test_sem_mudanca_real_nao_gera_historico(self):
        corpo = self.patch(dict(status='ATIVA', tempo_minimo_minutos=0)).json()
        self.assertEqual((False, []), (corpo['alterado'], corpo['alteracoes']))
        self.assertEqual([], self.historico())

    # ------------------------------------------------------------------ recusas (tudo ou nada)
    def test_valor_invalido_recusa_e_nao_aplica_nada_do_pedido(self):
        resposta = self.patch(dict(status='INATIVA', tempo_minimo_minutos=45,
                                   condicoes=[dict(ordem=1, operador='MAIOR_QUE', valor='abc')]))
        self.assertEqual(422, resposta.status_code)
        self.assertIn('HH:MM', resposta.json()['detail'])
        self.assertEqual(('ATIVA', 0), (self.regra()['status'], self.regra()['tempo_minimo_minutos']))
        self.assertEqual([], self.historico())

    def test_operador_fora_do_cardapio_do_campo_e_recusado(self):
        for operador in ('CONTEM', 'EM_LISTA', 'MENOR_QUE_CAMPO', 'DROP TABLE'):
            with self.subTest(operador=operador):
                resposta = self.patch(dict(condicoes=[dict(ordem=1, operador=operador, valor='00:10')]))
                self.assertEqual(422, resposta.status_code)
        self.assertEqual('MAIOR_QUE', self.linha('regra_condicao_configuracao', condicao_id=CFG + ':c1')[0]['operador'])

    def test_condicao_ou_excecao_inexistente_e_recusada(self):
        self.assertEqual(422, self.patch(dict(condicoes=[dict(ordem=9, operador='MAIOR_QUE', valor='00:10')])).status_code)
        self.assertEqual(422, self.patch(dict(excecoes=[dict(ordem=9, ativa=False)])).status_code)
        self.assertEqual([], self.historico())

    def test_regra_inexistente_nao_e_criada(self):
        resposta = self.patch(dict(status='ATIVA'), codigo='REGRA_INVENTADA')
        self.assertEqual(404, resposta.status_code)
        self.assertEqual([], self.linha('regra_configuracao', codigo_interno='REGRA_INVENTADA'))
        self.assertEqual(404, self.patch(dict(status='ATIVA'), marca='OUTRA').status_code)

    def test_ativar_exige_condicao_ativa(self):
        with self.db.engine.begin() as c:
            c.execute(text("UPDATE regra_condicao_configuracao SET status='INATIVA' WHERE tipo='CONDICAO'"))
            c.execute(text("UPDATE regra_configuracao SET status='INATIVA', geracao_automatica_ativa=0"))
        resposta = self.patch(dict(status='ATIVA'))
        self.assertEqual(422, resposta.status_code)
        self.assertIn('condição ativa', resposta.json()['detail'])
        self.assertEqual('INATIVA', self.regra()['status'])

    def test_corpo_invalido(self):
        casos = {
            'motivo curto': dict(motivo='ok'),
            'sem usuario valido': dict(usuario='  '),
            'usuario com caracteres estranhos': dict(usuario="x'; DROP--"),
            'tempo negativo': dict(tempo_minimo_minutos=-1),
            'tempo absurdo': dict(tempo_minimo_minutos=99999),
            'status livre': dict(status='EM_VALIDACAO'),
            'campo que nao se edita': dict(codigo_interno='OUTRA'),
            'marca no corpo': dict(marca='OUTRA'),
        }
        for nome, extra in casos.items():
            with self.subTest(nome):
                self.assertEqual(422, self.patch({'status': 'INATIVA', **extra}).status_code, nome)
        # Sem nada a alterar tambem e' recusado.
        resposta = self.client.patch(f'/api/v2/configuracoes/regras/{CODIGO}', json=CORPO,
                                     params={'marca': MARCA})
        self.assertEqual(422, resposta.status_code)
        self.assertEqual('ATIVA', self.regra()['status'])

    def test_exige_token_e_conta_de_edicao(self):
        anonimo = TestClient(create_app(Settings(token=TOKEN), self.db, self.writer))
        self.assertEqual(401, anonimo.patch(f'/api/v2/configuracoes/regras/{CODIGO}', json=dict(CORPO, status='INATIVA'),
                                            params={'marca': MARCA}).status_code)
        somente_leitura = TestClient(create_app(Settings(token=TOKEN), self.db))       # sem conta de edicao
        somente_leitura.headers['Authorization'] = 'Bearer ' + TOKEN
        resposta = somente_leitura.patch(f'/api/v2/configuracoes/regras/{CODIGO}',
                                         json=dict(CORPO, status='INATIVA'), params={'marca': MARCA})
        self.assertEqual(503, resposta.status_code)
        self.assertEqual('ATIVA', self.regra()['status'])

    def test_o_endpoint_de_leitura_continua_somente_leitura(self):
        for metodo in (self.client.post, self.client.put, self.client.patch, self.client.delete):
            self.assertIn(metodo('/api/v2/configuracoes/operacao').status_code, (404, 405))
        self.assertEqual(405, self.client.delete(f'/api/v2/configuracoes/regras/{CODIGO}').status_code)
        self.assertEqual(405, self.client.post(f'/api/v2/configuracoes/regras/{CODIGO}').status_code)

    # ------------------------------------------------------------------ leitura para a tela
    def test_leitura_traz_estado_fonte_e_vocabulario_de_negocio(self):
        (regra,) = self.config()['regras_governanca']
        self.assertEqual((True, True, None, 0), (regra['ativa'], regra['gera_oportunidade'],
                                                 regra['motivo_sem_geracao'], regra['tempo_minimo_minutos']))
        self.assertEqual(dict(papel='pdoh', rotulo='PDOH Platina', tabela='exclusivo_bracell_platina_relatorio_pdoh',
                              campo='horas_nao_registradas', campo_rotulo='Horas não registradas'), regra['fonte'])
        (condicao,) = regra['condicoes']
        self.assertEqual(('Horas não registradas', 'Maior que', 'Horas não registradas maior que 00:00', True),
                         (condicao['campo_rotulo'], condicao['operador_rotulo'], condicao['texto'],
                          condicao['editavel']))
        self.assertIn('MAIOR_IGUAL', [o['codigo'] for o in condicao['operadores']])
        self.assertEqual(['Atestado', 'Afastamento', 'Sem jornada', 'Sem roteiro'],
                         [e['descricao'] for e in regra['excecoes']])

    def test_leitura_reflete_a_edicao_imediatamente(self):
        self.patch(dict(status='INATIVA'))
        (regra,) = self.config()['regras_governanca']
        self.assertEqual((False, False), (regra['ativa'], regra['gera_oportunidade']))
        self.assertEqual('ALTERACAO', self.config()['historico_governanca'][0]['acao'])

    # ------------------------------------------------------------------ efeito na fila
    def test_desativar_pela_tela_tira_a_oportunidade_da_fila_e_reativar_devolve(self):
        self.db.insert('execucao', execution_id='run', marca=MARCA, status_execucao='INICIADA',
                       periodo_inicio=date(2026, 9, 1), periodo_fim=date(2026, 9, 5))
        self.db.insert('regra_tratativa', regra_id=CODIGO, marca=MARCA, tipo_problema=CODIGO,
                       classificacao='OPORTUNIDADE', status_regra='ATIVA', prioridade=10, severidade_padrao='MEDIA',
                       impacto_negocio='Horas não registradas', acao_recomendada='Validar',
                       responsavel_padrao='Lider da operacao')
        achado = dict(tipo_problema=CODIGO, marca=MARCA, colaborador='ANA', origem='PDOH_PLATINA',
                      tabela_origem='exclusivo_bracell_platina_relatorio_pdoh', descricao_detalhada='x',
                      severidade='MEDIA', data_referencia=date(2026, 9, 1),
                      evidencia={'campo': 'horas_nao_registradas', 'comprovacao': dict(
                          resultado='confirmado', regra=CODIGO, fonte='PDOH Platina', campo='horas_nao_registradas',
                          jornada_origem='INVOLVES', justificativa=False, atestado=False, motivo=None, verificacoes=[])})
        with patch.dict(os.environ, {'PDOH_EXECUTION_ID': 'run'}), redirect_stdout(io.StringIO()):
            self.assertEqual(1, registrar_achado(SQLiteWriter(self.db.engine), [achado]))
        with patch('api.app.findings_repository.hoje_local', return_value=date(2026, 9, 9)):
            def fila():
                resposta = self.client.get('/api/v2/oportunidades/resumo', params=dict(incluir_legado=False))
                self.assertEqual(200, resposta.status_code, resposta.text)
                return resposta.json()['total']
            self.assertEqual(1, fila())
            self.patch(dict(status='INATIVA'))
            self.assertEqual(0, fila())
            self.patch(dict(status='ATIVA'))
            self.assertEqual(1, fila())


class CriarRegraTest(unittest.TestCase):
    """POST /api/v2/configuracoes/regras: sem configuração, não existe oportunidade."""

    def setUp(self):
        self.db = FixtureDatabase()
        cadastrar_horas_ausentes(self.db)          # modelo cujas 4 exceções viram o template
        self.writer = FixtureRuleWriter(self.db)
        self.client = TestClient(create_app(Settings(token=TOKEN), self.db, self.writer))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.headers['Authorization'] = 'Bearer ' + TOKEN

    def linha(self, tabela, **filtros):
        onde = ' AND '.join(f'{c}=:{c}' for c in filtros)
        with self.db.connection() as c:
            return [dict(r._mapping) for r in c.execute(text(f'SELECT * FROM {tabela} WHERE {onde}'), filtros)]

    def criar(self, corpo=None, **params):
        base = dict(usuario='joao.vitor', motivo='Nova oportunidade pela tela de Configurações.',
                    nome_regra='Ócio acima do limite', descricao='Ócio maior que o tolerado no dia.',
                    papel_fonte='pdoh', campo_logico='ocio', operador='MAIOR_QUE', valor='01:00',
                    excecoes=[1, 3], status='ATIVA', gerar_oportunidade=True)
        return self.client.post('/api/v2/configuracoes/regras', json={**base, **(corpo or {})},
                                params={'marca': MARCA, 'operacao': OPERACAO, **params})

    def test_cria_com_codigo_derivado_do_nome_condicao_e_excecoes_marcadas(self):
        resposta = self.criar()
        self.assertEqual(200, resposta.status_code, resposta.text)
        corpo = resposta.json()
        self.assertTrue(corpo['criado'])
        regra = corpo['regra']
        self.assertEqual('OCIO_ACIMA_DO_LIMITE', regra['codigo_interno'])
        self.assertEqual((True, True, 2), (regra['ativa'], regra['gera_oportunidade'], regra['prioridade']))
        (condicao,) = regra['condicoes']
        self.assertEqual(('pdoh', 'ocio', 'MAIOR_QUE', '01:00'),
                         (condicao['papel_fonte'], condicao['campo_logico'], condicao['operador'],
                          condicao['valor_esperado']))
        situacao = {e['descricao']: e['status'] for e in regra['excecoes']}
        # Excecoes 1 e 3 do modelo foram marcadas; as demais vieram desligadas.
        self.assertEqual(2, sum(1 for s in situacao.values() if s == 'ATIVA'))
        self.assertEqual(4, len(situacao))
        self.assertTrue(next(t['gera_oportunidade'] for t in regra['tratativas'] if t['resultado'] == 'CONFIRMADO'))
        # Banco: 1 regra nova + 1 condicao + 4 excecoes + 3 tratativas = 9 linhas de historico CADASTRO.
        historico = self.linha('governanca_configuracao_historico', codigo_referencia='OCIO_ACIMA_DO_LIMITE')
        self.assertEqual(9, len(historico))
        self.assertTrue(all(h['acao'] == 'CADASTRO' for h in historico))
        self.assertTrue(all(h['usuario'] == 'joao.vitor' for h in historico))

    def test_codigo_duplicado_ganha_sufixo(self):
        primeiro = self.criar().json()
        segundo = self.criar().json()          # mesmo nome -> mesmo slug de base
        self.assertEqual('OCIO_ACIMA_DO_LIMITE', primeiro['regra']['codigo_interno'])
        self.assertEqual('OCIO_ACIMA_DO_LIMITE_2', segundo['regra']['codigo_interno'])

    def test_sem_configuracao_nao_ha_oportunidade__estado_vazio_antes_de_criar(self):
        """Só HORAS_AUSENTES (o modelo) existe antes da criação; nenhuma outra regra aparece."""
        antes = self.client.get('/api/v2/configuracoes/operacao', params={'marca': MARCA}).json()
        self.assertEqual(['HORAS_AUSENTES'], [r['codigo_interno'] for r in antes['regras_governanca']])
        self.criar()
        depois = self.client.get('/api/v2/configuracoes/operacao', params={'marca': MARCA}).json()
        self.assertEqual({'HORAS_AUSENTES', 'OCIO_ACIMA_DO_LIMITE'},
                         {r['codigo_interno'] for r in depois['regras_governanca']})

    def test_criada_inativa_nao_gera_e_ativa_gera(self):
        inativa = self.criar(dict(status='INATIVA')).json()['regra']
        self.assertEqual((False, False), (inativa['ativa'], inativa['gera_oportunidade']))
        ativa = self.criar(dict(nome_regra='Deslocamento excessivo')).json()['regra']
        self.assertEqual((True, True), (ativa['ativa'], ativa['gera_oportunidade']))

    def test_campo_fora_do_vocabulario_e_recusado_e_nada_e_gravado(self):
        resposta = self.criar(dict(papel_fonte='pdoh', campo_logico='campo_inventado'))
        self.assertEqual(422, resposta.status_code)
        self.assertEqual([], self.linha('regra_configuracao', codigo_interno='OCIO_ACIMA_DO_LIMITE'))

    def test_operador_incompativel_com_o_tipo_do_campo_e_recusado(self):
        # 'ocio' e' duracao: CONTEM nao se aplica.
        resposta = self.criar(dict(operador='CONTEM'))
        self.assertEqual(422, resposta.status_code)
        self.assertEqual([], self.linha('regra_configuracao', codigo_interno='OCIO_ACIMA_DO_LIMITE'))

    def test_valor_invalido_e_recusado(self):
        resposta = self.criar(dict(valor='abc'))
        self.assertEqual(422, resposta.status_code)
        self.assertIn('HH:MM', resposta.json()['detail'])

    def test_excecao_fora_do_modelo_e_recusada(self):
        resposta = self.criar(dict(excecoes=[1, 9]))
        self.assertEqual(422, resposta.status_code)

    def test_nome_curto_e_recusado_pelo_contrato(self):
        self.assertEqual(422, self.criar(dict(nome_regra='ab')).status_code)
        self.assertEqual(422, self.criar(dict(descricao='')).status_code)

    def test_sem_conta_de_edicao_a_criacao_e_recusada(self):
        somente_leitura = TestClient(create_app(Settings(token=TOKEN), self.db))
        somente_leitura.headers['Authorization'] = 'Bearer ' + TOKEN
        resposta = somente_leitura.post('/api/v2/configuracoes/regras', json=dict(
            usuario='joao.vitor', motivo='x', nome_regra='Nova regra', descricao='Descrição válida.',
            papel_fonte='pdoh', campo_logico='ocio', operador='MAIOR_QUE', valor='01:00',
            excecoes=[], status='INATIVA'), params={'marca': MARCA})
        self.assertEqual(503, resposta.status_code)

    def test_regra_criada_pode_ser_editada_pela_mesma_rota_de_sempre(self):
        codigo = self.criar().json()['regra']['codigo_interno']
        resposta = self.client.patch(f'/api/v2/configuracoes/regras/{codigo}',
                                     json=dict(usuario='joao.vitor', motivo='ajuste', status='INATIVA'),
                                     params={'marca': MARCA, 'operacao': OPERACAO})
        self.assertEqual(200, resposta.status_code, resposta.text)
        self.assertFalse(resposta.json()['regra']['ativa'])


class TravasDaContaDeEdicaoTest(unittest.TestCase):
    """A conta de escrita so' pode o que `atualizar_regra` faz, e a API recusa a que puder mais."""

    def grants(self, *extras, sem=()):
        colunas = lambda tabela: ', '.join(f'`{c}`' for c in COLUNAS_EDITAVEIS[tabela])
        base = ['GRANT USAGE ON *.* TO `pdoh_cx_config`@`%`']
        base += ['GRANT SELECT ON `pdoh_controle`.`jornada_consolidada` TO `pdoh_cx_config`@`%`']
        for tabela in COLUNAS_EDITAVEIS:
            if tabela in sem:
                continue
            base += [f'GRANT SELECT, INSERT, UPDATE ({colunas(tabela)}) ON `pdoh_controle`.`{tabela}` '
                     'TO `pdoh_cx_config`@`%`']
        base += ['GRANT INSERT ON `pdoh_controle`.`governanca_configuracao_historico` TO `pdoh_cx_config`@`%`']
        return base + list(extras)

    def test_conta_exata_e_aceita(self):
        validate_writer_grants(self.grants())

    def test_privilegios_separados_por_linha_tambem_sao_aceitos(self):
        linhas = ['GRANT USAGE ON *.* TO `u`@`%`',
                  'GRANT SELECT ON `pdoh_controle`.`jornada_consolidada` TO `u`@`%`',
                  'GRANT INSERT ON `pdoh_controle`.`governanca_configuracao_historico` TO `u`@`%`']
        for tabela, colunas in COLUNAS_EDITAVEIS.items():
            linhas += [f'GRANT SELECT ON `pdoh_controle`.`{tabela}` TO `u`@`%`',
                       f'GRANT INSERT ON `pdoh_controle`.`{tabela}` TO `u`@`%`',
                       'GRANT UPDATE (' + ', '.join(f'`{c}`' for c in colunas) + f') ON `pdoh_controle`.`{tabela}` TO `u`@`%`']
        validate_writer_grants(linhas)

    def test_recusa_qualquer_excesso(self):
        excessos = [
            'GRANT DELETE ON `pdoh_controle`.`regra_configuracao` TO `u`@`%`',
            'GRANT UPDATE ON `pdoh_controle`.`regra_configuracao` TO `u`@`%`',                 # tabela inteira
            'GRANT UPDATE (`codigo_interno`) ON `pdoh_controle`.`regra_configuracao` TO `u`@`%`',
            'GRANT INSERT (`marca`) ON `pdoh_controle`.`regra_configuracao` TO `u`@`%`',       # INSERT parcial
            'GRANT SELECT ON `pdoh_controle`.`oportunidade` TO `u`@`%`',
            'GRANT SELECT ON `pdoh_controle`.* TO `u`@`%`',
            'GRANT UPDATE ON `produtos_platina`.`exclusivo_bracell_platina_relatorio_pdoh` TO `u`@`%`',
            'GRANT ALL PRIVILEGES ON *.* TO `u`@`%`',
            'GRANT SELECT ON *.* TO `u`@`%`',
            'GRANT SELECT ON `pdoh_controle`.`regra_configuracao` TO `u`@`%` WITH GRANT OPTION',
            '`role_admin`@`%`',
        ]
        for excesso in excessos:
            with self.subTest(excesso), self.assertRaises(RuntimeError):
                validate_writer_grants(self.grants(excesso))

    def test_recusa_conta_a_que_falta_privilegio(self):
        with self.assertRaises(RuntimeError):
            validate_writer_grants(self.grants(sem=('regra_tratamento_configuracao',)))
        with self.assertRaises(RuntimeError):
            validate_writer_grants([g for g in self.grants() if 'governanca_configuracao_historico' not in g])
        # SELECT+UPDATE sem INSERT: suficiente para editar, mas nao para criar oportunidade nova.
        apenas_update = [g.replace('SELECT, INSERT, UPDATE', 'SELECT, UPDATE') for g in self.grants()]
        with self.assertRaises(RuntimeError):
            validate_writer_grants(apenas_update)

    def test_sql_permitido_e_so_o_que_o_modulo_emite(self):
        permitidos = [
            'SELECT * FROM pdoh_controle.regra_configuracao WHERE codigo_interno = %(c)s FOR UPDATE',
            'UPDATE pdoh_controle.regra_configuracao SET status=%(status)s WHERE configuracao_id=%(id)s',
            'UPDATE `pdoh_controle`.`regra_condicao_configuracao` SET operador=%(o)s WHERE condicao_id=%(id)s',
            'UPDATE pdoh_controle.regra_tratamento_configuracao SET gera_oportunidade=1 WHERE tratamento_id=%(id)s',
            'INSERT INTO pdoh_controle.regra_configuracao (configuracao_id) VALUES (%(id)s)',
            'INSERT INTO pdoh_controle.regra_condicao_configuracao (condicao_id) VALUES (%(id)s)',
            'INSERT INTO pdoh_controle.regra_tratamento_configuracao (tratamento_id) VALUES (%(id)s)',
            'INSERT INTO pdoh_controle.governanca_configuracao_historico (marca) VALUES (%(m)s)',
            'SHOW GRANTS',
        ]
        proibidos = [
            'DELETE FROM pdoh_controle.regra_configuracao',
            'UPDATE pdoh_controle.oportunidade SET status_oportunidade=1',
            'UPDATE pdoh_controle.regra_tratativa SET status_regra=1',
            'INSERT INTO pdoh_controle.oportunidade (marca) VALUES (1)',
            'INSERT INTO pdoh_controle.regra_tratativa (marca) VALUES (1)',
            'DROP TABLE pdoh_controle.regra_configuracao',
            'ALTER TABLE pdoh_controle.regra_configuracao ADD x INT',
            'TRUNCATE pdoh_controle.regra_configuracao',
            'GRANT ALL ON *.* TO x',
            'UPDATE produtos_platina.exclusivo_bracell_platina_relatorio_pdoh SET x=1',
        ]
        for sql in permitidos:
            self.assertTrue(_SQL_PERMITIDO.match(sql), sql)
        for sql in proibidos:
            self.assertFalse(_SQL_PERMITIDO.match(sql), sql)


class ReflexaoDaContaDeEdicaoTest(unittest.TestCase):
    def test_reflete_colunas_e_chave_primaria_sem_chaves_estrangeiras(self):
        db = FixtureDatabase()
        self.addCleanup(db.close)
        with db.engine.connect() as conexao:
            tabela = refletir_colunas(conexao, 'regra_configuracao', MetaData(), schema=None)
        self.assertEqual({'configuracao_id'}, {c.name for c in tabela.primary_key.columns})
        self.assertIn('tempo_minimo_minutos', tabela.c)
        self.assertEqual(set(), set(tabela.foreign_keys))


if __name__ == '__main__':
    unittest.main()
