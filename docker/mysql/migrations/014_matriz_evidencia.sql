-- Matriz de origem das oportunidades: de qual tabela RAW e de qual campo cada
-- cenario nasce, e quais criterios precisam ser comprovados antes de cobrar.
--
--   configuracao_evidencia        : marca + operacao + papel -> tabela fisica + campos
--   configuracao_evidencia_regra  : tipo_problema -> papel, campo, esperado, criterios
--
-- Multimarca por construcao: nenhuma tabela `*_bracell`, nenhuma coluna por marca.
-- Atender TANGARA ou FLORA e' inserir linhas, nunca criar arquivo ou objeto novo.
--
-- Aditivo e idempotente. Control-DB only: NAO toca calculo PDOH, Platina, Gold, ETL,
-- oportunidade, historico nem processadores travados no manifesto.

CREATE TABLE IF NOT EXISTS pdoh_controle.configuracao_evidencia (
    marca        VARCHAR(80)  NOT NULL,
    operacao     VARCHAR(80)  NOT NULL DEFAULT 'EXCLUSIVA',
    -- Papel semantico da fonte: status_day, colaborador, checkin, visitas, pesquisas.
    papel        VARCHAR(40)  NOT NULL,
    -- Nome fisico da tabela na origem somente-leitura (involves_exclusivos).
    tabela       VARCHAR(160) NOT NULL,
    -- Campos usados na comprovacao, por apelido: {"entrada":"primeiro_checkin", ...}
    campos       JSON         NOT NULL,
    descricao    VARCHAR(255) NULL,
    atualizado_em DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (marca, operacao, papel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS pdoh_controle.configuracao_evidencia_regra (
    marca          VARCHAR(80)  NOT NULL,
    operacao       VARCHAR(80)  NOT NULL DEFAULT 'EXCLUSIVA',
    tipo_problema  VARCHAR(100) NOT NULL,
    papel          VARCHAR(40)  NOT NULL,
    campo          VARCHAR(160) NULL,
    valor_esperado VARCHAR(255) NULL,
    -- Criterios que o motor sabe executar, na ordem de apresentacao ao lider.
    criterios      JSON         NOT NULL,
    papeis_apoio   JSON         NULL,
    atualizado_em  DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (marca, operacao, tipo_problema)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Fontes oficiais da BRACELL. Os nomes fisicos sao os mesmos consumidos por
-- `bracell/src/data_loader.py::carregar_dados_involves`; os apelidos de campo seguem
-- o schema real de `status_day_operacao_bracell`.
INSERT INTO pdoh_controle.configuracao_evidencia (marca, operacao, papel, tabela, campos, descricao)
VALUES
 ('BRACELL','EXCLUSIVA','status_day','status_day_operacao_bracell',
  JSON_OBJECT('colaborador','colaborador','data','dia_referencia','roteiro','tem_roteiro',
              'entrada','primeiro_checkin','saida','ultimo_checkout','afastamento','afastado',
              'perfil','perfil_acesso','evolucao','data_evolucao','dimensao','data_dimensao'),
  'Operacao diaria: roteiro, entrada, saida e ausencia. `evolucao` e a data da extracao: o mesmo dia aparece em varios snapshots e vale o mais recente.'),
 ('BRACELL','EXCLUSIVA','colaborador','colaboradores_ativos_bracell',
  JSON_OBJECT('colaborador','nome_colaborador','ativo','usuario_ativo','perfil','perfil_acesso',
              'jornada','nome_pai','dimensao','data_dimensao','evolucao','data_evolucao'),
  'Cadastro vigente: vinculo, perfil e jornada semanal.'),
 ('BRACELL','EXCLUSIVA','checkin','relatorio_checkin_bracell',
  JSON_OBJECT('colaborador','colaborador','data','data_roteiro','entrada','hora_entrada',
              'saida','hora_saida','tipo','tipo_checkin'),
  'Marcacoes de entrada e saida por roteiro.'),
 ('BRACELL','EXCLUSIVA','visitas','gerencial_visitas_bracell',
  JSON_OBJECT('colaborador','colaborador','data','data_visita','situacao','situacao_checkin'),
  'Visitas planejadas e realizadas.'),
 ('BRACELL','EXCLUSIVA','pesquisas','painel_pesquisas_bracell',
  JSON_OBJECT('colaborador','responsavel','data','data_solicitacao','status','status',
              'conclusao','data_conclusao','expiracao','data_expiracao'),
  'Pesquisas solicitadas, respondidas e expiradas.')
ON DUPLICATE KEY UPDATE tabela = VALUES(tabela), campos = VALUES(campos),
                        descricao = VALUES(descricao);

-- Como comprovar cada cenario. `criterios` e' a lista que o motor executa; a ausencia de
-- um criterio nunca e' tratada como aprovada -- vira "evidencia indisponivel".
INSERT INTO pdoh_controle.configuracao_evidencia_regra
  (marca, operacao, tipo_problema, papel, campo, valor_esperado, criterios, papeis_apoio)
VALUES
 ('BRACELL','EXCLUSIVA','CHECKIN_ENTRADA_AUSENTE','status_day','primeiro_checkin',
  'Entrada registrada no dia trabalhado',
  JSON_ARRAY('colaborador_vigente','dia_trabalhado','jornada_resolvida','sem_abono'),
  JSON_ARRAY('colaborador')),
 ('BRACELL','EXCLUSIVA','CHECKOUT_AUSENTE','checkin','hora_saida',
  'Check-out real apos a entrada registrada',
  JSON_ARRAY('colaborador_vigente','dia_trabalhado','houve_entrada','sem_abono'),
  JSON_ARRAY('status_day')),
 ('BRACELL','EXCLUSIVA','INCONSISTENCIA_HORARIO','checkin','hora_entrada+hora_saida',
  'Saida posterior a entrada, dentro da jornada',
  JSON_ARRAY('colaborador_vigente','dia_trabalhado','houve_entrada','jornada_resolvida'),
  JSON_ARRAY('status_day')),
 ('BRACELL','EXCLUSIVA','JORNADA_NAO_ENCONTRADA','colaborador','nome_pai',
  'Jornada semanal cadastrada na fonte oficial',
  JSON_ARRAY('colaborador_vigente','jornada_resolvida'),
  JSON_ARRAY()),
 ('BRACELL','EXCLUSIVA','CADASTRO_UF_AUSENTE','colaborador','uf',
  'UF preenchida no cadastro de origem',
  JSON_ARRAY('colaborador_vigente'),
  JSON_ARRAY())
ON DUPLICATE KEY UPDATE papel = VALUES(papel), campo = VALUES(campo),
                        valor_esperado = VALUES(valor_esperado), criterios = VALUES(criterios),
                        papeis_apoio = VALUES(papeis_apoio);
