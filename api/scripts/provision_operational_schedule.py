"""Aplica apenas o cadastro de horarios e suas permissoes, sem executar a esteira."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from api.scripts.provision_config_writer import mysql, main as provision_writer


def main():
    for migration in ('017_jornada_operacao.sql', '019_jornadas_manuais.sql'):
        mysql((ROOT / 'docker/mysql/migrations' / migration).read_text(encoding='utf-8'))
    provision_writer()
    print('Cadastro de jornada instalado, sem horarios preenchidos nem regras ativadas.')


if __name__ == '__main__':
    main()
