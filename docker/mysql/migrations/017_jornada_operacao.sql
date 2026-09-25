-- Camada de configuracao apenas. Nenhum horario ou regra e ativado pelo deploy.
CREATE TABLE IF NOT EXISTS pdoh_controle.configuracao_jornada_operacao (
 id CHAR(36) NOT NULL PRIMARY KEY,
 configuracao_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 marca VARCHAR(80) NOT NULL,
 operacao VARCHAR(80) NOT NULL,
 jornada DECIMAL(8,2) NOT NULL,
 hora_entrada_padrao CHAR(5) NULL,
 hora_saida_padrao CHAR(5) NULL,
 ativo BOOLEAN NOT NULL DEFAULT 0,
 usuario_alteracao VARCHAR(160) NOT NULL,
 criada_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 atualizada_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 UNIQUE KEY uk_config_jornada (configuracao_id, jornada),
 KEY ix_jornada_operacao (marca, operacao),
 FOREIGN KEY (configuracao_id) REFERENCES pdoh_controle.regra_configuracao(configuracao_id)
) COMMENT='Horarios esperados para validacao operacional, nunca substituem monitoramento';
