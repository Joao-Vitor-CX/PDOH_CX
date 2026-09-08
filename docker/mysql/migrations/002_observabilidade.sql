CREATE DATABASE IF NOT EXISTS pdoh_controle
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'pdoh_cx_app'@'%' IDENTIFIED BY 'pdoh_cx_dev';
GRANT SELECT, INSERT, UPDATE ON pdoh_controle.* TO 'pdoh_cx_app'@'%';

CREATE TABLE IF NOT EXISTS pdoh_controle.execucao (
    execution_id VARCHAR(80) NOT NULL,
    marca VARCHAR(80) NOT NULL,
    periodo_inicio DATE NULL,
    periodo_fim DATE NULL,
    status_execucao VARCHAR(40) NOT NULL,
    componente_atual VARCHAR(80) NULL,
    etapa_atual VARCHAR(80) NULL,
    iniciado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    finalizado_em DATETIME(6) NULL,
    linhas_recebidas BIGINT UNSIGNED NOT NULL DEFAULT 0,
    linhas_tratadas BIGINT UNSIGNED NOT NULL DEFAULT 0,
    linhas_geradas BIGINT UNSIGNED NOT NULL DEFAULT 0,
    linhas_persistidas BIGINT UNSIGNED NOT NULL DEFAULT 0,
    total_alertas BIGINT UNSIGNED NOT NULL DEFAULT 0,
    total_fallbacks BIGINT UNSIGNED NOT NULL DEFAULT 0,
    houve_persistencia TINYINT(1) NOT NULL DEFAULT 0,
    erro_resumo TEXT NULL,
    versao_aplicacao VARCHAR(80) NULL,
    atualizado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (execution_id),
    INDEX idx_execucao_marca_periodo (marca, periodo_inicio, periodo_fim),
    INDEX idx_execucao_status_inicio (status_execucao, iniciado_em)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.execucao_etapa (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    execution_id VARCHAR(80) NOT NULL,
    componente VARCHAR(80) NOT NULL,
    etapa VARCHAR(80) NOT NULL,
    status_etapa VARCHAR(40) NOT NULL,
    origem VARCHAR(80) NULL,
    tabela_origem VARCHAR(160) NULL,
    linhas_recebidas BIGINT UNSIGNED NULL,
    linhas_tratadas BIGINT UNSIGNED NULL,
    linhas_geradas BIGINT UNSIGNED NULL,
    linhas_persistidas BIGINT UNSIGNED NULL,
    mensagem TEXT NULL,
    contexto JSON NULL,
    ocorrido_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_etapa_execucao FOREIGN KEY (execution_id)
        REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    INDEX idx_etapa_execucao_data (execution_id, ocorrido_em),
    INDEX idx_etapa_nome_status (etapa, status_etapa)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.execucao_fonte (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    execution_id VARCHAR(80) NOT NULL,
    componente VARCHAR(80) NOT NULL,
    schema_origem VARCHAR(80) NOT NULL,
    tabela_origem VARCHAR(160) NOT NULL,
    filtro_periodo_inicio DATE NULL,
    filtro_periodo_fim DATE NULL,
    linhas_recebidas BIGINT UNSIGNED NOT NULL DEFAULT 0,
    linhas_apos_tratamento BIGINT UNSIGNED NOT NULL DEFAULT 0,
    duplicatas_identificadas BIGINT UNSIGNED NOT NULL DEFAULT 0,
    query_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    registrado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_fonte_execucao FOREIGN KEY (execution_id)
        REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    INDEX idx_fonte_execucao_tabela (execution_id, tabela_origem)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.execucao_evento (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    execution_id VARCHAR(80) NOT NULL,
    componente VARCHAR(80) NOT NULL,
    etapa VARCHAR(80) NULL,
    nivel VARCHAR(20) NOT NULL,
    categoria VARCHAR(50) NOT NULL,
    codigo VARCHAR(100) NOT NULL,
    mensagem TEXT NOT NULL,
    excecao_tipo VARCHAR(255) NULL,
    contexto JSON NULL,
    ocorrido_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_evento_execucao FOREIGN KEY (execution_id)
        REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    INDEX idx_evento_execucao_data (execution_id, ocorrido_em),
    INDEX idx_evento_nivel_codigo (nivel, codigo)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.fallback_evento (
    fallback_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    execution_id VARCHAR(80) NOT NULL,
    componente VARCHAR(80) NOT NULL,
    etapa VARCHAR(80) NOT NULL,
    codigo VARCHAR(100) NOT NULL,
    motivo TEXT NOT NULL,
    impacto_esperado TEXT NULL,
    severidade VARCHAR(20) NOT NULL,
    contexto JSON NULL,
    ocorrido_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (fallback_id),
    CONSTRAINT fk_fallback_execucao FOREIGN KEY (execution_id)
        REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    INDEX idx_fallback_execucao_data (execution_id, ocorrido_em),
    INDEX idx_fallback_codigo (codigo)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.colaborador_identidade (
    colaborador_id_interno CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    marca VARCHAR(80) NOT NULL,
    chave_identidade VARCHAR(350) NOT NULL,
    usuario_referencia VARCHAR(255) NULL,
    nome_referencia VARCHAR(255) NULL,
    nome_normalizado VARCHAR(255) NULL,
    primeira_execucao_id VARCHAR(80) NOT NULL,
    ultima_execucao_id VARCHAR(80) NOT NULL,
    primeira_observacao_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ultima_observacao_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    quantidade_observacoes BIGINT UNSIGNED NOT NULL DEFAULT 1,
    PRIMARY KEY (colaborador_id_interno),
    UNIQUE KEY uk_identidade_marca_chave (marca, chave_identidade),
    INDEX idx_identidade_nome (marca, nome_normalizado)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.colaborador_alias (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    colaborador_id_interno CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    marca VARCHAR(80) NOT NULL,
    nome_original VARCHAR(255) COLLATE utf8mb4_0900_as_cs NOT NULL,
    nome_normalizado VARCHAR(255) NOT NULL,
    origem VARCHAR(80) NOT NULL,
    tabela_origem VARCHAR(160) NOT NULL,
    primeira_execucao_id VARCHAR(80) NOT NULL,
    ultima_execucao_id VARCHAR(80) NOT NULL,
    primeira_observacao_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ultima_observacao_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    quantidade_observacoes BIGINT UNSIGNED NOT NULL DEFAULT 1,
    PRIMARY KEY (id),
    CONSTRAINT fk_alias_identidade FOREIGN KEY (colaborador_id_interno)
        REFERENCES pdoh_controle.colaborador_identidade (colaborador_id_interno)
        ON DELETE RESTRICT,
    UNIQUE KEY uk_alias_identidade_origem (
        colaborador_id_interno, nome_original, tabela_origem
    ),
    INDEX idx_alias_nome (marca, nome_normalizado)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.oportunidade (
    oportunidade_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    execution_id VARCHAR(80) NOT NULL,
    marca VARCHAR(80) NOT NULL,
    data_referencia DATE NULL,
    origem VARCHAR(80) NOT NULL,
    tabela_origem VARCHAR(160) NOT NULL,
    colaborador VARCHAR(255) COLLATE utf8mb4_0900_as_cs NULL,
    colaborador_id_interno CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    tipo_problema VARCHAR(100) NOT NULL,
    descricao_detalhada TEXT NOT NULL,
    severidade VARCHAR(20) NOT NULL,
    status_oportunidade VARCHAR(30) NOT NULL DEFAULT 'ABERTA',
    fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    evidencia JSON NULL,
    identificada_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizada_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (oportunidade_id),
    CONSTRAINT fk_oportunidade_execucao FOREIGN KEY (execution_id)
        REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    UNIQUE KEY uk_oportunidade_execucao_fingerprint (execution_id, fingerprint),
    INDEX idx_oportunidade_fila (status_oportunidade, severidade, identificada_em),
    INDEX idx_oportunidade_colaborador (marca, colaborador)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.oportunidade_historico (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    oportunidade_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    execution_id VARCHAR(80) NOT NULL,
    status_anterior VARCHAR(30) NULL,
    status_novo VARCHAR(30) NOT NULL,
    acao VARCHAR(80) NOT NULL,
    observacao TEXT NULL,
    contexto JSON NULL,
    registrado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_historico_oportunidade FOREIGN KEY (oportunidade_id)
        REFERENCES pdoh_controle.oportunidade (oportunidade_id) ON DELETE RESTRICT,
    CONSTRAINT fk_historico_execucao FOREIGN KEY (execution_id)
        REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    INDEX idx_historico_oportunidade_data (oportunidade_id, registrado_em)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.notificacao_outbox (
    notificacao_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    execution_id VARCHAR(80) NOT NULL,
    oportunidade_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    fallback_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    tipo_notificacao VARCHAR(80) NOT NULL,
    canal VARCHAR(50) NULL,
    destinatario VARCHAR(255) NULL,
    prioridade TINYINT UNSIGNED NOT NULL DEFAULT 5,
    status_notificacao VARCHAR(30) NOT NULL DEFAULT 'PENDENTE',
    dedupe_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    payload JSON NOT NULL,
    tentativas INT UNSIGNED NOT NULL DEFAULT 0,
    disponivel_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    enviado_em DATETIME(6) NULL,
    ultimo_erro TEXT NULL,
    criado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (notificacao_id),
    UNIQUE KEY uk_notificacao_dedupe (dedupe_key),
    CONSTRAINT fk_notificacao_execucao FOREIGN KEY (execution_id)
        REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    CONSTRAINT fk_notificacao_oportunidade FOREIGN KEY (oportunidade_id)
        REFERENCES pdoh_controle.oportunidade (oportunidade_id) ON DELETE RESTRICT,
    CONSTRAINT fk_notificacao_fallback FOREIGN KEY (fallback_id)
        REFERENCES pdoh_controle.fallback_evento (fallback_id) ON DELETE RESTRICT,
    CONSTRAINT ck_notificacao_referencia CHECK (
        oportunidade_id IS NOT NULL OR fallback_id IS NOT NULL
    ),
    INDEX idx_notificacao_fila (status_notificacao, disponivel_em, prioridade, notificacao_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS pdoh_controle.saida_linhagem (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    execution_id VARCHAR(80) NOT NULL,
    marca VARCHAR(80) NOT NULL,
    tabela_destino VARCHAR(200) NOT NULL,
    colaborador VARCHAR(255) NULL,
    data_referencia DATE NULL,
    chave_negocio_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    linha_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    acao VARCHAR(40) NOT NULL,
    registrado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    CONSTRAINT fk_linhagem_execucao FOREIGN KEY (execution_id)
        REFERENCES pdoh_controle.execucao (execution_id) ON DELETE RESTRICT,
    UNIQUE KEY uk_linhagem_execucao_chave (execution_id, chave_negocio_hash),
    INDEX idx_linhagem_chave (chave_negocio_hash),
    INDEX idx_linhagem_colaborador_data (colaborador, data_referencia)
) ENGINE=InnoDB;

FLUSH PRIVILEGES;
