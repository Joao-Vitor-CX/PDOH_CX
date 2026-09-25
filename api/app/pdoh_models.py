"""Contratos da camada v2.1 (PDOH Platform). Somente leitura e consolidacao."""
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from .models import Contract, ResolvedPeriod
from .finding_models import FindingFilter

UNIDADE_PERCENTUAL = '%'


class Indicator(Contract):
    """Indicador oficial ja consolidado. `valor` em pontos percentuais (0-100)."""
    valor: float
    unidade: str = UNIDADE_PERCENTUAL
    variacao_periodo_anterior: float | None = None


class PdohSource(Contract):
    """Cobertura real da fonte oficial no periodo. Auditoria do que foi lido."""
    tabela: str | None
    acessivel: bool
    registros_no_periodo: int
    colaboradores_no_periodo: int
    dias_no_periodo: int
    indicadores_disponiveis: list[str]
    # Intervalo que a fonte oficial realmente cobre (sem filtro de periodo, colaborador ou
    # estado). E' o que permite dizer "ha dados de X a Y" quando o periodo pedido esta vazio.
    disponivel_de: date | None = None
    disponivel_ate: date | None = None


class PdohComposition(Contract):
    """Composicao da jornada: cada parte sobre as horas programadas do periodo."""
    produtividade: Indicator | None = None
    ocio: Indicator | None = None
    deslocamento: Indicator | None = None
    horas_nao_registradas: Indicator | None = None


class PdohHeadline(Contract):
    """Resultado principal. `meta` so existe se houver meta oficial cadastrada."""
    valor: float
    unidade: str = UNIDADE_PERCENTUAL
    variacao_periodo_anterior: float | None = None
    meta: float | None = None
    motivo_meta: str | None = None


class TrendPoint(Contract):
    periodo: date
    inicio: date
    fim: date
    pdoh: float


class LegacyTrendPoint(Contract):
    """Formato consumido hoje pelo grafico do painel."""
    data: date
    percentual: float


class PdohPercentages(Contract):
    produtividade: float | None = None
    visitas: float | None = None
    pesquisas: float | None = None
    efetividade: float | None = None


class PdohJourneyAudit(Contract):
    """Jornada da linha: resolucao oficial vigente na data + fallback do processador PDOH a parte."""
    fonte: str | None = None
    horario_aplicado: str | None = None
    houve_fallback: bool | None = None          # fallback de jornada decidido pela resolucao oficial
    origem_fallback: str | None = None
    jornada_aplicada: str | None = None
    origem: str | None = None                   # INVOLVES / RAW / CONFIGURACAO / FALLBACK
    motivo: str | None = None
    status_resolucao: str | None = None
    data_resolucao: str | None = None
    fallback_processador_pdoh: bool | None = None   # `fillna(44)` do processador (fallback_evento)


class PdohDayValidation(Contract):
    """Status do dia na validacao diaria (somente exibicao; nao entra no calculo PDOH)."""
    status: Literal['VALIDO', 'CHECKOUT_ESQUECIDO', 'DESCONSIDERADO', 'SEM_ATIVIDADE_PREVISTA']
    considerado: bool                    # entra nas contagens da analise
    fallback_aplicado: bool              # checkout esquecido com saida considerada pela jornada
    saida_considerada: str | None = None  # HH:MM
    origem_saida: Literal['CONFIGURACAO', 'JORNADA_PADRAO'] | None = None
    motivo: str
    gerou_oportunidade: bool = False     # ha oportunidade aberta de checkout gravada para o dia


class PdohValidationSummary(Contract):
    """Contagem da validacao no periodo inteiro (todas as paginas), com os mesmos filtros."""
    dias: int
    considerados: int
    validos: int
    checkout_esquecido: int
    fallback_aplicado: int
    desconsiderados: int
    sem_atividade_prevista: int
    colaboradores: int
    oportunidades: int = 0               # dias com oportunidade aberta de checkout
    justificativas: dict[str, int] = Field(default_factory=dict)


class PdohDailyRow(Contract):
    """Linha diaria preservada da saida tratada do PDOH, sem calculo no cliente."""
    colaborador: str
    estado: str | None = None
    data: date
    nome_do_dia: str | None = None
    deslocamento: str | None = None
    ocio: str | None = None
    produtividade: str | None = None
    horas_nao_registradas: str | None = None
    horas_programadas: str | None = None
    primeiro_checkin: str | None = None
    ultimo_checkout: str | None = None
    visitas: int
    visitas_realizadas: int
    pesquisas: int
    pesquisas_realizadas: int
    percentuais: PdohPercentages
    jornada: PdohJourneyAudit
    justificativa: str | None = None     # justificativa do dia na Platina (coluna do dia da semana)
    validacao: PdohDayValidation | None = None
    origem_dado: str


