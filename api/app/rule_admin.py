"""Edicao e criacao auditadas das regras de oportunidade: a unica escrita da API.

A API de consulta e' somente leitura (`pdoh_cx_reader`). Criar uma oportunidade, ativa-la/
desativa-la ou ajustar o tempo minimo e' configuracao, nao consulta -- por isso existe UMA
superficie de escrita e ela nao usa a conta de leitura:

  * conta propria (`pdoh_cx_config`): SELECT + INSERT + UPDATE (so' nas colunas editaveis) nas
    tres tabelas de regra, e INSERT na tabela de historico. Nao apaga, nao troca codigo depois de
    criado, nao mexe em marca, fonte ou catalogo (`validate_writer_grants` recusa qualquer
    privilegio alem disso);
  * SQL restrito ao que este modulo emite (`_SQL_PERMITIDO`);
  * toda mudanca e o historico (antes/depois, usuario, motivo) entram na MESMA transacao
    (`shared.governance_config.insert_audited`/`upsert_audited`);
  * `criar_regra` so' cadastra o que o usuario configurou -- sem isso a oportunidade nao existe
    (principio de negocio: sem configuracao, nao ha oportunidade). `atualizar_regra` so' altera
    regra ja cadastrada; regra inexistente no PATCH e' 404;
  * sem conta configurada a rota responde 503 e a API continua somente leitura (fail-closed).

Nada aqui recalcula PDOH, toca a Platina, o Gold ou o historico de oportunidades: criar/ativar uma
regra so' passa a valer para os proximos processamentos.
"""
from contextlib import contextmanager
import logging
import re
import unicodedata
import uuid
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import Column, MetaData, Table, create_engine, event, inspect, select

from shared.governance_config import insert_audited, upsert_audited
from shared.rule_engine import (
    STATUS_ATIVA, STATUS_INATIVA, TIPO_CONDICAO, TIPO_EXCECAO, TRATAMENTO_CONFIRMADO, ConfiguracaoInvalida,
    operadores_do_tipo, rotulo_do_campo, tipo_do_campo, validar_valor,
)

from .models import Contract
from .schedule_config import ScheduleEdit, save_schedules
from shared.operational_schedule import TABLE as SCHEDULE_TABLE, CHECKOUT

SCHEMA = 'pdoh_controle'
HISTORICO = 'governanca_configuracao_historico'
# Regra-modelo cujas 4 exceções (ordem 1-4) servem de template para toda oportunidade nova: os
# checkboxes fixos "Não gerar quando" da tela vêm daqui, não de um catálogo separado a manter.
REGRA_MODELO = 'HORAS_AUSENTES'
# Unica superficie de escrita: tabela -> colunas que a tela pode alterar (UPDATE) ou preencher
# (INSERT completo, ao criar uma oportunidade nova).
COLUNAS_EDITAVEIS = {
    'regra_configuracao': ('nome_regra', 'descricao', 'status', 'geracao_automatica_ativa',
                           'tempo_minimo_minutos', 'usuario_alteracao'),
    'regra_condicao_configuracao': ('operador', 'valor_esperado', 'status', 'usuario_alteracao'),
    'regra_tratamento_configuracao': ('gera_oportunidade', 'usuario_alteracao'),
}
TABELAS_DE_REGRA = tuple(COLUNAS_EDITAVEIS)
COLUNAS_EDITAVEIS[SCHEDULE_TABLE] = ('jornada', 'nome_jornada', 'intervalo', 'origem_configuracao',
                                   'hora_entrada_padrao', 'hora_saida_padrao', 'ativo', 'usuario_alteracao')
TABELAS_ESCRITA = tuple(COLUNAS_EDITAVEIS)
ROTULOS_DE_CAMPO = {
    'nome_regra': 'Nome', 'descricao': 'Descrição', 'status': 'Status',
    'tempo_minimo_minutos': 'Tempo mínimo (minutos)', 'gera_oportunidade': 'Gerar oportunidade',
    'operador': 'Regra', 'valor_esperado': 'Valor',
}

