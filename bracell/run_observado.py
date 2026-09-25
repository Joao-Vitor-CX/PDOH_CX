"""Executor lateral da esteira BRACELL com um unico ``execution_id``.

Os processadores sao iniciados como subprocessos isolados, exatamente como no
shell legado. O executor apenas observa saida, arquivo de erro e eventos do banco.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from src.database import criar_engine, criar_engine_origem
from src.de_para import bootstrap_de_para
from src.observability import (
    definir_execution_id,
    finalizar_execucao,
    gerar_execution_id,
    iniciar_execucao,
    obter_execution_id,
    obter_resumo_execucao,
    registrar_erro_tecnico,
    registrar_etapa,
    registrar_evento,
    registrar_fallback,
    registrar_achado,
    resolver_tratativa,
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

# Filtro de lideranca usado por cada processador de lideres (perfil_acesso).
# Permite a pre-checagem preventiva do orquestrador sem tocar nos scripts
# replicados (que sao travados por hash no manifesto).
FILTRO_LIDER_POR_SCRIPT = {
    "lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py": "LIDER EXCLUSIVO",
    "lideres_pdoh_bracell.py": "PROMOTORES LIDERES",
}


def _criterio_lider(engine, script: str) -> str | None:
    """Perfil que identifica lideranca para a pre-checagem do orquestrador.

    Parametrizavel via regra `CRITERIO_LIDER` (campo regra_identificacao = JSON
    {script: perfil}); cai para o default fixo `FILTRO_LIDER_POR_SCRIPT` se a regra
    nao existir. So se aplica a scripts de lideres. Fail-open para o default.

    IMPORTANTE: este criterio deve espelhar o filtro interno (travado) do processador;
    ele decide apenas se o subprocesso sera lancado, nao altera o calculo.
    """

    padrao = FILTRO_LIDER_POR_SCRIPT.get(script)
    if padrao is None:
        return None
    try:
        regra = resolver_tratativa(engine, "CRITERIO_LIDER")
        if regra and regra.get("regra_identificacao"):
            mapa = json.loads(regra["regra_identificacao"])
            if isinstance(mapa, dict) and mapa.get(script):
                return str(mapa[script])
    except Exception:
        pass
    return padrao


def _snapshot_sem_lideres(filtro: str) -> bool:
    """Reproduz o tratamento de colaboradores do data_loader (snapshot do
    data_evolucao mais recente + usuario_ativo='sim' + dedup pelo data_dimensao
    mais recente por nome) e verifica, na origem somente-leitura, se existe algum
    colaborador cujo perfil casa com o filtro de lideranca.

    Fail-open: qualquer duvida/indisponibilidade retorna False (nao pula o
    componente), preservando o comportamento atual.
    """

    try:
        engine_origem = criar_engine_origem()
        consulta = text(
            "SELECT COUNT(*) FROM ("
            "  SELECT perfil_acesso, ROW_NUMBER() OVER "
            "    (PARTITION BY nome_colaborador ORDER BY data_dimensao DESC) AS rn"
            "  FROM colaboradores_ativos_bracell"
            "  WHERE data_evolucao = (SELECT MAX(data_evolucao) FROM colaboradores_ativos_bracell)"
            "    AND LOWER(TRIM(usuario_ativo)) = 'sim'"
            ") t WHERE t.rn = 1 AND UPPER(t.perfil_acesso) LIKE :filtro"
        )
        with engine_origem.connect() as conexao:
            total = conexao.execute(consulta, {"filtro": f"%{filtro.upper()}%"}).scalar() or 0
        return int(total) == 0
    except Exception:
        return False


def _tratar_ausencia_lideres(engine, script, filtro, args, arquivo_log) -> None:
    """Registra a oportunidade parametrizada e ignora o componente de lideranca
    sem lancar o subprocesso (evita o erro tecnico do caso sem lideres)."""

    os.environ["PDOH_COMPONENTE"] = "LIDERES"
    regra = resolver_tratativa(engine, "SEM_LIDERES_NO_PERIODO")
    registrar_achado(
        engine,
        [
            {
                "tipo_problema": "SEM_LIDERES_NO_PERIODO",
                "origem": "INVOLVES_BRACELL",
                "tabela_origem": "colaboradores_ativos_bracell",
                "colaborador": None,
                "descricao_detalhada": (
                    f"Nenhum colaborador de lideranca (filtro '{filtro}') no periodo; "
                    "componente de lideranca ignorado sem gerar registros."
                ),
                "severidade": "BAIXA",
                "regra_id": (regra or {}).get("regra_id"),
                "evidencia": {
                    "script": script,
                    "filtro": filtro,
                    "periodo_inicio": args.data_inicio,
                    "periodo_fim": args.data_fim,
                    "acao_regra": (regra or {}).get("acao_aplicacao"),
                    "permite_processamento": (regra or {}).get("permite_processamento"),
                },
            }
        ],
    )
    registrar_etapa(
        engine,
        etapa="PROCESSAMENTO_PDOH",
        status="IGNORADA",
        mensagem="Componente LIDERES ignorado: sem lideres no periodo (parametrizacao SEM_LIDERES_NO_PERIODO).",
        contexto={"script": script, "filtro": filtro},
    )
    mensagem = (
        f"AVISO: sem lideres no periodo (filtro '{filtro}'); "
        "componente LIDERES ignorado por parametrizacao, processamento continua."
    )
    print(mensagem)
    arquivo_log.write(mensagem + "\n")
    arquivo_log.flush()


class _LogSeguro:
    """Arquivo lateral que degrada para descarte sem afetar os subprocessos."""

    def __init__(self, caminho: Path):
        self.caminho = caminho
        self.erro: Exception | None = None
        self._arquivo = None
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            self._arquivo = caminho.open("a", encoding="utf-8", newline="")
        except Exception as exc:
            self.erro = exc

    @property
    def disponivel(self) -> bool:
        return self._arquivo is not None

    def write(self, conteudo: str) -> None:
        if self._arquivo is None:
            return
        try:
            self._arquivo.write(conteudo)
        except Exception as exc:
            self.erro = exc
            try:
                self._arquivo.close()
            except Exception:
                pass
            self._arquivo = None

    def flush(self) -> None:
        if self._arquivo is None:
            return
        try:
            self._arquivo.flush()
        except Exception as exc:
            self.erro = exc
            try:
                self._arquivo.close()
            except Exception:
                pass
            self._arquivo = None

    def close(self) -> None:
        if self._arquivo is not None:
            try:
                self._arquivo.close()
            except Exception as exc:
                self.erro = exc
            finally:
                self._arquivo = None


def _assinatura_arquivo(caminho: Path) -> tuple[int, int] | None:
    try:
        status = caminho.stat()
        return status.st_mtime_ns, status.st_size
    except Exception:
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
    try:
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
    except Exception as exc:
        mensagem = f"Nao foi possivel iniciar o componente {componente}: {exc}"
        registrar_erro_tecnico(
            engine,
            etapa="PROCESSAMENTO_PDOH",
            mensagem=mensagem,
            excecao=exc,
        )
        arquivo_log.write(f"[ERRO_INICIALIZACAO] {mensagem}\n")
        arquivo_log.flush()
        return 127, mensagem
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


def _periodo_da_execucao(engine, args):
    """Periodo processado: o informado na CLI ou o que os processadores gravaram na execucao."""
    if args.data_inicio and args.data_fim:
        return args.data_inicio, args.data_fim
    with engine.connect() as conexao:
        linha = conexao.execute(
            text("SELECT periodo_inicio, periodo_fim FROM pdoh_controle.execucao WHERE execution_id = :id"),
            {"id": obter_execution_id()},
        ).mappings().first()
    return (linha or {}).get("periodo_inicio"), (linha or {}).get("periodo_fim")


def _executar_regras_configuradas(engine, args, arquivo_log) -> None:
    """Configuracao -> regra ativa -> motor valida -> criterios atendidos -> oportunidade.

    So' as regras cadastradas e ATIVAS geram oportunidade; nenhuma regra de negocio esta no
    codigo (ver ``src/regras_configuradas.py``). Fail-open: uma falha aqui vira evento e a
    esteira segue -- nunca altera calculo, Platina, Gold ou historico.
    """
    os.environ["PDOH_COMPONENTE"] = "REGRAS_CONFIGURADAS"
    try:
        inicio, fim = _periodo_da_execucao(engine, args)
        if not inicio or not fim:
            registrar_evento(
                engine,
                nivel="ALERTA",
                categoria="GOVERNANCA",
                codigo="REGRAS_CONFIGURADAS_SEM_PERIODO",
                mensagem="Regras configuradas nao executadas: a execucao nao tem periodo definido.",
                etapa="REGRAS_CONFIGURADAS",
            )
            return
        try:
            source_engine = criar_engine_origem()
        except Exception as erro:
            # Sem a origem a jornada oficial nao e resolvida: os candidatos ficam INDISPONIVEIS
            # (nunca viram oportunidade) e o motivo fica registrado.
            source_engine = None
            registrar_evento(
                engine,
                nivel="ALERTA",
                categoria="GOVERNANCA",
                codigo="REGRAS_CONFIGURADAS_SEM_ORIGEM",
                mensagem="Origem somente leitura indisponivel para as regras configuradas.",
                etapa="REGRAS_CONFIGURADAS",
                excecao=erro,
            )
        from src.regras_configuradas import executar_regras

        resumo = executar_regras(engine, source_engine, periodo_inicio=inicio, periodo_fim=fim)
        arquivo_log.write(
            "regras_configuradas="
            + json.dumps(
                {k: resumo[k] for k in ("regras", "ignoradas", "sem_executor", "erros")},
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )
    except Exception as erro:
        registrar_evento(
            engine,
            nivel="ERRO",
            categoria="GOVERNANCA",
            codigo="REGRAS_CONFIGURADAS_INDISPONIVEL",
            mensagem="Falha ao executar as regras configuradas; a esteira continua.",
            etapa="REGRAS_CONFIGURADAS",
            excecao=erro,
        )
    finally:
        os.environ["PDOH_COMPONENTE"] = "ORQUESTRADOR"


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
    caminho_log = BASE_DIR / "logs" / f"{execution_id}.log"
    arquivo_log = _LogSeguro(caminho_log)

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
    # Mapeamentos De/Para disponiveis antes dos processadores (fail-open). Catalogo de
    # classificacao (regra_tratativa) nao existe mais como tabela -- shared/treatment_catalog.py.
    bootstrap_de_para(engine)
    registrar_evento(
        engine,
        nivel="INFO",
        categoria="OPERACIONAL",
        codigo="PIPELINE_INICIADO",
        mensagem="Esteira BRACELL iniciada com observabilidade lateral.",
        etapa="INICIALIZACAO",
        contexto={"scripts": scripts, "arquivo_log": str(caminho_log)},
    )
    if arquivo_log.erro:
        registrar_evento(
            engine,
            nivel="ALERTA",
            categoria="OBSERVABILIDADE",
            codigo="ARQUIVO_LOG_INDISPONIVEL",
            mensagem="O arquivo lateral de log nao esta disponivel; banco e console continuam ativos.",
            etapa="INICIALIZACAO",
            contexto={"erro": str(arquivo_log.erro)[:1000]},
        )

    primeiro_codigo_nao_zero = 0
    houve_erro_legado = False
    arquivo_log.write(f"execution_id={execution_id}\n")
    arquivo_log.write(f"scripts={','.join(scripts)}\n")
    arquivo_log.write("status=INICIADA\n")
    for script in scripts:
        # Pre-checagem preventiva (Opcao A): se o componente de lideres nao tem
        # lideres no periodo, registra a oportunidade e ignora o subprocesso em
        # vez de deixa-lo falhar. Nao altera calculo nem resultado da Platina.
        filtro_lider = _criterio_lider(engine, script)
        if filtro_lider and _snapshot_sem_lideres(filtro_lider):
            _tratar_ausencia_lideres(engine, script, filtro_lider, args, arquivo_log)
            continue

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

    os.environ["PDOH_COMPONENTE"] = "ORQUESTRADOR"
    if not primeiro_codigo_nao_zero:
        # Com a esteira interrompida nao ha Platina confiavel para avaliar.
        _executar_regras_configuradas(engine, args, arquivo_log)
    resumo = obter_resumo_execucao(engine)
    if houve_erro_legado or primeiro_codigo_nao_zero or resumo.get("status_execucao") == "FALHA_TECNICA":
        status_final = finalizar_execucao(engine, status="FALHA_TECNICA")
    else:
        status_final = finalizar_execucao(engine)
    arquivo_log.write(f"status_final={status_final}\n")
    arquivo_log.flush()
    arquivo_log.close()

    print(f"EXECUTION_ID={execution_id}")
    print(f"LOG_EXECUCAO={caminho_log if arquivo_log.erro is None else 'INDISPONIVEL'}")
    # O retorno do subprocesso e preservado. Erros engolidos pelo legado ficam
    # corretamente classificados no controle, mas continuam retornando zero.
    return primeiro_codigo_nao_zero


if __name__ == "__main__":
    raise SystemExit(main())
