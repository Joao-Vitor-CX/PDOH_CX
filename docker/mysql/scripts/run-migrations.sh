#!/bin/sh
set -eu

# Credenciais chegam somente pelo ambiente do container. O conjunto restrito
# de caracteres evita injecao na criacao e na rotacao das contas locais.
validar_identificador() {
    nome="$1"
    valor="$2"
    case "$valor" in
        ""|*[!A-Za-z0-9_]*)
            echo "Configuracao invalida para $nome." >&2
            exit 2
            ;;
    esac
}

validar_segredo() {
    nome="$1"
    valor="$2"
    if [ "${#valor}" -lt 20 ]; then
        echo "Configuracao invalida para $nome: use pelo menos 20 caracteres." >&2
        exit 2
    fi
    case "$valor" in
        *[!A-Za-z0-9_+-]*)
            echo "Configuracao invalida para $nome: caracteres nao autorizados." >&2
            exit 2
            ;;
    esac
}

validar_identificador PDOH_DB_USER "$PDOH_DB_USER"
validar_identificador PDOH_MIGRATION_USER "$PDOH_MIGRATION_USER"
validar_segredo MYSQL_ROOT_PASSWORD "$MYSQL_ROOT_PASSWORD"
validar_segredo PDOH_DB_PASSWORD "$PDOH_DB_PASSWORD"
validar_segredo PDOH_MIGRATION_PASSWORD "$PDOH_MIGRATION_PASSWORD"

# A conta administrativa e usada somente para criar/rotacionar as duas contas
# locais e reaplicar seus limites de privilegio.
MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql \
    -h mysql -uroot --default-character-set=utf8mb4 <<SQL
CREATE USER IF NOT EXISTS '$PDOH_DB_USER'@'%' IDENTIFIED BY '$PDOH_DB_PASSWORD';
ALTER USER '$PDOH_DB_USER'@'%' IDENTIFIED BY '$PDOH_DB_PASSWORD';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM '$PDOH_DB_USER'@'%';
GRANT SELECT ON involves_bracell.* TO '$PDOH_DB_USER'@'%';
GRANT SELECT, INSERT, UPDATE ON produtos_platina.* TO '$PDOH_DB_USER'@'%';
GRANT SELECT, INSERT, UPDATE ON pdoh_controle.* TO '$PDOH_DB_USER'@'%';

CREATE USER IF NOT EXISTS '$PDOH_MIGRATION_USER'@'%' IDENTIFIED BY '$PDOH_MIGRATION_PASSWORD';
ALTER USER '$PDOH_MIGRATION_USER'@'%' IDENTIFIED BY '$PDOH_MIGRATION_PASSWORD';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM '$PDOH_MIGRATION_USER'@'%';
GRANT CREATE, ALTER, DROP, INDEX, REFERENCES ON produtos_platina.* TO '$PDOH_MIGRATION_USER'@'%';
GRANT CREATE, ALTER, DROP, INDEX, REFERENCES, CREATE VIEW, SHOW VIEW, SELECT ON pdoh_controle.* TO '$PDOH_MIGRATION_USER'@'%';
FLUSH PRIVILEGES;
SQL

# As migracoes DDL executam com a conta propria de menor privilegio.
for migration in /migrations/*.sql; do
    MYSQL_PWD="$PDOH_MIGRATION_PASSWORD" mysql \
        -h mysql -u"$PDOH_MIGRATION_USER" --default-character-set=utf8mb4 \
        < "$migration"
done
