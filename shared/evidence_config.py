"""Matriz de origem das oportunidades — configuracao, nunca codigo por marca.

Por que existe
    Toda oportunidade precisa dizer de qual tabela RAW e de qual campo ela nasceu. Esse
    vinculo nao pode ser um `if marca == 'BRACELL'` espalhado: e' cadastro. Aqui ficam
    apenas as ESTRUTURAS e a leitura da configuracao; os valores vivem em
    `pdoh_controle.configuracao_evidencia` (uma linha por marca/operacao/papel).

O que este modulo NAO faz
    Nao calcula PDOH, nao cria regra, nao classifica achado e nao adivinha nome de
    tabela. Marca sem configuracao cadastrada devolve `None` — e quem chamar responde
    "evidencia indisponivel" em vez de inventar uma fonte.

Multimarca
    BRACELL, TANGARA, FLORA e as proximas usam este mesmo modulo. Acrescentar uma marca
    e' inserir linhas na tabela de configuracao; nenhum arquivo novo, nenhum `elif`.
"""
import json

# Papeis semanticos das cinco fontes operacionais do Involves. Os nomes fisicos mudam
# por marca (status_day_operacao_bracell, status_day_operacao_tangara, ...); o papel nao.
PAPEL_STATUS_DAY = 'status_day'
PAPEL_COLABORADOR = 'colaborador'
PAPEL_CHECKIN = 'checkin'
PAPEL_VISITAS = 'visitas'
PAPEL_PESQUISAS = 'pesquisas'
PAPEIS = (PAPEL_STATUS_DAY, PAPEL_COLABORADOR, PAPEL_CHECKIN, PAPEL_VISITAS, PAPEL_PESQUISAS)

# Resultado da avaliacao de uma evidencia.
CONFIRMADO = 'confirmado'          # todos os criterios comprovados na fonte oficial
NAO_APLICAVEL = 'nao_aplicavel'    # atestado/afastamento/justificativa abona o dia
INDISPONIVEL = 'indisponivel'      # falta fonte ou campo: nao vira oportunidade

# Origem da jornada, na ordem de prioridade acordada. E' rotulo de evidencia, nao regra:
# quem decide se a jornada existe continua sendo `shared.journey.resolve`.
JORNADA_INVOLVES = 'INVOLVES'
JORNADA_RAW = 'RAW'
JORNADA_CONFIGURACAO = 'CONFIGURACAO'
JORNADA_FALLBACK = 'FALLBACK'
# Ocorrencia que o reprocessamento nao encontrou mais (dado corrigido). Fica no historico,
# sai da fila; se a divergencia voltar, uma nova gravacao ABERTA a traz de volta.
STATUS_OCORRENCIA_ENCERRADA = 'ENCERRADA'
JORNADA_INDISPONIVEL = 'INDISPONIVEL'
PRIORIDADE_JORNADA = (JORNADA_INVOLVES, JORNADA_RAW, JORNADA_CONFIGURACAO, JORNADA_FALLBACK)

# O que cada criterio exige, em linguagem de operacao. Serve para explicar a regra quando
# ela ainda NAO foi avaliada; o texto do criterio avaliado vem do proprio motor.
DESCRICAO_CRITERIO = {
    'colaborador_vigente': 'Colaborador ativo e com perfil operacional no cadastro oficial.',
    'dia_trabalhado': 'Dia com roteiro previsto na operação.',
    'sem_abono': 'Dia sem atestado, afastamento ou justificativa abonável.',
    'jornada_resolvida': 'Jornada semanal resolvida em fonte oficial.',
    'houve_entrada': 'Entrada registrada antes da saída cobrada.',
    'ocorrencia_na_fonte': 'A ocorrência do achado confere com o registro da fonte oficial.',
}


def _json(valor, padrao):
    """O driver devolve JSON ja convertido no MySQL e texto no SQLite."""
    if valor is None:
        return padrao
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except ValueError:
            return padrao
    return valor if isinstance(valor, type(padrao)) else padrao


