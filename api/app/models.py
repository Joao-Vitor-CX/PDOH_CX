"""Contrato v1. Nomes e estados preservam o banco; datas sem fuso são locais."""
from datetime import date, datetime
from typing import Any, Generic, TypeVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pagination(Contract):
    pagina: int = Field(1, ge=1, le=10000)
    tamanho: int = Field(50, ge=1, le=200)


class PeriodFilter(Contract):
    marca: str | None = Field(None, min_length=1, max_length=80)
    operacao: str | None = Field(None, min_length=1, max_length=80)
    periodo_inicio: date | None = None
    periodo_fim: date | None = None

    @model_validator(mode="after")
    def ordered_period(self):
        if self.periodo_inicio and self.periodo_fim and self.periodo_inicio > self.periodo_fim:
            raise ValueError("periodo_inicio deve ser menor ou igual a periodo_fim")
        return self


class DashboardFilter(PeriodFilter, Pagination):
    status: str | None = Field(None, min_length=1, max_length=40)


class ExecutionFilter(DashboardFilter):
    pass


class OpportunityFilter(PeriodFilter, Pagination):
    tipo: str | None = Field(None, min_length=1, max_length=100)
    status: str | None = Field(None, min_length=1, max_length=30)
    regra: str | None = Field(None, min_length=1, max_length=36)
    execution_id: str | None = Field(None, min_length=1, max_length=80)
    classificacao: Literal['OPORTUNIDADE', 'ALERTA', 'TELEMETRIA'] | None = None


class AlertFilter(OpportunityFilter):
    classificacao: Literal['ALERTA'] = 'ALERTA'
    campo: str | None = Field(None, min_length=1, max_length=120)


class RuleFilter(Pagination):
    marca: str | None = Field(None, min_length=1, max_length=80)
    incluir_globais: bool = True
    status: str | None = Field(None, min_length=1, max_length=20)
    tipo: str | None = Field(None, min_length=1, max_length=100)


class MappingFilter(Pagination):
    marca: str | None = Field(None, min_length=1, max_length=80)
    incluir_globais: bool = True
    status: str | None = Field(None, min_length=1, max_length=20)
    processo: str | None = Field(None, min_length=1, max_length=80)
    campo_origem: str | None = Field(None, min_length=1, max_length=120)


class EntityFilter(Pagination):
    marca: str | None = Field(None, min_length=1, max_length=80)
    tipo_entidade: str | None = Field(None, min_length=1, max_length=20)
    status: str | None = Field(None, min_length=1, max_length=20)


T = TypeVar("T")


class ResolvedPeriod(Contract):
    """Janela efetivamente aplicada pela API (nunca calculada pelo cliente)."""
    inicio: date | None = None
    fim: date | None = None


class Page(Contract, Generic[T]):
    items: list[T]
    total: int
    pagina: int
    tamanho: int
    paginas: int


class Execution(Contract):
    execution_id: str
    operacao: str = 'EXCLUSIVA'
    marca: str
    periodo_inicio: date | None
    periodo_fim: date | None
    status_execucao: str
    componente_atual: str | None
    etapa_atual: str | None
    iniciado_em: datetime
    finalizado_em: datetime | None
    linhas_recebidas: int
    linhas_tratadas: int
    linhas_geradas: int
    linhas_persistidas: int
    total_alertas: int
    total_fallbacks: int
    houve_persistencia: bool
    erro_resumo: str | None
    versao_aplicacao: str | None
    atualizado_em: datetime


class Stage(Contract):
    id: int
    execution_id: str
    componente: str
    etapa: str
    status_etapa: str
    origem: str | None
    tabela_origem: str | None
    linhas_recebidas: int | None
    linhas_tratadas: int | None
    linhas_geradas: int | None
    linhas_persistidas: int | None
    mensagem: str | None
    contexto: Any | None
    ocorrido_em: datetime


class Source(Contract):
    id: int
    execution_id: str
    componente: str
    schema_origem: str
    tabela_origem: str
    filtro_periodo_inicio: date | None
    filtro_periodo_fim: date | None
    linhas_recebidas: int
    linhas_apos_tratamento: int
    duplicatas_identificadas: int
    query_hash: str | None
    registrado_em: datetime


