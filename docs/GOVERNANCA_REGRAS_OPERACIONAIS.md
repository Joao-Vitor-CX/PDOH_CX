# Governança configurável de regras operacionais

## Escopo e decisão de implementação

A camada foi criada em paralelo ao processamento atual. Ela não é consultada pelos
processadores, não altera o cálculo do PDOH e não autoriza geração automática de
oportunidades. O cadastro inicial usa `status = EM_VALIDACAO`, e os campos
`geracao_automatica_ativa`, `gera_oportunidade` e `aplicado_no_processamento` iniciam
como `false`.

A API continua somente leitura. O endpoint existente
`GET /api/v2/configuracoes/operacao` foi ampliado para entregar regras, condições,
exceções, tratativas, fontes semânticas, prioridade de jornada e histórico. Nenhum
endpoint foi criado.

## Mapeamento da estrutura anterior

| Regra/cenário | Onde estava definido | Fonte e campo | Critério atual | Resultado esperado |
|---|---|---|---|---|
| `CHECKIN_ENTRADA_AUSENTE` | Candidato em `bracell/src/operational_detectors.py`; comprovação em `shared/evidence_engine.py`; matriz parcial em `configuracao_evidencia_regra` | papel `status_day`, `primeiro_checkin`; cadastro e jornada como apoio | entrada vazia, colaborador vigente, dia trabalhado, jornada resolvida e sem abono | confirmado, não aplicável ou indisponível |
| `CHECKOUT_AUSENTE` | Detecção/fallback legado em `bracell/src/legacy_fallbacks.py`; comprovação no motor de evidências | papel `checkin`, `hora_saida`; `status_day` como apoio | houve entrada, saída real ausente, colaborador vigente, dia trabalhado e sem abono | confirmado, não aplicável ou indisponível |
| `INCONSISTENCIA_HORARIO` | Detecção em `bracell/src/data_quality.py`; roteamento e textos em `bracell/src/observability.py` | papel `checkin`, par `hora_entrada` + `hora_saida` | saída anterior à entrada, com contexto de jornada | confirmado, não aplicável ou indisponível |
| `JORNADA_NAO_ENCONTRADA` | Resolução em `shared/journey.py`; captura em `bracell/src/legacy_fallbacks.py`; catálogo em `observability.py` | papel `colaborador`/`jornada`; hoje `nome_pai` e alternativa RAW `nome_do_pai` | nenhuma carga semanal válida nas fontes vigentes | registrar origem consultada e preservar fallback atual |
| cadastro inconsistente | Cenários relacionados `DIVERGENCIA_CADASTRAL` e `CADASTRO_UF_AUSENTE` em `observability.py` e `cadastral_alerts.py`; não havia regra única | papel `colaborador`; campos dependem da divergência | valores incompatíveis entre snapshots/fontes | governança até definição do critério canônico |

Antes desta entrega, o catálogo `regra_tratativa`, a matriz
`configuracao_evidencia`/`configuracao_evidencia_regra`, a configuração de operação e
o fallback já forneciam configuração parcial. Permaneciam fixos no código: a lista de
regras semeadas por `bootstrap_regras`, alguns textos/classificações, os detectores e os
rótulos da prioridade de jornada. Esses pontos foram preservados para não mudar o
processamento; a nova camada agora descreve a decisão futura sem ser executada.

O motor de evidências consome marca, operação, papel semântico, tabela resolvida,
mapeamento de campos, regra, campo esperado, critérios, papéis de apoio, status do dia,
jornada resolvida, justificativas abonáveis e registros de check-in. Ele devolve
`confirmado`, `nao_aplicavel` ou `indisponivel`, junto das verificações e da origem da
jornada.

## Estrutura de dados

| Tabela | Responsabilidade |
|---|---|
| `regra_configuracao` | identidade operacional da regra, escopo, categoria, status, prioridade e comportamento esperado |
| `regra_condicao_configuracao` | condições, exceções e bloqueios referenciando papéis semânticos e campos lógicos |
| `fonte_semantica_configuracao` | resolução central de papel para schema, tabela e campos físicos por marca/operação |
| `regra_tratamento_configuracao` | ação e destino por resultado de evidência, com geração automática explicitamente controlada |
| `jornada_prioridade_configuracao` | ordem proposta de resolução e indicação de fallback, sem conexão com o processador atual |
| `governanca_configuracao_historico` | antes/depois, usuário, data e motivo de cada cadastro ou alteração |

