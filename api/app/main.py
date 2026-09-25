"""Factory: python -m uvicorn api.app.main:create_app --factory --host 127.0.0.1."""
from contextlib import asynccontextmanager
import hmac
import logging
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError

from . import models as m
from .config import Settings
from .database import Database
from .repository import Repository
from .fallback import resolve_fallback, simulate_fallback
from .fallback_models import FallbackQuery, FallbackResolution, SimulationRequest, SimulationResult
from .finding_models import (
    AlertGroupPage, FindingFilter, FindingSummary, FindingView, GroupDetail, GroupFilter, OpportunityGroup,
)
from .findings_repository import (
    alert_summary, finding_page, finding_resumo, group_details, opportunity_summary,
)
from .evidence_models import EvidenceMatrix, GroupEvidence
from .evidence_repository import evidence_matrix, group_evidence
from .operation_config import _fontes_semanticas, _governance_rules, operation_config
from .pdoh_models import (
    GovernanceRule, OperationConfigResponse, PdohCollaborator, PdohCompositionResponse, PdohSummary,
    PdohFilter, PdohTrendFilter, PdohTrendResponse,
)
from .pdoh_repository import pdoh_colaborador, pdoh_composicao, pdoh_evolucao, pdoh_summary
from .rule_admin import RuleChange, RuleCreate, RuleEdit, RuleWriter, atualizar_regra, criar_regra
from .models import Contract

Identifier = Annotated[str, Path(min_length=1, max_length=80)]
# O grupo_id codifica marca + regra + colaborador, entao e' mais longo que um UUID.
GroupIdentifier = Annotated[str, Path(min_length=1, max_length=512)]
PageQuery = Annotated[m.Pagination, Query()]
# O id do colaborador e' opaco (marca + nome em base64url); nunca um UUID interno.
CollaboratorIdentifier = Annotated[str, Path(min_length=1, max_length=512)]
BrandQuery = Annotated[str | None, Query(min_length=1, max_length=80)]


class RuleEditResult(Contract):
    """Resposta do PATCH de regra: o que mudou e a regra como ficou (mesma forma da leitura)."""
    alterado: bool
    alteracoes: list[RuleChange]
    regra: GovernanceRule


class RuleCreateResult(Contract):
    """Resposta do POST de regra: a oportunidade nasce já como o usuário configurou."""
    criado: bool
    alteracoes: list[RuleChange]
    regra: GovernanceRule


