"""Dispatcher de achados. So o catalogo escolhe o destino; nao executa calculo/ETL.

Uma transacao por lote, serializada por execucao, guarda destino e decisao atomicos.
Nenhuma atualizacao/reclassificacao de achados anteriores. Falhas nao param a esteira.
"""
import base64
import hashlib
import json
import uuid
from shared.operational_policy import assess
from shared.rule_engine import (
    REGRA_INATIVA, REGRA_NAO_CADASTRADA, REGRA_SEM_GERACAO, gera_oportunidade,
)

from sqlalchemy import text

# CONFIGURACAO descreve o cadastro da marca/periodo, nao a execucao de uma pessoa:
# fica registrada como evento (disponivel para governanca), fora da fila operacional
# e sem notificacao.
DESTINOS = {"OPORTUNIDADE": "oportunidade", "ALERTA": "alerta", "TELEMETRIA": "execucao_evento",
            "CONFIGURACAO": "execucao_evento"}
SEPARADOR_GRUPO = "\x1f"

# Por que uma regra nao gerou oportunidade. Codigos de evento estaveis, agregados por lote.
MENSAGENS_PORTA = {
    REGRA_NAO_CADASTRADA: "Achado sem oportunidade: nao ha regra cadastrada para este cenario.",
    REGRA_INATIVA: "Achado sem oportunidade: a regra cadastrada esta inativa.",
    REGRA_SEM_GERACAO: "Achado sem oportunidade: a regra esta configurada para nao gerar oportunidade.",
}
AMOSTRA_PORTA = 5


def regra_liberada(connection, marca, operacao, tipo):
    """A regra cadastrada permite criar oportunidade? (liberado, motivo_se_nao).

    A definicao de "cadastrada, ativa e configurada para gerar" e' uma so
    (`shared.rule_engine.gera_oportunidade`); a API usa a mesma para decidir o que a fila exibe.
    """
    regra = connection.execute(text(
        "SELECT configuracao_id,status,geracao_automatica_ativa FROM pdoh_controle.regra_configuracao "
        "WHERE marca=:marca AND operacao=:operacao AND codigo_interno=:tipo"),
        {"marca": marca, "operacao": operacao, "tipo": tipo}).mappings().first()
    tratamentos = []
    if regra:
        tratamentos = [dict(linha) for linha in connection.execute(text(
            "SELECT resultado,gera_oportunidade,status FROM pdoh_controle.regra_tratamento_configuracao "
            "WHERE configuracao_id=:id"), {"id": regra["configuracao_id"]}).mappings().all()]
    return gera_oportunidade(dict(regra) if regra else None, tratamentos)


def campos_da_evidencia(evidencia):
    """Dimensao do problema (campo afetado). Espelha `evidence_fields` da API."""
    if isinstance(evidencia, str):
        try:
            evidencia = json.loads(evidencia)
        except (ValueError, TypeError):
            evidencia = {}
    if not isinstance(evidencia, dict):
        return []
    candidatos = evidencia.get("campo_esperado")
    if candidatos is None:
        candidatos = evidencia.get("campo", evidencia.get("campo_origem", evidencia.get("coluna")))
    if candidatos is None:
        candidatos = [evidencia.get("campo_inicio"), evidencia.get("campo_fim")]
    if not isinstance(candidatos, list):
        candidatos = [candidatos]
    return sorted({str(c) for c in candidatos if isinstance(c, str) and c.strip()})


def grupo_operacional(marca, tipo_problema, colaborador_id, colaborador, tabela_origem, evidencia, operacao='EXCLUSIVA'):
    """Chave do problema operacional: marca + regra + colaborador + contexto (origem + campo).

    Nao depende de dia, execucao, registro nem repeticao. Mesmo formato do `grupo_id`
    entregue pela API, para que notificacao e card apontem para o mesmo problema.
    """
    partes = [marca or "", tipo_problema or "", colaborador_id or "", '' if colaborador_id else (colaborador or ""),
              tabela_origem or "", "+".join(campos_da_evidencia(evidencia))]
    if operacao != 'EXCLUSIVA':
        partes.append(operacao)
    return base64.urlsafe_b64encode(SEPARADOR_GRUPO.join(partes).encode("utf-8")).decode("ascii").rstrip("=")


def resolver_classificacao(connection, tipo_problema, marca, tabela_origem=None):
    """Resolve a regra vigente do catalogo em codigo; retorna snapshot ou None.

    A classificacao efetiva considera a excecao por origem declarada na propria regra
    (origem_excecao/classificacao_excecao): o mesmo tipo pode ser tecnico numa origem e
    operacional em outra, sem duplicar linha no catalogo. `connection` nao e' mais usado
    (mantido na assinatura por compatibilidade do chamador).
    """
    from shared.treatment_catalog import classificacao_efetiva, resolver_regra
    regra = resolver_regra(tipo_problema, marca)
    if not regra:
        return None
    efetiva = classificacao_efetiva(regra, tabela_origem)
    if efetiva not in DESTINOS:
        return None
    # O snapshot congela a classificacao realmente aplicada a este achado.
    regra = dict(regra)
    regra["classificacao"] = efetiva
    return regra


