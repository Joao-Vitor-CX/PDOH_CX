-- Aditiva e idempotente. Preserva horarios, ativacao, carga semanal e regras existentes.

SET @sql := (SELECT IF(COUNT(*) = 0,
 'ALTER TABLE pdoh_controle.configuracao_jornada_operacao ADD COLUMN nome_jornada VARCHAR(120) NULL', 'DO 0')
 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = 'pdoh_controle'
 AND TABLE_NAME = 'configuracao_jornada_operacao' AND COLUMN_NAME = 'nome_jornada');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
 'ALTER TABLE pdoh_controle.configuracao_jornada_operacao ADD COLUMN intervalo CHAR(5) NULL', 'DO 0')
 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = 'pdoh_controle'
 AND TABLE_NAME = 'configuracao_jornada_operacao' AND COLUMN_NAME = 'intervalo');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
 'ALTER TABLE pdoh_controle.configuracao_jornada_operacao ADD COLUMN origem_configuracao VARCHAR(24) NOT NULL DEFAULT ''CADASTRO_OPERACIONAL''', 'DO 0')
 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = 'pdoh_controle'
 AND TABLE_NAME = 'configuracao_jornada_operacao' AND COLUMN_NAME = 'origem_configuracao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