_SQL_PERMITIDO = re.compile(
    r'^\s*(?:SELECT\b|SHOW\b'
    r'|UPDATE\s+`?' + SCHEMA + r'`?\.`?(?:' + '|'.join(TABELAS_ESCRITA) + r')`?\s'
    r'|INSERT\s+INTO\s+`?' + SCHEMA + r'`?\.`?(?:' + '|'.join((*TABELAS_ESCRITA, HISTORICO)) + r')`?\s)', re.I)


# --------------------------------------------------------------------------- contrato
class ConditionEdit(Contract):
    ordem: int = Field(ge=1, le=99)
    operador: str = Field(min_length=1, max_length=30)
    valor: Any | None = None


class ExceptionEdit(Contract):
    ordem: int = Field(ge=1, le=99)
    ativa: bool
    # Opcional: novos valores da excecao (ex.: incluir uma justificativa na lista). Ausente = mantem.
    valor: Any | None = None


class RuleEdit(Contract):
    """Corpo do PATCH. Campos ausentes ficam como estao; `usuario` e `motivo` sao obrigatorios."""
    usuario: str = Field(min_length=3, max_length=160, pattern=r'^[\w.@ \-]+$')
    motivo: str = Field(min_length=5, max_length=500)
    nome_regra: str | None = Field(None, min_length=3, max_length=160)
    descricao: str | None = Field(None, min_length=3, max_length=2000)
    status: Literal['ATIVA', 'INATIVA'] | None = None
    gerar_oportunidade: bool | None = None
    tempo_minimo_minutos: int | None = Field(None, ge=0, le=1440)
    condicoes: list[ConditionEdit] | None = Field(None, max_length=10)
    excecoes: list[ExceptionEdit] | None = Field(None, max_length=20)
    jornadas: list[ScheduleEdit] | None = Field(None, max_length=100)

    @model_validator(mode='after')
    def algo_a_alterar(self):
        editaveis = (self.nome_regra, self.descricao, self.status, self.gerar_oportunidade,
                     self.tempo_minimo_minutos, self.condicoes, self.excecoes, self.jornadas)
        if all(valor is None for valor in editaveis):
            raise ValueError('Informe ao menos um campo a alterar.')
        return self


class RuleChange(Contract):
    entidade: Literal['REGRA', 'CONDICAO', 'EXCECAO', 'TRATAMENTO', 'JORNADA']
    referencia: str | None = None
    campo: str
    antes: Any | None = None
    depois: Any | None = None


class RuleCreate(Contract):
    """Corpo do POST. Cria a oportunidade com o mínimo que o motor precisa para avaliá-la.

    Sem isso não existe execução parcial: a regra nasce com 1 condição e as 4 exceções padrão
    (ligadas ou desligadas conforme `excecoes`) e as 3 tratativas (CONFIRMADO/NAO_APLICAVEL/
    INDISPONIVEL), do mesmo jeito que HORAS_AUSENTES foi cadastrada.
    """
    usuario: str = Field(min_length=3, max_length=160, pattern=r'^[\w.@ \-]+$')
    motivo: str = Field(default='Oportunidade criada pela tela de Configurações.', max_length=500)
    nome_regra: str = Field(min_length=3, max_length=160)
    descricao: str = Field(min_length=3, max_length=2000)
    papel_fonte: str = Field(min_length=1, max_length=40)
    campo_logico: str = Field(min_length=1, max_length=160)
    operador: str = Field(min_length=1, max_length=30)
    valor: Any | None = None
    excecoes: list[int] = Field(default_factory=list, max_length=4)
    status: Literal['ATIVA', 'INATIVA'] = 'INATIVA'
    gerar_oportunidade: bool = True
    tipo_oportunidade: Literal['CONDICAO', 'CHECKOUT_AUSENTE'] = 'CONDICAO'
    jornadas: list[ScheduleEdit] = Field(default_factory=list, max_length=100)


class RuleCreated(Contract):
    codigo: str
    alteracoes: list[RuleChange]


