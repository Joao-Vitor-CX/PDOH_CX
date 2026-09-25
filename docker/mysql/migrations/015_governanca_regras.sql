-- Camada de governanca operacional. Estrutura shadow: nenhuma tabela deste arquivo
-- participa do calculo PDOH ou da geracao atual de oportunidades.
--
-- Os valores iniciais sao cadastrados por scripts/apply_governance_config.py usando a
-- conta operacional. A conta de migracao permanece restrita a DDL.

CREATE TABLE IF NOT EXISTS pdoh_controle.regra_configuracao (
    configuracao_id          CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    marca                    VARCHAR(80)  NOT NULL,
    operacao                 VARCHAR(80)  NOT NULL,
    nome_regra               VARCHAR(160) NOT NULL,
    codigo_interno           VARCHAR(100) NOT NULL,
    categoria                VARCHAR(80)  NOT NULL,
    status                   VARCHAR(30)  NOT NULL DEFAULT 'EM_VALIDACAO',
    prioridade               SMALLINT UNSIGNED NOT NULL DEFAULT 100,
    descricao                TEXT NOT NULL,
    comportamento_esperado   TEXT NOT NULL,
    regra_catalogo_id        CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
    geracao_automatica_ativa TINYINT(1) NOT NULL DEFAULT 0,
    usuario_alteracao        VARCHAR(160) NOT NULL,
    criada_em                DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizada_em            DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (configuracao_id),
    UNIQUE KEY uk_regra_config_escopo (marca, operacao, codigo_interno),
    KEY ix_regra_config_consulta (marca, operacao, status, prioridade),
    CONSTRAINT fk_regra_config_catalogo FOREIGN KEY (regra_catalogo_id)
        REFERENCES pdoh_controle.regra_tratativa (regra_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Regras em governanca, nao ativa o motor nem cria oportunidades';

CREATE TABLE IF NOT EXISTS pdoh_controle.regra_condicao_configuracao (
    condicao_id       CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    configuracao_id   CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    tipo              VARCHAR(20)  NOT NULL,
    ordem             SMALLINT UNSIGNED NOT NULL,
    papel_fonte       VARCHAR(40)  NOT NULL,
    campo_logico      VARCHAR(160) NOT NULL,
    operador          VARCHAR(30)  NOT NULL,
    valor_esperado    JSON NULL,
    descricao         VARCHAR(500) NOT NULL,
    status            VARCHAR(20)  NOT NULL DEFAULT 'ATIVA',
    usuario_alteracao VARCHAR(160) NOT NULL,
    criada_em         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizada_em     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                          ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (condicao_id),
    UNIQUE KEY uk_regra_condicao_ordem (configuracao_id, tipo, ordem),
    KEY ix_regra_condicao_papel (papel_fonte, campo_logico),
    CONSTRAINT fk_regra_condicao_config FOREIGN KEY (configuracao_id)
        REFERENCES pdoh_controle.regra_configuracao (configuracao_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Condicoes, excecoes e bloqueios declarativos por papel semantico';

CREATE TABLE IF NOT EXISTS pdoh_controle.fonte_semantica_configuracao (
    fonte_id           CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    marca              VARCHAR(80)  NOT NULL,
    operacao           VARCHAR(80)  NOT NULL,
    papel              VARCHAR(40)  NOT NULL,
    tipo               VARCHAR(20)  NOT NULL,
    prioridade         SMALLINT UNSIGNED NOT NULL,
    schema_fisico      VARCHAR(160) NULL,
    tabela_fisica      VARCHAR(160) NULL,
    mapeamento_campos  JSON NOT NULL,
    status             VARCHAR(30)  NOT NULL,
    descricao          VARCHAR(500) NULL,
    usuario_alteracao  VARCHAR(160) NOT NULL,
    criada_em          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizada_em      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                           ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (fonte_id),
    UNIQUE KEY uk_fonte_semantica (marca, operacao, papel, prioridade),
    KEY ix_fonte_semantica_consulta (marca, operacao, status, papel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Resolve papeis estaveis para fontes fisicas por marca e operacao';

CREATE TABLE IF NOT EXISTS pdoh_controle.regra_tratamento_configuracao (
    tratamento_id      CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    configuracao_id    CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    resultado          VARCHAR(30)  NOT NULL,
    acao_recomendada   VARCHAR(500) NOT NULL,
    destino            VARCHAR(40)  NOT NULL,
    gera_oportunidade  TINYINT(1) NOT NULL DEFAULT 0,
    status             VARCHAR(20) NOT NULL DEFAULT 'ATIVO',
    usuario_alteracao  VARCHAR(160) NOT NULL,
    criada_em          DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizada_em      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                           ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (tratamento_id),
    UNIQUE KEY uk_regra_tratamento_resultado (configuracao_id, resultado),
    CONSTRAINT fk_regra_tratamento_config FOREIGN KEY (configuracao_id)
        REFERENCES pdoh_controle.regra_configuracao (configuracao_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Tratativas recomendadas por resultado, geracao automatica inicia desativada';

CREATE TABLE IF NOT EXISTS pdoh_controle.jornada_prioridade_configuracao (
    etapa_id                     CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    marca                        VARCHAR(80) NOT NULL,
    operacao                     VARCHAR(80) NOT NULL,
    prioridade                   SMALLINT UNSIGNED NOT NULL,
    origem_codigo                VARCHAR(40) NOT NULL,
    papel_fonte                  VARCHAR(40) NOT NULL,
    fallback                     TINYINT(1) NOT NULL DEFAULT 0,
    status                       VARCHAR(30) NOT NULL DEFAULT 'EM_VALIDACAO',
    aplicado_no_processamento    TINYINT(1) NOT NULL DEFAULT 0,
    descricao                    VARCHAR(500) NOT NULL,
    usuario_alteracao            VARCHAR(160) NOT NULL,
    criada_em                    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    atualizada_em                DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
                                     ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (etapa_id),
    UNIQUE KEY uk_jornada_prioridade (marca, operacao, prioridade),
    KEY ix_jornada_prioridade_origem (marca, operacao, origem_codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Ordem futura de resolucao de jornada, nao altera o fallback vigente';

CREATE TABLE IF NOT EXISTS pdoh_controle.governanca_configuracao_historico (
    id                 BIGINT NOT NULL AUTO_INCREMENT,
    marca              VARCHAR(80) NOT NULL,
    operacao           VARCHAR(80) NOT NULL,
    entidade_tipo      VARCHAR(60) NOT NULL,
    entidade_id        VARCHAR(100) NOT NULL,
    codigo_referencia  VARCHAR(160) NULL,
    acao               VARCHAR(30) NOT NULL,
    valor_anterior     JSON NULL,
    valor_novo         JSON NULL,
    usuario            VARCHAR(160) NOT NULL,
    motivo             VARCHAR(500) NOT NULL,
    registrado_em      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY ix_governanca_historico_escopo (marca, operacao, registrado_em),
    KEY ix_governanca_historico_entidade (entidade_tipo, entidade_id, registrado_em)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='Antes/depois imutavel das configuracoes operacionais';
