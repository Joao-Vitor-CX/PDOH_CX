"""Validacao real: snapshot -> HTTP/SQL SELECT -> snapshot; historico opcional com rollback.

--test-history usa SOMENTE registros novos de teste nas duas tabelas de fallback,
em uma transacao nunca confirmada. Nao altera configuracoes/historicos preexistentes.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import DBAPIError

from api.app.config import Settings
from api.app.database import Database
from api.app.main import create_app
from api.scripts.validate_live import snapshot


def local_admin():
    values = dotenv_values(PROJECT / ".env")
    return create_engine(URL.create("mysql+pymysql", username="root", password=values["MYSQL_ROOT_PASSWORD"],
        host="127.0.0.1", port=int(values.get("PDOH_MYSQL_PORT", "3307"))),
        hide_parameters=True, connect_args={"connect_timeout": 5})


def platina_snapshot(engine):
    with engine.connect() as c:
        c.exec_driver_sql("SET SESSION TRANSACTION READ ONLY")
        rows = c.exec_driver_sql("SELECT * FROM produtos_platina.exclusivo_bracell_platina_relatorio_pdoh").mappings()
        hashes = sorted(hashlib.sha256(json.dumps(dict(r), sort_keys=True, default=str).encode()).hexdigest() for r in rows)
        c.rollback()
        c.exec_driver_sql("SET SESSION TRANSACTION READ WRITE")
        return {"linhas": len(hashes), "sha256": hashlib.sha256("".join(hashes).encode()).hexdigest()}


def test_history(engine):
    identifier = str(uuid4())
    with engine.connect() as c:
        transaction = c.begin()
        try:
            c.execute(text("""INSERT INTO pdoh_controle.regra_fallback_config
                (id,marca,regra,escopo,chave,valor_fallback,vigencia_inicio,status,usuario_alteracao)
                VALUES (:id,'BRACELL_TESTE_TRANSACIONAL','CHECKOUT_AUSENTE','MARCA','*','18:00','2026-09-01','INATIVO','teste_rollback')"""), {"id": identifier})
            c.execute(text("UPDATE pdoh_controle.regra_fallback_config SET valor_fallback='19:00', vigencia_fim='2026-09-30', usuario_alteracao='teste_rollback_2' WHERE id=:id"), {"id": identifier})
            rows = c.execute(text("SELECT * FROM pdoh_controle.regra_fallback_historico WHERE config_id=:id ORDER BY id"), {"id": identifier}).mappings().all()
            assert len(rows) == 2
            assert rows[0]["valor_anterior"] is None and rows[0]["novo_valor"] == "18:00"
            assert rows[1]["valor_anterior"] == "18:00" and rows[1]["novo_valor"] == "19:00"
            assert rows[1]["usuario_alteracao"] == "teste_rollback_2"
            assert json.loads(rows[1]["estado_anterior"])["vigencia_fim"] is None
            assert json.loads(rows[1]["estado_novo"])["vigencia_fim"] == "2026-09-30"
            rejected = 0
            for sql in (
                "UPDATE pdoh_controle.regra_fallback_historico SET novo_valor='20:00' WHERE config_id=:id",
                "DELETE FROM pdoh_controle.regra_fallback_historico WHERE config_id=:id",
                "DELETE FROM pdoh_controle.regra_fallback_config WHERE id=:id",
                "UPDATE pdoh_controle.regra_fallback_config SET chave='OUTRA' WHERE id=:id",
            ):
                try:
                    c.execute(text(sql), {"id": identifier})
                except DBAPIError as error:
                    assert error.orig.args[0] == 1644, "Falha deve vir do trigger SIGNAL, nao de permissoes."
                    rejected += 1
                else:
                    raise AssertionError("Protecao de historico/identidade nao rejeitou a operacao.")
            for assignment in ("valor_fallback='24:00'", "vigencia_fim='2026-08-31'", "usuario_alteracao=''", "status='INVALIDO'"):
                try:
                    c.execute(text("UPDATE pdoh_controle.regra_fallback_config SET " + assignment + " WHERE id=:id"), {"id": identifier})
                except DBAPIError as error:
                    assert error.orig.args[0] == 3819, "Falha deve vir do CHECK constraint."
                    rejected += 1
                else:
                    raise AssertionError("CHECK nao rejeitou configuracao invalida.")
            assert rejected == 8
        finally:
            transaction.rollback()
        assert c.execute(text("SELECT COUNT(*) FROM pdoh_controle.regra_fallback_config WHERE id=:id"), {"id": identifier}).scalar_one() == 0
        assert c.execute(text("SELECT COUNT(*) FROM pdoh_controle.regra_fallback_historico WHERE config_id=:id"), {"id": identifier}).scalar_one() == 0
    return {"historico_automatico": True, "bloqueios_validados": rejected, "rollback_confirmado": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-history", action="store_true")
    parser.add_argument("--check-platina", action="store_true", help="SELECT/hash da tabela local de saida, sem recalculo.")
    args = parser.parse_args()
    settings = replace(Settings.load(), host="127.0.0.1", port=int(dotenv_values(PROJECT / ".env").get("PDOH_MYSQL_PORT", "3307")))
    database = Database(settings)
    database.initialize()
    before = snapshot(database)
    checks = {}
    admin = local_admin() if args.test_history or args.check_platina else None
    try:
        platina_before = platina_snapshot(admin) if args.check_platina else None
        if args.test_history:
            checks["historico"] = test_history(admin)
        with TestClient(create_app(settings, database)) as client:
            client.headers["Authorization"] = "Bearer " + settings.token
            for value in ("23:59", "18:00"):
                response = client.post("/api/fallback/simular", json={"marca": "BRACELL", "regra": "CHECKOUT_AUSENTE", "novo_valor": value})
                assert response.status_code == 200, response.text
                checks[value] = response.json()
            result = checks["18:00"]
            with database.connection() as c:
                assert c.exec_driver_sql("SELECT @@session.transaction_read_only").scalar_one() == 1
                sql = c.execute(text("""SELECT SUM(CAST(JSON_UNQUOTE(JSON_EXTRACT(evidencia,'$.ocorrencias')) AS UNSIGNED)) registros,
                    COUNT(DISTINCT LOWER(TRIM(colaborador))) colaboradores, COUNT(*) grupos FROM pdoh_controle.oportunidade
                    WHERE execution_id=:id AND marca='BRACELL' AND tipo_problema='CHECKOUT_AUSENTE'"""), {"id": result["execution_id"]}).mappings().one()
                assert sql["registros"] == result["registros_afetados"]
                assert sql["colaboradores"] == result["colaboradores_afetados"]
                assert sql["grupos"] == result["grupos_observados"]
            assert checks["23:59"]["registros_afetados"] == 0
            after = snapshot(database)
            assert before == after, "Dados de controle divergiram; verificar atividade concorrente."
            checks["controle_antes"] = before
            checks["controle_depois"] = after
        if args.check_platina:
            platina_after = platina_snapshot(admin)
            assert platina_before == platina_after
            checks["platina_antes"] = platina_before
            checks["platina_depois"] = platina_after
        checks["read_only_e_sem_mutacao"] = True
        print(json.dumps(checks, ensure_ascii=False, sort_keys=True, default=str))
    finally:
        database.close()
        if admin:
            admin.dispose()


if __name__ == "__main__":
    main()
