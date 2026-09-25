"""Aplica somente a migracao 008; nunca executa bootstrap/reclassificacao/pipeline."""
import argparse
from pathlib import Path
from provision_reader import mysql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print('Plano: criar alerta e achado_roteamento, sem migrar dados ou alterar classificacoes. Use --apply.')
        return
    path = Path(__file__).resolve().parents[2] / 'docker/mysql/migrations/008_roteamento_achados.sql'
    mysql(path.read_text(encoding='utf-8'))
    print('Estrutura de novos achados criada; historico e catalogo existentes preservados.')


if __name__ == '__main__':
    main()
