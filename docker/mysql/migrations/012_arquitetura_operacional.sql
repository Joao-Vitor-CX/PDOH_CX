-- Additive, generic architecture. Historical findings and business output are not rewritten.

SET @sql := (SELECT IF(COUNT(*) = 0, 'ALTER TABLE pdoh_controle.execucao ADD COLUMN operacao VARCHAR(80) NOT NULL DEFAULT ''EXCLUSIVA''', 'DO 0') FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='pdoh_controle' AND TABLE_NAME='execucao' AND COLUMN_NAME='operacao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0, 'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN responsavel_padrao VARCHAR(160) NULL', 'DO 0') FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='pdoh_controle' AND TABLE_NAME='regra_tratativa' AND COLUMN_NAME='responsavel_padrao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0, 'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN origem VARCHAR(160) NULL', 'DO 0') FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='pdoh_controle' AND TABLE_NAME='regra_tratativa' AND COLUMN_NAME='origem');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0, 'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN campo_afetado VARCHAR(160) NULL', 'DO 0') FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='pdoh_controle' AND TABLE_NAME='regra_tratativa' AND COLUMN_NAME='campo_afetado');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0, 'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN criterios_operacionais JSON NULL', 'DO 0') FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='pdoh_controle' AND TABLE_NAME='regra_tratativa' AND COLUMN_NAME='criterios_operacionais');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

CREATE TABLE IF NOT EXISTS pdoh_controle.configuracao_operacao (
 marca VARCHAR(80) NOT NULL,
 operacao VARCHAR(80) NOT NULL,
 descricao VARCHAR(255) NOT NULL,
 fontes_jornada JSON NOT NULL,
 perfis_operacionais JSON NOT NULL,
 atualizado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 PRIMARY KEY (marca, operacao)
) COMMENT='Governanca por marca e operacao - mapeamentos explicitos de fontes oficiais';

CREATE TABLE IF NOT EXISTS pdoh_controle.jornada_consolidada (
 resolucao_id CHAR(64) NOT NULL PRIMARY KEY,
 marca VARCHAR(80) NOT NULL,
 operacao VARCHAR(80) NOT NULL,
 execution_id VARCHAR(80) NULL,
 colaborador_chave VARCHAR(255) NOT NULL,
 colaborador VARCHAR(255) NOT NULL,
 usuario_origem VARCHAR(255) NULL,
 data_referencia DATE NOT NULL,
 perfil VARCHAR(100) NULL,
 vigente BOOLEAN NOT NULL,
 elegivel BOOLEAN NOT NULL,
 jornada_semanal DECIMAL(8,2) NULL,
 fonte VARCHAR(255) NULL,
 campo VARCHAR(120) NULL,
 status_resolucao VARCHAR(40) NOT NULL,
 evidencia JSON NOT NULL,
 registrado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 INDEX ix_jornada_escopo (marca,operacao,data_referencia),
 INDEX ix_jornada_execucao (execution_id)
) COMMENT='Resolucao auditavel de jornada - append-only - nao substitui a Platina';

CREATE TABLE IF NOT EXISTS pdoh_controle.execucao_contexto (
 execution_id VARCHAR(80) NOT NULL PRIMARY KEY,
 marca VARCHAR(80) NOT NULL,
 operacao VARCHAR(80) NOT NULL,
 finalidade VARCHAR(30) NOT NULL,
 justificativa VARCHAR(500) NOT NULL,
 registrado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) COMMENT='Escopo explicito de execucoes operacionais e de validacao sem apagar historico';

CREATE TABLE IF NOT EXISTS pdoh_controle.achado_revisao (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 chave_validacao CHAR(64) NOT NULL UNIQUE,
 registro_id VARCHAR(80) NOT NULL,
 origem_registro VARCHAR(40) NOT NULL,
 execution_id VARCHAR(80) NOT NULL,
 marca VARCHAR(80) NOT NULL,
 operacao VARCHAR(80) NOT NULL,
 classificacao VARCHAR(30) NOT NULL,
 motivo VARCHAR(500) NOT NULL,
 evidencia JSON NOT NULL,
 registrado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 INDEX ix_revisao_registro (origem_registro,registro_id,id)
) COMMENT='Reavaliacoes append-only com prova da fonte - preserva a decisao e evidencia originais';
