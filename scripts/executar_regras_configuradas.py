"""Executa as regras de oportunidade CONFIGURADAS sobre um periodo ja carregado na Platina.

    python scripts/executar_regras_configuradas.py --inicio 2026-08-31 --fim 2026-09-05
    python scripts/executar_regras_configuradas.py --inicio 2026-08-31 --fim 2026-09-05 --aplicar
    python scripts/executar_regras_configuradas.py --inicio 2026-08-31 --fim 2026-09-06 --aplicar --reprocessar

Sem ``--aplicar`` e' um ensaio: le a configuracao, a Platina e a origem (somente SELECT), mostra
o que cada regra ativa geraria e NAO grava nada. Com ``--aplicar`` abre uma execucao operacional
propria (componente REGRAS_CONFIGURADAS), cria as oportunidades pelo dispatcher normal e a encerra.
Com ``--reprocessar`` (exige ``--aplicar``) tambem encerra, com historico, as ocorrencias abertas da
janela que foram avaliadas de novo e nao apresentam mais divergencia (ex.: checkout lancado depois).

Nao recalcula PDOH, nao toca Platina/Gold/ETL/historico. A origem `involves_exclusivos` e' sempre
somente leitura (sessao READ ONLY + validacao de SQL em `criar_engine_origem`).

Credenciais: lidas de `.env` / `.env.cadastro` (ja fora do Git) para a MEMORIA do processo, ou das
variaveis de ambiente se ja definidas. Nunca sao gravadas, exibidas ou registradas.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'bracell'))

ORIGEM = ('PDOH_SOURCE_DB_HOST', 'PDOH_SOURCE_DB_PORT', 'PDOH_SOURCE_DB_NAME',
          'PDOH_SOURCE_DB_USER', 'PDOH_SOURCE_DB_PASSWORD')


def preparar_ambiente():
    """Preenche o ambiente do processo (so' o que faltar). Nada e' escrito em disco."""
    base = dotenv_values(ROOT / '.env')
    cadastro = dotenv_values(ROOT / '.env.cadastro')
    padroes = {
        'PDOH_DB_HOST': '127.0.0.1',
        'PDOH_DB_PORT': base.get('PDOH_MYSQL_PORT') or '3307',
        'PDOH_DB_USER': base.get('PDOH_DB_USER'),
        'PDOH_DB_PASSWORD': base.get('PDOH_DB_PASSWORD'),
        **{chave: cadastro.get(chave) for chave in ORIGEM},
    }
    for chave, valor in padroes.items():
        if valor and not os.environ.get(chave):
            os.environ[chave] = valor


def contagens(engine, marca, operacao):
    with engine.connect() as conexao:
        total = conexao.execute(text('SELECT COUNT(*) FROM pdoh_controle.oportunidade')).scalar()
        regra = conexao.execute(text(
            "SELECT COUNT(*) FROM pdoh_controle.oportunidade WHERE marca=:marca AND tipo_problema='HORAS_AUSENTES'"),
            {'marca': marca}).scalar()
    return dict(oportunidades_total=total, horas_ausentes=regra)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--inicio', required=True, help='Data inicial YYYY-MM-DD.')
    parser.add_argument('--fim', required=True, help='Data final YYYY-MM-DD.')
    parser.add_argument('--marca', default='BRACELL')
    parser.add_argument('--operacao', default='EXCLUSIVA')
    parser.add_argument('--aplicar', action='store_true',
                        help='Cria a execucao e as oportunidades. Sem isto, apenas simula.')
    parser.add_argument('--reprocessar', action='store_true',
                        help='Com --aplicar: encerra as ocorrencias da janela que deixaram de existir.')
    args = parser.parse_args()
    if args.reprocessar and not args.aplicar:
        parser.error('--reprocessar exige --aplicar.')
    sys.stdout.reconfigure(encoding='utf-8')     # console Windows (cp1252) nao le acentos

    preparar_ambiente()
    from src.database import criar_engine, criar_engine_origem
    from src.observability import (
        definir_execution_id, finalizar_execucao, gerar_execution_id, iniciar_execucao,
    )
    from src.regras_configuradas import executar_regras

    engine = criar_engine('involves_bracell')
    try:
        origem = criar_engine_origem()
    except Exception as erro:
        origem = None
        print(f'AVISO: origem indisponivel ({type(erro).__name__}); a jornada oficial nao sera resolvida.',
              file=sys.stderr)

    saida = dict(modo='REPROCESSAR' if args.reprocessar else 'APLICAR' if args.aplicar else 'ENSAIO', marca=args.marca, operacao=args.operacao,
                 periodo=[args.inicio, args.fim])
    if not args.aplicar:
        saida['resultado'] = executar_regras(
            engine, origem, periodo_inicio=args.inicio, periodo_fim=args.fim, marca=args.marca,
            operacao=args.operacao, criar=False, registrar=False)
        print(json.dumps(saida, ensure_ascii=False, indent=2, default=str))
        return 0

    saida['antes'] = contagens(engine, args.marca, args.operacao)
    execution_id = definir_execution_id(gerar_execution_id(args.marca))
    os.environ['PDOH_COMPONENTE'] = 'REGRAS_CONFIGURADAS'
    iniciar_execucao(engine, execution_id=execution_id, marca=args.marca, periodo_inicio=args.inicio,
                     periodo_fim=args.fim, componente='REGRAS_CONFIGURADAS', operacao=args.operacao,
                     finalidade='OPERACIONAL')
    resultado = executar_regras(engine, origem, periodo_inicio=args.inicio, periodo_fim=args.fim,
                                marca=args.marca, operacao=args.operacao, reconciliar=args.reprocessar)
    criadas = sum(regra['criadas'] for regra in resultado['regras'])
    if resultado['erros']:
        status = 'FALHA_TECNICA'
    else:
        status = 'CONCLUIDA_COM_ALERTAS' if criadas else 'CONCLUIDA_SEM_RESULTADO'
    saida.update(execution_id=execution_id, status=finalizar_execucao(engine, status=status),
                 resultado=resultado, depois=contagens(engine, args.marca, args.operacao))
    print(json.dumps(saida, ensure_ascii=False, indent=2, default=str))
    return 1 if resultado['erros'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
