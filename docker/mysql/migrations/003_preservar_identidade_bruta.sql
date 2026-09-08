-- Upgrade idempotente para volumes criados antes da camada de outbox/fallback.
-- Cada ALTER so ocorre quando INFORMATION_SCHEMA aponta divergencia real.

SET @alias_precisa_collation = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = 'pdoh_controle'
      AND table_name = 'colaborador_alias'
      AND column_name = 'nome_original'
      AND collation_name <> 'utf8mb4_0900_as_cs'
);
SET @ddl_alias_collation = IF(
    @alias_precisa_collation > 0,
    'ALTER TABLE pdoh_controle.colaborador_alias MODIFY nome_original VARCHAR(255) COLLATE utf8mb4_0900_as_cs NOT NULL',
    'DO 0'
);
PREPARE stmt_alias_collation FROM @ddl_alias_collation;
EXECUTE stmt_alias_collation;
DEALLOCATE PREPARE stmt_alias_collation;

SET @oportunidade_precisa_collation = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = 'pdoh_controle'
      AND table_name = 'oportunidade'
      AND column_name = 'colaborador'
      AND collation_name <> 'utf8mb4_0900_as_cs'
);
SET @ddl_oportunidade_collation = IF(
    @oportunidade_precisa_collation > 0,
    'ALTER TABLE pdoh_controle.oportunidade MODIFY colaborador VARCHAR(255) COLLATE utf8mb4_0900_as_cs NULL',
    'DO 0'
);
PREPARE stmt_oportunidade_collation FROM @ddl_oportunidade_collation;
EXECUTE stmt_oportunidade_collation;
DEALLOCATE PREPARE stmt_oportunidade_collation;

SET @outbox_oportunidade_precisa_nullable = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = 'pdoh_controle'
      AND table_name = 'notificacao_outbox'
      AND column_name = 'oportunidade_id'
      AND is_nullable = 'NO'
);
SET @ddl_outbox_oportunidade_nullable = IF(
    @outbox_oportunidade_precisa_nullable > 0,
    'ALTER TABLE pdoh_controle.notificacao_outbox MODIFY oportunidade_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL',
    'DO 0'
);
PREPARE stmt_outbox_oportunidade_nullable FROM @ddl_outbox_oportunidade_nullable;
EXECUTE stmt_outbox_oportunidade_nullable;
DEALLOCATE PREPARE stmt_outbox_oportunidade_nullable;

SET @fallback_coluna_existe = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = 'pdoh_controle'
      AND table_name = 'notificacao_outbox'
      AND column_name = 'fallback_id'
);
SET @ddl_fallback_coluna = IF(
    @fallback_coluna_existe = 0,
    'ALTER TABLE pdoh_controle.notificacao_outbox ADD COLUMN fallback_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL AFTER oportunidade_id',
    'DO 0'
);
PREPARE stmt_fallback_coluna FROM @ddl_fallback_coluna;
EXECUTE stmt_fallback_coluna;
DEALLOCATE PREPARE stmt_fallback_coluna;

SET @fallback_fk_correta = (
    SELECT COUNT(*) FROM information_schema.key_column_usage
    WHERE constraint_schema = 'pdoh_controle'
      AND table_name = 'notificacao_outbox'
      AND constraint_name = 'fk_notificacao_fallback'
      AND column_name = 'fallback_id'
      AND referenced_table_schema = 'pdoh_controle'
      AND referenced_table_name = 'fallback_evento'
      AND referenced_column_name = 'fallback_id'
);
SET @ddl_fallback_fk = IF(
    @fallback_fk_correta = 0,
    'ALTER TABLE pdoh_controle.notificacao_outbox ADD CONSTRAINT fk_notificacao_fallback FOREIGN KEY (fallback_id) REFERENCES pdoh_controle.fallback_evento (fallback_id) ON DELETE RESTRICT',
    'DO 0'
);
PREPARE stmt_fallback_fk FROM @ddl_fallback_fk;
EXECUTE stmt_fallback_fk;
DEALLOCATE PREPARE stmt_fallback_fk;

SET @referencia_check_existe = (
    SELECT COUNT(*) FROM information_schema.table_constraints
    WHERE constraint_schema = 'pdoh_controle'
      AND table_name = 'notificacao_outbox'
      AND constraint_name = 'ck_notificacao_referencia'
      AND constraint_type = 'CHECK'
);
SET @ddl_referencia_check = IF(
    @referencia_check_existe = 0,
    'ALTER TABLE pdoh_controle.notificacao_outbox ADD CONSTRAINT ck_notificacao_referencia CHECK (oportunidade_id IS NOT NULL OR fallback_id IS NOT NULL)',
    'DO 0'
);
PREPARE stmt_referencia_check FROM @ddl_referencia_check;
EXECUTE stmt_referencia_check;
DEALLOCATE PREPARE stmt_referencia_check;

-- Runtime nao precisa criar/apagar objetos no schema lateral.
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'pdoh_cx_app'@'%';
GRANT SELECT ON involves_bracell.* TO 'pdoh_cx_app'@'%';
GRANT ALL PRIVILEGES ON produtos_platina.* TO 'pdoh_cx_app'@'%';
GRANT SELECT, INSERT, UPDATE ON pdoh_controle.* TO 'pdoh_cx_app'@'%';

FLUSH PRIVILEGES;
