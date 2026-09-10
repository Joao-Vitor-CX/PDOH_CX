"""Valida o UPSERT/linhagem e reverte a linha sintetica na mesma transacao."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from .alch import NOME_TABELA, inserir_produto
from .database import criar_engine
from .observability import (
    definir_execution_id,
    finalizar_execucao,
    iniciar_execucao,
    obter_resumo_execucao,
    registrar_erro_tecnico,
)


COLABORADOR_TESTE = "__PDOH_CX_VALIDACAO_PERSISTENCIA__"
DATA_TESTE = "2099-12-31"


def _quantidade_platina(engine, connection=None) -> int:
    if connection is not None:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {NOME_TABELA}")).scalar_one())
    with engine.connect() as conexao:
        return int(
            conexao.execute(
                text(f"SELECT COUNT(*) FROM {NOME_TABELA}")
            ).scalar_one()
        )


def _linha_teste_existe(engine, connection=None) -> bool:
    consulta = text(
        f"SELECT COUNT(*) FROM {NOME_TABELA} "
        "WHERE colaborador = :colaborador AND data = :data"
    )
    parametros = {"colaborador": COLABORADOR_TESTE, "data": DATA_TESTE}
    if connection is not None:
        return bool(connection.execute(consulta, parametros).scalar_one())
    with engine.connect() as conexao:
        return bool(conexao.execute(consulta, parametros).scalar_one())


def _dataframe_teste() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "colaborador": COLABORADOR_TESTE,
                "superior": "VALIDACAO",
                "estado": "SP",
                "data": DATA_TESTE,
                "nome_do_dia": "QUINTA-FEIRA",
                "deslocamento": "01:00:00",
                "ocio": "00:30:00",
                "produtividade": "06:00:00",
                "horas_nao_registradas": "00:00:00",
                "horas_programadas": "08:00:00",
                "almoco": "01:00:00",
                "media_tempo_em_loja": "01:00:00",
                "primeiro_checkin": "08:00:00",
                "ultimo_checkout": "17:00:00",
                "visitas_diarias": 1,
                "visitas_diarias_realizadas": 1,
                "pesquisas_diarias": 1,
                "pesquisas_diarias_realizadas": 1,
                "percentual_produtividade": 0.75,
                "percentual_visitas": 1.0,
                "percentual_pesquisas": 1.0,
                "percentual_efetividade": 0.75,
                "justificativas_seg": None,
                "justificativas_ter": None,
                "justificativas_qua": None,
                "justificativas_qui": "VALIDACAO TECNICA",
                "justificativas_sex": None,
                "justificativas_sab": None,
            }
        ]
    )


def main() -> int:
    engine = criar_engine("involves_bracell")
    if _linha_teste_existe(engine):
        print("PERSISTENCIA_NAO_EXECUTADA: a chave sintética já existe; nada foi alterado.")
        return 2

    execution_id = definir_execution_id(
        f"BRACELL_VALIDACAO_PERSISTENCIA_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    )
    iniciar_execucao(
        engine,
        execution_id=execution_id,
        marca="BRACELL",
        periodo_inicio=DATA_TESTE,
        periodo_fim=DATA_TESTE,
        componente="VALIDACAO_PERSISTENCIA",
    )
    total_antes = _quantidade_platina(engine)
    persistiu = False
    removida = False
    transaction = None
    try:
        with engine.connect() as conexao_validacao:
            transaction = conexao_validacao.begin()
            inserir_produto(
                _dataframe_teste(),
                engine,
                connection=conexao_validacao,
            )
            persistiu = _linha_teste_existe(engine, connection=conexao_validacao)
            resumo = obter_resumo_execucao(engine)
            with engine.connect() as conexao_controle:
                linhagem = int(
                    conexao_controle.execute(
                        text(
                            "SELECT COUNT(*) FROM pdoh_controle.saida_linhagem "
                            "WHERE execution_id = :id"
                        ),
                        {"id": execution_id},
                    ).scalar_one()
                )
            if not persistiu or not resumo.get("houve_persistencia") or linhagem != 1:
                raise RuntimeError("UPSERT, flag de persistencia ou linhagem nao foram confirmados")
            transaction.rollback()
            transaction = None
        removida = not _linha_teste_existe(engine)
    except Exception as exc:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        registrar_erro_tecnico(
            engine,
            etapa="VALIDACAO_PERSISTENCIA",
            mensagem=f"Smoke test de persistencia falhou: {exc}",
            excecao=exc,
        )

    total_depois = _quantidade_platina(engine)
    resumo_final = obter_resumo_execucao(engine)
    valido = (
        persistiu
        and removida
        and total_antes == total_depois
        and resumo_final.get("status_execucao") != "FALHA_TECNICA"
    )
    status = finalizar_execucao(engine, status="CONCLUIDA" if valido else "FALHA_TECNICA")
    resultado = {
        "execution_id": execution_id,
        "persistencia_confirmada": persistiu,
        "linha_sintetica_removida": removida,
        "linhas_platina_antes": total_antes,
        "linhas_platina_depois": total_depois,
        "status": status,
    }
    print("PERSISTENCIA_OK" if valido else "PERSISTENCIA_FALHOU")
    print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
    return 0 if valido else 1


if __name__ == "__main__":
    raise SystemExit(main())