# --------------------------------------------------------------------------- conta de escrita
def _privilegios(texto):
    """'SELECT, UPDATE (`a`, `b`)' -> [('SELECT', None), ('UPDATE', {'a', 'b'})]."""
    itens, nivel, atual = [], 0, ''
    for caractere in texto:
        nivel += (caractere == '(') - (caractere == ')')
        if caractere == ',' and nivel == 0:
            itens.append(atual.strip())
            atual = ''
        else:
            atual += caractere
    if atual.strip():
        itens.append(atual.strip())
    resultado = []
    for item in itens:
        achado = re.fullmatch(r'([A-Z ]+?)\s*(?:\((.*)\))?', item, re.S)
        if not achado:
            raise RuntimeError('Privilegio de banco nao reconhecido.')
        colunas = {c.strip().strip('`') for c in achado.group(2).split(',')} if achado.group(2) else None
        resultado.append((achado.group(1).strip(), colunas))
    return resultado


def validate_writer_grants(grants):
    """A conta de edicao deve ter EXATAMENTE o necessario para criar/atualizar regra.

    Recusa qualquer outro privilegio, tabela, coluna, role ou GRANT OPTION -- e tambem a conta a
    que falte algo, para que o problema apareca na partida e nao no primeiro clique do usuario.
    """
    concedido = {tabela: set() for tabela in (*TABELAS_ESCRITA, HISTORICO, 'jornada_consolidada')}
    for grant in grants:
        if 'WITH GRANT OPTION' in grant:
            raise RuntimeError('A conta de edicao nao pode possuir GRANT OPTION.')
        achado = re.match(r'^GRANT (?P<privilegios>.+?) ON (?P<objeto>\S+) TO ', grant, re.S)
        if not achado:
            raise RuntimeError('Concessao de banco nao reconhecida para a conta de edicao.')
        objeto = achado.group('objeto').replace('`', '')
        if objeto == '*.*':
            if achado.group('privilegios').strip() != 'USAGE':
                raise RuntimeError('A conta de edicao nao pode ter privilegios globais.')
            continue
        schema, _, tabela = objeto.partition('.')
        if schema != SCHEMA or tabela not in concedido:
            raise RuntimeError('A conta de edicao so pode acessar as tabelas de regra e o historico.')
        for privilegio, colunas in _privilegios(achado.group('privilegios')):
            if privilegio == 'SELECT' and colunas is None and tabela in (*TABELAS_ESCRITA, 'jornada_consolidada'):
                concedido[tabela].add('SELECT')
            elif (privilegio == 'UPDATE' and colunas is not None and tabela in COLUNAS_EDITAVEIS
                    and colunas <= set(COLUNAS_EDITAVEIS[tabela])):
                concedido[tabela].add('UPDATE')
            elif privilegio == 'INSERT' and colunas is None and tabela in (*TABELAS_ESCRITA, HISTORICO):
                concedido[tabela].add('INSERT')
            else:
                raise RuntimeError('Privilegio nao permitido para a conta de edicao.')
    faltando = [tabela for tabela in TABELAS_ESCRITA if concedido[tabela] != {'SELECT', 'UPDATE', 'INSERT'}]
    if faltando or 'INSERT' not in concedido[HISTORICO] or concedido['jornada_consolidada'] != {'SELECT'}:
        raise RuntimeError('Conta de edicao sem os privilegios minimos das regras e do historico.')


def refletir_colunas(connection, nome, metadata, schema=SCHEMA):
    """Tabela com colunas e chave primaria lidas do banco, SEM refletir chaves estrangeiras.

    A reflexao completa consulta tabelas referenciadas (aqui, o catalogo `regra_tratativa`) que a
    conta de edicao nao enxerga -- e nao precisa: atualizar e inserir nao usam as referencias.
    """
    inspetor = inspect(connection)
    chave = set(inspetor.get_pk_constraint(nome, schema=schema).get('constrained_columns') or ())
    colunas = [Column(coluna['name'], coluna['type'], primary_key=coluna['name'] in chave)
               for coluna in inspetor.get_columns(nome, schema=schema)]
    return Table(nome, metadata, *colunas)


