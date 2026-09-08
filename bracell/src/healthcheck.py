"""Valida, sem escrita, a comunicacao do backend com os bancos locais."""

from __future__ import annotations

import argparse
import json
import time

from sqlalchemy import text

from .database import criar_engine


TABELAS_ORIGEM = (
    "status_day_operacao_bracell",
    "colaboradores_ativos_bracell",
    "relatorio_checkin_bracell",
    "gerencial_visitas_bracell",
    "painel_pesquisas_bracell",
)
TABELA_PLATINA = "exclusivo_bracell_platina_relatorio_pdoh"
TABELAS_CONTROLE = (
    "execucao",
    "execucao_etapa",
    "execucao_fonte",
    "execucao_evento",
    "fallback_evento",
    "colaborador_identidade",
    "colaborador_alias",
    "oportunidade",
    "oportunidade_historico",
    "notificacao_outbox",
    "saida_linhagem",
)


def _engine():
    return criar_engine("involves_bracell")


def verificar() -> dict:
    resultado = {"origem": {}, "platina": {}, "controle": {}}
    with _engine().connect() as conexao:
        for tabela in TABELAS_ORIGEM:
            total = conexao.execute(
                text(f"SELECT COUNT(*) FROM `involves_bracell`.`{tabela}`")
            ).scalar_one()
            resultado["origem"][tabela] = int(total)

        total_platina = conexao.execute(
            text(
                "SELECT COUNT(*) FROM `produtos_platina`."
                "`exclusivo_bracell_platina_relatorio_pdoh`"
            )
        ).scalar_one()
        resultado["platina"][TABELA_PLATINA] = int(total_platina)
        for tabela in TABELAS_CONTROLE:
            total = conexao.execute(
                text(f"SELECT COUNT(*) FROM `pdoh_controle`.`{tabela}`")
            ).scalar_one()
            resultado["controle"][tabela] = int(total)
    return resultado


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--tentativas", type=int, default=30)
    parser.add_argument("--intervalo", type=float, default=2.0)
    args = parser.parse_args()

    tentativas = args.tentativas if args.wait else 1
    for tentativa in range(1, tentativas + 1):
        try:
            resultado = verificar()
            print("COMUNICACAO_OK")
            print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
            return 0
        except Exception as exc:
            if tentativa == tentativas:
                print(f"COMUNICACAO_FALHOU: {exc}")
                return 1
            print(f"Aguardando MySQL ({tentativa}/{tentativas})...")
            time.sleep(args.intervalo)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
