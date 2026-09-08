#!/usr/bin/env bash
set -euo pipefail

# 1 - abrindo a copia independente da aplicacao
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 2 - ativando a venv local quando a execucao ocorrer fora do container
VENV_ATIVA=0
if [[ -f venv/bin/activate ]]; then
    source venv/bin/activate
    VENV_ATIVA=1
fi

# 3 - O executor chama os mesmos scripts, na mesma ordem e em subprocessos
# isolados, acrescentando somente rastreabilidade lateral.
echo "[INICIO] Executando esteira BRACELL observada"
python run_observado.py
echo "[FIM] Esteira BRACELL observada concluída"

# 4 - desativando a venv, quando aplicavel
if [[ "$VENV_ATIVA" -eq 1 ]]; then
    deactivate
fi

echo "[SUCESSO] Todos os scripts executados com sucesso!"
