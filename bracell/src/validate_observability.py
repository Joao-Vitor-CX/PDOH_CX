"""Smoke test da camada lateral sem escrever na origem nem na Platina."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from .data_quality import observar_qualidade
from .database import criar_engine
from .identity import observar_identidades
from .observability import (
    definir_execution_id,
    finalizar_execucao,
    iniciar_execucao,
    registrar_fallback,
)


def _contar(conexao, tabela: str, execution_id: str) -> int:
    return int(
        conexao.execute(
            text(f"SELECT COUNT(*) FROM pdoh_controle.{tabela} WHERE execution_id = :id"),
            {"id": execution_id},
        ).scalar_one()
    )


def main() -> int:
    execution_id = definir_execution_id(
        f"BRACELL_VALIDACAO_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    )
    engine = criar_engine("involves_bracell")
    with engine.connect() as conexao:
        platina_antes = int(
            conexao.execute(
                text(
                    "SELECT COUNT(*) FROM produtos_platina."
                    "exclusivo_bracell_platina_relatorio_pdoh"
                )
            ).scalar_one()
        )

    iniciar_execucao(
        engine,
        execution_id=execution_id,
        marca="BRACELL",
        periodo_inicio="2026-09-01",
        periodo_fim="2026-09-06",
        componente="VALIDACAO",
    )

    checkin = pd.DataFrame(
        [
            {
                "colaborador": "João",
                "data_roteiro": "2026-09-01",
                "hora_entrada": "2026-09-01 10:00:00",
                "hora_saida": "2026-09-01 09:00:00",
                "estado": "SP",
            },
            {
                "colaborador": "João",
                "data_roteiro": "2026-09-01",
                "hora_entrada": "2026-09-01 10:00:00",
                "hora_saida": "2026-09-01 09:00:00",
                "estado": "SP",
            },
            {
                "colaborador": " João ",
                "data_roteiro": "2026-09-02",
                "hora_entrada": None,
                "hora_saida": None,
                "estado": "INVALIDO",
            },
        ]
    )
    colaboradores = pd.DataFrame(
        [
            {
                "nome_colaborador": "João",
                "usuario": "u.teste.validacao",
                "usuario_ativo": "Sim",
                "data_evolucao": "2026-09-01",
            },
            {
                "nome_colaborador": "João Silva",
                "usuario": "u.teste.validacao",
                "usuario_ativo": "Sim",
                "data_evolucao": "2026-09-01",
            },
        ]
    )
    oportunidades_qualidade = observar_qualidade(
        engine,
        checkin,
        "checkin",
        "relatorio_checkin_bracell",
        periodo_inicio="2026-09-01",
        periodo_fim="2026-09-06",
    )
    identidades = observar_identidades(
        engine,
        {"colaboradores": colaboradores, "checkin": checkin},
    )
    registrar_fallback(
        engine,
        codigo="VALIDACAO_FALLBACK_CONTROLADO",
        motivo="Evento sintetico usado apenas para validar o canal de fallback.",
        etapa="VALIDACAO",
        severidade="ALTA",
        contexto={"sintetico": True},
    )
    finalizar_execucao(engine, status="CONCLUIDA_SEM_RESULTADO")

    with engine.connect() as conexao:
        platina_depois = int(
            conexao.execute(
                text(
                    "SELECT COUNT(*) FROM produtos_platina."
                    "exclusivo_bracell_platina_relatorio_pdoh"
                )
            ).scalar_one()
        )
        resultado = {
            "execution_id": execution_id,
            "oportunidades": _contar(conexao, "oportunidade", execution_id),
            "historicos": _contar(conexao, "oportunidade_historico", execution_id),
            "fallbacks": _contar(conexao, "fallback_evento", execution_id),
            "notificacoes_pendentes": int(
                conexao.execute(
                    text(
                        "SELECT COUNT(*) FROM pdoh_controle.notificacao_outbox "
                        "WHERE execution_id = :id AND status_notificacao = 'PENDENTE'"
                    ),
                    {"id": execution_id},
                ).scalar_one()
            ),
            "identidades_observadas": identidades,
            "oportunidades_retornadas": oportunidades_qualidade,
            "platina_antes": platina_antes,
            "platina_depois": platina_depois,
        }

    verificacoes = (
        resultado["oportunidades"] > 0,
        resultado["historicos"] == resultado["oportunidades"],
        resultado["fallbacks"] == 1,
        resultado["notificacoes_pendentes"] > 0,
        resultado["identidades_observadas"] > 0,
        resultado["platina_antes"] == resultado["platina_depois"],
    )
    if not all(verificacoes):
        print("OBSERVABILIDADE_FALHOU")
        print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
        return 1
    print("OBSERVABILIDADE_OK")
    print(json.dumps(resultado, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