class FonteOperacional:
    """Uma fonte oficial da marca: papel semantico, tabela fisica e campos usados."""

    __slots__ = ('papel', 'tabela', 'campos')

    def __init__(self, papel, tabela, campos=None):
        self.papel = papel
        self.tabela = tabela
        self.campos = dict(campos or {})

    def campo(self, nome):
        return self.campos.get(nome)

    def como_dicionario(self):
        return dict(papel=self.papel, tabela=self.tabela, campos=dict(self.campos))


class MatrizDeOrigem:
    """Fontes de uma marca/operacao. Sem cadastro, `fonte()` devolve None."""

    __slots__ = ('marca', 'operacao', '_fontes')

    def __init__(self, marca, operacao, fontes):
        self.marca = marca
        self.operacao = operacao
        self._fontes = {fonte.papel: fonte for fonte in fontes}

    def fonte(self, papel):
        return self._fontes.get(papel)

    def tabela(self, papel):
        fonte = self._fontes.get(papel)
        return fonte.tabela if fonte else None

    @property
    def papeis_configurados(self):
        return sorted(self._fontes)

    def como_dicionario(self):
        return dict(marca=self.marca, operacao=self.operacao,
                    fontes=[self._fontes[papel].como_dicionario() for papel in sorted(self._fontes)])


def matriz_de_linhas(linhas):
    """Monta as matrizes a partir das linhas de `configuracao_evidencia`.

    Uma linha invalida (sem marca, papel ou tabela) e' ignorada em silencio: configuracao
    incompleta vira "evidencia indisponivel" na leitura, nunca uma fonte inventada.
    """
    agrupado = {}
    for linha in linhas:
        marca = (linha.get('marca') or '').strip().upper()
        operacao = (linha.get('operacao') or 'EXCLUSIVA').strip().upper()
        papel = (linha.get('papel') or '').strip().lower()
        tabela = (linha.get('tabela') or '').strip()
        if not marca or papel not in PAPEIS or not tabela:
            continue
        agrupado.setdefault((marca, operacao), []).append(
            FonteOperacional(papel, tabela, _json(linha.get('campos'), {})))
    return {chave: MatrizDeOrigem(chave[0], chave[1], fontes)
            for chave, fontes in agrupado.items()}


def matriz_da_marca(linhas, marca, operacao='EXCLUSIVA'):
    if not marca:
        return None
    chave = (marca.strip().upper(), (operacao or 'EXCLUSIVA').strip().upper())
    return matriz_de_linhas(linhas).get(chave)


class RegraDeEvidencia:
    """Como comprovar um tipo de problema: qual papel, qual campo, quais criterios.

    Os criterios sao os nomes das checagens que o motor sabe executar (ver
    `shared.evidence_engine.CRITERIOS`). A ordem e' a ordem de apresentacao ao lider.
    """

    __slots__ = ('tipo_problema', 'papel', 'campo', 'valor_esperado', 'criterios', 'papeis_apoio')

    def __init__(self, tipo_problema, papel, campo, valor_esperado=None,
                 criterios=(), papeis_apoio=()):
        self.tipo_problema = tipo_problema
        self.papel = papel
        self.campo = campo
        self.valor_esperado = valor_esperado
        self.criterios = tuple(criterios)
        self.papeis_apoio = tuple(papeis_apoio)

    def como_dicionario(self):
        return dict(tipo_problema=self.tipo_problema, papel=self.papel, campo=self.campo,
                    valor_esperado=self.valor_esperado, criterios=list(self.criterios),
                    papeis_apoio=list(self.papeis_apoio))


def regras_de_linhas(linhas):
    """Regras de evidencia vindas de `configuracao_evidencia_regra`, por tipo_problema."""
    regras = {}
    for linha in linhas:
        tipo = (linha.get('tipo_problema') or '').strip()
        papel = (linha.get('papel') or '').strip().lower()
        if not tipo or papel not in PAPEIS:
            continue
        regras[tipo] = RegraDeEvidencia(
            tipo_problema=tipo, papel=papel, campo=(linha.get('campo') or '').strip() or None,
            valor_esperado=linha.get('valor_esperado'),
            criterios=_json(linha.get('criterios'), []),
            papeis_apoio=_json(linha.get('papeis_apoio'), []))
    return regras