def registrar_achado(engine, achados):
    from .observability import (obter_execution_id, obter_componente, _data, _texto,
                                _fingerprint_oportunidade, _falha_observabilidade, _emitir)
    inserted = 0
    try:
        items = [achados] if isinstance(achados, dict) else list(achados)
        if not items:
            return 0
        execution_id = obter_execution_id(criar=False)
        if not execution_id:
            raise ValueError("Achado exige execucao existente; dispatcher nao cria execucoes.")
        with engine.begin() as c:
            execution = c.execute(text("SELECT marca,status_execucao,operacao FROM pdoh_controle.execucao "
                "WHERE execution_id=:id FOR UPDATE"), {"id": execution_id}).mappings().first()
            if not execution or execution["status_execucao"] in (
                    "CONCLUIDA", "CONCLUIDA_COM_ALERTAS", "CONCLUIDA_SEM_RESULTADO", "FALHA_TECNICA"):
                raise ValueError("Execucao ausente ou encerrada: nenhum achado historico sera alterado.")
            brand = execution["marca"]
            operacao = execution.get("operacao") or "EXCLUSIVA"
            cache, warning_count = {}, 0
            porta, bloqueados = {}, {}
            for original in items:
                item = dict(original)  # nao modifica entrada do detector
                if item.get("marca", brand) != brand or item.get("execution_id", execution_id) != execution_id:
                    raise ValueError("Marca/execucao do achado divergente do contexto.")
                item["marca"] = brand
                kind = item.get("tipo_problema")
                if not kind:
                    raise ValueError("Achado sem tipo_problema.")
                origem_tabela = item.get("tabela_origem")
                key = (brand, kind, origem_tabela)
                if key not in cache:
                    cache[key] = resolver_classificacao(c, kind, brand, origem_tabela)
                rule = cache[key]
                if not rule:
                    # Diagnostico tecnico nao e classificacao alternativa do achado.
                    c.execute(text("INSERT INTO pdoh_controle.execucao_evento "
                        "(execution_id,componente,etapa,nivel,categoria,codigo,mensagem,contexto) "
                        "VALUES (:id,:componente,'ROTEAMENTO','ERRO','ROTEAMENTO','CLASSIFICACAO_NAO_RESOLVIDA',"
                        "'Achado sem regra ativa univoca; nao persistido na fila operacional.',CAST(:contexto AS JSON))"),
                        {"id": execution_id, "componente": obter_componente(),
                         "contexto": json.dumps({"marca": brand, "achado": item}, ensure_ascii=False, default=str)})
                    continue
                classification, criterio = assess(rule, item)
                if classification == "OPORTUNIDADE":
                    # Configuracao -> regra ativa -> motor valida -> criterios atendidos -> oportunidade.
                    # Sem regra cadastrada e ativa nada e' criado, por mais comprovado que o achado esteja.
                    if kind not in porta:
                        porta[kind] = regra_liberada(c, brand, operacao, kind)
                    liberado, motivo_porta = porta[kind]
                    if not liberado:
                        grupo = bloqueados.setdefault((motivo_porta, kind), {"total": 0, "amostra": []})
                        grupo["total"] += 1
                        if len(grupo["amostra"]) < AMOSTRA_PORTA:
                            grupo["amostra"].append({"colaborador": item.get("colaborador"),
                                                     "data_referencia": item.get("data_referencia")})
                        continue
                fingerprint = item.get("fingerprint") or _fingerprint_oportunidade(item)
                known = c.execute(text("SELECT achado_id FROM pdoh_controle.achado_roteamento "
                    "WHERE execution_id=:id AND marca=:marca AND fingerprint=:fingerprint"),
                    {"id": execution_id, "marca": brand, "fingerprint": fingerprint}).first()
                if known:
                    continue
                # Nao adota/backfilla registros legados de uma execucao ainda aberta.
                if c.execute(text("SELECT oportunidade_id FROM pdoh_controle.oportunidade "
                    "WHERE execution_id=:id AND fingerprint=:fingerprint"),
                    {"id": execution_id, "fingerprint": fingerprint}).first():
                    continue
                collaborator_id = item.get("colaborador_id_interno")
                if collaborator_id:
                    identity = c.execute(text("SELECT marca FROM pdoh_controle.colaborador_identidade "
                        "WHERE colaborador_id_interno=:id"), {"id": collaborator_id}).first()
                    if not identity or identity[0] != brand:
                        raise ValueError("Identidade do colaborador nao pertence a marca da execucao.")
                from shared.evidence_engine import deve_gerar_oportunidade
                evidence = item.get('evidencia') or {}
                # Toda oportunidade exige comprovacao confirmada -- nao so' as regras operacionais.
                if classification == 'OPORTUNIDADE' and not deve_gerar_oportunidade(
                        evidence.get('comprovacao') if isinstance(evidence, dict) else None):
                    c.execute(text("INSERT INTO pdoh_controle.execucao_evento "
                        "(execution_id,componente,etapa,nivel,categoria,codigo,mensagem,contexto) "
                        "VALUES (:id,:componente,'COMPROVACAO','INFO','EVIDENCIA',"
                        "'ACHADO_SEM_EVIDENCIA_CONFIRMADA','Oportunidade bloqueada por ausência de comprovação.',"
                        "CAST(:contexto AS JSON))"), dict(id=execution_id, componente=obter_componente(),
                        contexto=json.dumps(dict(tipo_problema=kind, colaborador=item.get('colaborador'),
                            data_referencia=item.get('data_referencia'), resultado='indisponivel',
                            motivo='Caminho de registro sem evidência confirmada.', evidencia=evidence), default=str)))
                    continue
                if classification == 'OPORTUNIDADE' and kind == 'CHECKOUT_AUSENTE':
                    from .operational_schedule import evidence_matches
                    if not evidence_matches(c, brand, operacao, evidence.get('comprovacao')):
                        c.execute(text("INSERT INTO pdoh_controle.execucao_evento "
                            "(execution_id,componente,etapa,nivel,categoria,codigo,mensagem,contexto) "
                            "VALUES (:id,:componente,'COMPROVACAO','INFO','EVIDENCIA',"
                            "'JORNADA_SEM_CONFIGURACAO_COMPROVADA','Checkout bloqueado: configuracao ou monitoramento ausente.',"
                            "CAST(:contexto AS JSON))"), dict(id=execution_id, componente=obter_componente(),
                            contexto=json.dumps(dict(tipo_problema=kind), default=str)))
                        continue
                rule = {**rule, 'classificacao': classification, 'criterio_operacional': criterio}
                identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, f"PDOH:{execution_id}:{brand}:{fingerprint}"))
                evidence = item.get("evidencia")
                params = {"achado_id": identifier, "oportunidade_id": identifier, "alerta_id": identifier,
                    "execution_id": execution_id, "marca": brand, "tipo": kind, "regra_id": rule["regra_id"],
                    "data": _data(item.get("data_referencia")), "origem": _texto(item.get("origem", "INVOLVES"), 80),
                    "tabela": _texto(item.get("tabela_origem", "DESCONHECIDA"), 160),
                    "colaborador": _texto(item.get("colaborador"), 255), "colaborador_id": collaborator_id,
                    "descricao": _texto(item.get("descricao_detalhada", "Achado identificado."), 65000),
                    "severidade": _texto(item.get("severidade") or rule.get("severidade_padrao") or "MEDIA", 20),
                    "evidencia": json.dumps(evidence, ensure_ascii=False, default=str), "fingerprint": fingerprint,
                    "classificacao": classification, "destino": DESTINOS[classification],
                    "snapshot": json.dumps(rule, ensure_ascii=False, default=str), "registro_id": identifier,
                    "componente": obter_componente(), "tratativa": rule.get("tratamento_esperado")}
                if classification in ("OPORTUNIDADE", "ALERTA"):
                    table = DESTINOS[classification]  # enum interno, nunca identificador do produtor
                    id_column = "oportunidade_id" if classification == "OPORTUNIDADE" else "alerta_id"
                    status_column = "status_oportunidade" if classification == "OPORTUNIDADE" else "status_alerta"
                    extra_columns, extra_values = "", ""
                    if classification == "ALERTA":
                        field = evidence.get("campo", evidence.get("campo_origem", evidence.get("campo_esperado"))) if isinstance(evidence, dict) else None
                        params["campo"] = _texto(field, 120) if isinstance(field, str) else None
                        extra_columns, extra_values = ",campo,tratativa", ",:campo,:tratativa"
                    c.execute(text(f"INSERT INTO pdoh_controle.{table} ({id_column},execution_id,marca,data_referencia,"
                        f"origem,tabela_origem,colaborador,colaborador_id_interno,tipo_problema,regra_id,descricao_detalhada,"
                        f"severidade,{status_column},fingerprint,evidencia{extra_columns}) VALUES "
                        f"(:achado_id,:execution_id,:marca,:data,:origem,:tabela,:colaborador,:colaborador_id,:tipo,:regra_id,"
                        f":descricao,:severidade,'ABERTA',:fingerprint,CAST(:evidencia AS JSON){extra_values})"), params)
                    if classification == "OPORTUNIDADE":
                        c.execute(text("INSERT INTO pdoh_controle.oportunidade_historico "
                            "(oportunidade_id,execution_id,status_anterior,status_novo,acao,observacao) VALUES "
                            "(:achado_id,:execution_id,NULL,'ABERTA','IDENTIFICADA','Novo achado roteado pelo catalogo.')"), params)
                        if params["severidade"] in {"ALTA", "CRITICA"}:
                            # Uma notificacao por PROBLEMA operacional, nao por evento: a chave
                            # nao carrega execucao nem fingerprint. Repeticao em outro dia ou
                            # reprocessamento cai no IGNORE e atualiza o grupo pela leitura.
                            grupo_id = grupo_operacional(brand, kind, collaborator_id, params["colaborador"],
                                                         params["tabela"], evidence, execution.get('operacao') or 'EXCLUSIVA')
                            c.execute(text("INSERT IGNORE INTO pdoh_controle.notificacao_outbox "
                                "(notificacao_id,execution_id,oportunidade_id,tipo_notificacao,prioridade,status_notificacao,dedupe_key,payload) "
                                "VALUES (:nid,:execution_id,:achado_id,'OPORTUNIDADE_OPERACIONAL',:prioridade,'PENDENTE',:dedupe,CAST(:payload AS JSON))"),
                                {**params, "nid": str(uuid.uuid4()), "prioridade": 1 if params["severidade"] == "CRITICA" else 3,
                                 "dedupe": hashlib.sha256(f"OPORTUNIDADE_OPERACIONAL:{grupo_id}".encode()).hexdigest(),
                                 "payload": json.dumps({"grupo_id": grupo_id, "execution_id": execution_id, "marca": brand,
                                    "oportunidade_id": identifier, "tipo_problema": kind, "severidade": params["severidade"],
                                    "descricao": params["descricao"], "data_referencia": params["data"],
                                    "impacto": item.get("impacto") or params["descricao"]}, default=str, ensure_ascii=False)})
                    warning_count += 1
                else:
                    context = {"versao_roteamento": 1, "achado_id": identifier, "marca": brand,
                        "regra_id": rule["regra_id"], "classificacao": classification, "origem": params["origem"],
                        "tabela_origem": params["tabela"], "colaborador": params["colaborador"],
                        "colaborador_id_interno": collaborator_id, "data_referencia": params["data"],
                        "evidencia": evidence, "fingerprint": fingerprint}
                    result = c.execute(text("INSERT INTO pdoh_controle.execucao_evento "
                        "(execution_id,componente,etapa,nivel,categoria,codigo,mensagem,contexto) VALUES "
                        "(:execution_id,:componente,'ACHADOS','INFO',:categoria,:tipo,:descricao,CAST(:contexto AS JSON))"),
                        {**params, "categoria": classification,
                         "contexto": json.dumps(context, default=str, ensure_ascii=False)})
                    params["registro_id"] = str(result.lastrowid)
                c.execute(text("INSERT INTO pdoh_controle.achado_roteamento "
                    "(achado_id,execution_id,marca,tipo_problema,fingerprint,regra_id,classificacao,destino,registro_id,regra_snapshot) "
                    "VALUES (:achado_id,:execution_id,:marca,:tipo,:fingerprint,:regra_id,:classificacao,:destino,:registro_id,CAST(:snapshot AS JSON))"), params)
                inserted += 1
            for (motivo_porta, kind), grupo in sorted(bloqueados.items()):
                c.execute(text("INSERT INTO pdoh_controle.execucao_evento "
                    "(execution_id,componente,etapa,nivel,categoria,codigo,mensagem,contexto) "
                    "VALUES (:id,:componente,'REGRA','INFO','GOVERNANCA',:codigo,:mensagem,CAST(:contexto AS JSON))"),
                    {"id": execution_id, "componente": obter_componente(), "codigo": motivo_porta,
                     "mensagem": MENSAGENS_PORTA[motivo_porta],
                     "contexto": json.dumps({"marca": brand, "operacao": operacao, "tipo_problema": kind,
                         "total": grupo["total"], "amostra": grupo["amostra"]}, ensure_ascii=False, default=str)})
            if warning_count:
                c.execute(text("UPDATE pdoh_controle.execucao SET total_alertas=total_alertas+:total WHERE execution_id=:id"),
                    {"total": warning_count, "id": execution_id})
        if inserted:
            _emitir("INFO", "ACHADOS_ROTEADOS", f"{inserted} novo(s) achado(s) roteado(s) pelo catalogo.")
        return inserted
    except Exception as error:
        _falha_observabilidade("registrar_achado", error)
        return 0
