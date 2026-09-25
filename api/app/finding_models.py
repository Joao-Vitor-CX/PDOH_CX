from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from .evidence_models import EvidenceSummary, ValidationSummary
from .models import Contract, Page, Pagination, PeriodFilter, ResolvedPeriod


class AlertRecord(Contract):
    alerta_id: str
    execution_id: str
    regra_id: str
    marca: str
    tipo_problema: str
    data_referencia: date | None
    origem: str
    tabela_origem: str
    colaborador: str | None
    colaborador_id_interno: str | None
    campo: str | None
    descricao_detalhada: str
    severidade: str
    status_alerta: str
    tratativa: str | None
    evidencia: Any | None
    fingerprint: str
    identificada_em: datetime
    atualizada_em: datetime


class FindingRoute(Contract):
    achado_id: str
    execution_id: str
    marca: str
    tipo_problema: str
    fingerprint: str
    regra_id: str
    classificacao: str
    destino: str
    registro_id: str
    regra_snapshot: Any
    registrado_em: datetime


class ExecutionContext(Contract):
    execution_id: str
    marca: str
    operacao: str
    finalidade: str
    justificativa: str
    registrado_em: datetime


class FindingReview(Contract):
    id: int
    chave_validacao: str
    registro_id: str
    origem_registro: str
    execution_id: str
    marca: str
    operacao: str
    classificacao: str
    motivo: str
    evidencia: Any
    registrado_em: datetime


class FallbackEvent(Contract):
    fallback_id: str
    execution_id: str
    componente: str
    etapa: str
    codigo: str
    motivo: str
    impacto_esperado: str | None
    severidade: str
    contexto: Any | None
    ocorrido_em: datetime


class FindingFilter(PeriodFilter, Pagination):
    tipo: str | None = Field(None, min_length=1, max_length=100)
    status: str | None = Field(None, min_length=1, max_length=30)
    execution_id: str | None = Field(None, min_length=1, max_length=80)
    regra: str | None = Field(None, min_length=1, max_length=36)
    severidade: str | None = Field(None, min_length=1, max_length=20)
    colaborador: str | None = Field(None, min_length=1, max_length=255)
    periodo: Literal['automatico', 'semana', 'mes', 'personalizado'] | None = None
    incluir_legado: bool = True


class SeverityBreakdown(Contract):
    total: int = 0
    critica: int = 0
    alta: int = 0
    media: int = 0
    baixa: int = 0


class CountOnly(Contract):
    total: int = 0


class FindingSummary(Contract):
    oportunidades: SeverityBreakdown
    alertas: CountOnly
    telemetria: CountOnly
    periodo: ResolvedPeriod


STATUS_OPERACIONAL = Literal['ABERTA', 'EM_ANALISE', 'RESOLVIDA', 'IGNORADA', 'REABERTA']


class OpportunityGroupStatus(Contract):
    """Espelha pdoh_controle.oportunidade_grupo_status (tabela lateral)."""
    grupo_id: str
    marca: str
    tipo_problema: str
    colaborador_id_interno: str | None
    colaborador: str | None
    status_operacional: str
    responsavel: str | None
    observacao: str | None
    resolvido_em: datetime | None
    criado_em: datetime
    atualizado_em: datetime


class GroupFilter(PeriodFilter, Pagination):
    tipo: str | None = Field(None, min_length=1, max_length=100)
    colaborador: str | None = Field(None, min_length=1, max_length=255)
    severidade: str | None = Field(None, min_length=1, max_length=20)
    regra: str | None = Field(None, min_length=1, max_length=36)
    status: STATUS_OPERACIONAL | None = None
    periodo: Literal['automatico', 'semana', 'mes', 'personalizado'] | None = None
    # Por padrao a fila mostra so o que exige acao; resolvidas/ignoradas seguem
    # consultaveis pelo historico.
    incluir_encerradas: bool = False
    incluir_legado: bool = True


