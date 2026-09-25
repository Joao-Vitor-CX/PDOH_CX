"""Resolucao e simulacao SELECT-only. Sem import de ETL/processador/observadores."""
from datetime import datetime, timezone, timedelta
import json
import re

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select

from .fallback_models import FallbackResolution, HOUR_PATTERN

DEFAULT = "23:59"
MAX_GROUPS = 100_000
COMPLETED = ("CONCLUIDA", "CONCLUIDA_COM_ALERTAS", "CONCLUIDA_SEM_RESULTADO")


def local_today():
    return datetime.now(timezone(timedelta(hours=-3))).date()


def resolve_fallback(connection, tables, query):
    """Vigencia por data local, limites inclusivos; ambiguidades nunca sao arbitradas."""
    day = query.data_referencia or local_today()
    c = tables["regra_fallback_config"].c
    scopes = [("LIDER", query.lider_id)] if query.lider_id else []
    scopes.append(("MARCA", "*"))
    for scope, key in scopes:
        matches = connection.execute(select(c.id, c.valor_fallback).where(
            c.marca == query.marca, c.regra == query.regra,
            c.escopo == scope, c.chave == key, c.status == "ATIVO",
            c.vigencia_inicio <= day,
            or_(c.vigencia_fim.is_(None), c.vigencia_fim >= day),
        ).limit(2)).mappings().all()
        if len(matches) > 1:
            raise HTTPException(409, "Configuracoes ativas sobrepostas no mesmo escopo; resolucao ambigua.")
        if matches:
            value = matches[0]["valor_fallback"]
            if not re.fullmatch(HOUR_PATTERN, value):
                raise HTTPException(409, "Configuracao de fallback invalida.")
            return FallbackResolution(origem=scope, valor=value, config_id=matches[0]["id"], data_referencia=day)
    return FallbackResolution(origem="DEFAULT", valor=DEFAULT, data_referencia=day)


