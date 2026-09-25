"""Sem imports do pipeline, DDL ou bootstrap; falha se schema/privilegios divergem."""
from contextlib import contextmanager
from datetime import datetime
import json
import logging
import re

from sqlalchemy import JSON, MetaData, Table, cast, create_engine, event, literal, select, union_all
from sqlalchemy.dialects.mysql import CHAR as MySQLChar

from . import models as m
from .fallback_models import FallbackConfig, FallbackHistory
from .finding_models import AlertRecord, FindingRoute, OpportunityGroupStatus, ExecutionContext, FindingReview, FallbackEvent
from shared.treatment_catalog import listar_regras

TABLE_MODELS = {
    "execucao": m.Execution, "execucao_etapa": m.Stage, "execucao_fonte": m.Source,
    "oportunidade": m.Opportunity, "oportunidade_historico": m.OpportunityHistory,
    "regra_tratativa": m.Rule, "de_para": m.Mapping, "de_para_historico": m.MappingHistory,
    "colaborador_identidade": m.Collaborator, "identificador_entidade": m.Entity,
    "saida_linhagem": m.Lineage,
    "execucao_evento": m.ExecutionEvent,
    "configuracao_operacao": m.OperationConfig,
    "configuracao_evidencia": m.EvidenceSource,
    "configuracao_evidencia_regra": m.EvidenceRule,
    "regra_configuracao": m.GovernanceRuleConfig,
    "regra_condicao_configuracao": m.GovernanceConditionConfig,
    "fonte_semantica_configuracao": m.SemanticSourceConfig,
    "regra_tratamento_configuracao": m.GovernanceTreatmentConfig,
    "jornada_prioridade_configuracao": m.JourneyPriorityConfig,
    "governanca_configuracao_historico": m.GovernanceHistory,
    "regra_fallback_config": FallbackConfig,
    "regra_fallback_historico": FallbackHistory,
    "alerta": AlertRecord, "achado_roteamento": FindingRoute,
    "oportunidade_grupo_status": OpportunityGroupStatus,
    "execucao_contexto": ExecutionContext, "achado_revisao": FindingReview,
    "fallback_evento": FallbackEvent,
}

# Fonte oficial do indicador PDOH por marca: (schema, tabela) da Platina. Leitura de
# UMA tabela por marca; nenhum outro objeto fora de pdoh_controle e' aceito.
PLATINA_PDOH = {
    "BRACELL": ("produtos_platina", "exclusivo_bracell_platina_relatorio_pdoh"),
}
COLUNAS_PLATINA_PDOH = {"colaborador", "data"}


def _grants_platina_permitidos():
    return {f"GRANT SELECT ON `{schema}`.`{tabela}`" for schema, tabela in PLATINA_PDOH.values()}


def validate_grants(grants):
    """Recusa contas com escrita, roles, GRANT OPTION ou acesso fora do permitido.

    Permitido: USAGE, SELECT em pdoh_controle.* e SELECT nas tabelas oficiais do PDOH
    listadas em PLATINA_PDOH (somente leitura, tabela a tabela).
    """
    has_select = False
    platina = _grants_platina_permitidos()
    for grant in grants:
        privilege = grant.split(" TO ", 1)[0]
        if "WITH GRANT OPTION" in grant:
            raise RuntimeError("A conta da API nao pode possuir GRANT OPTION.")
        if privilege == "GRANT USAGE ON *.*":
            continue
        if privilege == "GRANT SELECT ON `pdoh_controle`.*":
            has_select = True
            continue
        if privilege in platina:
            continue
        raise RuntimeError("A conta da API deve possuir apenas SELECT em pdoh_controle.*, "
                           "SELECT nas tabelas oficiais do PDOH e USAGE.")
    if not has_select:
        raise RuntimeError("SELECT em pdoh_controle.* ausente.")


# `regra_tratativa` deixou de ser tabela: o catalogo (shared.treatment_catalog) e' a
# fonte, montado aqui como um FromClause (UNION ALL de linhas literais) para que todo o
# SQL existente que faz JOIN/subquery/filtro/paginacao contra `repo.tables['regra_tratativa']`
# continue funcionando sem nenhuma alteracao -- so' o texto SQL final muda (a tabela vira
# uma derived table de ~24 linhas fixas), a logica de paginacao/filtro/ordenacao das
# consultas que a usam (em findings_repository.py e repository.py) nao e' tocada.
# `criada_em`/`atualizada_em` nao tem mais sentido por linha (nao ha mais UPDATE de banco);
# fixado no momento desta migracao so' para satisfazer o contrato de `models.Rule`, sem
# nenhum uso de exibicao/ordenacao encontrado no codigo.
_CATALOGO_MIGRADO_EM = datetime(2026, 9, 23)


