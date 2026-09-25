-- Tempo minimo da regra: o valor medido precisa alcanca-lo para a condicao virar oportunidade.
-- E' o campo "Tempo (minutos)" da tela de Configuracoes.
--
-- Aditivo e idempotente. Control-DB only: NAO toca calculo PDOH, Platina, Gold, ETL,
-- oportunidade, historico nem processadores travados no manifesto. O padrao 0 preserva o
-- comportamento das regras ja cadastradas (nenhuma tolerancia adicional).

SET @sql := (SELECT IF(COUNT(*) = 0,
    'ALTER TABLE pdoh_controle.regra_configuracao ADD COLUMN tempo_minimo_minutos SMALLINT UNSIGNED NOT NULL DEFAULT 0 AFTER prioridade',
    'DO 0')
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_configuracao'
      AND COLUMN_NAME = 'tempo_minimo_minutos');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
