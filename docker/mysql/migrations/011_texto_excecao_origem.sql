-- Textos de negocio da excecao por origem.
-- Quando `origem_excecao` coincide com a origem do registro, a regra ja muda de
-- classificacao (008). Os textos precisam acompanhar: o mesmo tipo pode afetar a jornada
-- no check-in e ser so qualidade cadastral em pesquisas. Sem texto de excecao, vale o
-- texto base da regra.
--
-- Aditivo e idempotente. Control-DB only: NAO toca calculo, Platina, Gold, ETL,
-- oportunidade, historico nem processadores.

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN impacto_negocio_excecao VARCHAR(160) NULL AFTER classificacao_excecao',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'impacto_negocio_excecao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN acao_recomendada_excecao VARCHAR(400) NULL AFTER impacto_negocio_excecao',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'acao_recomendada_excecao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
