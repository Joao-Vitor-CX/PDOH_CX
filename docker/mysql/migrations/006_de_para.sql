-- Camada De/Para parametrizada (padronizacao/validacao das informacoes de origem).
-- Idempotente (CREATE IF NOT EXISTS). DDL-only: sem seed (conta de migracao so tem DDL);
-- os mapeamentos iniciais sao semeados pela aplicacao (bootstrap_de_para).
-- Camada shadow: NAO altera calculo nem processadores travados.

CREATE TABLE IF NOT EXISTS pdoh_controle.de_para (
    de_para_id        CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    marca             VARCHAR(80) NULL,
    processo          VARCHAR(80) NOT NULL,
    campo_origem      VARCHAR(120) NOT NULL,
    valor_origem      VARCHAR(350) NOT NULL,
    valor_padronizado VARCHAR(350) NOT NULL,
    descricao         TEXT NULL,
    status            VARCHAR(20) NOT NULL DEFAULT 'ATIVO',
    criado_em         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizado_em     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                      ON UPDATE CURRENT_TIMESTAMP(6),
    responsavel       VARCHAR(120) NULL,
    PRIMARY KEY (de_para_id),
    UNIQUE KEY uk_de_para (marca, processo, campo_origem, valor_origem),
    INDEX idx_de_para_lookup (status, processo, campo_origem, marca)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.de_para_historico (
    id                         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    de_para_id                 CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    acao                       VARCHAR(40) NOT NULL,
    valor_padronizado_anterior VARCHAR(350) NULL,
    valor_padronizado_novo     VARCHAR(350) NULL,
    status_anterior            VARCHAR(20) NULL,
    status_novo                VARCHAR(20) NULL,
    responsavel                VARCHAR(120) NULL,
    observacao                 TEXT NULL,
    registrado_em              DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_de_para_historico FOREIGN KEY (de_para_id)
        REFERENCES pdoh_controle.de_para (de_para_id) ON DELETE RESTRICT,
    INDEX idx_de_para_historico (de_para_id, registrado_em)
) ENGINE=InnoDB;