def evidence_object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def simulate_fallback(connection, tables, request):
    from .fallback_models import FallbackQuery, SimulationResult

    e, o = tables["execucao"].c, tables["oportunidade"].c
    # A amostra pertence a UMA execucao concluida, nunca soma reprocessamentos.
    clauses = [e.marca == request.marca, e.status_execucao.in_(COMPLETED),
               e.periodo_inicio.is_not(None), e.periodo_fim.is_not(None),
               ~e.execution_id.contains("VALIDACAO"),
               or_(e.componente_atual.is_(None), e.componente_atual != "VALIDACAO")]
    if request.periodo_inicio:
        clauses.append(e.periodo_fim >= request.periodo_inicio)
    if request.periodo_fim:
        clauses.append(e.periodo_inicio <= request.periodo_fim)
    if request.execution_id:
        clauses.append(e.execution_id == request.execution_id)
    else:
        clauses.append(exists(select(1).where(
            o.execution_id == e.execution_id, o.marca == request.marca,
            o.tipo_problema == request.regra)))
    execution = connection.execute(select(tables["execucao"]).where(*clauses)
        .order_by(e.iniciado_em.desc(), e.execution_id.desc()).limit(1)).mappings().first()
    if not execution:
        raise HTTPException(404, "Nenhuma execucao concluida com evidencias no recorte. Ausencia de evidencia nao significa impacto zero.")
    start = max(filter(None, [execution["periodo_inicio"], request.periodo_inicio]))
    end = min(filter(None, [execution["periodo_fim"], request.periodo_fim]))
    identifier = execution["execution_id"]
    rows = connection.execute(select(tables["oportunidade"]).where(
        o.execution_id == identifier, o.marca == request.marca,
        o.tipo_problema == request.regra,
        or_(o.data_referencia.is_(None), and_(o.data_referencia >= start, o.data_referencia <= end)),
    ).limit(MAX_GROUPS + 1)).mappings().all()
    if len(rows) > MAX_GROUPS:
        raise HTTPException(422, "Limite de evidencias excedido; reduza o periodo.")
    if not rows:
        raise HTTPException(409, "Recorte sem evidencias CHECKOUT_AUSENTE; nao e possivel afirmar impacto zero.")
    groups, people, indices = {}, {}, set()
    duplicate, missing, count, sampled = 0, 0, 0, False
    for row in rows:
        ev = evidence_object(row["evidencia"])
        quantity = ev.get("ocorrencias")
        refs = ev.get("registro_afetado")
        # Nao conta observacoes antigas sem prova de uso do fallback, ou dados invalidos.
        if (ev.get("campo_esperado") != "hora_saida" or ev.get("fallback_usado") is not True
                or ev.get("fallback_valor") not in ("23:59", "23:59:00")
                or row["tabela_origem"] != "relatorio_checkin_bracell"
                or not row["data_referencia"]
                or type(quantity) is not int or quantity <= 0
                or not isinstance(refs, list) or not refs
                or any(not isinstance(x, (str, int)) or isinstance(x, bool) or not str(x).strip() for x in refs)
                or len(set(map(str, refs))) != len(refs) or len(refs) > quantity):
            raise HTTPException(409, "Evidencias incompletas/incompativeis: simulacao segura indisponivel para esta execucao.")
        name = " ".join((row["colaborador"] or "").split()).casefold()
        person = name or row["colaborador_id_interno"]
        key = (row["tabela_origem"], person, row["data_referencia"])
        signature = (quantity, tuple(sorted(map(str, refs))))
        if key in groups:
            if groups[key] != signature:
                raise HTTPException(409, "Grupos sobrepostos/ambiguos: nao e seguro somar as ocorrencias.")
            duplicate += 1
            continue
        source_indices = {(row["tabela_origem"], str(x)) for x in refs}
        if indices & source_indices:
            raise HTTPException(409, "Indices de origem repetidos entre grupos; contagem ambigua.")
        indices.update(source_indices)
        groups[key] = signature
        count += quantity
        sampled |= quantity > len(refs)
        if person:
            people.setdefault(person, set()).add(row["colaborador_id_interno"])
        else:
            missing += 1
    if any(len(ids - {None}) > 1 for ids in people.values()):
        raise HTTPException(409, "Homonomos com identificadores diferentes; contagem de colaboradores ambigua.")
    # Contagem por identidade quando existente, senao por nome: nao afirma identidades verificadas.
    person_count = len({next(iter(ids - {None})) if ids - {None} else "nome:" + name for name, ids in people.items()})
    notices = [
        "Simulacao de abrangencia de CHECKOUT_AUSENTE observado, nao de todas as linhas hora_saida NULL do processador.",
        "Nao estima minutos, produtividade ou valor PDOH; nao recalcula nem aplica configuracoes.",
        "Contagens historicas da execucao informada; nao representam necessariamente a origem atual.",
    ]
    if not request.execution_id:
        notices.append("Selecionada a ultima execucao concluida COM evidencias; pode existir execucao posterior sem evidencias.")
    if sampled:
        notices.append("IDs de origem sao amostrais em alguns grupos; total utiliza ocorrencias da evidencia.")
    if missing:
        notices.append("Ha grupos sem identificacao; a contagem de colaboradores e parcial.")
    if any(None in ids for ids in people.values()):
        notices.append("Parte dos colaboradores foi contada por nome normalizado, sem identificador interno verificavel.")
    events = tables["execucao_evento"].c
    if connection.execute(select(events.id).where(events.execution_id == identifier,
            events.codigo == "VOLUME_OPORTUNIDADES_TRUNCADO").limit(1)).first():
        notices.append("A execucao registra truncamento de oportunidades; abrangencia limitada aos grupos persistidos, sem garantia de cobertura integral.")
    configured = resolve_fallback(connection, tables, FallbackQuery(marca=request.marca))
    changed = request.novo_valor != DEFAULT
    return SimulationResult(
        regra=request.regra, marca=request.marca, execution_id=identifier,
        criterio_execucao="EXPLICITA" if request.execution_id else "ULTIMA_CONCLUIDA_COM_EVIDENCIAS",
        periodo_inicio=start, periodo_fim=end, fallback_atual=DEFAULT,
        fallback_simulado=request.novo_valor, configuracao_marca=configured,
        registros_identificados=count, registros_afetados=count if changed else 0,
        colaboradores_identificados=person_count, colaboradores_afetados=person_count if changed else 0,
        criterio_colaboradores="ID interno quando disponivel; senao nome normalizado (possiveis homonimos)",
        grupos_observados=len(groups), grupos_sem_colaborador=missing,
        evidencias_duplicadas_desconsideradas=duplicate,
        abrangencia="EVIDENCIAS_PERSISTIDAS_DE_UMA_EXECUCAO", avisos=notices,
    )
