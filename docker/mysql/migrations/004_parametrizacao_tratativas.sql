-- Camada de parametrizacao de tratativas de inconsistencias (PDOH_CX).
-- Idempotente: o runner reaplica todas as migracoes a cada execucao.
-- Executada pela conta de migracao (somente DDL). O seed de regras e feito
-- pela aplicacao (bootstrap_regras), pois a conta de migracao nao tem INSERT.

CREATE TABLE IF NOT EXISTS pdoh_controle.regra_tratativa (
    regra_id              CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    marca                 VARCHAR(80) NULL,
    tipo_problema         VARCHAR(100) NOT NULL,
    descricao_cenario     TEXT NOT NULL,
    regra_identificacao   TEXT NOT NULL,
    tratamento_esperado   TEXT NOT NULL,
    acao_aplicacao        VARCHAR(40) NOT NULL,
    permite_processamento TINYINT(1) NOT NULL DEFAULT 1,
    necessita_aprovacao   TINYINT(1) NOT NULL DEFAULT 0,
    prioridade            SMALLINT UNSIGNED NOT NULL DEFAULT 100,
    status_regra          VARCHAR(20) NOT NULL DEFAULT 'ATIVA',
    criada_em             DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizada_em         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                          ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (regra_id),
    UNIQUE KEY uk_regra_marca_tipo (marca, tipo_problema),
    INDEX idx_regra_ativa (status_regra, marca, tipo_problema, prioridade)
) ENGINE=InnoDB;

-- (aditivo) oportunidade.regra_id: qual regra tratou a ocorrencia.
SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.oportunidade ADD COLUMN regra_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER tipo_problema',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'oportunidade' AND COLUMN_NAME = 'regra_id');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- FK oportunidade.regra_id -> regra_tratativa (ON DELETE SET NULL: nao apaga historico).
SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.oportunidade ADD CONSTRAINT fk_oportunidade_regra FOREIGN KEY (regra_id) REFERENCES pdoh_controle.regra_tratativa (regra_id) ON DELETE SET NULL',
    'DO 0')
    FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'oportunidade' AND CONSTRAINT_NAME = 'fk_oportunidade_regra');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.oportunidade ADD INDEX idx_oportunidade_regra (regra_id)',
    'DO 0')
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'oportunidade' AND INDEX_NAME = 'idx_oportunidade_regra');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- (aditivo) oportunidade_historico.responsavel: responsavel pela tratativa.
SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.oportunidade_historico ADD COLUMN responsavel VARCHAR(120) NULL AFTER observacao',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'oportunidade_historico' AND COLUMN_NAME = 'responsavel');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
