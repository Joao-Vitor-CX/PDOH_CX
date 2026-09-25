"""Catalogo de classificacao de achados/qualidade de dados (ex-tabela `regra_tratativa`).

Fonte unica em codigo: nao ha mais leitura em `pdoh_controle.regra_tratativa` para
resolver a classificacao/titulo/severidade/tratativa de um tipo_problema. `bracell/`
(ETL) e `api/` (leitura/exibicao) importam este modulo em vez de duplicar a lista.

`regra_id` continua deterministico (uuid5 de marca+tipo_problema), entao qualquer
regra_id ja gravado em oportunidade/alerta/achado_roteamento antes desta mudanca
continua resolvendo para a mesma entrada aqui.
"""
from __future__ import annotations

import uuid
from typing import Any

MARCA_PADRAO = "BRACELL"

REGRAS_PADRAO: list[dict[str, Any]] = [
    {
        "tipo_problema": "CADASTRO_UF_AUSENTE",
        "descricao_cenario": "Colaborador ativo BRACELL com UF/Estado nao preenchido.",
        "regra_identificacao": "Snapshot cadastral vigente; consolidar marca + usuario de origem + UF, sem alterar calculos.",
        "tratamento_esperado": "Atualizar cadastro na origem",
        "acao_aplicacao": "ALERTAR", "permite_processamento": 1,
        "necessita_aprovacao": 0, "prioridade": 100,
    },
    {
        "tipo_problema": "SEM_LIDERES_NO_PERIODO",
        "descricao_cenario": "Nenhum colaborador de lideranca encontrado no periodo processado.",
        "regra_identificacao": "O filtro de lideranca do processador resulta em conjunto vazio.",
        "tratamento_esperado": "Registrar oportunidade e continuar o processamento sem gerar registros de lideranca.",
        "acao_aplicacao": "ALERTAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 10,
    },
    # Catalogo para uso futuro (ainda nao vinculado a codigo nesta etapa).
    {
        "tipo_problema": "COLABORADOR_SEM_CLASSIFICACAO",
        "descricao_cenario": "Colaborador sem classificacao de perfil reconhecida.",
        "regra_identificacao": "perfil_acesso ausente ou fora do dominio conhecido.",
        "tratamento_esperado": "Registrar oportunidade para analise; nao interromper.",
        "acao_aplicacao": "REGISTRAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 100,
    },
    {
        "tipo_problema": "JORNADA_NAO_ENCONTRADA",
        "descricao_cenario": "Jornada semanal do colaborador nao encontrada/parametrizada.",
        "regra_identificacao": "jornada_semanal ausente; aplica-se o padrao legado.",
        "tratamento_esperado": "Registrar oportunidade; manter fallback legado de jornada.",
        "acao_aplicacao": "REGISTRAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 100,
    },
    {
        "tipo_problema": "CAMPO_OBRIGATORIO_VAZIO",
        "descricao_cenario": "Campo obrigatorio ausente em registro de origem.",
        "regra_identificacao": "Campo requerido nulo/vazio na massa carregada.",
        "tratamento_esperado": "Registrar oportunidade para analise; nao interromper.",
        "acao_aplicacao": "REGISTRAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 100,
    },
    {
        "tipo_problema": "DIVERGENCIA_CADASTRAL",
        "descricao_cenario": "Cadastro inconsistente entre fontes da origem.",
        "regra_identificacao": "Divergencia detectada na conferencia de cadastro.",
        "tratamento_esperado": "Registrar oportunidade para analise; nao interromper.",
        "acao_aplicacao": "REGISTRAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 100,
    },
    {
        "tipo_problema": "DADO_FORA_DO_PADRAO",
        "descricao_cenario": "Informacao fora do padrao esperado.",
        "regra_identificacao": "Valor fora do dominio/formato esperado.",
        "tratamento_esperado": "Registrar oportunidade para analise; nao interromper.",
        "acao_aplicacao": "REGISTRAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 100,
    },
    {
        "tipo_problema": "PDV_SEM_IDENTIFICADOR",
        "descricao_cenario": "PDV sem id_pdv/codigo confiavel; identificado apenas por nome.",
        "regra_identificacao": "Registro de PDV sem id_pdv e sem codigo; usa nome normalizado como ultimo recurso.",
        "tratamento_esperado": "Registrar oportunidade; manter processamento (identificacao por nome).",
        "acao_aplicacao": "ALERTAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 50,
    },
    {
        "tipo_problema": "PDV_MESMO_NOME_IDS_DISTINTOS",
        "descricao_cenario": "Um mesmo nome de PDV aparece com identificadores distintos.",
        "regra_identificacao": "nome_normalizado do PDV associado a mais de um identificador interno.",
        "tratamento_esperado": "Registrar oportunidade de ambiguidade; nao interromper.",
        "acao_aplicacao": "ALERTAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 50,
    },
    {
        "tipo_problema": "PDV_NOME_DIVERGENTE_MESMO_ID",
        "descricao_cenario": "Um mesmo PDV (mesmo id/codigo) aparece com nomes diferentes.",
        "regra_identificacao": "identificador interno de PDV associado a mais de um nome normalizado.",
        "tratamento_esperado": "Registrar oportunidade de alteracao cadastral; nao interromper.",
        "acao_aplicacao": "REGISTRAR",
        "permite_processamento": 1,
        "necessita_aprovacao": 0,
        "prioridade": 100,
    },
    # --- Cenarios ja emitidos pelos observadores de qualidade/identidade ---
    {"tipo_problema": "COLUNA_OBRIGATORIA_AUSENTE", "descricao_cenario": "Coluna obrigatoria ausente na fonte.",
     "regra_identificacao": "Coluna requerida nao recebida no dataframe.", "tratamento_esperado": "Registrar oportunidade critica; nao interromper.",
     "acao_aplicacao": "ALERTAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 30},
    {"tipo_problema": "REGISTRO_DUPLICADO", "descricao_cenario": "Duplicidade tecnica; deduplicacao e responsabilidade da ETL.",
     "regra_identificacao": "Linhas full-row iguais (exceto data_dimensao/data_evolucao).", "tratamento_esperado": "Nenhuma; a ETL ja deduplica. Nao gerar como oportunidade operacional.",
     "acao_aplicacao": "TELEMETRIA", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 200},
    {"tipo_problema": "DATA_HORA_INVALIDA", "descricao_cenario": "Campo de data/hora nao interpretavel.",
     "regra_identificacao": "Valor nao converte para data/hora.", "tratamento_esperado": "Registrar oportunidade; nao interromper.",
     "acao_aplicacao": "REGISTRAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 100},
    {"tipo_problema": "INCONSISTENCIA_HORARIO", "descricao_cenario": "Horario final anterior ao inicial.",
     "regra_identificacao": "fim < inicio em par de tempo.", "tratamento_esperado": "Registrar oportunidade; nao interromper.",
     "acao_aplicacao": "REGISTRAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 100},
    {"tipo_problema": "DATA_FORA_DO_PERIODO", "descricao_cenario": "Data de referencia fora da janela solicitada.",
     "regra_identificacao": "data fora de [inicio, fim].", "tratamento_esperado": "Telemetria tecnica; manter fora da visao operacional.",
     "acao_aplicacao": "TELEMETRIA", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 200},
    {"tipo_problema": "DADO_INCOMPLETO", "descricao_cenario": "Registro concluido sem campo dependente obrigatorio.",
     "regra_identificacao": "Status concluido sem data de conclusao (ex.: pesquisas).", "tratamento_esperado": "Registrar oportunidade; nao interromper.",
     "acao_aplicacao": "REGISTRAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 100},
    {"tipo_problema": "IDENTIFICACAO_COLABORADOR", "descricao_cenario": "Nome de colaborador com espacos externos (cosmetico).",
     "regra_identificacao": "Nome difere apos strip.", "tratamento_esperado": "Nao gerar oportunidade (ruido cosmetico).",
     "acao_aplicacao": "TELEMETRIA", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 200},
    {"tipo_problema": "IDENTIFICACAO_AMBIGUA", "descricao_cenario": "Mesmo nome normalizado associado a usuarios distintos.",
     "regra_identificacao": "nome_normalizado -> mais de um usuario.", "tratamento_esperado": "Registrar oportunidade de ambiguidade; nao interromper.",
     "acao_aplicacao": "ALERTAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 50},
    {"tipo_problema": "VOLUME_OPORTUNIDADES_TRUNCADO", "descricao_cenario": "Volume de evidencias truncado para proteger a esteira.",
     "regra_identificacao": "Numero de ocorrencias acima do limite de evidencias.", "tratamento_esperado": "Telemetria tecnica; contagem preservada em evento, nao como oportunidade.",
     "acao_aplicacao": "TELEMETRIA", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 200},
    # --- Regra operacional ativa (governada por regra_configuracao; esta entrada so'
    # cobre o texto/severidade exibidos, igual ja' estava em produção). ---
    {"tipo_problema": "HORAS_AUSENTES", "descricao_cenario": "Colaborador possui jornada sem registro correspondente.",
     "regra_identificacao": "Campo horas_nao_registradas da Platina PDOH conforme a condição, o tempo mínimo e as exceções cadastrados em regra_configuracao.",
     "tratamento_esperado": "Validar o período sem registro com o colaborador.",
     "acao_aplicacao": "ALERTAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 10},
    # --- Fallbacks silenciosos elevados a oportunidade rastreavel ---
    {"tipo_problema": "CHECKOUT_AUSENTE", "descricao_cenario": "Check-out ausente; o legado assume 23:59:00 para continuar.",
     "regra_identificacao": "checkin.hora_saida nula.", "tratamento_esperado": "Corrigir o check-out na origem/operacao; o valor 23:59 e um fallback tecnico.",
     "acao_aplicacao": "ALERTAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 60},
    {"tipo_problema": "PESQUISA_CAMPOS_NULOS", "descricao_cenario": "Campo obrigatorio de pesquisa nulo; o legado usa data tecnica 1999-01-01.",
     "regra_identificacao": "Campo obrigatorio (config de qualidade) nulo em painel_pesquisas_bracell.", "tratamento_esperado": "Corrigir o cadastro da pesquisa na origem; a data 1999 e um fallback tecnico.",
     "acao_aplicacao": "ALERTAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 60},
    # --- Falha de parametrizacao (cenario sem regra cadastrada) ---
    {"tipo_problema": "FALHA_PARAMETRIZACAO", "descricao_cenario": "Cenario identificado sem regra de tratamento cadastrada.",
     "regra_identificacao": "resolver_tratativa retornou vazio para um cenario detectado.", "tratamento_esperado": "Registrar oportunidade para cadastro de regra; nao interromper.",
     "acao_aplicacao": "ALERTAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 20},
    # --- De/Para: valor de origem sem padronizacao cadastrada ---
    {"tipo_problema": "VALOR_SEM_PADRONIZACAO", "descricao_cenario": "Valor recebido da origem sem De/Para cadastrado.",
     "regra_identificacao": "valor_origem de um processo/campo governado por De/Para nao encontrado (ATIVO).",
     "tratamento_esperado": "Manter comportamento atual e registrar oportunidade para cadastro do De/Para.",
     "acao_aplicacao": "ALERTAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 40},
    # --- Criterio de identificacao de lider (consultado pelo orquestrador) ---
    {"tipo_problema": "CRITERIO_LIDER",
     "descricao_cenario": "Criterio de perfil que identifica lideranca por processador (pre-checagem do orquestrador).",
     "regra_identificacao": "{\"lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py\": \"LIDER EXCLUSIVO\", \"lideres_pdoh_bracell.py\": \"PROMOTORES LIDERES\"}",
     "tratamento_esperado": "Orquestrador usa estes perfis na pre-checagem de ausencia de lideres. Deve espelhar o filtro interno dos processadores travados.",
     "acao_aplicacao": "IDENTIFICAR", "permite_processamento": 1, "necessita_aprovacao": 0, "prioridade": 10},
]

# Classificacao operacional por tipo (ex-parametrizavel via regra_tratativa; fixa em codigo agora).
# OPORTUNIDADE = exige acao; ALERTA = qualidade/padronizacao (fora da fila operacional);
# TELEMETRIA = tecnico/auditoria; CONFIGURACAO = regra de apoio (nao vira oportunidade).
CLASSIFICACAO_POR_TIPO: dict[str, str] = {
    "CADASTRO_UF_AUSENTE": "ALERTA",
    "JORNADA_NAO_ENCONTRADA": "OPORTUNIDADE",
    "CAMPO_OBRIGATORIO_VAZIO": "ALERTA",
    "COLUNA_OBRIGATORIA_AUSENTE": "TELEMETRIA",
    "DATA_HORA_INVALIDA": "ALERTA",
    "DADO_INCOMPLETO": "ALERTA",
    "FALHA_PARAMETRIZACAO": "CONFIGURACAO",
    "HORAS_AUSENTES": "OPORTUNIDADE",
    "CHECKOUT_AUSENTE": "OPORTUNIDADE",
    # Ausencia de cadastro de lideranca da marca/periodo: nao tem colaborador
    # responsavel e nao e' falha de execucao individual -> governanca, fora da fila.
    "SEM_LIDERES_NO_PERIODO": "CONFIGURACAO",
    "DADO_FORA_DO_PADRAO": "ALERTA",
    "VALOR_SEM_PADRONIZACAO": "ALERTA",
    "DIVERGENCIA_CADASTRAL": "ALERTA",
    "IDENTIFICACAO_AMBIGUA": "ALERTA",
    "COLABORADOR_SEM_CLASSIFICACAO": "ALERTA",
    "PDV_SEM_IDENTIFICADOR": "ALERTA",
    "PDV_NOME_DIVERGENTE_MESMO_ID": "ALERTA",
    # Sem impacto comprovado no PDOH: 0 pesquisas "Respondida" com responsavel nulo.
    "PESQUISA_CAMPOS_NULOS": "TELEMETRIA",
    # Artefato do hash da camada de identidade: 0 colisoes de id_pdv reais na origem.
    "PDV_MESMO_NOME_IDS_DISTINTOS": "TELEMETRIA",
    # Caso geral (pesquisas: expiracao truncada as 00:00) e' convencao sistemica.
    # A excecao por origem (check-in/check-out) esta em EXCECAO_ORIGEM_POR_TIPO.
    "INCONSISTENCIA_HORARIO": "TELEMETRIA",
    "REGISTRO_DUPLICADO": "TELEMETRIA",
    "DATA_FORA_DO_PERIODO": "TELEMETRIA",
    "VOLUME_OPORTUNIDADES_TRUNCADO": "TELEMETRIA",
    "IDENTIFICACAO_COLABORADOR": "TELEMETRIA",
    "CRITERIO_LIDER": "CONFIGURACAO",
}
TITULO_POR_TIPO: dict[str, str] = {
    "CADASTRO_UF_AUSENTE": "UF nao preenchida",
    "JORNADA_NAO_ENCONTRADA": "Jornada nao cadastrada",
    "CAMPO_OBRIGATORIO_VAZIO": "Campo obrigatorio vazio",
    "COLUNA_OBRIGATORIA_AUSENTE": "Coluna obrigatoria ausente",
    "DATA_HORA_INVALIDA": "Data/hora invalida",
    "DADO_INCOMPLETO": "Registro incompleto",
    "FALHA_PARAMETRIZACAO": "Cenario sem regra cadastrada",
    "HORAS_AUSENTES": "Horas ausentes",
    "CHECKOUT_AUSENTE": "Check-out nao registrado",
    "SEM_LIDERES_NO_PERIODO": "Sem lideres no periodo",
    "DADO_FORA_DO_PADRAO": "Informacao fora do padrao",
    "VALOR_SEM_PADRONIZACAO": "Valor sem padronizacao (De/Para)",
    "DIVERGENCIA_CADASTRAL": "Divergencia cadastral",
    "IDENTIFICACAO_AMBIGUA": "Identificacao ambigua",
    "COLABORADOR_SEM_CLASSIFICACAO": "Colaborador sem classificacao",
    "PDV_SEM_IDENTIFICADOR": "PDV sem identificador",
    "PDV_NOME_DIVERGENTE_MESMO_ID": "PDV com nomes divergentes",
    "PDV_MESMO_NOME_IDS_DISTINTOS": "Mesmo nome de PDV, ids distintos",
    "PESQUISA_CAMPOS_NULOS": "Campo obrigatorio de pesquisa ausente",
    "INCONSISTENCIA_HORARIO": "Inconsistencia de horario",
    "REGISTRO_DUPLICADO": "Registro duplicado (tecnico)",
    "DATA_FORA_DO_PERIODO": "Data fora do periodo (tecnico)",
    "VOLUME_OPORTUNIDADES_TRUNCADO": "Volume truncado (tecnico)",
    "IDENTIFICACAO_COLABORADOR": "Nome com espacos (cosmetico)",
    "CRITERIO_LIDER": "Criterio de lider (configuracao)",
}
SEVERIDADE_POR_TIPO: dict[str, str] = {
    "CADASTRO_UF_AUSENTE": "BAIXA",
    "COLUNA_OBRIGATORIA_AUSENTE": "CRITICA",
    "CAMPO_OBRIGATORIO_VAZIO": "ALTA", "INCONSISTENCIA_HORARIO": "ALTA",
    "DATA_HORA_INVALIDA": "ALTA", "DADO_INCOMPLETO": "ALTA", "JORNADA_NAO_ENCONTRADA": "ALTA",
    "IDENTIFICACAO_AMBIGUA": "ALTA", "DIVERGENCIA_CADASTRAL": "ALTA", "PDV_MESMO_NOME_IDS_DISTINTOS": "ALTA",
    "SEM_LIDERES_NO_PERIODO": "BAIXA", "IDENTIFICACAO_COLABORADOR": "BAIXA",
}

# Linguagem de negocio exibida ao lider: {tipo: (titulo_exibicao, impacto_negocio,
# acao_recomendada)}. Telemetria nao tem acao operacional (None), por definicao.
TEXTOS_NEGOCIO_POR_TIPO: dict[str, tuple[str, str, str | None]] = {
    # --- Oportunidades ---
    "HORAS_AUSENTES": ("Horas ausentes", "Horas não registradas",
        "Validar com o colaborador o período sem registro e orientar o apontamento correto das atividades."),
    "CHECKOUT_AUSENTE": ("Checkout não registrado", "Tempo em loja",
        "Validar a ausência de checkout com o colaborador e orientar o registro correto da saída."),
    "CAMPO_OBRIGATORIO_VAZIO": ("Campo obrigatório não preenchido", "Jornada",
        "Verificar o registro incompleto com o colaborador e orientar o preenchimento do campo na origem."),
    # Base = caso geral (pesquisas, TELEMETRIA); o texto operacional do check-in esta
    # em TEXTOS_EXCECAO_ORIGEM_POR_TIPO, junto da excecao de classificacao.
    "INCONSISTENCIA_HORARIO": ("Horário inconsistente", "Sem impacto operacional", None),
    "JORNADA_NAO_ENCONTRADA": ("Jornada semanal não cadastrada", "Produtividade",
        "Cadastrar a jornada semanal do colaborador; sem ela o cálculo assume 44 horas."),
    "SEM_LIDERES_NO_PERIODO": ("Liderança não identificada no período", "Cobertura de liderança",
        "Revisar o cadastro de liderança da marca para o período."),
    "DATA_HORA_INVALIDA": ("Data ou hora inválida", "Jornada",
        "Corrigir o registro de data e hora na origem."),
    "DADO_INCOMPLETO": ("Registro incompleto", "Qualidade do registro",
        "Completar o registro na origem."),
    "COLUNA_OBRIGATORIA_AUSENTE": ("Coluna obrigatória ausente na fonte", "Processamento",
        "Acionar o responsável pela integração para restaurar a coluna na fonte."),
    "FALHA_PARAMETRIZACAO": ("Cenário sem regra cadastrada", "Governança",
        "Cadastrar a regra de tratamento para o cenário identificado."),
    # --- Alertas ---
    "DADO_FORA_DO_PADRAO": ("Informação fora do padrão", "Qualidade cadastral",
        "Corrigir o valor no cadastro de origem."),
    "VALOR_SEM_PADRONIZACAO": ("Valor sem padronização", "Qualidade cadastral",
        "Cadastrar a correspondência no De/Para."),
    "DIVERGENCIA_CADASTRAL": ("Divergência cadastral", "Qualidade cadastral",
        "Conferir e unificar o cadastro na origem."),
    "IDENTIFICACAO_AMBIGUA": ("Identificação ambígua", "Vínculo do colaborador",
        "Revisar o cadastro para garantir identificação única do colaborador."),
    "COLABORADOR_SEM_CLASSIFICACAO": ("Colaborador sem perfil definido", "Vínculo do colaborador",
        "Atribuir o perfil de acesso no cadastro do colaborador."),
    "PDV_SEM_IDENTIFICADOR": ("PDV sem identificador", "Qualidade cadastral",
        "Cadastrar o identificador do PDV na origem."),
    "PDV_NOME_DIVERGENTE_MESMO_ID": ("PDV com nomes divergentes", "Qualidade cadastral",
        "Padronizar o nome do PDV no cadastro."),
    "CADASTRO_UF_AUSENTE": ("UF não preenchida", "Qualidade cadastral",
        "Preencher a UF no cadastro do colaborador."),
    # --- Telemetria (sem acao operacional) ---
    "REGISTRO_DUPLICADO": ("Registro duplicado", "Sem impacto operacional", None),
    "DATA_FORA_DO_PERIODO": ("Data fora do período", "Sem impacto operacional", None),
    "VOLUME_OPORTUNIDADES_TRUNCADO": ("Volume de evidências truncado", "Sem impacto operacional", None),
    "IDENTIFICACAO_COLABORADOR": ("Nome com espaços extras", "Sem impacto operacional", None),
    "PESQUISA_CAMPOS_NULOS": ("Pesquisa com campo nulo", "Sem impacto operacional", None),
    "PDV_MESMO_NOME_IDS_DISTINTOS": ("PDV com mesmo nome e identificadores distintos", "Sem impacto operacional", None),
    # --- Configuracao ---
    "CRITERIO_LIDER": ("Critério de liderança", "Configuração", None),
}

# Textos da excecao por origem: {tipo: (impacto_negocio, acao_recomendada)}. Valem so
# quando a origem do registro e' a `origem_excecao` da regra -- os mesmos casos em que a
# classificacao muda. Mantem a mensagem coerente com a classificacao exibida.
TEXTOS_EXCECAO_ORIGEM_POR_TIPO: dict[str, tuple[str, str | None]] = {
    # Check-in/check-out: par de horarios impossivel afeta a jornada (OPORTUNIDADE).
    "INCONSISTENCIA_HORARIO": ("Jornada",
        "Conferir com o colaborador os horários de entrada e saída e corrigir o registro na origem."),
    # Pesquisas: nao operacional (TELEMETRIA), portanto sem acao para o lider.
    "CAMPO_OBRIGATORIO_VAZIO": ("Sem impacto operacional", None),
}

# Excecao de classificacao por origem do dado: {tipo: (tabela_origem, classificacao)}.
# Um mesmo cenario pode ser tecnico em uma origem e operacional em outra; a regra
# continua unica no catalogo (uma linha por marca+tipo), com a excecao declarada nela.
EXCECAO_ORIGEM_POR_TIPO: dict[str, tuple[str, str]] = {
    # Par temporal impossivel no check-in/check-out e' falha operacional real;
    # em pesquisas, e' a expiracao truncada as 00:00 (convencao da propria base).
    "INCONSISTENCIA_HORARIO": ("relatorio_checkin_bracell", "OPORTUNIDADE"),
    # Campo obrigatorio ausente em pesquisas (responsavel) nao e' operacional: nao
    # impacta PDOH, produtividade nem jornada e nao impede o processamento.
    # Em check-in (hora_entrada) segue OPORTUNIDADE.
    "CAMPO_OBRIGATORIO_VAZIO": ("painel_pesquisas_bracell", "TELEMETRIA"),
}

_COLUNAS_REGRA = (
    "regra_id", "marca", "tipo_problema", "classificacao", "titulo", "severidade_padrao",
    "titulo_exibicao", "impacto_negocio", "acao_recomendada", "responsavel_padrao", "origem",
    "campo_afetado", "criterios_operacionais",
    "impacto_negocio_excecao", "acao_recomendada_excecao",
    "origem_excecao", "classificacao_excecao",
    "descricao_cenario", "regra_identificacao", "tratamento_esperado", "acao_aplicacao",
    "permite_processamento", "necessita_aprovacao", "prioridade", "status_regra",
)

_POR_TIPO: dict[str, dict[str, Any]] = {regra["tipo_problema"]: regra for regra in REGRAS_PADRAO}

# Reconciliacao com os valores que ja estavam em producao em `regra_tratativa` antes desta
# migracao (conferido campo a campo contra o banco em 2026-09-23): alguns registros foram
# editados/ajustados diretamente no banco em algum momento e nunca voltaram para o codigo
# fonte (bootstrap_regras so' faz INSERT IGNORE, nunca sobrescreve). Estas sobreposicoes
# existem so' para nao mudar nada do que ja' e' exibido hoje; qualquer regra nova daqui pra
# frente deve nascer certa nos dicionarios acima, sem precisar de ajuste aqui.
_AJUSTES_LIVE: dict[str, dict[str, Any]] = {
    "CAMPO_OBRIGATORIO_VAZIO": {
        "impacto_negocio": "Qualidade do registro de origem",
        "acao_recomendada": "Conferir se o campo se aplica ao registro e corrigir o cadastro na origem.",
        "acao_aplicacao": "ALERTAR",
    },
    "CRITERIO_LIDER": {"responsavel_padrao": "Governanca de dados"},
    "FALHA_PARAMETRIZACAO": {"responsavel_padrao": "Governanca de dados"},
    "SEM_LIDERES_NO_PERIODO": {"responsavel_padrao": "Governanca de dados", "acao_aplicacao": "IDENTIFICAR"},
    "INCONSISTENCIA_HORARIO": {"acao_aplicacao": "TELEMETRIA"},
    "PDV_MESMO_NOME_IDS_DISTINTOS": {"acao_aplicacao": "TELEMETRIA"},
    "PESQUISA_CAMPOS_NULOS": {"acao_aplicacao": "TELEMETRIA"},
    "HORAS_AUSENTES": {"origem": "PDOH Platina", "campo_afetado": "horas_nao_registradas"},
}

# CADASTRO_UF_AUSENTE existe em codigo (bracell/src/cadastral_alerts.py detecta o cenario)
# mas nunca foi semeado em `regra_tratativa` (bootstrap_regras so' roda INSERT IGNORE, e
# ninguem rodou depois que a regra foi escrita) -- hoje, se o detector gerar um achado
# desse tipo, ele fica sem classificacao resolvida (mesmo efeito de resolver_tratativa
# retornar None). Excluido daqui de propos'ito, so' para nao mudar esse comportamento
# como efeito colateral desta migracao: ativar a regra e' uma decisao separada, nao
# incluida aqui. Remover desta lista quando isso for decidido.
_PENDENTE_DE_ATIVACAO = frozenset({"CADASTRO_UF_AUSENTE"})


def regra_id_para(marca: str, tipo_problema: str) -> str:
    """UUID deterministico -- igual ao que semeava `regra_tratativa.regra_id`."""

    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{marca}:{tipo_problema}"))


def montar_regra(tipo_problema: str, marca: str = MARCA_PADRAO) -> dict[str, Any] | None:
    """Monta o registro completo (mesmas colunas de `regra_tratativa`) para um tipo.

    Unica funcao que combina os dicionarios de apoio (classificacao/titulo/severidade/
    textos) -- nao duplicar esta montagem em outro lugar.
    """

    if tipo_problema in _PENDENTE_DE_ATIVACAO:
        return None
    base = _POR_TIPO.get(tipo_problema)
    if not base:
        return None
    titulo_exibicao, impacto_negocio, acao_recomendada = TEXTOS_NEGOCIO_POR_TIPO.get(
        tipo_problema, (None, None, None)
    )
    impacto_excecao, acao_excecao = TEXTOS_EXCECAO_ORIGEM_POR_TIPO.get(tipo_problema, (None, None))
    origem_excecao, classificacao_excecao = EXCECAO_ORIGEM_POR_TIPO.get(tipo_problema, (None, None))
    classificacao = CLASSIFICACAO_POR_TIPO.get(tipo_problema)
    montado = {
        "regra_id": regra_id_para(marca, tipo_problema),
        "marca": marca,
        "tipo_problema": tipo_problema,
        "classificacao": classificacao,
        "titulo": TITULO_POR_TIPO.get(tipo_problema),
        "severidade_padrao": SEVERIDADE_POR_TIPO.get(tipo_problema, "MEDIA"),
        "titulo_exibicao": titulo_exibicao,
        "impacto_negocio": impacto_negocio,
        "acao_recomendada": acao_recomendada,
        "responsavel_padrao": (
            "Lider da operacao" if classificacao == "OPORTUNIDADE" or tipo_problema == "INCONSISTENCIA_HORARIO"
            else "Responsavel pelo cadastro"
        ),
        "origem": "Fonte identificada no achado",
        "campo_afetado": "Campo identificado na evidencia",
        "criterios_operacionais": (
            {"evidencia": {"resolucao_completa": True, "vigente": True, "perfil_elegivel": True}}
            if tipo_problema == "JORNADA_NAO_ENCONTRADA" else {}
        ),
        "impacto_negocio_excecao": impacto_excecao,
        "acao_recomendada_excecao": acao_excecao,
        "origem_excecao": origem_excecao,
        "classificacao_excecao": classificacao_excecao,
        "descricao_cenario": base["descricao_cenario"],
        "regra_identificacao": base["regra_identificacao"],
        "tratamento_esperado": base["tratamento_esperado"],
        "acao_aplicacao": base["acao_aplicacao"],
        "permite_processamento": base["permite_processamento"],
        "necessita_aprovacao": base["necessita_aprovacao"],
        "prioridade": base["prioridade"],
        "status_regra": "ATIVA",
    }
    montado.update(_AJUSTES_LIVE.get(tipo_problema, {}))
    return montado


def resolver_regra(tipo_problema: str, marca: str = MARCA_PADRAO) -> dict[str, Any] | None:
    """Equivalente a `resolver_tratativa`, sem consulta ao banco."""

    return montar_regra(tipo_problema, marca)


def listar_regras(marca: str = MARCA_PADRAO) -> list[dict[str, Any]]:
    """Equivalente a `carregar_regras_tratativa`, sem consulta ao banco."""

    return [regra for tipo in sorted(_POR_TIPO) if (regra := montar_regra(tipo, marca)) is not None]


def classificacao_efetiva(regra: dict[str, Any] | None, tabela_origem: str | None) -> str | None:
    """Aplica a excecao por origem declarada na propria regra do catalogo."""

    if not regra:
        return None
    origem = regra.get("origem_excecao")
    if origem and tabela_origem and origem == tabela_origem and regra.get("classificacao_excecao"):
        return regra["classificacao_excecao"]
    return regra.get("classificacao")
