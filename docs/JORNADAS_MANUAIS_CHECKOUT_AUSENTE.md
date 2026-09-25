# Jornadas manuais — CHECKOUT_AUSENTE

Implementado em 23/09/2026. Alterações limitadas à configuração, persistência e formulário. **A migração MySQL e a atualização dos privilégios ainda não foram aplicadas ao ambiente real.** Homologação visual pendente por ausência de navegador conectado.

## Arquivos alterados nesta etapa

- `api/app/schedule_config.py`: contrato, validação, leitura combinada de cadastro e configuração manual, gravação auditada e isolamento por configuração/marca/operação.
- `api/app/rule_admin.py`: somente a lista de colunas permitidas para UPDATE da tabela de jornadas. Nenhuma função de geração ou regra foi alterada.
- `api/scripts/provision_operational_schedule.py`: provisionamento passa a incluir a migração 019 antes de atualizar as permissões restritas.
- `docker/mysql/migrations/019_jornadas_manuais.sql`: migração aditiva/idempotente de metadados.
- `frontend/src/services/governance-api.ts`: contrato dos campos adicionais.
- `frontend/src/lib/rule-settings.ts`: rascunho, validação, diff por ID e histórico legível. As funções de prévia e duração não foram alteradas.
- `frontend/components/platform/rule-settings.tsx`: adicionar jornada habilitado, formulário manual, origem visual, automáticas somente leitura, intervalo persistido, prévia e carregamento das jornadas efetivamente retornadas pela API.
- `api/tests/test_operational_schedule.py`: fixture e testes de persistência/edição/isolamento/duplicidade.
- `api/tests/test_manual_schedule_flow.py`: teste integrado reproduzível em SQLite em memória.
- `frontend/scripts/rule-settings.test.ts`: testes dos metadados, identidade, validação e prévia.
- Este relatório.

## Estrutura e compatibilidade

A tabela existente `configuracao_jornada_operacao` continua vinculada por `configuracao_id`, com unicidade `(configuracao_id, jornada)`. Não foi criado endpoint ou tabela paralela.

| Campo | Persistência |
| --- | --- |
| Nome | Novo `nome_jornada VARCHAR(120) NULL` |
| Carga semanal | Existente `jornada DECIMAL(8,2)` |
| Entrada/saída | Existentes `hora_entrada_padrao` / `hora_saida_padrao` |
| Intervalo | Novo `intervalo CHAR(5) NULL`, formato HH:MM |
| Origem | Novo `origem_configuracao VARCHAR(24)`, padrão CADASTRO_OPERACIONAL; alternativa MANUAL |

A migração não reescreve horas, ativações, regras ou cálculos existentes. Intervalos antigos permanecem desconhecidos (NULL); a tela não inventa um intervalo salvo ou uma prévia quando ele não existe.

O mesmo POST/PATCH de `/api/v2/configuracoes/regras` salva a configuração. A leitura de `/api/v2/configuracoes/operacao` devolve as duas origens. Jornadas manuais não exigem presença no cadastro consolidado. IDs são validados dentro da configuração e do escopo. A origem não pode ser trocada em uma linha já persistida. Alterar a carga de uma jornada manual preserva seu ID. Duplicidade é recusada para não introduzir prioridade/seleção nova no motor.

As jornadas automáticas são somente leitura no formulário. Jornadas manuais permitem editar nome, carga, horários, intervalo e ativação. Rascunhos novos podem ser removidos; jornadas já salvas podem ser desativadas. Nenhuma exclusão de dados persistidos foi adicionada.

O intervalo é armazenado para a configuração e prévia visual; **não foi introduzido como novo insumo do cálculo PDOH ou da decisão de ausência**. O motor continua consumindo carga semanal e horários esperados como antes. Criar uma configuração manual não inventa a jornada oficial de um colaborador: a resolução cadastral continua obrigatória.

## Teste controlado

`api/tests/test_manual_schedule_flow.py::ManualScheduleFlowTest.test_manual_44_fallback_generation_and_notification_api`:

1. JSON sintético em memória: COLABORADOR TESTE 44H, carga 44, entrada 08:00, checkout null.
2. Sem jornada no cadastro consolidado do fixture, a API adiciona via PATCH à CHECKOUT_AUSENTE já existente a configuração Manual 44H / 08:00 / 19:00 / intervalo 01:00 / MANUAL. Comparação integral das tabelas de regras, condições e tratamentos antes/depois comprova que nenhuma regra foi criada ou modificada; o ID da regra permanece o mesmo.
3. O resolvedor real recebe fonte principal sem horas e fonte secundária com 44H.
4. Resultado: RESOLVIDA, 44H, fonte secundária.
5. Executor e dispatcher reais, com adaptação de sintaxe MySQL para SQLite usada pelos testes existentes: uma oportunidade criada, reexecução gera zero duplicatas.
6. A evidência comprova saída esperada 19:00; saída observada permanece null; severidade MEDIA preservada.
7. GET do período, resumo e evidências retorna um grupo CHECKOUT_AUSENTE, com resultado confirmado.
8. Respostas reais capturadas foram consumidas pelo serviço TypeScript de produção do sino, usando transporte fetch de teste: contador 0 → 1 → 0 após leitura, detalhes confirmados e horário 19:00.
9. Prévia: 660 minutos brutos (11h), 600 líquidos (10h), intervalo 60 minutos.