`shared/governance_config.py` executa cadastro/alteração e auditoria na mesma transação.
Reaplicar os mesmos valores não produz atualização nem evento duplicado. Uma futura API
de escrita deverá usar essa rotina ou uma garantia transacional equivalente.

## Configuração inicial

Foram preparados os códigos `CHECKIN_ENTRADA_AUSENTE`, `CHECKOUT_AUSENTE`,
`INCONSISTENCIA_HORARIO`, `JORNADA_NAO_ENCONTRADA` e `CADASTRO_INCONSISTENTE`. Cada um
possui condição principal, cinco bloqueios operacionais e três resultados de tratamento:

- `CONFIRMADO` aponta para `OPORTUNIDADE_FUTURA`, com `gera_oportunidade = false`;
- `NAO_APLICAVEL` aponta para `GOVERNANCA`;
- `INDISPONIVEL` aponta para `AGUARDAR_DADOS`.

Os bloqueios cadastrados cobrem afastamento, atestado válido, ausência de roteiro,
perfil não operacional e jornada não resolvida.

Para BRACELL foram mapeados os papéis `checkin`, `checkout`, `jornada`, `colaborador`,
`visitas` e `pesquisas`. Check-in, checkout, jornada e colaborador têm fontes principal
e alternativa. FLORA e TANGARA possuem os mesmos papéis reservados com status
`PENDENTE_MAPEAMENTO`; nenhum nome físico foi inventado.

A ordem proposta de jornada é Involves, RAW operacional, configuração da operação e
jornada padrão. Todas as etapas estão em validação e com
`aplicado_no_processamento = false`.

## Levantamento dos endpoints existentes