class RuleWriter:
    """Conexao de escrita restrita. So' existe se a conta de edicao estiver configurada."""

    def __init__(self, settings):
        self.engine = create_engine(settings.config_url(), pool_pre_ping=True, pool_size=2, max_overflow=2,
                                    pool_recycle=300, hide_parameters=True,
                                    connect_args={'connect_timeout': 5, 'read_timeout': 15, 'write_timeout': 10})

        @event.listens_for(self.engine, 'connect')
        def configure(dbapi_connection, _):
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET SESSION time_zone = '-03:00'")
                cursor.execute('SET SESSION MAX_EXECUTION_TIME = 10000')

        @event.listens_for(self.engine, 'before_cursor_execute')
        def restrict(_conn, _cursor, statement, _parameters, _context, _many):
            if not _SQL_PERMITIDO.match(statement):
                raise RuntimeError('Comando SQL nao permitido na edicao de regras.')

        self.tables = {}
        self.disponivel = False

    def initialize(self):
        """Valida a conta e reflete as tabelas. Falha desabilita a edicao, nunca a consulta."""
        try:
            with self.engine.connect() as connection:
                validate_writer_grants([row[0] for row in connection.exec_driver_sql('SHOW GRANTS')])
                metadata = MetaData(schema=SCHEMA)
                for nome in (*TABELAS_ESCRITA, HISTORICO, 'jornada_consolidada'):
                    self.tables[nome] = refletir_colunas(connection, nome, metadata)
            self.disponivel = True
        except Exception as error:
            self.disponivel = False
            logging.getLogger('pdoh.api').error('Edicao de regras desabilitada; tipo=%s', type(error).__name__)

    @contextmanager
    def begin(self):
        with self.engine.begin() as connection:
            yield connection

    def close(self):
        self.engine.dispose()


# --------------------------------------------------------------------------- edicao
def _comparavel(campo, valor):
    if campo in ('geracao_automatica_ativa', 'gera_oportunidade'):
        return bool(valor)
    return valor


def _recusar(mensagem):
    raise HTTPException(422, mensagem)


def _linhas(conexao, tabela, **filtros):
    consulta = select(tabela)
    for coluna, valor in filtros.items():
        consulta = consulta.where(tabela.c[coluna] == valor)
    return [dict(linha) for linha in conexao.execute(consulta).mappings()]


# --------------------------------------------------------------------------- criacao
def _slugify(nome):
    """"Horas ausentes" -> "HORAS_AUSENTES": o codigo nasce do nome, nunca digitado a mao."""
    texto = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode('ascii')
    texto = re.sub(r'[^A-Za-z0-9]+', '_', texto).strip('_').upper()
    return texto or 'OPORTUNIDADE'


def _codigo_disponivel(conexao, regras, marca, operacao, base):
    codigo, sufixo = base, 1
    while conexao.execute(select(regras.c.configuracao_id).where(
            regras.c.marca == marca, regras.c.operacao == operacao,
            regras.c.codigo_interno == codigo)).first():
        sufixo += 1
        codigo = f'{base}_{sufixo}'
    return codigo


def _templates_de_excecao(conexao, condicoes, regras, marca, operacao):
    """As 4 exceções da regra-modelo, na ordem: o catálogo fixo que a tela oferece ao criar.

    Não há uma tabela própria de "modelos de exceção" -- reaproveita a regra já cadastrada em vez
    de duplicar o vocabulário (mesmo texto que o usuário vê em HORAS_AUSENTES).
    """
    modelo = conexao.execute(select(regras.c.configuracao_id).where(
        regras.c.marca == marca, regras.c.operacao == operacao,
        regras.c.codigo_interno == REGRA_MODELO)).scalar_one_or_none()
    if modelo is None:
        return []
    linhas = conexao.execute(select(condicoes).where(
        condicoes.c.configuracao_id == modelo, condicoes.c.tipo == TIPO_EXCECAO)
        .order_by(condicoes.c.ordem)).mappings().all()
    return [dict(linha) for linha in linhas]


