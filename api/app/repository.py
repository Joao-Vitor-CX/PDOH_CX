"""Consultas parametrizadas; nomes de tabela/coluna nunca vêm da requisição."""
import math

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select

from .database import TABLE_MODELS


class Repository:
    def __init__(self, connection, tables):
        self.connection = connection
        self.tables = tables

    def table(self, name):
        return self.tables[name]

    def rows(self, statement):
        return [dict(row) for row in self.connection.execute(statement).mappings()]

    def selection(self, name):
        table = self.table(name)
        return select(*(table.c[key] for key in TABLE_MODELS[name].model_fields))

    def count(self, name, *conditions):
        return self.connection.scalar(select(func.count()).select_from(self.table(name)).where(*conditions))

    def one(self, name, key, value, required=True):
        rows = self.rows(self.selection(name).where(self.table(name).c[key] == value).limit(1))
        if not rows and required:
            raise HTTPException(404, "Registro nao encontrado.")
        return rows[0] if rows else None

    def page(self, statement, pagination):
        total = self.connection.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        rows = self.rows(statement.limit(pagination.tamanho).offset((pagination.pagina - 1) * pagination.tamanho))
        return dict(items=rows, total=total, pagina=pagination.pagina, tamanho=pagination.tamanho,
                    paginas=math.ceil(total / pagination.tamanho))

    def period_conditions(self, filters):
        e = self.table("execucao").c
        clauses = []
        if filters.marca is not None:
            clauses.append(e.marca == filters.marca)
        if getattr(filters, 'operacao', None) is not None:
            clauses.append(e.operacao == filters.operacao)
        # Sobreposição inclusiva da janela processada; nunca mistura data de identificação.
        if filters.periodo_inicio is not None:
            clauses.extend([e.periodo_inicio.is_not(None), e.periodo_fim >= filters.periodo_inicio])
        if filters.periodo_fim is not None:
            clauses.extend([e.periodo_fim.is_not(None), e.periodo_inicio <= filters.periodo_fim])
        return clauses

    def executions(self, filters):
        e = self.table("execucao").c
        clauses = self.period_conditions(filters)
        if filters.status is not None:
            clauses.append(e.status_execucao == filters.status)
        return self.page(self.selection("execucao").where(*clauses).order_by(e.iniciado_em.desc(), e.execution_id.desc()), filters)

    def execution(self, identifier):
        result = self.one("execucao", "execution_id", identifier)
        for name, field in [("oportunidade", "quantidade_oportunidades"), ("execucao_etapa", "quantidade_etapas"),
                            ("execucao_fonte", "quantidade_fontes"), ("saida_linhagem", "quantidade_saidas")]:
            result[field] = self.count(name, self.table(name).c.execution_id == identifier)
        return result

    def children(self, parent, key, identifier, child, pagination, timestamp):
        self.one(parent, key, identifier)
        table = self.table(child).c
        return self.page(self.selection(child).where(table[key] == identifier).order_by(table[timestamp].asc(), table.id.asc()), pagination)

    def opportunity_selection(self, filters):
        o = self.table("oportunidade")
        e = self.table("execucao")
        r = self.table("regra_tratativa")
        clauses = self.period_conditions(filters)
        for param, column in [("tipo", "tipo_problema"), ("status", "status_oportunidade"), ("regra", "regra_id"), ("execution_id", "execution_id")]:
            if (value := getattr(filters, param)) is not None:
                clauses.append(o.c[column] == value)
        if filters.classificacao is not None:
            clauses.append(r.c.classificacao == filters.classificacao)
        source = o.join(e, o.c.execution_id == e.c.execution_id).outerjoin(r, and_(o.c.regra_id == r.c.regra_id, o.c.tipo_problema == r.c.tipo_problema))
        return self.selection('oportunidade').add_columns(r.c.classificacao, r.c.titulo).select_from(source).where(*clauses)

    def opportunities(self, filters):
        o = self.table('oportunidade').c
        statement = self.opportunity_selection(filters)
        # Título contextual não altera o contrato do registro bruto.
        statement = statement.with_only_columns(*[c for c in statement.selected_columns if c.key != 'titulo'])
        return self.page(statement.order_by(o.identificada_em.desc(), o.oportunidade_id.desc()), filters)

    def alerts(self, filters):
        from .alerts import aggregate_alerts, MAX_ALERT_RECORDS
        statement = self.opportunity_selection(filters).order_by(self.table('oportunidade').c.oportunidade_id).limit(MAX_ALERT_RECORDS + 1)
        result = self.connection.execute(statement.execution_options(yield_per=500))
        try:
            return aggregate_alerts(result.mappings(), filters)
        finally:
            result.close()

    def alert_records(self, group_key, filters):
        from .alerts import evidence_fields, group_identity, MAX_ALERT_RECORDS
        statement = self.opportunity_selection(filters).order_by(self.table('oportunidade').c.oportunidade_id).limit(MAX_ALERT_RECORDS + 1)
        result = self.connection.execute(statement.execution_options(yield_per=500))
        total, items = 0, []
        start = (filters.pagina - 1) * filters.tamanho
        try:
            for index, row in enumerate(result.mappings()):
                if index >= MAX_ALERT_RECORDS:
                    raise HTTPException(422, 'Refine marca, período ou execução: limite de 100.000 registros para consolidação.')
                if group_identity(row)[0] != group_key or (filters.campo and filters.campo.casefold() not in [field.casefold() for field in evidence_fields(row['evidencia'])]):
                    continue
                if start <= total < start + filters.tamanho:
                    items.append({key: value for key, value in row.items() if key != 'titulo'})
                total += 1
        finally:
            result.close()
        return dict(items=items, total=total, pagina=filters.pagina, tamanho=filters.tamanho, paginas=math.ceil(total / filters.tamanho))

    def opportunity(self, identifier):
        from .research import research_assessment
        result = self.one("oportunidade", "oportunidade_id", identifier)
        result['diagnostico_campos'] = research_assessment(result)
        result["execucao"] = self.one("execucao", "execution_id", result["execution_id"])
        result["regra_atual"] = self.one("regra_tratativa", "regra_id", result["regra_id"], False) if result["regra_id"] else None
        rule = result['regra_atual']
        result['classificacao'] = rule['classificacao'] if rule and rule['tipo_problema'] == result['tipo_problema'] else None
        identity = result["colaborador_id_interno"]
        result["identidade_colaborador"] = self.one("colaborador_identidade", "colaborador_id_interno", identity, False) if identity else None
        history = self.table("oportunidade_historico").c
        latest = self.rows(self.selection("oportunidade_historico").where(history.oportunidade_id == identifier)
                           .order_by(history.registrado_em.desc(), history.id.desc()).limit(1))
        result["ultima_tratativa"] = latest[0] if latest else None
        return result

    def catalog(self, name, filters):
        c = self.table(name).c
        conditions = []
        if filters.marca is not None:
            brand = c.marca == filters.marca
            conditions.append(or_(brand, c.marca.is_(None)) if filters.incluir_globais else brand)
        status_column = "status_regra" if name == "regra_tratativa" else "status"
        if filters.status is not None:
            conditions.append(c[status_column] == filters.status)
        for param, column in [("tipo", "tipo_problema"), ("processo", "processo"), ("campo_origem", "campo_origem")]:
            if (value := getattr(filters, param, None)) is not None:
                conditions.append(c[column] == value)
        order = [c.prioridade.asc(), c.regra_id.asc()] if name == "regra_tratativa" else [c.processo.asc(), c.campo_origem.asc(), c.de_para_id.asc()]
        return self.page(self.selection(name).where(*conditions).order_by(*order), filters)

    def entities(self, filters):
        c = self.table("identificador_entidade").c
        conditions = [c[key] == getattr(filters, key) for key in ["marca", "tipo_entidade", "status"] if getattr(filters, key) is not None]
        return self.page(self.selection("identificador_entidade").where(*conditions).order_by(c.identificador_id.asc()), filters)

    def dashboard(self, filters):
        e, o = self.table("execucao"), self.table("oportunidade")
        conditions = self.period_conditions(filters)
        if filters.status is not None:
            conditions.append(e.c.status_execucao == filters.status)
        executions = self.selection("execucao").where(*conditions)
        joined = o.join(e, o.c.execution_id == e.c.execution_id)

        def grouped(column, source):
            return self.rows(select(column.label("valor"), func.count().label("quantidade"))
                             .select_from(source).where(*conditions).group_by(column)
                             .order_by(func.count().desc(), column.asc()))

        periods = select(e.c.marca, e.c.periodo_inicio, e.c.periodo_fim, func.count().label("quantidade_execucoes"))\
            .where(*conditions).group_by(e.c.marca, e.c.periodo_inicio, e.c.periodo_fim)\
            .order_by(e.c.periodo_inicio.desc(), e.c.periodo_fim.desc(), e.c.marca.asc())
        return dict(
            total_execucoes=self.connection.scalar(select(func.count()).select_from(e).where(*conditions)),
            quantidade_oportunidades=self.connection.scalar(select(func.count()).select_from(joined).where(*conditions)),
            status_execucoes=grouped(e.c.status_execucao, e),
            status_oportunidades=grouped(o.c.status_oportunidade, joined),
            distribuicao_por_tipo=grouped(o.c.tipo_problema, joined),
            marcas_periodos=self.page(periods, filters),
            ultimas_execucoes=self.rows(executions.order_by(e.c.iniciado_em.desc(), e.c.execution_id.desc()).limit(10)),
        )