| Endpoint | Fonte | Responsabilidade | Consumidor atual | Decisão preliminar |
|---|---|---|---|---|
| `GET /api/v2/configuracoes/operacao` | configurações, catálogo, fallback e novas tabelas de governança | visão completa somente leitura da operação | telas Configurações/Governança | manter; foi reutilizado nesta entrega |
| `GET /api/v2/configuracoes/evidencias` | `configuracao_evidencia*` | matriz técnica de fontes e critérios | detalhe de evidência/validação | manter; avaliar incorporação futura na visão de operação |
| `GET /api/v1/regras` | `regra_tratativa` | catálogo vigente do motor atual | Parametrizações e apresentação de oportunidades | manter enquanto o motor atual usar o catálogo |
| `GET /api/v1/fallback/resolver` | `regra_fallback_config` | resolver fallback vigente por escopo/data | simulação e auditoria | manter |
| `POST /api/v1/fallback/simular` e `POST /api/fallback/simular` | fallback + evidências existentes | simulação sem escrita e sem recálculo do PDOH | validação técnica | consolidar as duas rotas após decisão de versão |
| `GET /api/v2/pdoh/resumo` | Platina PDOH oficial e auditoria de jornada | indicador, filtros e linhas diárias | dashboard PDOH | manter; estudar view para detalhe de 12 meses |
| `GET /api/v2/pdoh/composicao` | Platina PDOH oficial | composição consolidada | dashboard/integrações | manter |
| `GET /api/v2/pdoh/evolucao` | Platina PDOH oficial | série temporal | gráfico do dashboard | manter |
| `GET /api/v2/pdoh/colaborador/{id}` | Platina + achados | visão individual e impactadores | detalhe do colaborador | manter |
| `GET /api/v2/oportunidades`, `/alertas`, `/telemetria` | achados históricos + catálogo | listas classificadas | serviços operacionais do Front | manter; revisar sobreposição com resumos |
| `GET /api/v2/findings/resumo` | achados históricos | totais por classificação | cabeçalhos operacionais | manter |
| `GET /api/v2/oportunidades/resumo` | oportunidades agrupadas | fila operacional por regra/colaborador | cards operacionais | manter |
| `GET /api/v2/oportunidades/{grupo_id}/detalhes` | oportunidades e status de grupo | ocorrências e contexto do grupo | detalhe/modal futuro | manter; é candidato natural para o modal posterior |
| `GET /api/v2/oportunidades/{grupo_id}/evidencias` | matriz + evidência persistida | comprovação e tratativa recomendada | detalhe operacional | manter |
| `GET /api/v2/alertas/resumo` | alertas agrupados | visão de qualidade de dados | painel de alertas | manter |
| `GET /api/v1/dashboard` | execuções e oportunidades | painel técnico legado | páginas de plataforma | avaliar substituição pela camada v2 |
| `GET /api/v1/execucoes` e `/{id}` | `execucao` | histórico e detalhe de execução | páginas técnicas | manter |
| `GET /api/v1/execucoes/{id}/etapas` | `execucao_etapa` | etapas da execução | rastreabilidade | manter; view pode simplificar consultas compostas |
| `GET /api/v1/execucoes/{id}/fontes` | `execucao_fonte` | fontes efetivamente consumidas | rastreabilidade | manter |
| `GET /api/v1/execucoes/{id}/linhagem` | `saida_linhagem` | linhagem da saída | rastreabilidade | manter; avaliar view por volume |
| `GET /api/v1/alertas` e `/{id}/registros` | alerta/oportunidade | contrato legado de alertas | páginas legadas | avaliar substituição pelas rotas v2 |
| `GET /api/v1/oportunidades`, `/{id}` e `/{id}/historico` | oportunidade e histórico | contrato legado por ocorrência | páginas técnicas | manter durante transição; evitar usar no modal novo |
| `GET /api/v1/de-para` e `/{id}/historico` | de/para e histórico | padronização consultável | Parametrizações | manter |
| `GET /api/v1/colaboradores/{id}` | identidade consolidada | rastreabilidade da pessoa | detalhes técnicos | manter |
| `GET /api/v1/entidades` e `/{id}` | identidade genérica | rastreabilidade de entidades | páginas técnicas | manter; considerar view de consulta |
| `GET /api/v1/health` | conexão de leitura | saúde da API | Docker/orquestração | manter |

## Necessidades futuras e decisões de arquitetura

1. Validar com a liderança os operadores permitidos e a semântica de combinação
   (AND/OR, agrupamento e vigência) antes de conectar a configuração ao motor.
2. Definir se `regra_tratativa` será absorvida por `regra_configuracao` ou continuará
   como catálogo de execução, evitando duas fontes de verdade após a transição.
3. Mapear as tabelas e campos reais de FLORA e TANGARA.
4. Definir autenticação, autorização, aprovação e motivo obrigatório antes de liberar
   escrita no Front; a leitura atual permanece sem edição.
5. Decidir se o histórico ficará no banco de controle, em trilha corporativa externa ou
   em ambos, e qual será sua política de retenção.
6. Definir a vigência temporal das regras, condições, fontes e prioridades.
7. Homologar a ordem de fallback de jornada e o significado de jornada padrão antes de
   marcar qualquer etapa como aplicada no processamento.
8. Consolidar rotas v1/v2 e avaliar views para consultas volumosas somente depois do
   mapeamento conjunto com a liderança.

## Validação executada em 21/09/2026

- banco local: 5 regras, 32 condições/bloqueios, 15 tratativas, 22 mapeamentos de
  fonte, 4 etapas de jornada e 96 eventos de auditoria;
- segunda aplicação do cadastro: zero alterações, comprovando idempotência;
- oportunidades antes/depois do cadastro: 59.618 / 59.618;
- validação live da API: 843 verificações aprovadas e hashes preservados durante a
  consulta;
- reconciliação BRACELL: 300 registros, PDOH 72,8326% e efetividade 68,818%, iguais à
  fonte tratada já validada;
- testes: 126 testes da API aprovados (1 ignorado), 69 testes da esteira aprovados e 16
  testes do Front aprovados;
- TypeScript, lint, build de produção e fluxo live pelo proxy do Front aprovados.
