"""Executor lateral da esteira BRACELL com um unico ``execution_id``.

Os processadores sao iniciados como subprocessos isolados, exatamente como no
shell legado. O executor apenas observa saida, arquivo de erro e eventos do banco.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from src.database import criar_engine
from src.observability import (
    definir_execution_id,
    finalizar_execucao,
    gerar_execution_id,
    iniciar_execucao,
    obter_resumo_execucao,
    registrar_erro_tecnico,
    registrar_etapa,
    registrar_evento,
    registrar_fallback,
)


BASE_DIR = Path(__file__).resolve().parent
ARQUIVO_ERRO = BASE_DIR / "Erro na automação.txt"
SCRIPTS_PADRAO = (
    "pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
    "lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
)
SCRIPTS_PERMITIDOS = {
    "pdoh_bracell.py",
    "pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
    "lideres_pdoh_bracell.py",
    "lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py",
}


def _assinatura_arquivo(caminho: Path) -> tuple[int, int] | None:
    try:
        status = caminho.stat()
        return status.st_mtime_ns, status.st_size
    except FileNotFoundError:
        return None


def _ler_erro(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8", errors="replace")[:16000]
    except Exception as exc:
        return f"Nao foi possivel ler o arquivo de erro: {exc}"


def _codigo_fallback(mensagem: str) -> str:
    sufixo = hashlib.sha256(mensagem.encode("utf-8")).hexdigest()[:10].upper()
    return f"FALLBACK_LEGADO_{sufixo}"


def _executar_componente(
    engine,
    script: str,
    argumentos_script: list[str],
    arquivo_log,
) -> tuple[int, str | None]:
    componente = "LIDERES" if script.startswith("lideres_") else "PROMOTORES"
    ambiente = os.environ.copy()
    ambiente["PDOH_COMPONENTE"] = componente
    os.environ["PDOH_COMPONENTE"] = componente
    assinatura_anterior = _assinatura_arquivo(ARQUIVO_ERRO)

    registrar_etapa(
        engine,
        etapa="PROCESSAMENTO_PDOH",
        status="INICIADA",
        mensagem=f"Componente {componente} iniciado pelo executor lateral.",
        contexto={"script": script},
    )
    comando = [sys.executable, str(BASE_DIR / script), *argumentos_script]
    processo = subprocess.Popen(
        comando,
        cwd=BASE_DIR,
        env=ambiente,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert processo.stdout is not None
    for linha in processo.stdout:
        sys.stdout.write(linha)
        sys.stdout.flush()
        arquivo_log.write(linha)
        arquivo_log.flush()
        mensagem = linha.strip()
        if mensagem.startswith("AVISO:"):
            registrar_fallback(
                engine,
                codigo=_codigo_fallback(mensagem),
                motivo=mensagem,
                etapa="PROCESSAMENTO_PDOH",
                severidade="MEDIA",
                impacto_esperado="Fallback legado aplicado sem alteracao do resultado calculado.",
                contexto={"script": script, "componente": componente},
            )
    retorno = processo.wait()

    assinatura_atual = _assinatura_arquivo(ARQUIVO_ERRO)
    erro_arquivo = None
    if assinatura_atual is not None and assinatura_atual != assinatura_anterior:
        erro_arquivo = _ler_erro(ARQUIVO_ERRO)

    if retorno != 0:
        mensagem = f"Componente {componente} terminou com codigo {retorno}."
        registrar_erro_tecnico(engine, etapa="PROCESSAMENTO_PDOH", mensagem=mensagem)
    elif erro_arquivo:
        mensagem = (
            f"Componente {componente} registrou erro tecnico no arquivo legado, "
            "apesar do codigo de saida zero."
        )
        registrar_erro_tecnico(
            engine,
            etapa="PROCESSAMENTO_PDOH",
            mensagem=f"{mensagem} {erro_arquivo[:4000]}",
        )
        arquivo_log.write(f"[ERRO_TECNICO_LEGADO] {erro_arquivo}\n")
        arquivo_log.flush()
    else:
        registrar_etapa(
            engine,
            etapa="PROCESSAMENTO_PDOH",
            status="COMPONENTE_CONCLUIDO",
            mensagem=f"Componente {componente} terminou com o mesmo codigo de saida do legado.",
            contexto={"script": script, "codigo_saida": retorno},
        )
    return retorno, erro_arquivo


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa a replica BRACELL com rastreabilidade lateral.")
    parser.add_argument(
        "--script",
        action="append",
        choices=sorted(SCRIPTS_PERMITIDOS),
        help="Script especifico; pode ser repetido. Sem a opcao, executa a esteira atual.",
    )
    parser.add_argument("--data-inicio", help="Data inicial YYYY-MM-DD para scripts que aceitam CLI.")
    parser.add_argument("--data-fim", help="Data final YYYY-MM-DD para scripts que aceitam CLI.")
    args = parser.parse_args()
    if bool(args.data_inicio) != bool(args.data_fim):
        parser.error("--data-inicio e --data-fim devem ser informados juntos")

    scripts = tuple(args.script or SCRIPTS_PADRAO)
    argumentos_script = [args.data_inicio, args.data_fim] if args.data_inicio else []
    execution_id = definir_execution_id(gerar_execution_id("BRACELL"))
    os.environ["PDOH_COMPONENTE"] = "ORQUESTRADOR"
    logs_dir = BASE_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    caminho_log = logs_dir / f"{execution_id}.log"

    engine = criar_engine("involves_bracell")
    try:
        with engine.connect() as conexao:
            conexao.execute(text("SELECT 1"))
    except Exception:
        # iniciar_execucao emitira o diagnostico fail-open; o legado seguira e
        # manterá exatamente sua propria forma de tratar indisponibilidade.
        pass
    iniciar_execucao(
        engine,
        execution_id=execution_id,
        periodo_inicio=args.data_inicio,
        periodo_fim=args.data_fim,
        componente="ORQUESTRADOR",
    )
    registrar_evento(
        engine,
        nivel="INFO",
        categoria="OPERACIONAL",
        codigo="PIPELINE_INICIADO",
        mensagem="Esteira BRACELL iniciada com observabilidade lateral.",
        etapa="INICIALIZACAO",
        contexto={"scripts": scripts, "arquivo_log": str(caminho_log)},
    )

    primeiro_codigo_nao_zero = 0
    houve_erro_legado = False
    with caminho_log.open("a", encoding="utf-8", newline="") as arquivo_log:
        arquivo_log.write(f"execution_id={execution_id}\n")
        arquivo_log.write(f"scripts={','.join(scripts)}\n")
        arquivo_log.write("status=INICIADA\n")
        for script in scripts:
            retorno, erro_arquivo = _executar_componente(
                engine,
                script,
                argumentos_script,
                arquivo_log,
            )
            houve_erro_legado = houve_erro_legado or bool(erro_arquivo)
            if retorno != 0:
                primeiro_codigo_nao_zero = retorno
                # Equivale ao set -e do exec_pdoh_main.sh anterior.
                break

    resumo = obter_resumo_execucao(engine)
    if houve_erro_legado or primeiro_codigo_nao_zero or resumo.get("status_execucao") == "FALHA_TECNICA":
        status_final = finalizar_execucao(engine, status="FALHA_TECNICA")
    else:
        status_final = finalizar_execucao(engine)
    with caminho_log.open("a", encoding="utf-8", newline="") as arquivo_log:
        arquivo_log.write(f"status_final={status_final}\n")

    print(f"EXECUTION_ID={execution_id}")
    print(f"LOG_EXECUCAO={caminho_log}")
    # O retorno do subprocesso e preservado. Erros engolidos pelo legado ficam
    # corretamente classificados no controle, mas continuam retornando zero.
    return primeiro_codigo_nao_zero


if __name__ == "__main__":
    raise SystemExit(main())
