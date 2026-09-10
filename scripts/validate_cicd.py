"""Valida as travas de isolamento da esteira sem conectar a qualquer banco."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORIO_PROIBIDO = re.compile(r"(?i)(?:/|:)PDOH_EXCLUSIVO(?:\.git)?$")
REPOSITORIO_ESPERADO = re.compile(r"(?i)(?:/|:)PDOH_CX(?:\.git)?$")


def _ler(relativo: str) -> str:
    return (ROOT / relativo).read_text(encoding="utf-8")


def _arquivos_versionados() -> set[str]:
    resultado = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return {
        item.decode("utf-8").replace("\\", "/")
        for item in resultado.stdout.split(b"\0")
        if item
    }


def _validar_manifesto(erros: list[str]) -> None:
    manifesto = json.loads(_ler("manifesto_replicacao.json"))
    for relativo, esperado in manifesto["arquivos"].items():
        caminho = ROOT / relativo
        atual = hashlib.sha256(caminho.read_bytes()).hexdigest()
        if atual != esperado:
            erros.append(f"Arquivo protegido foi alterado: {relativo}")


def _validar_segredos(erros: list[str]) -> None:
    versionados = _arquivos_versionados()
    proibidos = {
        nome
        for nome in versionados
        if Path(nome).name == ".env"
        or (Path(nome).suffix.lower() in {".pem", ".key"})
        or Path(nome).name.startswith("SECRETS-")
        or Path(nome).name.endswith("-HANDOFF.env")
    }
    if proibidos:
        erros.append("Arquivos sensiveis versionados: " + ", ".join(sorted(proibidos)))

    exemplo = _ler(".env.example")
    for linha in exemplo.splitlines():
        if "PASSWORD=" not in linha or linha.lstrip().startswith("#"):
            continue
        valor = linha.split("=", 1)[1].strip()
        if valor and not valor.startswith("CHANGE_ME"):
            erros.append(".env.example contem valor de senha que nao e placeholder.")


def _validar_workflows(erros: list[str]) -> None:
    ci = _ler(".github/workflows/ci.yml")
    cd = _ler(".github/workflows/cd.yml")
    deploy = _ler("scripts/deploy-local.ps1")

    requisitos_ci = (
        "pull_request:",
        "branches: [main]",
        "python -m unittest discover -s tests -v",
        "docker compose --profile pipeline config --quiet",
        "docker build --tag pdoh_cx:ci .",
    )
    for requisito in requisitos_ci:
        if requisito not in ci:
            erros.append(f"CI sem requisito obrigatorio: {requisito}")
    if re.search(r"(?m)^\s{2}push:\s*$", ci):
        erros.append("CI deve executar em Pull Request, nao em push direto.")

    requisitos_cd = (
        "push:",
        "workflow_dispatch:",
        "runs-on: [self-hosted, Windows, pdoh-cx-local]",
        "PDOH_CX_ALLOWED_REPOSITORY",
        "Exigir PR com CI aprovado",
        "./scripts/deploy-local.ps1",
    )
    for requisito in requisitos_cd:
        if requisito not in cd:
            erros.append(f"CD sem requisito obrigatorio: {requisito}")

    comandos_proibidos = (
        r"docker\s+compose\s+down",
        r"docker\s+(?:volume|system)\s+prune",
        r"docker\s+compose.*--profile\s+pipeline.*(?:run|up)",
        r"docker\s+compose.*\b(?:run|up)\b.*\b(?:mysql|migrate|pipeline)\b",
    )
    for padrao in comandos_proibidos:
        if re.search(padrao, deploy, flags=re.IGNORECASE):
            erros.append(f"Deploy contem comando proibido: {padrao}")

    if "--no-deps" not in deploy or "backend" not in deploy:
        erros.append("Deploy deve recriar somente o backend com --no-deps.")
    if "snapshotAntes" not in deploy or "snapshotDepois" not in deploy:
        erros.append("Deploy deve comparar snapshots de leitura antes e depois.")


def _validar_isolamento(erros: list[str]) -> None:
    compose = _ler("docker-compose.yml")
    database = _ler("bracell/src/database.py")
    if '127.0.0.1:${PDOH_MYSQL_PORT:-3307}:3306' not in compose:
        erros.append("MySQL nao esta limitado a 127.0.0.1.")
    if "internal: true" not in compose:
        erros.append("Rede Docker nao esta marcada como interna.")
    if "USER 10001:10001" not in _ler("Dockerfile"):
        erros.append("Imagem do backend nao declara usuario nao-root.")
    if '{"mysql", "localhost", "127.0.0.1"}' not in database:
        erros.append("Allowlist de hosts locais nao foi localizada.")


def _validar_remote(erros: list[str]) -> str | None:
    resultado = subprocess.run(
        ["git", "remote", "get-url", "--push", "origin"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    remote = resultado.stdout.strip()
    if resultado.returncode != 0 or not remote:
        erros.append("Remote origin de push nao esta configurado.")
        return None
    if REPOSITORIO_PROIBIDO.search(remote):
        erros.append("Remote origin aponta para PDOH_EXCLUSIVO; push e deploy recusados.")
    elif not REPOSITORIO_ESPERADO.search(remote):
        erros.append("Remote origin nao aponta para um repositorio chamado PDOH_CX.")
    return remote


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-remote", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    erros: list[str] = []
    _validar_manifesto(erros)
    _validar_segredos(erros)
    _validar_workflows(erros)
    _validar_isolamento(erros)
    remote = _validar_remote(erros) if args.check_remote else None

    relatorio = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "APROVADO" if not erros else "REPROVADO",
        "escopo": "validacao estatica sem conexao com banco",
        "carga_executada": False,
        "migracao_executada": False,
        "pipeline_executado": False,
        "remote_push": remote,
        "erros": erros,
    }
    if args.output:
        destino = args.output if args.output.is_absolute() else ROOT / args.output
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(relatorio, ensure_ascii=False, sort_keys=True))
    return 0 if not erros else 1


if __name__ == "__main__":
    raise SystemExit(main())