class ExecutionEvent(Contract):
    id: int
    execution_id: str
    componente: str
    etapa: str | None
    nivel: str
    categoria: str
    codigo: str
    mensagem: str
    excecao_tipo: str | None
    contexto: Any | None
    ocorrido_em: datetime


class Opportunity(Contract):
    oportunidade_id: str
    execution_id: str
    marca: str
    data_referencia: date | None
    origem: str
    tabela_origem: str
    colaborador: str | None
    colaborador_id_interno: str | None
    tipo_problema: str
    regra_id: str | None
    descricao_detalhada: str
    severidade: str
    status_oportunidade: str
    fingerprint: str
    evidencia: Any | None
    identificada_em: datetime
    atualizada_em: datetime


class OpportunityHistory(Contract):
    id: int
    oportunidade_id: str
    execution_id: str
    status_anterior: str | None
    status_novo: str
    acao: str
    observacao: str | None
    responsavel: str | None
    contexto: Any | None
    registrado_em: datetime


class Rule(Contract):
    regra_id: str
    marca: str | None
    tipo_problema: str
    classificacao: str | None = None
    titulo: str | None = None
    titulo_exibicao: str | None = None
    impacto_negocio: str | None = None
    acao_recomendada: str | None = None
    responsavel_padrao: str | None = None
    origem: str | None = None
    campo_afetado: str | None = None
    criterios_operacionais: Any | None = None
    severidade_padrao: str | None = None
    origem_excecao: str | None = None
    classificacao_excecao: str | None = None
    impacto_negocio_excecao: str | None = None
    acao_recomendada_excecao: str | None = None
    descricao_cenario: str
    regra_identificacao: str
    tratamento_esperado: str
    acao_aplicacao: str
    permite_processamento: bool
    necessita_aprovacao: bool
    prioridade: int
    status_regra: str
    criada_em: datetime
    atualizada_em: datetime


class Mapping(Contract):
    de_para_id: str
    marca: str | None
    processo: str
    campo_origem: str
    valor_origem: str
    valor_padronizado: str
    descricao: str | None
    status: str
    criado_em: datetime
    atualizado_em: datetime
    responsavel: str | None


class MappingHistory(Contract):
    id: int
    de_para_id: str
    acao: str
    valor_padronizado_anterior: str | None
    valor_padronizado_novo: str | None
    status_anterior: str | None
    status_novo: str | None
    responsavel: str | None
    observacao: str | None
    registrado_em: datetime


class Collaborator(Contract):
    colaborador_id_interno: str
    marca: str
    chave_identidade: str
    usuario_referencia: str | None
    nome_referencia: str | None
    nome_normalizado: str | None
    primeira_execucao_id: str
    ultima_execucao_id: str
    primeira_observacao_em: datetime
    ultima_observacao_em: datetime
    quantidade_observacoes: int


class OperationConfig(Contract):
    """Espelha pdoh_controle.configuracao_operacao (parametros da operacao)."""
    marca: str
    operacao: str
    descricao: str
    fontes_jornada: Any
    perfis_operacionais: Any
    atualizado_em: datetime


class EvidenceSource(Contract):
    """Espelha pdoh_controle.configuracao_evidencia (matriz de origem por marca)."""
    marca: str
    operacao: str
    papel: str
    tabela: str
    campos: Any
    descricao: str | None
    atualizado_em: datetime


class EvidenceRule(Contract):
    """Espelha pdoh_controle.configuracao_evidencia_regra (como comprovar o cenario)."""
    marca: str
    operacao: str
    tipo_problema: str
    papel: str
    campo: str | None
    valor_esperado: str | None
    criterios: Any
    papeis_apoio: Any
    atualizado_em: datetime


class GovernanceRuleConfig(Contract):
    configuracao_id: str
    marca: str
    operacao: str
    nome_regra: str
    codigo_interno: str
    categoria: str
    status: str
    prioridade: int
    tempo_minimo_minutos: int
    descricao: str
    comportamento_esperado: str
    regra_catalogo_id: str | None
    geracao_automatica_ativa: bool
    usuario_alteracao: str
    criada_em: datetime
    atualizada_em: datetime


class GovernanceConditionConfig(Contract):
    condicao_id: str
    configuracao_id: str
    tipo: str
    ordem: int
    papel_fonte: str
    campo_logico: str
    operador: str
    valor_esperado: Any | None
    descricao: str
    status: str
    usuario_alteracao: str
    criada_em: datetime
    atualizada_em: datetime


