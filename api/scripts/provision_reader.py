"""Provisionamento local explícito. Nunca executado ao iniciar a API ou no CD."""
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from dotenv import dotenv_values


def mysql(sql):
    result = subprocess.run(
        ["docker", "exec", "-i", "pdoh_cx_mysql", "sh", "-c",
         'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot --batch --skip-column-names'],
        input=sql, text=True, capture_output=True, encoding="utf-8", timeout=30,
    )
    if result.returncode:
        # O erro original pode incluir SQL com a senha; nunca o imprime.
        raise RuntimeError("Provisionamento falhou. Confira acesso administrativo ao Docker/MySQL.")
    return result.stdout.strip()


def main():
    config = ROOT / ".env.api"
    if config.exists():
        print("api/.env.api ja existe; credenciais e conta preservadas. Execute a validacao da API.")
        return
    if mysql("SELECT COUNT(*) FROM mysql.user WHERE User='pdoh_cx_reader';") != "0":
        raise RuntimeError("A conta pdoh_cx_reader ja existe. Configure api/.env.api com a credencial existente; nenhuma conta foi alterada.")
    password, token = secrets.token_urlsafe(36), secrets.token_urlsafe(48)
    mysql("CREATE USER 'pdoh_cx_reader'@'%' IDENTIFIED BY '" + password + "';\n"
          "GRANT SELECT ON pdoh_controle.* TO 'pdoh_cx_reader'@'%';\n")
    port = dotenv_values(ROOT.parent / ".env").get("PDOH_MYSQL_PORT", "3307")
    with config.open("x", encoding="utf-8") as stream:
        stream.write(f"PDOH_API_DB_HOST=127.0.0.1\nPDOH_API_DB_PORT={port}\n"
                     f"PDOH_API_DB_USER=pdoh_cx_reader\nPDOH_API_DB_PASSWORD={password}\n"
                     f"PDOH_API_TOKEN={token}\n"
                     "PDOH_API_ORIGINS=http://127.0.0.1:5173,http://localhost:5173\n")
    print("Conta pdoh_cx_reader criada: SELECT somente em pdoh_controle.*. Credenciais em api/.env.api (ignorado pelo Git).")


if __name__ == "__main__":
    main()
