"""DDL aditivo explicito, fora da inicializacao API/CD/pipeline. Sem seed ou UPDATE."""
import argparse
from pathlib import Path

from provision_reader import mysql

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_regra_fallback.sql"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Cria somente tabelas/triggers de fallback no MySQL local.")
    args = parser.parse_args()
    if not args.apply:
        print("Planejado: regra_fallback_config, regra_fallback_historico e 7 triggers. Sem dados iniciais. Use --apply.")
        return
    mysql(MIGRATION.read_text(encoding="utf-8"))
    print("Estrutura de fallback provisionada. Nenhuma configuracao ativada; processadores nao integrados.")


if __name__ == "__main__":
    main()
