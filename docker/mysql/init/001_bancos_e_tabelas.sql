CREATE DATABASE IF NOT EXISTS involves_bracell
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS produtos_platina
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE DATABASE IF NOT EXISTS pdoh_controle
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS involves_bracell.status_day_operacao_bracell (
    colaborador VARCHAR(255),
    colaborador_superior VARCHAR(255),
    regional VARCHAR(150),
    estado VARCHAR(50),
    perfil_acesso VARCHAR(150),
    dia_referencia DATE,
    tem_roteiro VARCHAR(20),
    primeiro_checkin DATETIME,
    ultimo_checkout DATETIME,
    afastado VARCHAR(255),
    data_dimensao DATETIME,
    data_evolucao DATETIME,
    INDEX idx_status_day_data (dia_referencia),
    INDEX idx_status_day_colaborador (colaborador)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS involves_bracell.colaboradores_ativos_bracell (
    nome_colaborador VARCHAR(255),
    usuario VARCHAR(255),
    usuario_ativo VARCHAR(20),
    perfil_acesso VARCHAR(150),
    equipe_campo VARCHAR(255),
    regionais VARCHAR(255),
    colaborador_superior VARCHAR(255),
    jornada_trabalho VARCHAR(255),
    nome_pai VARCHAR(255),
    nome_mae VARCHAR(255),
    uf VARCHAR(10),
    cidade VARCHAR(150),
    data_dimensao DATETIME,
    data_evolucao DATETIME,
    INDEX idx_colaboradores_nome (nome_colaborador),
    INDEX idx_colaboradores_evolucao (data_evolucao)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS involves_bracell.relatorio_checkin_bracell (
    colaborador VARCHAR(255),
    colaborador_superior VARCHAR(255),
    regional VARCHAR(150),
    rede VARCHAR(255),
    bandeira VARCHAR(255),
    ponto_venda VARCHAR(500),
    cidade VARCHAR(150),
    estado VARCHAR(50),
    data_roteiro DATE,
    tipo_checkin VARCHAR(100),
    hora_entrada DATETIME,
    hora_saida DATETIME,
    data_dimensao DATETIME,
    data_evolucao DATETIME,
    INDEX idx_checkin_data (data_roteiro),
    INDEX idx_checkin_colaborador (colaborador)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS involves_bracell.gerencial_visitas_bracell (
    colaborador VARCHAR(255),
    colaborador_superior VARCHAR(255),
    regional VARCHAR(150),
    rede VARCHAR(255),
    bandeira VARCHAR(255),
    ponto_venda VARCHAR(500),
    estado VARCHAR(50),
    cidade VARCHAR(150),
    data_visita DATE,
    tipo_check_in VARCHAR(100),
    tempo_loja_executado VARCHAR(50),
    data_dimensao DATETIME,
    data_evolucao DATETIME,
    INDEX idx_visitas_data (data_visita),
    INDEX idx_visitas_colaborador (colaborador)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS involves_bracell.painel_pesquisas_bracell (
    id VARCHAR(100),
    rotulo VARCHAR(500),
    tipo_coleta VARCHAR(150),
    ponto_venda VARCHAR(500),
    rede VARCHAR(255),
    bandeira VARCHAR(255),
    estado VARCHAR(50),
    responsavel VARCHAR(255),
    perfil_acesso VARCHAR(150),
    colaborador_superior VARCHAR(255),
    data_solicitacao DATETIME,
    data_conclusao DATETIME,
    data_expiracao DATETIME,
    tempo_gasto VARCHAR(50),
    status VARCHAR(100),
    data_dimensao DATETIME,
    data_evolucao DATETIME,
    INDEX idx_pesquisas_periodo (data_solicitacao, data_expiracao),
    INDEX idx_pesquisas_responsavel (responsavel)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS produtos_platina.exclusivo_bracell_platina_relatorio_pdoh (
    colaborador VARCHAR(255) NOT NULL,
    superior VARCHAR(255),
    estado VARCHAR(50),
    data DATE NOT NULL,
    nome_do_dia VARCHAR(50),
    deslocamento TIME,
    ocio TIME,
    produtividade TIME,
    horas_nao_registradas TIME,
    horas_programadas TIME,
    almoco TIME,
    media_tempo_em_loja TIME,
    primeiro_checkin TIME,
    ultimo_checkout TIME,
    visitas_diarias INT NOT NULL DEFAULT 0,
    visitas_diarias_realizadas INT NOT NULL DEFAULT 0,
    pesquisas_diarias INT NOT NULL DEFAULT 0,
    pesquisas_diarias_realizadas INT NOT NULL DEFAULT 0,
    percentual_produtividade DECIMAL(12, 6) NOT NULL DEFAULT 0,
    percentual_visitas DECIMAL(12, 6) NOT NULL DEFAULT 0,
    percentual_pesquisas DECIMAL(12, 6) NOT NULL DEFAULT 0,
    percentual_efetividade DECIMAL(12, 6) NOT NULL DEFAULT 0,
    justificativas_seg TEXT,
    justificativas_ter TEXT,
    justificativas_qua TEXT,
    justificativas_qui TEXT,
    justificativas_sex TEXT,
    justificativas_sab TEXT,
    CONSTRAINT uk_pdoh_colab_data UNIQUE (colaborador, data),
    INDEX idx_pdoh_data (data),
    INDEX idx_pdoh_superior (superior)
) ENGINE=InnoDB;