def _tabela_regra_tratativa_do_catalogo():
    linhas = listar_regras()

    def linha_select(regra):
        return select(
            # regra_id e' CHAR(36) CHARACTER SET ascii COLLATE ascii_bin na tabela original
            # (e em oportunidade.regra_id/alerta.regra_id, que comparam contra ele) -- sem
            # casar charset/collation aqui, COALESCE/JOIN com essas colunas falha com
            # "Illegal mix of collations" no MySQL.
            cast(literal(regra["regra_id"]), MySQLChar(36, charset="ascii")).collate("ascii_bin").label("regra_id"),
            literal(regra["marca"]).label("marca"),
            literal(regra["tipo_problema"]).label("tipo_problema"),
            literal(regra["classificacao"]).label("classificacao"),
            literal(regra["titulo"]).label("titulo"),
            literal(regra["titulo_exibicao"]).label("titulo_exibicao"),
            literal(regra["impacto_negocio"]).label("impacto_negocio"),
            literal(regra["acao_recomendada"]).label("acao_recomendada"),
            literal(regra["responsavel_padrao"]).label("responsavel_padrao"),
            literal(regra["origem"]).label("origem"),
            literal(regra["campo_afetado"]).label("campo_afetado"),
            cast(literal(json.dumps(regra["criterios_operacionais"])), JSON).label("criterios_operacionais"),
            literal(regra["severidade_padrao"]).label("severidade_padrao"),
            literal(regra["origem_excecao"]).label("origem_excecao"),
            literal(regra["classificacao_excecao"]).label("classificacao_excecao"),
            literal(regra["impacto_negocio_excecao"]).label("impacto_negocio_excecao"),
            literal(regra["acao_recomendada_excecao"]).label("acao_recomendada_excecao"),
            literal(regra["descricao_cenario"]).label("descricao_cenario"),
            literal(regra["regra_identificacao"]).label("regra_identificacao"),
            literal(regra["tratamento_esperado"]).label("tratamento_esperado"),
            literal(regra["acao_aplicacao"]).label("acao_aplicacao"),
            literal(regra["permite_processamento"]).label("permite_processamento"),
            literal(regra["necessita_aprovacao"]).label("necessita_aprovacao"),
            literal(regra["prioridade"]).label("prioridade"),
            literal(regra["status_regra"]).label("status_regra"),
            literal(_CATALOGO_MIGRADO_EM).label("criada_em"),
            literal(_CATALOGO_MIGRADO_EM).label("atualizada_em"),
        )

    return union_all(*[linha_select(regra) for regra in linhas]).subquery("regra_tratativa")


class Database:
    def __init__(self, settings):
        self.engine = create_engine(settings.url(), pool_pre_ping=True, pool_size=5,
                                    max_overflow=5, pool_recycle=300, hide_parameters=True,
                                    isolation_level="REPEATABLE READ",
                                    connect_args={"connect_timeout": 5, "read_timeout": 15, "write_timeout": 5})

        @event.listens_for(self.engine, "connect")
        def configure(dbapi_connection, _):
            with dbapi_connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute("SET SESSION MAX_EXECUTION_TIME = 10000")
                cursor.execute("SET SESSION time_zone = '-03:00'")

        @event.listens_for(self.engine, "before_cursor_execute")
        def restrict(_conn, _cursor, statement, _parameters, _context, _many):
            # Defesa adicional: nem consultas arbitrarias nem SQL de escrita entram aqui.
            if not re.match(r"^\s*(SELECT|SHOW|DESCRIBE)\b", statement, re.I):
                raise RuntimeError("Comando SQL nao permitido na API de consulta.")

        self.tables = {}

    def initialize(self):
        with self.engine.connect() as connection:
            validate_grants([row[0] for row in connection.exec_driver_sql("SHOW GRANTS")])
            metadata = MetaData(schema="pdoh_controle")
            for name, model in TABLE_MODELS.items():
                if name == "regra_tratativa":
                    # Catalogo em codigo (shared.treatment_catalog), nao mais tabela: nao ha
                    # o que refletir do banco.
                    continue
                table = Table(name, metadata, autoload_with=connection)
                missing = set(model.model_fields) - set(table.c.keys())
                if missing:
                    raise RuntimeError(f"Schema incompativel: {name}; campos ausentes: {sorted(missing)}")
                self.tables[name] = table
            self.tables["regra_tratativa"] = _tabela_regra_tratativa_do_catalogo()
            faltando_catalogo = set(m.Rule.model_fields) - set(self.tables["regra_tratativa"].c.keys())
            if faltando_catalogo:
                raise RuntimeError(
                    f"Catalogo de regra_tratativa incompleto; campos ausentes: {sorted(faltando_catalogo)}")
            # Fonte oficial do PDOH e' opcional: sem permissao ou sem tabela, o indicador
            # responde "indisponivel" com o motivo, e o restante da API segue no ar.
            for marca, (schema, nome) in PLATINA_PDOH.items():
                try:
                    tabela = Table(nome, MetaData(schema=schema), autoload_with=connection)
                except Exception as error:  # permissao ausente ou tabela inexistente
                    logging.getLogger("pdoh.api").warning(
                        "Fonte oficial do PDOH indisponivel; marca=%s; tipo=%s", marca, type(error).__name__)
                    continue
                if COLUNAS_PLATINA_PDOH <= set(tabela.c.keys()):
                    self.tables[f"platina_pdoh:{marca}"] = tabela
            # Estrutura de auditoria existente. E opcional para manter compatibilidade
            try:
                self.tables['configuracao_jornada_operacao'] = Table('configuracao_jornada_operacao',
                    MetaData(schema='pdoh_controle'), autoload_with=connection)
            except Exception:
                logging.getLogger('pdoh.api').warning('Configuracao de horarios ainda nao provisionada.')
            # com bases anteriores; sua ausencia aparece como origem nao identificada.
            try:
                jornada = Table("jornada_consolidada", MetaData(schema="pdoh_controle"),
                                autoload_with=connection)
                self.tables["jornada_consolidada"] = jornada
            except Exception as error:
                logging.getLogger("pdoh.api").warning(
                    "Auditoria de jornada indisponivel; tipo=%s", type(error).__name__)

    @contextmanager
    def connection(self):
        # Mesma transacao/snapshot para totais e itens de uma resposta.
        with self.engine.connect() as connection:
            with connection.begin():
                yield connection

    def close(self):
        self.engine.dispose()