def criar_regra(writer, marca, operacao, criacao):
    """Cadastra uma oportunidade nova: 1 condição + as exceções padrão marcadas + 3 tratativas.

    Sem isso a oportunidade não existe (princípio de negócio); por isso tudo entra na mesma
    transação, com `insert_audited` registrando CADASTRO para cada linha criada.
    """
    operational = criacao.tipo_oportunidade == CHECKOUT
    if operational:
        criacao = criacao.model_copy(update=dict(papel_fonte='checkout', campo_logico='hora_saida',
                                                 operador='IS NULL', valor=None))
    elif criacao.jornadas or _slugify(criacao.nome_regra) in ('CHECK_OUT_AUSENTE', CHECKOUT):
        _recusar('Selecione o tipo Check-out ausente para configurar jornadas.')
    tabelas = writer.tables
    regras, condicoes, tratamentos = (tabelas[nome] for nome in TABELAS_DE_REGRA)
    escopo = dict(marca=marca, operacao=operacao)
    alteracoes = []
    with writer.begin() as conexao:
        tipo = tipo_do_campo(criacao.papel_fonte, criacao.campo_logico)
        if tipo is None:
            _recusar('Campo analisado não reconhecido para este papel de fonte.')
        oferecidos = operadores_do_tipo(tipo)
        if criacao.operador not in {opcao['codigo'] for opcao in oferecidos}:
            _recusar('Operador não permitido para este campo.')
        try:
            valor = validar_valor(criacao.operador, tipo, criacao.valor)
        except ConfiguracaoInvalida as erro:
            _recusar(str(erro))

        modelos = _templates_de_excecao(conexao, condicoes, regras, marca, operacao)
        if criacao.excecoes and set(criacao.excecoes) - {m['ordem'] for m in modelos}:
            _recusar('Exceção informada não existe no modelo padrão.')

        codigo = _codigo_disponivel(conexao, regras, marca, operacao, CHECKOUT if operational else _slugify(criacao.nome_regra))
        if operational and codigo != CHECKOUT:
            raise HTTPException(409, 'Check-out ausente já cadastrado. Edite a oportunidade existente.')
        prioridade = 1 + (conexao.execute(select(regras.c.prioridade).where(
            regras.c.marca == marca, regras.c.operacao == operacao)
            .order_by(regras.c.prioridade.desc()).limit(1)).scalar() or 0)
        configuracao_id = str(uuid.uuid4())

        insert_audited(conexao, regras, tabelas[HISTORICO], key={'configuracao_id': configuracao_id},
                       values={**escopo, 'nome_regra': criacao.nome_regra, 'codigo_interno': codigo,
                               'categoria': 'Configurável', 'status': criacao.status, 'prioridade': prioridade,
                               'tempo_minimo_minutos': 0, 'descricao': criacao.descricao,
                               'comportamento_esperado': f'Criada pela tela de Configurações ({rotulo_do_campo(criacao.papel_fonte, criacao.campo_logico)}).',
                               'regra_catalogo_id': None, 'geracao_automatica_ativa': criacao.status == STATUS_ATIVA,
                               'usuario_alteracao': criacao.usuario},
                       scope=escopo, entity_type='REGRA', entity_id=configuracao_id, reference=codigo,
                       user=criacao.usuario, reason=criacao.motivo)
        alteracoes.append(dict(entidade='REGRA', referencia=codigo, campo='Cadastro', antes=None, depois=criacao.nome_regra))

        condicao_id = str(uuid.uuid4())
        insert_audited(conexao, condicoes, tabelas[HISTORICO], key={'condicao_id': condicao_id},
                       values={'configuracao_id': configuracao_id, 'tipo': TIPO_CONDICAO, 'ordem': 1,
                               'papel_fonte': criacao.papel_fonte, 'campo_logico': criacao.campo_logico,
                               'operador': criacao.operador, 'valor_esperado': valor,
                               'descricao': f'{rotulo_do_campo(criacao.papel_fonte, criacao.campo_logico)} '
                                            f'{next(o["rotulo"] for o in oferecidos if o["codigo"] == criacao.operador).lower()} {criacao.valor}',
                               'status': STATUS_ATIVA, 'usuario_alteracao': criacao.usuario},
                       scope=escopo, entity_type=TIPO_CONDICAO, entity_id=condicao_id, reference=codigo,
                       user=criacao.usuario, reason=criacao.motivo)

        for modelo in modelos:
            excecao_id = str(uuid.uuid4())
            insert_audited(conexao, condicoes, tabelas[HISTORICO], key={'condicao_id': excecao_id},
                           values={'configuracao_id': configuracao_id, 'tipo': TIPO_EXCECAO,
                                   'ordem': modelo['ordem'], 'papel_fonte': modelo['papel_fonte'],
                                   'campo_logico': modelo['campo_logico'], 'operador': modelo['operador'],
                                   'valor_esperado': modelo['valor_esperado'],
                                   'descricao': modelo['descricao'],
                                   'status': STATUS_ATIVA if modelo['ordem'] in criacao.excecoes else STATUS_INATIVA,
                                   'usuario_alteracao': criacao.usuario},
                           scope=escopo, entity_type=TIPO_EXCECAO, entity_id=excecao_id, reference=codigo,
                           user=criacao.usuario, reason=criacao.motivo)

        for resultado, acao, destino, gera in (
                (TRATAMENTO_CONFIRMADO, 'Validar a ocorrência com o colaborador.', 'OPORTUNIDADE',
                 criacao.gerar_oportunidade),
                ('NAO_APLICAVEL', 'Registrar a exceção somente na governança.', 'GOVERNANCA', False),
                ('INDISPONIVEL', 'Aguardar complemento ou recuperação da fonte de dados.',
                 'AGUARDAR_DADOS', False)):
            tratamento_id = str(uuid.uuid4())
            insert_audited(conexao, tratamentos, tabelas[HISTORICO], key={'tratamento_id': tratamento_id},
                           values={'configuracao_id': configuracao_id, 'resultado': resultado,
                                   'acao_recomendada': acao, 'destino': destino, 'gera_oportunidade': gera,
                                   'status': 'ATIVO', 'usuario_alteracao': criacao.usuario},
                           scope=escopo, entity_type='TRATAMENTO', entity_id=tratamento_id, reference=codigo,
                           user=criacao.usuario, reason=criacao.motivo)
        if operational:
            alteracoes.extend(save_schedules(conexao, tabelas, configuracao_id, escopo, criacao.jornadas,
                                             criacao.usuario, criacao.motivo, codigo))
    return codigo, alteracoes