def create_app(settings=None, database=None, writer=None):
    settings = settings or Settings.load()
    database = database or Database(settings)
    # Edicao de regras: conta propria e opcional. Sem ela a API e' somente leitura (503 na rota).
    if writer is None and settings.config_password:
        writer = RuleWriter(settings)

    @asynccontextmanager
    async def lifespan(app):
        try:
            database.initialize()
            if writer is not None:
                writer.initialize()
            yield
        finally:
            database.close()
            if writer is not None:
                writer.close()

    app = FastAPI(title="PDOH_CX API de Consulta", version="1.0.0", lifespan=lifespan,
                  description="Somente leitura, exceto a edicao auditada de regras de oportunidade (PATCH /api/v2/configuracoes/regras/{codigo}), feita por conta propria de minimo privilegio. Periodos filtram a janela processada (sobreposicao inclusiva). Datas DATETIME sao locais em America/Sao_Paulo. Status preservam o banco.")
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.origins), allow_methods=["GET", "POST", "PATCH"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False)
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
        if not settings.token or credentials is None or not hmac.compare_digest(credentials.credentials.encode(), settings.token.encode()):
            raise HTTPException(401, "Autenticacao necessaria.", headers={"WWW-Authenticate": "Bearer"})

    def repository(_=Depends(authenticate)):
        with database.connection() as connection:
            yield Repository(connection, database.tables)

    Repo = Annotated[Repository, Depends(repository)]

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def unavailable(_request, error):
        identifier = str(uuid4())
        logging.getLogger("pdoh.api").error("Consulta indisponivel; id=%s; tipo=%s", identifier, type(error).__name__)
        return JSONResponse(status_code=503, content={"detail": "Banco de consulta indisponivel.", "error_id": identifier})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, error):
        # Não retorna objetos de exceção nem valores sensíveis enviados pelo cliente.
        return JSONResponse(status_code=422, content={"detail": [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in error.errors()
        ]})

    prefix = "/api/v1"

    @app.get('/api/v2/oportunidades', response_model=m.Page[FindingView], tags=['Achados v2'])
    def operational_findings(filters: Annotated[FindingFilter, Query()], repo: Repo):
        return finding_page(repo, filters, 'OPORTUNIDADE')

    @app.get('/api/v2/alertas', response_model=m.Page[FindingView], tags=['Achados v2'])
    def alert_findings(filters: Annotated[FindingFilter, Query()], repo: Repo):
        return finding_page(repo, filters, 'ALERTA')

    @app.get('/api/v2/telemetria', response_model=m.Page[FindingView], tags=['Achados v2'])
    def telemetry_findings(filters: Annotated[FindingFilter, Query()], repo: Repo):
        return finding_page(repo, filters, 'TELEMETRIA')

    @app.get('/api/v2/findings/resumo', response_model=FindingSummary, tags=['Achados v2'])
    def findings_summary(filters: Annotated[FindingFilter, Query()], repo: Repo):
        return finding_resumo(repo, filters)

    @app.get('/api/v2/oportunidades/resumo', response_model=m.Page[OpportunityGroup], tags=['Fila operacional'])
    def opportunity_groups(filters: Annotated[GroupFilter, Query()], repo: Repo):
        return opportunity_summary(repo, filters)

    @app.get('/api/v2/oportunidades/{grupo_id}/detalhes', response_model=GroupDetail, tags=['Fila operacional'])
    def opportunity_group_details(grupo_id: GroupIdentifier, filters: Annotated[GroupFilter, Query()], repo: Repo):
        return group_details(repo, grupo_id, filters)

    @app.get('/api/v2/alertas/resumo', response_model=AlertGroupPage, tags=['Fila operacional'])
    def alert_groups(filters: Annotated[GroupFilter, Query()], repo: Repo):
        return alert_summary(repo, filters)

    @app.get('/api/v2/oportunidades/{grupo_id}/evidencias', response_model=GroupEvidence,
             tags=['Evidencia operacional'])
    def opportunity_group_evidence(grupo_id: GroupIdentifier, filters: Annotated[GroupFilter, Query()], repo: Repo):
        return group_evidence(repo, grupo_id, filters)

    @app.get('/api/v2/configuracoes/evidencias', response_model=EvidenceMatrix, tags=['Configuracao'])
    def evidence_settings(repo: Repo, marca: BrandQuery = None, operacao: str = 'EXCLUSIVA'):
        return evidence_matrix(repo, marca, operacao)

    @app.get('/api/v2/pdoh/resumo', response_model=PdohSummary, tags=['Indicador PDOH'])
    def pdoh_indicator(filters: Annotated[PdohFilter, Query()], repo: Repo):
        return pdoh_summary(repo, filters)

    @app.get('/api/v2/pdoh/composicao', response_model=PdohCompositionResponse, tags=['Indicador PDOH'])
    def pdoh_composition(filters: Annotated[PdohFilter, Query()], repo: Repo):
        return pdoh_composicao(repo, filters)

    @app.get('/api/v2/pdoh/evolucao', response_model=PdohTrendResponse, tags=['Indicador PDOH'])
    def pdoh_trend(filters: Annotated[PdohTrendFilter, Query()], repo: Repo):
        return pdoh_evolucao(repo, filters, filters.granularidade)

    @app.get('/api/v2/pdoh/colaborador/{id}', response_model=PdohCollaborator, tags=['Indicador PDOH'])
    def pdoh_collaborator(id: CollaboratorIdentifier, filters: Annotated[PdohFilter, Query()], repo: Repo):
        return pdoh_colaborador(repo, id, filters)

    @app.get('/api/v2/configuracoes/operacao', response_model=OperationConfigResponse, tags=['Configuracao'])
    def operation_settings(repo: Repo, marca: BrandQuery = None, operacao: BrandQuery = None):
        return operation_config(repo, marca, operacao)

    @app.post('/api/v2/configuracoes/regras', response_model=RuleCreateResult, tags=['Configuracao'])
    def create_rule(criacao: RuleCreate, marca: Annotated[str, Query(min_length=1, max_length=80)],
                     operacao: Annotated[str, Query(min_length=1, max_length=80)] = 'EXCLUSIVA',
                     _=Depends(authenticate)):
        """Cadastra a oportunidade que o usuário configurou. Sem isso, ela não existe."""
        if writer is None or not writer.disponivel:
            raise HTTPException(503, "Edicao de regras indisponivel neste ambiente.")
        codigo, alteracoes = criar_regra(writer, marca, operacao, criacao)
        with database.connection() as connection:
            leitura = Repository(connection, database.tables)
            fontes = _fontes_semanticas(leitura, marca, operacao)
            regra = next((item for item in _governance_rules(leitura, marca, operacao, fontes)
                          if item['codigo_interno'] == codigo), None)
        if regra is None:
            raise HTTPException(500, "Oportunidade criada, mas não encontrada na releitura.")
        return dict(criado=True, alteracoes=alteracoes, regra=regra)

    @app.patch('/api/v2/configuracoes/regras/{codigo}', response_model=RuleEditResult, tags=['Configuracao'])
    def edit_rule(codigo: Identifier, edicao: RuleEdit, marca: Annotated[str, Query(min_length=1, max_length=80)],
                  operacao: Annotated[str, Query(min_length=1, max_length=80)] = 'EXCLUSIVA',
                  _=Depends(authenticate)):
        """Unica escrita da API: altera uma regra JA cadastrada, com historico na mesma transacao."""
        if writer is None or not writer.disponivel:
            raise HTTPException(503, "Edicao de regras indisponivel neste ambiente.")
        alteracoes = atualizar_regra(writer, marca, operacao, codigo, edicao)
        # Releitura em conexao nova, pelo mesmo caminho da tela: o que o usuario ve e' o que ficou.
        with database.connection() as connection:
            leitura = Repository(connection, database.tables)
            fontes = _fontes_semanticas(leitura, marca, operacao)
            regra = next((item for item in _governance_rules(leitura, marca, operacao, fontes)
                          if item['codigo_interno'] == codigo), None)
        if regra is None:
            raise HTTPException(404, "Regra nao encontrada apos a edicao.")
        return dict(alterado=bool(alteracoes), alteracoes=alteracoes, regra=regra)

    @app.get(prefix + "/fallback/resolver", response_model=FallbackResolution, tags=["Fallback"])
    def fallback_resolution(filters: Annotated[FallbackQuery, Query()], repo: Repo):
        return resolve_fallback(repo.connection, repo.tables, filters)

    @app.post("/api/fallback/simular", response_model=SimulationResult, tags=["Fallback"])
    @app.post(prefix + "/fallback/simular", response_model=SimulationResult, tags=["Fallback"])
    def fallback_simulation(payload: SimulationRequest, repo: Repo):
        return simulate_fallback(repo.connection, repo.tables, payload)

    @app.get(prefix + "/health", tags=["Operacao"])
    def health(repo: Repo):
        from sqlalchemy import text
        repo.connection.execute(text("SELECT 1"))
        return {"status": "ok", "modo": "somente_leitura",
                "edicao_de_regras": "habilitada" if writer is not None and writer.disponivel else "desabilitada"}

    @app.get(prefix + "/dashboard", response_model=m.Dashboard, tags=["Dashboard"])
    def dashboard(filters: Annotated[m.DashboardFilter, Query()], repo: Repo):
        return repo.dashboard(filters)

    @app.get(prefix + "/execucoes", response_model=m.Page[m.Execution], tags=["Execucoes"])
    def executions(filters: Annotated[m.ExecutionFilter, Query()], repo: Repo):
        return repo.executions(filters)

    @app.get(prefix + "/execucoes/{id}", response_model=m.ExecutionDetail, tags=["Execucoes"])
    def execution(id: Identifier, repo: Repo):
        return repo.execution(id)

    @app.get(prefix + "/execucoes/{id}/etapas", response_model=m.Page[m.Stage], tags=["Rastreabilidade"])
    def stages(id: Identifier, pagination: PageQuery, repo: Repo):
        return repo.children("execucao", "execution_id", id, "execucao_etapa", pagination, "ocorrido_em")

    @app.get(prefix + "/execucoes/{id}/fontes", response_model=m.Page[m.Source], tags=["Rastreabilidade"])
    def sources(id: Identifier, pagination: PageQuery, repo: Repo):
        return repo.children("execucao", "execution_id", id, "execucao_fonte", pagination, "registrado_em")

    @app.get(prefix + "/execucoes/{id}/linhagem", response_model=m.Page[m.Lineage], tags=["Rastreabilidade"])
    def lineage(id: Identifier, pagination: PageQuery, repo: Repo):
        return repo.children("execucao", "execution_id", id, "saida_linhagem", pagination, "registrado_em")

    @app.get(prefix + "/alertas", response_model=m.AlertPage, tags=["Alertas"])
    def alerts(filters: Annotated[m.AlertFilter, Query()], repo: Repo):
        return repo.alerts(filters)

    @app.get(prefix + "/alertas/{id}/registros", response_model=m.Page[m.OpportunityView], tags=["Alertas"])
    def alert_records(id: Identifier, filters: Annotated[m.AlertFilter, Query()], repo: Repo):
        return repo.alert_records(id, filters)

    @app.get(prefix + "/oportunidades", response_model=m.Page[m.OpportunityView], tags=["Oportunidades"])
    def opportunities(filters: Annotated[m.OpportunityFilter, Query()], repo: Repo):
        return repo.opportunities(filters)

    @app.get(prefix + "/oportunidades/{id}", response_model=m.OpportunityDetail, tags=["Oportunidades"])
    def opportunity(id: Identifier, repo: Repo):
        return repo.opportunity(id)

    @app.get(prefix + "/oportunidades/{id}/historico", response_model=m.Page[m.OpportunityHistory], tags=["Historico"])
    def opportunity_history(id: Identifier, pagination: PageQuery, repo: Repo):
        return repo.children("oportunidade", "oportunidade_id", id, "oportunidade_historico", pagination, "registrado_em")

    @app.get(prefix + "/regras", response_model=m.Page[m.Rule], tags=["Regras"])
    def rules(filters: Annotated[m.RuleFilter, Query()], repo: Repo):
        return repo.catalog("regra_tratativa", filters)

    @app.get(prefix + "/de-para", response_model=m.Page[m.Mapping], tags=["De/Para"])
    def mappings(filters: Annotated[m.MappingFilter, Query()], repo: Repo):
        return repo.catalog("de_para", filters)

    @app.get(prefix + "/de-para/{id}/historico", response_model=m.Page[m.MappingHistory], tags=["Historico"])
    def mapping_history(id: Identifier, pagination: PageQuery, repo: Repo):
        return repo.children("de_para", "de_para_id", id, "de_para_historico", pagination, "registrado_em")

    @app.get(prefix + "/colaboradores/{id}", response_model=m.Collaborator, tags=["Rastreabilidade"])
    def collaborator(id: Identifier, repo: Repo):
        return repo.one("colaborador_identidade", "colaborador_id_interno", id)

    @app.get(prefix + "/entidades", response_model=m.Page[m.Entity], tags=["Rastreabilidade"])
    def entities(filters: Annotated[m.EntityFilter, Query()], repo: Repo):
        return repo.entities(filters)

    @app.get(prefix + "/entidades/{id}", response_model=m.Entity, tags=["Rastreabilidade"])
    def entity(id: Identifier, repo: Repo):
        return repo.one("identificador_entidade", "identificador_id", id)

    return app
