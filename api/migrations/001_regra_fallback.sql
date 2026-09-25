-- MySQL 8.4. Provisionamento separado da esteira; nenhuma regra/dado existente e alterado.
-- Nao semeia configuracoes. O DEFAULT 23:59 pertence ao resolvedor, nao ao banco.
CREATE TABLE IF NOT EXISTS pdoh_controle.regra_fallback_config (
    id CHAR(36) NOT NULL PRIMARY KEY,
    marca VARCHAR(80) COLLATE utf8mb4_bin NOT NULL,
    regra VARCHAR(100) COLLATE utf8mb4_bin NOT NULL,
    escopo VARCHAR(10) COLLATE utf8mb4_bin NOT NULL,
    chave VARCHAR(160) COLLATE utf8mb4_bin NOT NULL,
    valor_fallback VARCHAR(5) NOT NULL,
    vigencia_inicio DATE NOT NULL,
    vigencia_fim DATE NULL,
    status VARCHAR(10) COLLATE utf8mb4_bin NOT NULL DEFAULT 'INATIVO',
    usuario_alteracao VARCHAR(160) NOT NULL,
    data_alteracao DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT ck_fallback_brand CHECK (CHAR_LENGTH(TRIM(marca)) > 0 AND marca = UPPER(TRIM(marca))),
    CONSTRAINT ck_fallback_rule CHECK (regra = 'CHECKOUT_AUSENTE'),
    CONSTRAINT ck_fallback_scope CHECK (escopo IN ('LIDER', 'MARCA')),
    CONSTRAINT ck_fallback_key CHECK ((escopo = 'MARCA' AND chave = '*') OR
        (escopo = 'LIDER' AND CHAR_LENGTH(TRIM(chave)) > 0 AND chave <> '*')),
    CONSTRAINT ck_fallback_time CHECK (REGEXP_LIKE(valor_fallback, '^([01][0-9]|2[0-3]):[0-5][0-9]$')),
    CONSTRAINT ck_fallback_dates CHECK (vigencia_fim IS NULL OR vigencia_fim >= vigencia_inicio),
    CONSTRAINT ck_fallback_status CHECK (status IN ('ATIVO', 'INATIVO')),
    CONSTRAINT ck_fallback_actor CHECK (CHAR_LENGTH(TRIM(usuario_alteracao)) > 0),
    UNIQUE KEY uk_fallback_start (marca, regra, escopo, chave, vigencia_inicio),
    KEY ix_fallback_resolution (marca, regra, escopo, chave, status, vigencia_inicio)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pdoh_controle.regra_fallback_historico (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    config_id CHAR(36) NOT NULL,
    acao VARCHAR(20) NOT NULL,
    valor_anterior VARCHAR(5) NULL,
    novo_valor VARCHAR(5) NOT NULL,
    usuario_alteracao VARCHAR(160) NOT NULL,
    data_alteracao DATETIME(6) NOT NULL,
    regra VARCHAR(100) NOT NULL,
    marca VARCHAR(80) NOT NULL,
    escopo VARCHAR(10) NOT NULL,
    chave VARCHAR(160) NOT NULL,
    estado_anterior JSON NULL,
    estado_novo JSON NOT NULL,
    KEY ix_fallback_history (config_id, id),
    CONSTRAINT fk_fallback_history FOREIGN KEY (config_id)
        REFERENCES pdoh_controle.regra_fallback_config (id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

DELIMITER $$
CREATE TRIGGER IF NOT EXISTS pdoh_controle.fallback_config_before_insert
BEFORE INSERT ON pdoh_controle.regra_fallback_config FOR EACH ROW
BEGIN
    SET NEW.data_alteracao = CURRENT_TIMESTAMP(6);
END$$

CREATE TRIGGER IF NOT EXISTS pdoh_controle.fallback_config_before_update
BEFORE UPDATE ON pdoh_controle.regra_fallback_config FOR EACH ROW
BEGIN
    IF NEW.id <> OLD.id OR NEW.marca <> OLD.marca OR NEW.regra <> OLD.regra
       OR NEW.escopo <> OLD.escopo OR NEW.chave <> OLD.chave THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Identidade da configuracao e imutavel; crie outra configuracao.';
    END IF;
    SET NEW.data_alteracao = CURRENT_TIMESTAMP(6);
END$$

CREATE TRIGGER IF NOT EXISTS pdoh_controle.fallback_config_no_delete
BEFORE DELETE ON pdoh_controle.regra_fallback_config FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Configuracao nao pode ser excluida; use INATIVO.';
END$$

CREATE TRIGGER IF NOT EXISTS pdoh_controle.fallback_config_after_insert
AFTER INSERT ON pdoh_controle.regra_fallback_config FOR EACH ROW
BEGIN
    INSERT INTO pdoh_controle.regra_fallback_historico
        (config_id, acao, valor_anterior, novo_valor, usuario_alteracao, data_alteracao,
         regra, marca, escopo, chave, estado_anterior, estado_novo)
    VALUES (NEW.id, 'CRIADA', NULL, NEW.valor_fallback, NEW.usuario_alteracao, NEW.data_alteracao,
        NEW.regra, NEW.marca, NEW.escopo, NEW.chave, NULL,
        JSON_OBJECT('id', NEW.id, 'marca', NEW.marca, 'regra', NEW.regra, 'escopo', NEW.escopo,
            'chave', NEW.chave, 'valor_fallback', NEW.valor_fallback, 'status', NEW.status,
            'vigencia_inicio', NEW.vigencia_inicio, 'vigencia_fim', NEW.vigencia_fim,
            'usuario_alteracao', NEW.usuario_alteracao, 'data_alteracao', NEW.data_alteracao));
END$$

CREATE TRIGGER IF NOT EXISTS pdoh_controle.fallback_config_after_update
AFTER UPDATE ON pdoh_controle.regra_fallback_config FOR EACH ROW
BEGIN
    INSERT INTO pdoh_controle.regra_fallback_historico
        (config_id, acao, valor_anterior, novo_valor, usuario_alteracao, data_alteracao,
         regra, marca, escopo, chave, estado_anterior, estado_novo)
    VALUES (NEW.id, 'ALTERADA', OLD.valor_fallback, NEW.valor_fallback, NEW.usuario_alteracao, NEW.data_alteracao,
        NEW.regra, NEW.marca, NEW.escopo, NEW.chave,
        JSON_OBJECT('id', OLD.id, 'marca', OLD.marca, 'regra', OLD.regra, 'escopo', OLD.escopo,
            'chave', OLD.chave, 'valor_fallback', OLD.valor_fallback, 'status', OLD.status,
            'vigencia_inicio', OLD.vigencia_inicio, 'vigencia_fim', OLD.vigencia_fim,
            'usuario_alteracao', OLD.usuario_alteracao, 'data_alteracao', OLD.data_alteracao),
        JSON_OBJECT('id', NEW.id, 'marca', NEW.marca, 'regra', NEW.regra, 'escopo', NEW.escopo,
            'chave', NEW.chave, 'valor_fallback', NEW.valor_fallback, 'status', NEW.status,
            'vigencia_inicio', NEW.vigencia_inicio, 'vigencia_fim', NEW.vigencia_fim,
            'usuario_alteracao', NEW.usuario_alteracao, 'data_alteracao', NEW.data_alteracao));
END$$

CREATE TRIGGER IF NOT EXISTS pdoh_controle.fallback_history_no_update
BEFORE UPDATE ON pdoh_controle.regra_fallback_historico FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Historico append-only: UPDATE proibido.';
END$$

CREATE TRIGGER IF NOT EXISTS pdoh_controle.fallback_history_no_delete
BEFORE DELETE ON pdoh_controle.regra_fallback_historico FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Historico append-only: DELETE proibido.';
END$$
DELIMITER ;