class OpportunityGroup(Contract):
    """Card operacional: um problema por regra + colaborador + contexto, nunca por evento."""
    grupo_id: str
    operacao: str = 'EXCLUSIVA'
    marca: str
    tipo_problema: str
    titulo: str                      # regra_tratativa.titulo_exibicao
    colaborador: str | None
    campo: str | None                # dimensao do problema (campo afetado)
    origem: str | None               # fonte do dado que originou o problema
    quantidade: int                  # ocorrencias distintas — contador, nunca novo card
    registros_historicos: int        # regravacoes por dia/execucao, so para auditoria
    dias_afetados: int
    primeira_ocorrencia: date | None
    ultima_ocorrencia: date | None
    severidade: str
    impacto: str | None              # regra_tratativa.impacto_negocio
    acao_recomendada: str | None     # regra_tratativa.acao_recomendada
    status_operacional: STATUS_OPERACIONAL
    responsavel: str | None
    # Comprovacao: de onde veio o dado e se a evidencia foi confirmada na fonte oficial.
    evidencia: EvidenceSummary
    validacao: ValidationSummary


class AlertGroup(Contract):
    """Card de alerta: um problema cadastral por regra + colaborador + contexto."""
    grupo_id: str
    operacao: str = 'EXCLUSIVA'
    marca: str
    tipo_problema: str
    titulo: str
    colaborador: str | None
    campo: str | None
    origem: str | None
    quantidade_alertas: int          # alertas distintos
    ocorrencias_acumuladas: int      # soma das ocorrencias informadas na evidencia
    registros_historicos: int
    dias_afetados: int
    primeira_ocorrencia: date | None
    ultima_ocorrencia: date | None
    severidade: str
    impacto: str | None          # por que e' pendencia (motivo cadastrado na regra)
    acao_recomendada: str | None # tratativa
    evidencia: EvidenceSummary
    validacao: ValidationSummary


class AlertCategory(Contract):
    tipo_problema: str
    titulo: str
    severidade: str
    grupos: int
    alertas: int
    ocorrencias_acumuladas: int
    colaboradores_afetados: int


class AlertOverview(Contract):
    """Totais de TODOS os grupos do filtro (nao so da pagina)."""
    periodo: ResolvedPeriod
    grupos: int
    alertas: int
    ocorrencias_acumuladas: int
    colaboradores_afetados: int
    por_regra: list[AlertCategory]


class AlertGroupPage(Page[AlertGroup]):
    resumo: AlertOverview


class OccurrenceView(Contract):
    """Ocorrencia individual dentro de um grupo (visao tecnica / auditoria)."""
    fingerprint: str
    oportunidade_id: str
    execution_id: str
    data_referencia: date | None
    tabela_origem: str
    origem: str
    severidade: str
    evidencia: Any | None
    identificada_em: datetime
    repeticoes: int          # quantas vezes o mesmo achado foi regravado por execucao


class GroupDetail(Contract):
    grupo_id: str
    operacao: str = 'EXCLUSIVA'
    marca: str
    tipo_problema: str
    titulo: str
    colaborador: str | None
    colaborador_id_interno: str | None
    campo: str | None
    origem: str | None
    quantidade: int
    impacto: str | None
    acao_recomendada: str | None
    status_operacional: STATUS_OPERACIONAL
    periodo: ResolvedPeriod
    ocorrencias: Page[OccurrenceView]


class FindingView(Contract):
    id: str
    origem_registro: Literal['OPORTUNIDADE', 'OPORTUNIDADE_LEGADO', 'ALERTA', 'EXECUCAO_EVENTO', 'FALLBACK_EVENTO']
    classificacao: Literal['OPORTUNIDADE', 'ALERTA', 'TELEMETRIA']
    criterio_classificacao: str
    execution_id: str
    marca: str
    regra_id: str | None
    tipo_problema: str
    data_referencia: date | None
    colaborador: str | None
    colaborador_id_interno: str | None
    descricao: str
    severidade: str
    status: str | None
    campo: str | None
    tratativa: str | None
    evidencia: Any | None
    regra_snapshot: Any | None
    registrado_em: datetime