class PdohDailyPage(Contract):
    items: list[PdohDailyRow]
    total: int
    pagina: int
    tamanho: int
    paginas: int


class PdohFilterOptions(Contract):
    colaboradores: list[str] = Field(default_factory=list)
    estados: list[str] = Field(default_factory=list)


class PdohSummary(Contract):
    """GET /api/v2/pdoh/resumo. Sem fonte oficial, `disponivel=false` e o motivo."""
    marca: str | None
    operacao: str | None = None
    periodo: ResolvedPeriod
    # True quando o cliente nao escolheu periodo e a API usou a semana mais recente com dados.
    periodo_automatico: bool = False
    disponivel: bool
    motivo: str | None
    # Contrato v2.1
    pdoh: PdohHeadline | None = None
    indicador: str | None = None          # qual coluna oficial alimenta `pdoh.valor`
    composicao: PdohComposition | None = None
    efetividade: Indicator | None = None  # indicador oficial composto (prod+visitas+pesquisas)
    fonte: str | None = None              # "PLATINA" quando ha consolidacao
    cobertura: PdohSource
    # Campos ja consumidos pelo painel; mantidos para nao quebrar o contrato vigente.
    percentual: float | None = None
    variacao_periodo_anterior: float | None = None
    indicadores: PdohComposition | None = None
    evolucao: list[LegacyTrendPoint] | None = None
    detalhes: PdohDailyPage
    filtros_disponiveis: PdohFilterOptions
    # Status da validacao diaria no periodo; None sem fonte ou acima do limite de linhas.
    validacao: PdohValidationSummary | None = None


class PdohCompositionResponse(Contract):
    """GET /api/v2/pdoh/composicao."""
    marca: str | None
    periodo: ResolvedPeriod
    disponivel: bool
    motivo: str | None
    fonte: str | None = None
    produtividade: Indicator | None = None
    ocio: Indicator | None = None
    deslocamento: Indicator | None = None
    horas_nao_registradas: Indicator | None = None
    cobertura: PdohSource


class PdohFilter(FindingFilter):
    """Filtros de validacao aceitos pelas rotas PDOH existentes."""
    estado: str | None = Field(None, min_length=2, max_length=50)
    periodo: Literal[
        'automatico', 'hoje', 'ontem', 'semana', 'ultimos_7_dias', 'ultimos_30_dias',
        'mes', 'tres_meses', 'doze_meses', 'personalizado', 'relativo'
    ] | None = None
    periodo_quantidade: int | None = Field(None, ge=1, le=3650)
    periodo_unidade: Literal['dias', 'semanas', 'meses'] | None = None


class PdohTrendFilter(PdohFilter):
    """Filtro da evolucao: mesma janela dos demais endpoints + granularidade."""
    granularidade: Literal['dia', 'semana', 'mes'] = 'dia'


class PdohTrendResponse(Contract):
    """GET /api/v2/pdoh/evolucao."""
    marca: str | None
    periodo: ResolvedPeriod
    granularidade: Literal['dia', 'semana', 'mes']
    disponivel: bool
    motivo: str | None
    fonte: str | None = None
    pontos: list[TrendPoint]


class CollaboratorImpact(Contract):
    """Impactador do colaborador. Sem UUID, fingerprint ou execution_id."""
    regra: str
    titulo: str
    quantidade: int
    impacto: str | None
    acao_recomendada: str | None
    severidade: str


class CollaboratorIdentity(Contract):
    id: str
    nome: str


class PdohCollaborator(Contract):
    """GET /api/v2/pdoh/colaborador/{id}."""
    colaborador: CollaboratorIdentity
    marca: str | None
    periodo: ResolvedPeriod
    disponivel: bool
    motivo: str | None
    fonte: str | None = None
    pdoh: PdohHeadline | None = None
    composicao: PdohComposition | None = None
    efetividade: Indicator | None = None
    dias_no_periodo: int = 0
    impactadores: list[CollaboratorImpact] = Field(default_factory=list)


class JourneySource(Contract):
    tabela: str
    prioridade: int
    campo_jornada: str | None = None
    campo_perfil: str | None = None
    campo_horas: str | None = None