def atualizar_regra(writer, marca, operacao, codigo, edicao):
    """Aplica `edicao` a uma regra CADASTRADA. Tudo ou nada; devolve as alteracoes feitas."""
    tabelas = writer.tables
    regras, condicoes, tratamentos = (tabelas[nome] for nome in TABELAS_DE_REGRA)
    escopo = dict(marca=marca, operacao=operacao)
    alteracoes = []
    with writer.begin() as conexao:
        regra = conexao.execute(select(regras).where(
            regras.c.marca == marca, regras.c.operacao == operacao,
            regras.c.codigo_interno == codigo).with_for_update()).mappings().first()
        if regra is None:
            raise HTTPException(404, 'Regra não cadastrada. Esta rota altera regras existentes; não cria regras.')
        regra = dict(regra)
        operational = codigo == CHECKOUT
        if operational and (edicao.condicoes is not None or edicao.tempo_minimo_minutos is not None):
            _recusar('Check-out ausente utiliza horários por jornada, não condição genérica.')
        if not operational and edicao.jornadas is not None:
            _recusar('Esta oportunidade não utiliza configuração de jornada.')
        configuracao_id = regra['configuracao_id']
        itens = _linhas(conexao, condicoes, configuracao_id=configuracao_id)
        principais = {i['ordem']: i for i in itens if i['tipo'] == TIPO_CONDICAO}
        excecoes = {i['ordem']: i for i in itens if i['tipo'] == TIPO_EXCECAO}
        confirmado = next((t for t in _linhas(conexao, tratamentos, configuracao_id=configuracao_id)
                           if t['resultado'] == TRATAMENTO_CONFIRMADO), None)

        def aplicar(nome_tabela, atual, chave, novos, entidade, referencia):
            mudancas = {c: v for c, v in novos.items()
                        if _comparavel(c, atual.get(c)) != _comparavel(c, v)}
            if not mudancas:
                return
            upsert_audited(conexao, tabelas[nome_tabela], tabelas[HISTORICO], key={chave: atual[chave]},
                           values={**mudancas, 'usuario_alteracao': edicao.usuario}, scope=escopo,
                           entity_type=entidade, entity_id=atual[chave], reference=codigo,
                           user=edicao.usuario, reason=edicao.motivo)
            for campo, depois in mudancas.items():
                if campo == 'geracao_automatica_ativa':
                    continue                                    # derivado do status; nao e' escolha do usuario
                alteracoes.append(dict(
                    entidade='EXCECAO' if entidade == TIPO_EXCECAO else 'CONDICAO' if entidade == TIPO_CONDICAO
                    else entidade, referencia=referencia, campo=ROTULOS_DE_CAMPO.get(campo, campo),
                    antes=atual.get(campo), depois=depois))

        # ---- valida tudo antes de escrever: uma recusa nao deixa alteracao pela metade
        novas_condicoes = []
        for pedido in edicao.condicoes or ():
            atual = principais.get(pedido.ordem)
            if atual is None:
                _recusar(f'Condição {pedido.ordem} não existe nesta regra.')
            tipo = tipo_do_campo(atual['papel_fonte'], atual['campo_logico'])
            oferecidos = operadores_do_tipo(tipo, atual['operador'])
            if len(oferecidos) < 2:
                _recusar('Esta condição não pode ser editada pela tela.')
            if pedido.operador not in {opcao['codigo'] for opcao in oferecidos}:
                _recusar('Operador não permitido para este campo.')
            try:
                valor = validar_valor(pedido.operador, tipo, pedido.valor)
            except ConfiguracaoInvalida as erro:
                _recusar(str(erro))
            novas_condicoes.append((atual, dict(operador=pedido.operador, valor_esperado=valor)))
        novas_excecoes = []
        for pedido in edicao.excecoes or ():
            atual = excecoes.get(pedido.ordem)
            if atual is None:
                _recusar(f'Exceção {pedido.ordem} não existe nesta regra.')
            novos = dict(status=STATUS_ATIVA if pedido.ativa else STATUS_INATIVA)
            if pedido.valor is not None:
                # Lista de exceção so' aceita lista de textos: nunca troca o formato gravado por engano.
                if atual['operador'] == 'EM_LISTA' and not (
                        isinstance(pedido.valor, list) and all(isinstance(item, str) for item in pedido.valor)):
                    _recusar('Informe a lista de valores da exceção como textos.')
                try:
                    novos['valor_esperado'] = validar_valor(
                        atual['operador'], tipo_do_campo(atual['papel_fonte'], atual['campo_logico']), pedido.valor)
                except ConfiguracaoInvalida as erro:
                    _recusar(str(erro))
            novas_excecoes.append((atual, novos))
        if edicao.gerar_oportunidade is not None and confirmado is None:
            _recusar('A regra não tem tratativa para o resultado confirmado.')
        if edicao.status == STATUS_ATIVA and not operational:
            depois = dict(principais)
            for atual, novos in novas_condicoes:
                depois[atual['ordem']] = {**atual, **novos}
            if not any(i['status'] == STATUS_ATIVA for i in depois.values()):
                _recusar('A regra precisa de ao menos uma condição ativa para ser ativada.')

        # ---- escreve
        if edicao.jornadas is not None:
            alteracoes.extend(save_schedules(conexao, tabelas, configuracao_id, escopo, edicao.jornadas,
                                             edicao.usuario, edicao.motivo, codigo))
        novos_da_regra = {}
        for campo in ('nome_regra', 'descricao', 'tempo_minimo_minutos'):
            if getattr(edicao, campo) is not None:
                novos_da_regra[campo] = getattr(edicao, campo)
        if edicao.status is not None:
            # "Ativa" e' uma so' chave para o lider: status e geracao automatica andam juntos.
            novos_da_regra.update(status=edicao.status, geracao_automatica_ativa=edicao.status == STATUS_ATIVA)
        aplicar('regra_configuracao', regra, 'configuracao_id', novos_da_regra, 'REGRA', codigo)
        for atual, novos in novas_condicoes:
            aplicar('regra_condicao_configuracao', atual, 'condicao_id', novos, TIPO_CONDICAO,
                    atual['descricao'])
        for atual, novos in novas_excecoes:
            aplicar('regra_condicao_configuracao', atual, 'condicao_id', novos, TIPO_EXCECAO,
                    atual['descricao'])
        if edicao.gerar_oportunidade is not None:
            aplicar('regra_tratamento_configuracao', confirmado, 'tratamento_id',
                    dict(gera_oportunidade=edicao.gerar_oportunidade), 'TRATAMENTO', 'Resultado confirmado')
    return alteracoes
