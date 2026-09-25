"""Reconcilia o contrato do dashboard BRACELL com a tabela tratada, somente leitura."""
from collections import Counter
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from sqlalchemy import distinct, func, select

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from api.app.config import Settings
from api.app.database import Database
from api.app.main import create_app

INICIO = date(2026, 8, 31)
FIM = date(2026, 9, 5)


def tempo(valor):
    if valor is None:
        return None
    if isinstance(valor, timedelta):
        segundos = int(valor.total_seconds())
        return f"{segundos // 3600:02d}:{segundos % 3600 // 60:02d}:{segundos % 60:02d}"
    return str(valor)


def main():
    settings = Settings.load()
    database = Database(settings)
    database.initialize()
    checks = []

    def check(condition, label):
        if not condition:
            raise AssertionError(label)
        checks.append(label)

    app = create_app(settings, database)
    with TestClient(app) as client, database.connection() as sql:
        client.headers["Authorization"] = "Bearer " + settings.token
        tabela = database.tables["platina_pdoh:BRACELL"]
        c = tabela.c
        janela = [c.data >= INICIO, c.data <= FIM]

        def resumo(**extra):
            params = dict(marca="BRACELL", periodo="personalizado",
                          periodo_inicio=str(INICIO), periodo_fim=str(FIM), tamanho=200)
            params.update(extra)
            response = client.get("/api/v2/pdoh/resumo", params=params)
            check(response.status_code == 200, "HTTP 200 PDOH BRACELL")
            return response.json()

        geral = resumo()
        cobertura = sql.execute(select(
            func.count().label("registros"),
            func.count(distinct(c.colaborador)).label("colaboradores"),
            func.count(distinct(c.data)).label("dias"),
        ).where(*janela)).mappings().one()
        pdoh_sql = sql.scalar(select(
            100 * func.sum(func.time_to_sec(c.produtividade)) /
            func.sum(func.time_to_sec(c.horas_programadas))
        ).where(*janela))
        check(geral["cobertura"]["tabela"] ==
              "produtos_platina.exclusivo_bracell_platina_relatorio_pdoh",
              "Origem tratada BRACELL, sem Gold")
        check(geral["cobertura"]["registros_no_periodo"] == cobertura["registros"] == 300,
              "Total de registros igual ao SQL")
        check(geral["cobertura"]["colaboradores_no_periodo"] == cobertura["colaboradores"],
              "Total de colaboradores igual ao SQL")
        check(geral["cobertura"]["dias_no_periodo"] == cobertura["dias"],
              "Total de dias igual ao SQL")
        check(abs(geral["percentual"] - float(pdoh_sql)) < 0.0001,
              "PDOH geral igual a razao de somas da fonte")

        estado = sql.scalar(select(func.min(c.estado)).where(*janela, c.estado.is_not(None)))
        por_estado = resumo(estado=estado)
        estado_cond = [*janela, c.estado == estado]
        estado_total = sql.scalar(select(func.count()).select_from(tabela).where(*estado_cond))
        estado_pdoh = sql.scalar(select(
            100 * func.sum(func.time_to_sec(c.produtividade)) /
            func.sum(func.time_to_sec(c.horas_programadas))
        ).where(*estado_cond))
        check(por_estado["detalhes"]["total"] == estado_total,
              "Filtro Estado igual ao SQL")
        check(abs(por_estado["percentual"] - float(estado_pdoh)) < 0.0001,
              "PDOH por Estado igual ao SQL")
        check(all(item["estado"] == estado for item in por_estado["detalhes"]["items"]),
              "Detalhes respeitam Estado")

        colaborador = sql.scalar(select(func.min(c.colaborador)).where(*janela))
        por_colaborador = resumo(colaborador=colaborador)
        colab_cond = [*janela, c.colaborador == colaborador]
        colab_total = sql.scalar(select(func.count()).select_from(tabela).where(*colab_cond))
        colab_pdoh = sql.scalar(select(
            100 * func.sum(func.time_to_sec(c.produtividade)) /
            func.sum(func.time_to_sec(c.horas_programadas))
        ).where(*colab_cond))
        check(por_colaborador["detalhes"]["total"] == colab_total,
              "Filtro Colaborador igual ao SQL")
        check(abs(por_colaborador["percentual"] - float(colab_pdoh)) < 0.0001,
              "PDOH por Colaborador igual ao SQL")

        segunda = resumo(pagina=2)
        ids_1 = {(item["colaborador"], item["data"]) for item in geral["detalhes"]["items"]}
        ids_2 = {(item["colaborador"], item["data"]) for item in segunda["detalhes"]["items"]}
        check(len(ids_1) == 200 and len(ids_2) == 100 and ids_1.isdisjoint(ids_2),
              "Paginacao cobre 300 linhas sem repeticao")

        opcoes_colaborador = set(geral["filtros_disponiveis"]["colaboradores"])
        opcoes_estado = set(geral["filtros_disponiveis"]["estados"])
        sql_colaboradores = set(sql.scalars(select(distinct(c.colaborador)).where(*janela)))
        sql_estados = set(sql.scalars(select(distinct(c.estado)).where(*janela, c.estado.is_not(None))))
        check(opcoes_colaborador == sql_colaboradores, "Opcoes de colaborador iguais ao SQL")
        check(opcoes_estado == sql_estados, "Opcoes de Estado iguais ao SQL")

        primeira = geral["detalhes"]["items"][0]
        original = sql.execute(select(tabela).where(
            c.colaborador == primeira["colaborador"], c.data == primeira["data"]
        )).mappings().one()
        for campo in ("deslocamento", "ocio", "produtividade", "horas_nao_registradas",
                      "horas_programadas", "primeiro_checkin", "ultimo_checkout"):
            check(primeira[campo] == tempo(original[campo]), "Campo diario preservado: " + campo)
        check(primeira["percentuais"]["produtividade"] == float(original["percentual_produtividade"]),
              "Percentual diario preservado")

        todas = geral["detalhes"]["items"] + segunda["detalhes"]["items"]
        fallbacks_confirmados = sum(item["jornada"]["houve_fallback"] is True for item in todas)
        fontes_identificadas = sum(item["jornada"]["fonte"] is not None for item in todas)
        fontes_jornada = Counter(item["jornada"]["fonte"] or "NAO_IDENTIFICADA" for item in todas)
        horas_programadas = Counter(item["horas_programadas"] or "NAO_INFORMADA" for item in todas)
        anonimo = hashlib.sha256(colaborador.encode("utf-8")).hexdigest()[:12]

    database.close()
    report = {
        "status": "APROVADO",
        "periodo": {"inicio": str(INICIO), "fim": str(FIM)},
        "fonte": geral["cobertura"]["tabela"],
        "registros": geral["cobertura"]["registros_no_periodo"],
        "colaboradores": geral["cobertura"]["colaboradores_no_periodo"],
        "dias": geral["cobertura"]["dias_no_periodo"],
        "estados": sorted(opcoes_estado),
        "pdoh": geral["percentual"],
        "efetividade": geral["efetividade"]["valor"],
        "filtro_estado_validado": estado,
        "filtro_colaborador_validado_hash": anonimo,
        "fallbacks_confirmados": fallbacks_confirmados,
        "linhas_com_fonte_jornada_identificada": fontes_identificadas,
        "fontes_jornada": dict(sorted(fontes_jornada.items())),
        "horas_programadas": dict(sorted(horas_programadas.items())),
        "verificacoes": len(checks),
        "checks": checks,
        "escopo": "Somente SELECT e GET; sem pipeline, migracao ou escrita de negocio.",
    }
    output = PROJECT / "artifacts" / "bracell-frontend-validation.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "registros", "colaboradores", "dias", "estados", "pdoh",
        "efetividade", "fallbacks_confirmados", "linhas_com_fonte_jornada_identificada",
        "fontes_jornada", "horas_programadas", "verificacoes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