class FallbackSetting(Contract):
    regra: str
    escopo: str
    chave: str
    valor_fallback: str
    vigencia_inicio: date
    vigencia_fim: date | None
    status: str


class RuleSetting(Contract):
    tipo_problema: str
    titulo: str | None
    classificacao: str | None
    severidade_padrao: str | None
    impacto_negocio: str | None
    acao_recomendada: str | None
    origem_excecao: str | None
    classificacao_excecao: str | None
    status_regra: str
    prioridade: int


class OperatorOption(Contract):
    codigo: str
    rotulo: str


class GovernanceCondition(Contract):
    tipo: str
    ordem: int
    papel_fonte: str
    campo_logico: str
    operador: str
    valor_esperado: object | None = None
    descricao: str
    status: str
    # Vocabulario de negocio para a tela; a fonte de verdade continua sendo o motor de regras.
    campo_rotulo: str | None = None
    operador_rotulo: str | None = None
    texto: str | None = None
    operadores: list[OperatorOption] = []
    editavel: bool = True


class GovernanceTreatment(Contract):
    resultado: str
    acao_recomendada: str
    destino: str
    gera_oportunidade: bool
    status: str


class RuleSourceRef(Contract):
    """De onde a regra le o dado que avalia (rotulo de negocio + tabela fisica)."""
    papel: str
    rotulo: str
    tabela: str | None = None
    campo: str | None = None
    campo_rotulo: str | None = None


class GovernanceRule(Contract):
    modelo_configuracao: str = 'CONDICAO'
    jornadas: list[dict] = []
    monitoramento: dict | None = None
    jornada_padrao: dict | None = None     # fallback do motor (em codigo), exibido na configuracao
    configuracao_id: str
    nome_regra: str
    codigo_interno: str
    categoria: str
    status: str
    prioridade: int
    tempo_minimo_minutos: int = 0
    # Mesma definicao de "ativa" e "gera" que a esteira e a fila usam (shared.rule_engine).
    ativa: bool = False
    gera_oportunidade: bool = False
    motivo_sem_geracao: str | None = None
    fonte: RuleSourceRef | None = None
    descricao: str
    comportamento_esperado: str
    regra_catalogo_id: str | None = None
    geracao_automatica_ativa: bool
    condicoes: list[GovernanceCondition]
    excecoes: list[GovernanceCondition]
    tratativas: list[GovernanceTreatment]
    atualizado_em: datetime


class AvailableField(Contract):
    """Campo que a tela de criação pode oferecer: já tem fonte física mapeada."""
    papel_fonte: str
    campo_logico: str
    rotulo: str
    tipo: str
    operadores: list[OperatorOption]


class SemanticSourceSetting(Contract):
    papel: str
    tipo: str
    prioridade: int
    schema_fisico: str | None = None
    tabela_fisica: str | None = None
    mapeamento_campos: dict[str, object]
    status: str
    descricao: str | None = None


class JourneyPrioritySetting(Contract):
    prioridade: int
    origem_codigo: str
    papel_fonte: str
    fallback: bool
    status: str
    aplicado_no_processamento: bool
    descricao: str


class GovernanceHistorySetting(Contract):
    id: int
    entidade_tipo: str
    codigo_referencia: str | None = None
    acao: str
    valor_anterior: object | None = None
    valor_novo: object | None = None
    usuario: str
    motivo: str
    registrado_em: datetime


class OperationParameters(Contract):
    """Parametros do calculo, como estao na base oficial travada."""
    pesos_efetividade: dict[str, float]
    base_pesos: str
    formula_pdoh: str
    indicador_pdoh: str
    semana_operacional: str
    meta_pdoh: float | None = None
    motivo_meta: str | None = None


class OperationConfigResponse(Contract):
    jornadas_disponiveis: list[dict] = []
    """GET /api/v2/configuracoes/operacao. Somente leitura nesta fase."""
    marca: str
    operacao: str
    descricao: str
    somente_leitura: bool = True
    jornada: list[JourneySource]
    perfis_operacionais: list[str]
    fallback: list[FallbackSetting]
    regras: list[RuleSetting]
    regras_governanca: list[GovernanceRule]
    fontes_semanticas: list[SemanticSourceSetting]
    campos_disponiveis: list[AvailableField] = []
    prioridade_jornada: list[JourneyPrioritySetting]
    historico_governanca: list[GovernanceHistorySetting]
    parametros: OperationParameters
    atualizado_em: datetime | None = None
