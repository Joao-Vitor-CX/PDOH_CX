-- Status operacional do GRUPO de oportunidades (marca + regra + colaborador).
-- O status pertence ao problema operacional, nao a cada linha de evento: resolver
-- uma de 15 linhas nao resolveria o problema do colaborador.
--
-- Tabela lateral e aditiva. NAO altera `oportunidade` nem `oportunidade_historico`,
-- que permanecem como historico imutavel. NAO toca calculo, Platina, Gold, ETL nem
-- processadores.

CREATE TABLE IF NOT EXISTS pdoh_controle.oportunidade_grupo_status (
    grupo_id                VARCHAR(255) NOT NULL,
    marca                   VARCHAR(80)  NOT NULL,
    tipo_problema           VARCHAR(100) NOT NULL,
    colaborador_id_interno  VARCHAR(36)  NULL,
    colaborador             VARCHAR(255) NULL,
    status_operacional      VARCHAR(20)  NOT NULL DEFAULT 'ABERTA',
    responsavel             VARCHAR(160) NULL,
    observacao              TEXT         NULL,
    -- Marco da resolucao: ocorrencia identificada depois disto reabre o grupo.
    resolvido_em            DATETIME(6)  NULL,
    criado_em               DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizado_em           DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (grupo_id),
    KEY idx_grupo_status_fila (marca, status_operacional),
    KEY idx_grupo_status_regra (marca, tipo_problema)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
