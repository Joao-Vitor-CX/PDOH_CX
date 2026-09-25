-- Excecao de classificacao por origem do dado, dentro da propria regra.
-- Permite que um mesmo tipo_problema seja TELEMETRIA no caso geral e OPORTUNIDADE
-- quando vem de uma origem especifica (ex.: INCONSISTENCIA_HORARIO em pesquisas x
-- em check-in/check-out), SEM criar uma segunda linha no catalogo -- o que quebraria
-- a unique key (marca, tipo_problema) e o upsert do bootstrap.
--
-- Aditivo e idempotente. Control-DB only: NAO toca calculo, Platina, Gold, ETL,
-- oportunidade, historico nem processadores.

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN origem_excecao VARCHAR(160) NULL AFTER severidade_padrao',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'origem_excecao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_tratativa ADD COLUMN classificacao_excecao VARCHAR(20) NULL AFTER origem_excecao',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_tratativa' AND COLUMN_NAME = 'classificacao_excecao');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
