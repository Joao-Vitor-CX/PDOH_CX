-- Linguagem de negocio no catalogo de regras, para a visao do lider.
--   titulo_exibicao  : nome amigavel (ex.: "Checkout não registrado")
--   impacto_negocio  : o que e' afetado na operacao (ex.: "Tempo em loja")
--   acao_recomendada : o que o lider deve fazer
-- Os textos vivem na regra (editaveis sem deploy); a API apenas os entrega.
--
-- Aditivo e idempotente. Control-DB only: NAO toca calculo, Platina, Gold, ETL,
-- oportunidade, historico nem processadores.

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN titulo_exibicao VARCHAR(160) NULL AFTER titulo',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'titulo_exibicao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN impacto_negocio VARCHAR(160) NULL AFTER titulo_exibicao',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'impacto_negocio');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN acao_recomendada VARCHAR(400) NULL AFTER impacto_negocio',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'acao_recomendada');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