class SemanticSourceConfig(Contract):
    fonte_id: str
    marca: str
    operacao: str
    papel: str
    tipo: str
    prioridade: int
    schema_fisico: str | None
    tabela_fisica: str | None
    mapeamento_campos: Any
    status: str
    descricao: str | None
    usuario_alteracao: str
    criada_em: datetime
    atualizada_em: datetime


class GovernanceTreatmentConfig(Contract):
    tratamento_id: str
    configuracao_id: str
    resultado: str
    acao_recomendada: str
    destino: str
    gera_oportunidade: bool
    status: str
    usuario_alteracao: str
    criada_em: datetime
    atualizada_em: datetime


class JourneyPriorityConfig(Contract):
    etapa_id: str
    marca: str
    operacao: str
    prioridade: int
    origem_codigo: str
    papel_fonte: str
    fallback: bool
    status: str
    aplicado_no_processamento: bool
    descricao: str
    usuario_alteracao: str
    criada_em: datetime
    atualizada_em: datetime


class GovernanceHistory(Contract):
    id: int
    marca: str
    operacao: str
    entidade_tipo: str
    entidade_id: str
    codigo_referencia: str | None
    acao: str
    valor_anterior: Any | None
    valor_novo: Any | None
    usuario: str
    motivo: str
    registrado_em: datetime


class Entity(Contract):
    identificador_id: str
    tipo_entidade: str
    identificador_interno: str
    chave_identidade: str
    nome_original: str | None
    nome_normalizado: str | None
    origem_dado: str
    marca: str
    primeira_execucao_id: str
    ultima_execucao_id: str
    quantidade_observacoes: int
    data_criacao: datetime
    data_atualizacao: datetime
    status: str


class Lineage(Contract):
    id: int
    execution_id: str
    marca: str
    tabela_destino: str
    colaborador: str | None
    data_referencia: date | None
    chave_negocio_hash: str
    linha_hash: str
    acao: str
    registrado_em: datetime


class ExecutionDetail(Execution):
    quantidade_oportunidades: int
    quantidade_etapas: int
    quantidade_fontes: int
    quantidade_saidas: int


class OpportunityView(Opportunity):
    classificacao: str | None = None


class ResearchAssessment(Contract):
    campo: str
    classificacao_sugerida: Literal['OPORTUNIDADE', 'ALERTA', 'TELEMETRIA']
    impacto: str


class OpportunityDetail(OpportunityView):
    execucao: Execution
    regra_atual: Rule | None
    identidade_colaborador: Collaborator | None
    ultima_tratativa: OpportunityHistory | None
    diagnostico_campos: list[ResearchAssessment] = []


class AlertField(Contract):
    campo: str
    tipo: str
    situacao: str
    categoria: str | None = None
    tratativa: str | None = None
    quantidade_ocorrencias: int
    amostra_ids: list[str]


class AlertGroup(Contract):
    chave_grupo: str
    classificacao: Literal['ALERTA'] = 'ALERTA'
    marca: str
    colaborador: str | None
    colaborador_id_interno: str | None
    referencia: str
    criterio_agrupamento: str
    quantidade_ocorrencias: int
    quantidade_registros: int
    primeira_data: date | None
    ultima_data: date | None
    campos: list[AlertField]


class AlertPage(Page[AlertGroup]):
    total_ocorrencias: int
    total_registros: int
    unidade: str = 'Ocorrências observadas (UF consolidada usa a contagem da evidência); repetições entre execuções são preservadas. Filtre execution_id para um snapshot.'


class CountBy(Contract):
    valor: str
    quantidade: int


class BrandPeriod(Contract):
    marca: str
    periodo_inicio: date | None
    periodo_fim: date | None
    quantidade_execucoes: int


class Dashboard(Contract):
    total_execucoes: int
    quantidade_oportunidades: int
    status_execucoes: list[CountBy]
    status_oportunidades: list[CountBy]
    distribuicao_por_tipo: list[CountBy]
    marcas_periodos: Page[BrandPeriod]
    ultimas_execucoes: list[Execution]
    fuso_horario: str = "America/Sao_Paulo"
