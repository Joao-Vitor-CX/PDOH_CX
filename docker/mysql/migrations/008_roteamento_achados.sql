-- Expansao aditiva, sem UPDATE/DELETE/backfill/rename ou alteracao do catalogo.
CREATE TABLE IF NOT EXISTS pdoh_controle.alerta (
    alerta_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    execution_id VARCHAR(80) NOT NULL,
    regra_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    marca VARCHAR(80) NOT NULL,
    tipo_problema VARCHAR(100) NOT NULL,
    data_referencia DATE NULL,
    origem VARCHAR(80) NOT NULL,
    tabela_origem VARCHAR(160) NOT NULL,
    colaborador VARCHAR(255) COLLATE utf8mb4_0900_as_cs NULL,
    colaborador_id_interno CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    campo VARCHAR(120) NULL,
    descricao_detalhada TEXT NOT NULL,
    severidade VARCHAR(20) NOT NULL,
    status_alerta VARCHAR(30) NOT NULL DEFAULT 'ABERTA',
    tratativa TEXT NULL,
    evidencia JSON NULL,
    fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    identificada_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizada_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_alerta_execucao FOREIGN KEY (execution_id) REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    CONSTRAINT fk_alerta_regra FOREIGN KEY (regra_id) REFERENCES pdoh_controle.regra_tratativa (regra_id) ON DELETE RESTRICT,
    UNIQUE KEY uk_alerta_execucao_fingerprint (execution_id, fingerprint),
    KEY idx_alerta_marca_fila (marca, status_alerta, identificada_em),
    KEY idx_alerta_colaborador (marca, colaborador_id_interno, campo)
) ENGINE=InnoDB;

-- Registro de decisao para novos achados. Nao duplica/migra evidencias antigas.
-- Preserva classificacao original e idempotencia mesmo se o catalogo mudar.
CREATE TABLE IF NOT EXISTS pdoh_controle.achado_roteamento (
    achado_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
    execution_id VARCHAR(80) NOT NULL,
    marca VARCHAR(80) NOT NULL,
    tipo_problema VARCHAR(100) NOT NULL,
    fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    regra_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    classificacao VARCHAR(20) NOT NULL,
    destino VARCHAR(30) NOT NULL,
    registro_id VARCHAR(80) NOT NULL,
    regra_snapshot JSON NOT NULL,
    registrado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_roteamento_execucao FOREIGN KEY (execution_id) REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    CONSTRAINT fk_roteamento_regra FOREIGN KEY (regra_id) REFERENCES pdoh_controle.regra_tratativa (regra_id) ON DELETE RESTRICT,
    CONSTRAINT ck_roteamento_destino CHECK (
        (classificacao='OPORTUNIDADE' AND destino='oportunidade') OR
        (classificacao='ALERTA' AND destino='alerta') OR
        (classificacao='TELEMETRIA' AND destino='execucao_evento')),
    UNIQUE KEY uk_roteamento_achado (execution_id, marca, fingerprint),
    UNIQUE KEY uk_roteamento_destino (destino, registro_id),
    KEY idx_roteamento_marca_classe (marca, classificacao, registrado_em)
) ENGINE=InnoDB;
