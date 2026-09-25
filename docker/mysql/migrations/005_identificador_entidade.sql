-- Camada de identidade generica para entidades nao-colaborador (PDV, MARCA).
-- Colaborador continua em pdoh_controle.colaborador_identidade/colaborador_alias.
-- Idempotente (CREATE IF NOT EXISTS). DDL-only: sem seed (conta de migracao so tem DDL);
-- os identificadores sao gerados pela aplicacao (conta com INSERT) durante o processamento.

CREATE TABLE IF NOT EXISTS pdoh_controle.identificador_entidade (
    identificador_id       CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    tipo_entidade          VARCHAR(20) NOT NULL,
    identificador_interno  CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    chave_identidade       VARCHAR(350) NOT NULL,
    nome_original          VARCHAR(255) COLLATE utf8mb4_0900_as_cs NULL,
    nome_normalizado       VARCHAR(255) NULL,
    origem_dado            VARCHAR(80) NOT NULL,
    marca                  VARCHAR(80) NOT NULL,
    primeira_execucao_id   VARCHAR(80) NOT NULL,
    ultima_execucao_id     VARCHAR(80) NOT NULL,
    quantidade_observacoes BIGINT UNSIGNED NOT NULL DEFAULT 1,
    data_criacao           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    data_atualizacao       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                           ON UPDATE CURRENT_TIMESTAMP(6),
    status                 VARCHAR(20) NOT NULL DEFAULT 'ATIVO',
    PRIMARY KEY (identificador_id),
    UNIQUE KEY uk_entidade_marca_tipo_chave (marca, tipo_entidade, chave_identidade),
    INDEX idx_entidade_tipo (tipo_entidade, marca),
    INDEX idx_entidade_nome (tipo_entidade, marca, nome_normalizado)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.identificador_entidade_alias (
    id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    identificador_id       CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    tipo_entidade          VARCHAR(20) NOT NULL,
    marca                  VARCHAR(80) NOT NULL,
    nome_original          VARCHAR(255) COLLATE utf8mb4_0900_as_cs NOT NULL,
    nome_normalizado       VARCHAR(255) NOT NULL,
    origem                 VARCHAR(80) NOT NULL,
    tabela_origem          VARCHAR(160) NOT NULL,
    primeira_execucao_id   VARCHAR(80) NOT NULL,
    ultima_execucao_id     VARCHAR(80) NOT NULL,
    quantidade_observacoes BIGINT UNSIGNED NOT NULL DEFAULT 1,
    primeira_observacao_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ultima_observacao_em   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_entidade_alias_identificador FOREIGN KEY (identificador_id)
        REFERENCES pdoh_controle.identificador_entidade (identificador_id) ON DELETE RESTRICT,
    UNIQUE KEY uk_entidade_alias (identificador_id, nome_original, tabela_origem),
    INDEX idx_entidade_alias_nome (marca, tipo_entidade, nome_normalizado)
) ENGINE=InnoDB;
