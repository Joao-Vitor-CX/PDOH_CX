"""Validação HTTP/SQL real somente leitura; não cria dados ou executa pipeline."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, inspect, select, text

from api.app.config import Settings
from api.app.database import Database, TABLE_MODELS
from api.app.main import create_app


def snapshot(database):
    result = {}
    with database.connection() as connection:
        for name in sorted(inspect(connection).get_table_names(schema="pdoh_controle")):
            table = Table(name, MetaData(), schema="pdoh_controle", autoload_with=connection)
            hashes = []
            for row in connection.execution_options(stream_results=True).execute(select(table)).mappings():
                encoded = json.dumps(dict(row), sort_keys=True, default=str, ensure_ascii=False).encode()
                hashes.append(hashlib.sha256(encoded).hexdigest())
            digest = hashlib.sha256("".join(sorted(hashes)).encode()).hexdigest()
            result[name] = {"linhas": len(hashes), "sha256": digest}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/api-validation.json")
    args = parser.parse_args()
    settings = Settings.load()
    database = Database(settings)
    database.initialize()
    before = snapshot(database)
    checks = []
    app = create_app(settings, database)
    with TestClient(app) as client, database.connection() as sql:
        client.headers["Authorization"] = "Bearer " + settings.token

        def check(condition, label):
            if not condition:
                raise AssertionError(label)
            checks.append(label)

        def get(path, **params):
            response = client.get("/api/v1" + path, params=params)
            check(response.status_code == 200, "HTTP 200 " + path)
            return response.json()

        def scalar(statement, **parameters):
            return sql.scalar(text(statement), parameters)

        def raw(name, identifier=None, key=None):
            table = database.tables[name]
            statement = select(*(table.c[k] for k in TABLE_MODELS[name].model_fields))
            if key:
                statement = statement.where(table.c[key] == identifier)
            row = sql.execute(statement.limit(1)).mappings().first()
            return TABLE_MODELS[name].model_validate(dict(row)).model_dump(mode="json") if row else None

        check(scalar("SELECT @@session.transaction_read_only") == 1, "Sessao MySQL READ ONLY")
        schema = {
            name: {
                "campos": list(table.c.keys()),
                "relacionamentos": inspect(sql).get_foreign_keys(
                    table.name, schema=table.schema or "pdoh_controle"
                ),
            }
            for name, table in database.tables.items()
        }
        dashboard = get("/dashboard")
        check(dashboard["total_execucoes"] == scalar("SELECT COUNT(*) FROM pdoh_controle.execucao"), "Total execucoes igual ao SQL")
        check(dashboard["quantidade_oportunidades"] == scalar("SELECT COUNT(*) FROM pdoh_controle.oportunidade"), "Total oportunidades igual ao SQL")
        check(sum(x["quantidade"] for x in dashboard["distribuicao_por_tipo"]) == dashboard["quantidade_oportunidades"], "Distribuicao soma total")
        for item in dashboard["status_execucoes"]:
            check(item["quantidade"] == scalar("SELECT COUNT(*) FROM pdoh_controle.execucao WHERE status_execucao=:s", s=item["valor"]), "Status execucao " + item["valor"])
        for item in dashboard["distribuicao_por_tipo"]:
            check(item["quantidade"] == scalar("SELECT COUNT(*) FROM pdoh_controle.oportunidade WHERE tipo_problema=:t", t=item["valor"]), "Tipo " + item["valor"])

        for path, name, key in [("/execucoes", "execucao", "execution_id"), ("/oportunidades", "oportunidade", "oportunidade_id"), ("/regras", "regra_tratativa", "regra_id"), ("/de-para", "de_para", "de_para_id"), ("/entidades", "identificador_entidade", "identificador_id")]:
            page = get(path, tamanho=7)
            check(page["total"] == before[name]["linhas"], "Contagem " + name)
            for item in page["items"]:
                original = raw(name, item[key], key)
                # Contratos podem acrescentar contexto consultado (por exemplo,
                # classificacao de catalogo), mas cada campo persistido deve permanecer igual.
                check(all(item.get(field) == value for field, value in original.items()),
                      "Campos reais " + name)
            second = get(path, tamanho=7, pagina=2)
            check(not ({x[key] for x in page["items"]} & {x[key] for x in second["items"]}), "Paginacao sem repeticao " + name)

        executions = get("/execucoes", tamanho=200)["items"]
        for execution in executions:
            identifier = execution["execution_id"]
            detail = get("/execucoes/" + identifier)
            check(all(detail[k] == v for k, v in execution.items()), "Detalhe execucao confere")
            for suffix, table, count_field in [("etapas", "execucao_etapa", "quantidade_etapas"), ("fontes", "execucao_fonte", "quantidade_fontes"), ("linhagem", "saida_linhagem", "quantidade_saidas")]:
                page = get(f"/execucoes/{identifier}/{suffix}", tamanho=5)
                expected = scalar(f"SELECT COUNT(*) FROM pdoh_controle.{table} WHERE execution_id=:id", id=identifier)
                check(page["total"] == expected == detail[count_field], "Rastreabilidade " + suffix)
                for row in page["items"]:
                    check(row == raw(table, row["id"], "id"), "Campos " + suffix)
            filters = {"marca": execution["marca"], "status": execution["status_execucao"]}
            expected = scalar("SELECT COUNT(*) FROM pdoh_controle.execucao WHERE marca=:marca AND status_execucao=:status", **filters)
            check(get("/execucoes", **filters)["total"] == expected, "Marca e status combinados")

        filters = dict(marca="BRACELL", periodo_inicio="2026-08-31", periodo_fim="2026-09-05")
        expected = scalar("SELECT COUNT(*) FROM pdoh_controle.execucao WHERE marca=:marca AND periodo_inicio<=:periodo_fim AND periodo_fim>=:periodo_inicio", **filters)
        check(get("/execucoes", **filters)["total"] == expected, "Periodo execucoes")
        expected = scalar("SELECT COUNT(*) FROM pdoh_controle.oportunidade o JOIN pdoh_controle.execucao e ON e.execution_id=o.execution_id WHERE e.marca=:marca AND e.periodo_inicio<=:periodo_fim AND e.periodo_fim>=:periodo_inicio", **filters)
        check(get("/oportunidades", **filters)["total"] == expected, "Periodo oportunidades via execucao")
        check(get("/dashboard", **filters)["quantidade_oportunidades"] == expected, "Periodo dashboard")

        opportunities = sql.execute(text("SELECT oportunidade_id FROM pdoh_controle.oportunidade WHERE regra_id IS NOT NULL LIMIT 3")).scalars().all()
        opportunities += sql.execute(text("SELECT oportunidade_id FROM pdoh_controle.oportunidade WHERE regra_id IS NULL LIMIT 1")).scalars().all()
        opportunities += sql.execute(text("SELECT oportunidade_id FROM pdoh_controle.oportunidade WHERE colaborador_id_interno IS NOT NULL LIMIT 1")).scalars().all()
        for identifier in opportunities:
            detail = get("/oportunidades/" + identifier)
            check(all(detail[k] == v for k, v in raw("oportunidade", identifier, "oportunidade_id").items()), "Detalhe oportunidade confere")
            history = get(f"/oportunidades/{identifier}/historico")
            check(history["total"] == scalar("SELECT COUNT(*) FROM pdoh_controle.oportunidade_historico WHERE oportunidade_id=:id", id=identifier), "Historico oportunidade confere")
            for row in history["items"]:
                check(row == raw("oportunidade_historico", row["id"], "id"), "Campos historico oportunidade")
            if detail["regra_id"]:
                check(detail["regra_atual"] == raw("regra_tratativa", detail["regra_id"], "regra_id"), "Regra atual vinculada")
                params = {"regra": detail["regra_id"], "tipo": detail["tipo_problema"], "status": detail["status_oportunidade"], "marca": detail["marca"]}
                expected = scalar("SELECT COUNT(*) FROM pdoh_controle.oportunidade WHERE regra_id=:regra AND tipo_problema=:tipo AND status_oportunidade=:status AND marca=:marca", **params)
                check(get("/oportunidades", **params)["total"] == expected, "Filtros regra tipo status marca")
            else:
                check(detail["regra_atual"] is None, "Regra ausente preservada")
            if detail["colaborador_id_interno"]:
                check(detail["identidade_colaborador"] == get("/colaboradores/" + detail["colaborador_id_interno"]), "Identidade colaborador vinculada")

        for mapping in get("/de-para")["items"]:
            identifier = mapping["de_para_id"]
            page = get(f"/de-para/{identifier}/historico")
            check(page["total"] == scalar("SELECT COUNT(*) FROM pdoh_controle.de_para_historico WHERE de_para_id=:id", id=identifier), "Historico De/Para confere")
            for row in page["items"]:
                check(row == raw("de_para_historico", row["id"], "id"), "Campos historico De/Para")
        check(get("/de-para", processo="JORNADA", status="ATIVO")["total"] == scalar("SELECT COUNT(*) FROM pdoh_controle.de_para WHERE processo='JORNADA' AND status='ATIVO'"), "Filtros De/Para")
        check(get("/regras", marca="BRACELL", status="ATIVA")["total"] == scalar("SELECT COUNT(*) FROM pdoh_controle.regra_tratativa WHERE (marca='BRACELL' OR marca IS NULL) AND status_regra='ATIVA'"), "Regras globais e marca")
        for params in ({"tipo_entidade": "PDV"}, {"marca": "BRACELL", "status": "ATIVO"}):
            page = get("/entidades", **params)
            for entity in page["items"][:2]:
                check(get("/entidades/" + entity["identificador_id"]) == entity, "Detalhe entidade")

        check(get("/oportunidades", marca="' OR 1=1 --")["total"] == 0, "Injecao tratada como literal")
        check(client.get("/api/v1/execucoes/nao-existe").status_code == 404, "Registro ausente 404")
        check(client.get("/api/v1/execucoes?pagina=0").status_code == 422, "Pagina invalida 422")
        check(client.get("/api/v1/execucoes?periodo_inicio=2026-09-12&periodo_fim=2026-09-01").status_code == 422, "Periodo invertido 422")
        for method in ("post", "put", "patch", "delete"):
            check(getattr(client, method)("/api/v1/oportunidades").status_code == 405, "Metodo bloqueado " + method)
        client.headers.pop("Authorization")
        check(client.get("/api/v1/dashboard").status_code == 401, "Sem token 401")
        openapi = app.openapi()
        # Segunda conexao, novo snapshot: não reutiliza a transacao de comparacao.
        after = snapshot(database)
        check(before == after, "Conteudo de todas as tabelas de controle preservado (SHA256)")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "APROVADO", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "verificacoes": len(checks), "checks": checks, "schema_real": schema,
              "snapshot_antes": before, "snapshot_depois": after,
              "resumo_dashboard": {k: dashboard[k] for k in ("total_execucoes", "quantidade_oportunidades", "status_execucoes", "distribuicao_por_tipo")},
              "escopo": "Somente SELECT. TestClient HTTP/ASGI contra MySQL real; sem carga, migracao ou pipeline."}
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    output.with_name("api-openapi.json").write_text(json.dumps(openapi, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "APROVADO", "verificacoes": len(checks), "execucoes": dashboard["total_execucoes"], "oportunidades": dashboard["quantidade_oportunidades"], "conteudo_controle_preservado": before == after}))


if __name__ == "__main__":
    main()
