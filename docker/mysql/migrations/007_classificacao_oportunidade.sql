-- Classificacao operacional das oportunidades (OPORTUNIDADE | ALERTA | TELEMETRIA)
-- + titulo amigavel + severidade padrao, parametrizaveis no catalogo de regras.
-- Aditivo e idempotente. Control-DB only: NAO toca calculo, Platina, oportunidade,
-- nem processadores. Seed dos valores e' feito pela aplicacao (bootstrap_regras).

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN classificacao VARCHAR(20) NULL AFTER tipo_problema',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'classificacao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN titulo VARCHAR(160) NULL AFTER classificacao',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'titulo');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN severidade_padrao VARCHAR(20) NULL AFTER titulo',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'severidade_padrao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