Não houve navegador montado neste teste: a integração da API com o consumidor e a lógica do contador foram comprovadas, mas não cliques, captura ou renderização visual do sino.

## Resultados e limites

- Build aprovado; aviso de bundle acima de 500 kB.
- Lint aprovado.
- 60 testes frontend aprovados.
- 74 testes Python aprovados no comando abaixo (inclui testes herdados/importados pelo fixture):
  `python -B -m unittest api.tests.test_operational_schedule api.tests.test_manual_schedule_flow api.tests.test_rule_admin api.tests.test_regras_configuradas`.
- A execução ampliada incluindo `api.tests.test_findings` executou 110 testes e apresentou 10 falhas nessa suíte: recusa sem comprovação, duplicação/reclassificação, filtros de colaborador/período/severidade, legado, classificação forçada, resumo, roteamento de tipos e seleção por marca. Não foram corrigidas alterando o motor. Não se declara aprovação global da suíte.
- Verificação de navegador retornou `apps: []`, `browsers: []`. Validação visual pendente.
- Não foi executada a migração em MySQL real; a persistência foi comprovada no esquema equivalente em SQLite.

## Preservação e limpeza

Comparação SHA-256 antes/depois: todos os 34 arquivos Python de `bracell/` e `shared/` permaneceram idênticos, incluindo motor, dispatcher, resolvedor, regras e cálculo PDOH. Principais hashes:

- `bracell/src/findings.py`: `CA0E943E1606B10B1C2926C8557C4C89ABDF6EEDD6D3FEE372E81EBA116F83D3`
- `bracell/src/operational_schedule.py`: `094FA3A1D5944F45C58A526407A4938ABA822F5E875A50DAA96A0BB751177849`
- `bracell/lideres_pdoh_bracell.py`: `A3F6B855A810A3FA5DAAA6F99A3AFE39B36B28635403C17AD70305737AD68ECD`
- `bracell/lideres_pdoh_bracell_sem_atestados_e_declaracoes_medicas.py`: `EE26573218634BB7BD858007EC84BCF1A16046904AB12A6BAF04FA0444A11F4D`
- `bracell/pdoh_bracell.py`: `B3015734C19AC708B021AAE3F353AA0992868936D6F210DCDC6896D11693EC05`
- `bracell/pdoh_bracell_sem_atestados_e_declaracoes_medicas.py`: `31DF17C3A7192CCC37370797D30980433D016FACD4F320FB15997F122DF6578B`
- `shared/journey.py`: `691A36B8D498E462C5509B2CD21FCD6B2BA2368C3769874CE947E6206A7A9AFD`
- `shared/operational_schedule.py`: `9A5A1BE3BD0D0707251DEA068A2D6CCE2A0D91734AFB8DDA5F48219CA9375C77`
- `shared/rule_engine.py`: `88E10E1784D21FD158F7BF47D81AEA4F671BD6A34B4FE07B2C63B3ED3D50CCD0`

Nenhum dado real foi alterado. Os JSONs/dados do teste residiram em memória; a captura temporária `frontend/scripts/manual-flow-temporary.json` e seu consumidor `manual-flow-temporary.ts` foram removidos e sua ausência conferida. O banco SQLite é descartado no cleanup e as substituições de ambiente/transporte são restauradas. Permanecem apenas testes de regressão, código de produção e documentação; não há flag de simulação no frontend de produção.

## Disponibilização no ambiente

### Revalidação do escopo

A jornada é somente configuração operacional do horário esperado da oportunidade única CHECKOUT_AUSENTE. Não foi criado ou ampliado um motor de jornada. No frontend, as origens aparecem como **Operação** e **Manual**, mantendo os códigos persistidos CADASTRO_OPERACIONAL e MANUAL.

Nesta revisão foram alterados apenas o texto/origem de `frontend/components/platform/rule-settings.tsx`, o reforço de invariância em `api/tests/test_manual_schedule_flow.py` e este relatório. A estrutura de persistência implementada anteriormente foi reutilizada sem novas alterações.

Teste integrado repetido com sucesso: regra existente intacta → configuração manual 44H → fallback secundário → saída esperada 19:00 → uma oportunidade → zero duplicatas. As novas respostas reais da API foram novamente consumidas pelo serviço TypeScript do sino: contador 0 → 1 → 0 após leitura; detalhes confirmados. Build e 74 testes Python aprovados novamente. Os 34 arquivos Python de bracell/shared mantiveram os hashes. O consumidor temporário de revalidação foi removido. Isso não substitui a homologação visual nem a implantação da migração no ambiente real.

Aplicar a migração 019 e reprovisionar a conta restrita de configuração (o script existente `api/scripts/provision_operational_schedule.py` agora faz 017 + 019 + privilégios), depois reiniciar a API para refletir as novas colunas e publicar o frontend. Esse provisionamento é uma operação de implantação, não foi executado nesta validação. Sem a migração, tentativa de salvar jornada manual retorna 503 explícito.
