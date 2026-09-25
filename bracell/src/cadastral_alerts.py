"""Observacao pura do cadastro: nao corrige, filtra ou devolve dados ao calculo."""
from __future__ import annotations

import hashlib
import json

import pandas as pd

TIPO_UF_AUSENTE = "CADASTRO_UF_AUSENTE"
TABELA_COLABORADORES = "colaboradores_ativos_bracell"
FONTES_CADASTRO = frozenset({TABELA_COLABORADORES, "raw_exclusivo_bracell_colaboradores_ativos"})


def _text(value):
    return None if pd.isna(value) else (str(value).strip() or None)


def avaliar_uf_ausente(dataframe, *, marca="BRACELL", tabela_origem=TABELA_COLABORADORES):
    """Consolida marca + usuario da origem + UF no snapshot cadastral vigente.

    Sem usuario, nome e apenas referencia NAO confirmada. Sem ambos, cada linha
    permanece separada. Nao inventa UUID interno antes da persistencia da identidade.
    N inclui apenas linhas ausentes do snapshot, nao o historico de execucoes.
    """
    report = dict(alertas=[], diagnostico=dict(linhas_fonte=len(dataframe), motivo=None))
    diagnostic = report["diagnostico"]
    if marca != "BRACELL" or tabela_origem not in FONTES_CADASTRO:
        diagnostic["motivo"] = "FONTE_FORA_DO_ESCOPO"
        return report
    required = {"nome_colaborador", "usuario_ativo", "data_evolucao", "data_dimensao"}
    fields = [field for field in ("uf", "estado") if field in dataframe.columns]
    if not required.issubset(dataframe.columns) or not fields:
        diagnostic["motivo"] = "COLUNAS_INSUFICIENTES"
        return report
    if dataframe.empty:
        diagnostic["motivo"] = "FONTE_VAZIA"
        return report
    evolution = pd.to_datetime(dataframe["data_evolucao"], errors="coerce")
    latest = evolution.max()
    if pd.isna(latest):
        diagnostic["motivo"] = "SNAPSHOT_NAO_IDENTIFICADO"
        return report
    diagnostic["data_evolucao"] = latest.isoformat()
    diagnostic["datas_evolucao_invalidas"] = int(evolution.isna().sum())
    snapshot = dataframe.loc[evolution.eq(latest)]
    diagnostic["linhas_snapshot"] = len(snapshot)
    groups = {}
    for position, (index, row) in enumerate(snapshot.iterrows()):
        if "marca" in row and (_text(row["marca"]) or "").upper() != marca:
            continue
        user, name = _text(row.get("usuario")), _text(row.get("nome_colaborador"))
        if user:
            criterion, identity = "USUARIO_ORIGEM", user
        elif name:
            criterion, identity = "NOME_NAO_CONFIRMADO", " ".join(name.upper().split())
        else:
            criterion, identity = "REGISTRO_SEM_IDENTIDADE", f"{index}:{position}"
        key = hashlib.sha256(json.dumps([marca, criterion, identity, "UF"], ensure_ascii=False).encode()).hexdigest()
        groups.setdefault(key, []).append(dict(
            linha=row, indice=str(index), criterio=criterion, identidade=identity,
            data=pd.to_datetime(row.get("data_dimensao"), errors="coerce"),
            ativo=(_text(row["usuario_ativo"]) or "").lower() == "sim",
            ausente=all(_text(row[field]) is None for field in fields),
        ))
    diagnostic["grupos_sem_data_referencia"] = 0
    for key, records in sorted(groups.items()):
        dates = [record["data"] for record in records if pd.notna(record["data"])]
        if not dates:
            diagnostic["grupos_sem_data_referencia"] += 1
            continue
        last_date = max(dates)
        current = [record for record in records if record["data"] == last_date]
        # Um registro mais recente preenchido/inativo impede falso alerta historico.
        if not all(record["ativo"] and record["ausente"] for record in current):
            continue
        missing = [record for record in records if record["ativo"] and record["ausente"]]
        representative = current[0]
        evidence = dict(
            versao_regra=1, classificacao="ALERTA", categoria="QUALIDADE_CADASTRAL",
            campo="UF", campo_esperado="UF", situacao="Não preenchido",
            valor_esperado="UF preenchida no cadastro de origem", valor_encontrado=None,
            fallback_usado=False, tratativa="Atualizar cadastro na origem",
            quantidade_ocorrencias=len(missing), chave_consolidacao=key,
            identidade_origem=dict(criterio=representative["criterio"], valor=representative["identidade"]),
            origem="INVOLVES_BRACELL", tabela_origem=tabela_origem,
            campos_origem=fields, data_evolucao=latest.isoformat(),
            data_referencia=last_date.date().isoformat(),
            unidade_ocorrencias="Linhas com UF ausente no snapshot cadastral desta execução",
            amostra_registros=[dict(indice=record["indice"],
                data_dimensao=None if pd.isna(record["data"]) else record["data"].isoformat(),
                valores={field: _text(record["linha"][field]) for field in fields}) for record in missing[:10]],
            amostra_limitada=len(missing) > 10,
        )
        report["alertas"].append(dict(
            marca=marca, origem="INVOLVES_BRACELL", tabela_origem=tabela_origem,
            colaborador=_text(representative["linha"]["nome_colaborador"]),
            data_referencia=last_date.date(), tipo_problema=TIPO_UF_AUSENTE,
            descricao_detalhada="Colaborador ativo sem UF preenchida no cadastro de origem.",
            severidade="BAIXA", evidencia=evidence,
            fingerprint=hashlib.sha256(f"{TIPO_UF_AUSENTE}:{key}".encode()).hexdigest(),
        ))
    diagnostic["grupos_alerta"] = len(report["alertas"])
    diagnostic["ocorrencias"] = sum(item["evidencia"]["quantidade_ocorrencias"] for item in report["alertas"])
    return report
