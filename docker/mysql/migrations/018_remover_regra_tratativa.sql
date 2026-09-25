-- Remove `regra_tratativa`: o catalogo de classificacao de achados agora vive em codigo
-- (shared/treatment_catalog.py), nao mais no banco. api/app/database.py monta a mesma
-- tabela como uma derived table (UNION ALL de linhas literais) a partir desse catalogo,
-- entao nenhuma consulta que fazia JOIN/subquery contra `regra_tratativa` precisou mudar.
-- Idempotente: o runner reaplica todas as migracoes a cada execucao.
--
-- Nao apaga historico: `oportunidade.regra_id`, `alerta.regra_id`,
-- `achado_roteamento.regra_id` e `regra_configuracao.regra_catalogo_id` continuam com os
-- UUIDs ja gravados (uuid5 deterministico -- o mesmo regra_id do catalogo em codigo
-- continua resolvendo o mesmo tipo_problema). So a FK e' removida; a coluna fica.

-- 1) Views que dependiam de regra_tratativa (nenhuma consultada pela API -- confirmado
--    por busca no codigo). Ordem: dependentes de achados_classificados primeiro.
DROP VIEW IF EXISTS pdoh_controle.telemetria;
DROP VIEW IF EXISTS pdoh_controle.alertas_qualidade;
DROP VIEW IF EXISTS pdoh_controle.oportunidades_operacionais;
DROP VIEW IF EXISTS pdoh_controle.achados_classificados;
DROP VIEW IF EXISTS pdoh_controle.configuracoes_governanca;
DROP VIEW IF EXISTS pdoh_controle.regras_negocio;

-- 2) FKs que referenciam regra_tratativa.regra_id.
SET @sql := (SELECT IF(COUNT(*) > 0,
    'ALTER TABLE pdoh_controle.oportunidade DROP FOREIGN KEY fk_oportunidade_regra',
    'DO 0')
    FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'oportunidade' AND CONSTRAINT_NAME = 'fk_oportunidade_regra');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) > 0,
    'ALTER TABLE pdoh_controle.alerta DROP FOREIGN KEY fk_alerta_regra',
    'DO 0')
    FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'alerta' AND CONSTRAINT_NAME = 'fk_alerta_regra');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) > 0,
    'ALTER TABLE pdoh_controle.achado_roteamento DROP FOREIGN KEY fk_roteamento_regra',
    'DO 0')
    FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'achado_roteamento' AND CONSTRAINT_NAME = 'fk_roteamento_regra');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @sql := (SELECT IF(COUNT(*) > 0,
    'ALTER TABLE pdoh_controle.regra_configuracao DROP FOREIGN KEY fk_regra_config_catalogo',
    'DO 0')
    FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = 'pdoh_controle' AND TABLE_NAME = 'regra_configuracao' AND CONSTRAINT_NAME = 'fk_regra_config_catalogo');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- 3) A tabela em si.
DROP TABLE IF EXISTS pdoh_controle.regra_tratativa;
