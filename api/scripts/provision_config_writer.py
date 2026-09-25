"""Provisionamento local explicito da conta de EDICAO de regras. Nunca roda ao iniciar a API nem no CD.

    api/.venv311/Scripts/python.exe api/scripts/provision_config_writer.py

A API de consulta continua somente leitura (`pdoh_cx_reader`). Esta conta existe apenas para
criar e editar regras (POST/PATCH /api/v2/configuracoes/regras) e recebe o MINIMO:

  * SELECT + INSERT nas tres tabelas de regra (INSERT so' serve para cadastrar oportunidade nova;
    UPDATE fica restrito as colunas que a tela edita, `rule_admin.COLUNAS_EDITAVEIS`);
  * INSERT na tabela de historico.

Nao apaga, nao troca codigo depois de criado, nao mexe em marca/fonte/catalogo, nao alcanca
oportunidades, Platina, Gold, ETL nem a origem. A API recusa a partida da edicao se a conta tiver
qualquer privilegio a mais ou a menos (`validate_writer_grants`).

Reexecutar este script e' seguro: as concessoes sao reaplicadas sempre (GRANT e' idempotente), so' a
senha e' preservada quando ja existe em api/.env.api. E' assim que uma conta ja provisionada ganha um
privilegio novo (como o INSERT desta versao) sem precisar recriar a conta.

A senha e' gerada aqui, gravada apenas em api/.env.api (ignorado pelo Git, o mesmo arquivo da conta de
leitura) e nunca impressa. Reverter: `DROP USER 'pdoh_cx_config'@'%'` e remover as duas linhas.
"""
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from api.app.rule_admin import COLUNAS_EDITAVEIS, HISTORICO, validate_writer_grants

USUARIO = 'pdoh_cx_config'
CHAVE_USUARIO, CHAVE_SENHA = 'PDOH_API_CONFIG_DB_USER', 'PDOH_API_CONFIG_DB_PASSWORD'


def mysql(sql):
    resultado = subprocess.run(
        ['docker', 'exec', '-i', 'pdoh_cx_mysql', 'sh', '-c',
         'export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"; exec mysql -uroot --batch --skip-column-names'],
        input=sql, text=True, capture_output=True, encoding='utf-8', timeout=30)
    if resultado.returncode:
        # O erro original pode incluir SQL com a senha; nunca o imprime.
        raise RuntimeError('Provisionamento falhou. Confira acesso administrativo ao Docker/MySQL.')
    return resultado.stdout.strip()


def concessoes():
    linhas = [f"GRANT SELECT, INSERT, UPDATE ({', '.join(colunas)}) ON pdoh_controle.{tabela} "
              f"TO '{USUARIO}'@'%';" for tabela, colunas in COLUNAS_EDITAVEIS.items()]
    linhas.append(f"GRANT INSERT ON pdoh_controle.{HISTORICO} TO '{USUARIO}'@'%';")
    linhas.append(f"GRANT SELECT ON pdoh_controle.jornada_consolidada TO '{USUARIO}'@'%';")
    return '\n'.join(linhas) + '\n'


def verificar():
    grants = [linha for linha in mysql(f"SHOW GRANTS FOR '{USUARIO}'@'%';").splitlines() if linha.strip()]
    validate_writer_grants(grants)


def main():
    destino = ROOT / '.env.api'
    if not destino.exists():
        raise RuntimeError('api/.env.api nao existe. Execute antes api/scripts/provision_reader.py.')
    atual = destino.read_text(encoding='utf-8')
    senha = None
    if CHAVE_SENHA not in atual:
        senha = secrets.token_urlsafe(36)
        existe = mysql(f"SELECT COUNT(*) FROM mysql.user WHERE User='{USUARIO}';") != '0'
        # Conta dedicada: se existe sem credencial gravada, a senha e' apenas redefinida.
        mysql((f"ALTER USER '{USUARIO}'@'%' IDENTIFIED BY '{senha}';\n" if existe
               else f"CREATE USER '{USUARIO}'@'%' IDENTIFIED BY '{senha}';\n"))
    mysql(concessoes() + 'FLUSH PRIVILEGES;\n')       # idempotente: reaplica mesmo em conta ja existente
    verificar()
    if senha:
        with destino.open('a', encoding='utf-8') as arquivo:
            arquivo.write(('' if atual.endswith('\n') else '\n') + f'{CHAVE_USUARIO}={USUARIO}\n{CHAVE_SENHA}={senha}\n')
        print(f'Conta {USUARIO} criada e credenciais gravadas em api/.env.api (ignorado pelo Git).')
    else:
        print(f'Conta {USUARIO} ja configurada; privilegios reaplicados e verificados (SELECT/INSERT/UPDATE '
              'nas regras, INSERT no historico).')
    print('Reinicie a API para habilitar a criacao/edicao de regras.')


if __name__ == '__main__':
    main()
