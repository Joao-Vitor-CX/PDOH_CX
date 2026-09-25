"""Contratos da camada de evidencia operacional. Somente leitura."""
from datetime import date
from typing import Any

from .models import Contract, ResolvedPeriod


class EvidenceSummary(Contract):
    """Prova resumida para o card da fila: o que se esperava e o que veio."""
    campo: str | None = None
    valor_esperado: str | None = None
    valor_encontrado: str | None = None
    fonte: str | None = None


class ValidationSummary(Contract):
    """Status da comprovacao. `indisponivel` nunca e' tratado como aprovado."""
    resultado: str
    rotulo: str
    motivo: str | None = None
    jornada_origem: str


class EvidenceLine(Contract):
    """Um criterio comprovado (ou nao) na fonte oficial."""
    fonte: str | None
    campo: str | None
    valor_encontrado: str | None
    valor_esperado: str | None
    validacao: str
    atendido: bool | None


class EvidenceOpportunity(Contract):
    grupo_id: str
    regra: str
    titulo: str
    impacto: str | None
    colaborador: str | None
    campo: str | None
    origem: str | None
    quantidade: int
    status_operacional: str
    periodo: ResolvedPeriod


class EvidenceValidation(ValidationSummary):
    justificativa: bool | None = None
    atestado: bool | None = None
    ocorrencias_comprovadas: int = 0
    ocorrencias_avaliadas: int = 0


class EvidenceOrigin(Contract):
    papel: str | None
    tabela: str | None
    campo: str | None
    valor_esperado: str | None
    criterios: list[str]


class EvidenceTreatment(Contract):
    acao_recomendada: str | None
    responsavel: str | None


class EvidenceOccurrence(Contract):
    regra: str
    colaborador: str | None
    data: str | None
    resultado_validacao: str
    fonte: str | None
    campo: str | None
    valor_esperado: str | None
    valor_encontrado: str | None
    motivo: str | None
    impacto: str | None
    tratativa: str | None
    jornada_origem: str
    # Regra configuravel: o que a regra concluiu e a configuracao vigente NAQUELE momento.
    resultado_regra: str | None = None
    configuracao: dict[str, Any] | None = None


class AppliedRule(Contract):
    """Regra que gerou a oportunidade, com a configuracao usada (auditoria)."""
    codigo: str
    nome: str | None
    fonte: str | None                 # rotulo de negocio, ex.: "PDOH Platina"
    fonte_tabela: str | None          # tabela fisica consultada
    campo: str | None
    esperado: str | None
    encontrado: str | None
    resultado: str | None             # ex.: "Oportunidade gerada"
    configuracao: dict[str, Any]      # tempo minimo, condicoes e excecoes vigentes


class GroupEvidence(Contract):
    """GET /api/v2/oportunidades/{grupo_id}/evidencias."""
    oportunidade: EvidenceOpportunity
    validacao: EvidenceValidation
    fonte: EvidenceOrigin
    evidencias: list[EvidenceLine]
    tratamento: EvidenceTreatment
    ocorrencias: list[EvidenceOccurrence] = []
    regra_aplicada: AppliedRule | None = None


class MatrixSource(Contract):
    papel: str
    tabela: str
    campos: dict[str, Any]


class MatrixRule(Contract):
    tipo_problema: str
    papel: str
    campo: str | None
    valor_esperado: str | None
    criterios: list[str]
    papeis_apoio: list[str]


class BrandMatrix(Contract):
    marca: str
    operacao: str
    fontes: list[MatrixSource]
    regras: list[MatrixRule]


class EvidenceMatrix(Contract):
    """GET /api/v2/configuracoes/evidencias — matriz de origem como cadastrada."""
    marcas: list[BrandMatrix]


class JourneyTrace(Contract):
    """Rastreabilidade da jornada de um colaborador na data consultada."""
    colaborador: str
    data_referencia: date | None
    jornada_semanal: float | None
    jornada_origem: str
    fonte: str | None
    campo: str | None
    status_resolucao: str
    vigente: bool
    elegivel: bool
    fontes_verificadas: list[dict[str, Any]]
