# Planejamento de reestruturação — Painel PDOH_CX

**Status:** proposta de arquitetura e experiência.  
**Data:** 17/09/2026.  
**Escopo desta etapa:** somente leitura e mapeamento. Nenhuma rota, componente, chamada de API, regra de negócio ou layout foi alterado.

## 1. Diagnóstico executivo

O front-end atual já é uma evolução funcional do protótipo visual. Ele possui uma base sólida e responsiva para consulta: React, TypeScript, Vite, Tailwind/shadcn, estados de carregamento/erro, filtros na URL, validação de contratos com Zod e um shell com menu lateral no desktop e drawer no celular.

O principal desalinhamento é de dados e hierarquia de navegação, não de identidade visual:

- a navegação ainda prioriza a antiga divisão `Oportunidades / Dashboard / Execuções`;
- as visões de Alertas e Telemetria existem apenas como abas dentro de Oportunidades;
- o cliente ainda consulta a API v1 e reclassifica registros usando o catálogo atual no navegador;
- a API v2 já separa `OPORTUNIDADE`, `ALERTA` e `TELEMETRIA`, mas não é consumida pelo front-end;
- alguns indicadores solicitados para gestão — PDOH geral, produtividade, jornada, equipe e região — ainda não possuem contrato nem definição de cálculo disponíveis para a interface.

Portanto, a próxima implementação deve priorizar **a troca da fonte de dados para os contratos v2**, e não apenas reorganizar cartões. Assim a interface não voltará a misturar categorias que o backend acabou de separar.

## 2. Estrutura atual

| Aspecto | Situação atual |
| --- | --- |
| Base técnica | React 19, TypeScript, Vite 8, React Router 7, Tailwind 4, shadcn/Base UI, Lucide e Zod. |
| Dados | Consultas reais, sem mocks de domínio nas telas funcionais. |
| Segurança | O navegador chama a própria origem em `/api/v1/*`; o proxy local injeta o token no servidor. Não há senha ou token no bundle. |
| Sessão | Há sessão demonstrativa apenas para desenvolvimento local; publicação depende de autenticação corporativa/gateway. |
| Estado de consulta | `usePdohResource` trata cancelamento, carregamento, erro, atualização e nova tentativa. |
| Responsividade | Menu lateral no desktop, drawer no mobile e componentes de tabela/cartão já adaptados. |
| Validação de retorno | Schemas Zod em `src/services/pdoh-api.ts`. |

Arquivos centrais: `frontend/src/app.tsx`, `frontend/components/platform/app-shell.tsx`, `frontend/src/pages/platform-pages.tsx`, `frontend/src/pages/opportunities-page.tsx`, `frontend/src/services/opportunity-service.ts` e `frontend/src/services/pdoh-api.ts`.

## 3. Navegação e rotas atuais

| Rota | Tela / situação |
| --- | --- |
| `/login` | Entrada de autenticação. |
| `/` | Redireciona para `/oportunidades`. |
| `/dashboard` | Dashboard atual. |
| `/operacoes` | Redireciona para o dashboard. |
| `/oportunidades` | Fila atual com abas Operacionais, Alertas e Telemetria. |
| `/oportunidades/registros` | Conferência técnica de registros e vínculos. |
| `/oportunidades/:opportunityId` | Detalhe de uma oportunidade. |
| `/processamentos` | Lista de execuções. |
| `/processamentos/:executionId` | Resultado, etapas e fontes de uma execução. |
| `/marcas/:brandId/dashboard` | Dashboard filtrado por marca. |

Há páginas prontas, mas fora do roteamento atual: `parameters-page.tsx` (Regras e De/Para) e `identifiers-page.tsx` (identificadores/rastreabilidade). Os componentes `brand-dashboard.tsx` e `catalog-summary.tsx` também não estão sendo usados por uma rota. Eles não devem ser expostos automaticamente: serão avaliados como material de reaproveitamento ou consulta contextual.

## 4. Mapeamento das telas atuais

| Tela | Objetivo atual | Dados consumidos | Problemas encontrados | Sugestão futura |
| --- | --- | --- | --- | --- |
| Dashboard | Mostrar situações operacionais, execuções e períodos processados. | `/api/v1/regras`, múltiplas chamadas `/api/v1/oportunidades`, `/api/v1/dashboard`. | Faz contagens N+1 por regra e classifica no cliente; indicadores misturam a visão v1 com categorias agora separadas no backend. | Tornar a abertura do Painel PDOH e usar agregados v2 consistentes. |
| Oportunidades | Consultar grupos, registros e detalhes. | `/api/v1/oportunidades`, `/api/v1/regras`, detalhe/histórico e De/Para v1. | A tela é densa; Alertas e Telemetria permanecem na mesma rota; o agrupamento depende do catálogo atual no navegador. | Fila operacional independente, cartões por regra/cenário e detalhe operacional v2. |
| Detalhe da oportunidade | Explicar problema, registro, esperado/encontrado, regra, fallback, tratativa e histórico. | Detalhe/histórico de oportunidade v1, regras e De/Para v1. | É o componente mais próximo do fluxo desejado, mas depende de chaves presentes na evidência; não há campo confiável de responsável operacional. | Reaproveitar o componente, consumindo um detalhe v2 com contrato explícito de impacto, responsável e contexto. |
| Alertas (aba) | Exibir alertas agrupados, como UF ausente. | `/api/v1/alertas` e `/api/v1/alertas/{id}/registros`. | Está dentro de Oportunidades e o contrato ainda se apoia nas estruturas legadas. | Criar rota e tela próprias de acompanhamento, com tom não crítico e agrupamento vindo da API v2. |
| Telemetria (aba) | Mostrar grupos informativos. | Registros `/api/v1/oportunidades` classificados pelo catálogo no cliente. | Não é uma visualização de log/evento; mistura o conceito técnico com a fila de oportunidades. | Criar tabela/log independente, alimentada por `/api/v2/telemetria`. |
| Execuções | Acompanhar processamento por marca, período e status. | `/api/v1/execucoes` e detalhes/etapas/fontes. | Já preserva caráter de acompanhamento, mas é uma área paralela à nova hierarquia proposta. | Manter como acesso contextual pelo Dashboard e por detalhes; não precisa ser o foco do menu principal. |
| Regras e De/Para (dormente) | Consultar parametrizações sem edição. | `/api/v1/regras`, `/api/v1/de-para` e histórico. | Não está roteada e não é uma área de autonomia ou aprovação. | Servir de referência visual para a futura Configurações, sem habilitar escrita. |
| Identificadores (dormente) | Consultar entidades e colaboradores rastreáveis. | `/api/v1/entidades` e `/api/v1/colaboradores`. | Está fora do fluxo operacional e expõe muitos códigos técnicos como tela independente. | Manter rastreabilidade dentro do detalhe de oportunidade, com rota técnica opcional somente para auditoria. |

## 5. Componentes que devem ser reaproveitados

| Componente | Reuso proposto |
| --- | --- |
| `AppShell` | Preservar identidade azul, sidebar desktop e drawer mobile; trocar apenas os itens de navegação numa fase aprovada. |
| `PageHeader` | Títulos e contexto de todas as novas páginas. |
| `FilterPanel`, `FilterField`, `DateFilters`, `Pagination` | Barra de filtros e paginação; ampliar somente depois de haver contratos para os novos filtros. |
| `ConsultationState` | Estados reais de carregamento, erro, atualização e vazio. |
| `StatusBadge` | Status de execução e, após revisão semântica, de situação operacional. |
| `OpportunityDetail`, `DetailSection`, `RuleExplanation`, `FallbackInfo`, `TraceabilityCard` | Base do detalhe operacional: preservar as perguntas que a tela já responde e trocar a fonte de dados por v2. |
| `ExecutionCard` e detalhe de execução | Acompanhamento contextual de processamento, sem transformar a experiência em tela técnica. |
| `Card`, `Table`, `Tabs`, `Sheet`, `Skeleton` e demais componentes shadcn | Componentes de apresentação já padronizados, acessíveis e responsivos. |

`recharts` já está instalado, porém não é usado. Só deve entrar em uma tela quando houver uma métrica com definição, origem e granularidade aprovadas; não deve ser usado para criar gráficos decorativos ou valores simulados.

## 6. Problemas que precisam ser resolvidos antes da evolução visual

1. **Fonte de classificação duplicada.** O front-end usa `/api/v1/oportunidades` e `catalogKind()` para decidir o que é operacional, alerta ou informativo. A separação oficial agora vive no backend v2. A classificação deve ter uma única fonte de verdade: o backend.
2. **Contagens de alto custo e sem snapshot único.** O resumo atual consulta o catálogo e faz chamadas adicionais por regra/status. Para os cartões do novo painel, a API deve entregar agregados próprios.
3. **Contratos v2 ainda não estão disponíveis no cliente.** `apiRequest()` usa apenas `/api/v1`, e o proxy de desenvolvimento também encaminha somente `/api/v1`. Isso é uma mudança de integração futura, não desta etapa.
4. **Filtros solicitados não estão todos disponíveis.** A API v2 oferece marca, período, tipo, status, execução, regra, severidade e colaborador. Não há contrato de equipe ou região. A interface atual expõe apenas marca, período e status em seus filtros principais.
5. **Indicadores de gestão sem fonte definida.** PDOH geral, produtividade e jornada não possuem endpoint/definição de cálculo retornados pela API de consulta. Eles não devem ser calculados no navegador nem exibidos como valor fictício.
6. **Semana operacional divergente.** O backend v2 hoje considera como semana fechada a segunda a domingo anteriores. O requisito do painel é segunda a sábado. A próxima fase deverá passar explicitamente a janela segunda–sábado ou alinhar o contrato de período no backend; não fazer essa conversão de modo implícito e inconsistente em cada tela.
7. **Responsável não é um campo de operação consolidado.** Há colaborador e histórico, mas não há um `responsavel`/proprietário de tratativa no item v2. O cartão não deve inventar esse dado.

## 7. Nova arquitetura de navegação proposta

```text
PAINEL PDOH
├── Dashboard
├── Oportunidades
├── Alertas
├── Telemetria
└── Configurações de regras (futuro)
    ├── Regras
    ├── Fallbacks
    └── Jornada
```

Rotas propostas para uma implementação futura:

| Área | Rota proposta | Papel |
| --- | --- | --- |
| Dashboard | `/dashboard` | Entrada do líder e leitura da saúde operacional. |
| Oportunidades | `/oportunidades` | Fila que exige análise/atuação. |
| Detalhe operacional | `/oportunidades/:findingId` | Contexto, evidência, impacto e orientação. |
| Alertas | `/alertas` | Acompanhamento de qualidade cadastral e pendências não críticas. |
| Telemetria | `/telemetria` | Auditoria técnica e eventos de processamento. |
| Configurações (futuro) | `/configuracoes/regras`, `/configuracoes/fallbacks`, `/configuracoes/jornada` | Consulta, simulação e, após aprovação de backend/RBAC, alteração controlada. |

As Execuções continuam acessíveis por links contextuais no Dashboard, na oportunidade e no detalhe. Isso preserva a rastreabilidade sem colocá-las no centro da jornada do líder.

## 8. Proposta do Dashboard PDOH

### Objetivo

Em uma abertura, o líder deve entender: qual período está sendo analisado, se houve execução confiável, quantas ações operacionais existem, quais alertas merecem acompanhamento e onde aprofundar a análise.

### Período padrão

Adotar **a última semana operacional encerrada de segunda-feira a sábado**, sempre sem domingo. Exemplo de regra de UX:

- segunda a sábado da semana atual ainda em andamento: usar a segunda–sábado da semana anterior;
- domingo: usar a segunda–sábado que terminou no dia anterior;
- período customizado: permitir seleção explícita, com o rótulo “Período personalizado”.

Esta definição deve ser centralizada no serviço/contrato futuro, para todas as páginas retornarem os mesmos dados.

### Filtros

| Filtro | Situação | Proposta |
| --- | --- | --- |
| Marca | Disponível | Controle principal no topo. |
| Período | Disponível | Seletor com padrão de semana operacional fechada e opção personalizada. |
| Equipe | Indisponível | Não exibir como filtro ativo até existir fonte e contrato. Pode aparecer desabilitado apenas se houver valor real de orientação no produto. |
| Região | Indisponível | Mesma regra de equipe. |

### Cartões principais

| Cartão | Fonte necessária | Situação de implementação futura |
| --- | --- | --- |
| Oportunidades abertas | `/api/v2/findings/resumo` + agregado por status/regra | Pode ser alimentado após a camada v2 do front. |
| Alertas pendentes | Resumo/agrupamento v2 de alertas | Pode ser alimentado após a camada v2 do front. |
| Marcas | Execuções/períodos ou agregado v2 por marca | Viável, desde que o rótulo deixe claro o que está sendo contado. |
| Última execução / saúde de processamento | `/api/v1/execucoes` ou um resumo de execuções | Já há dados reais e componente reutilizável. |
| PDOH geral | KPI formal, granularidade e período aprovados | Não exibir número até contrato existir. |
| Produtividade | KPI formal por colaborador/equipe/região | Não exibir número até contrato existir. |
| Jornada | KPI/ocorrência de jornada formal | Não exibir número até contrato existir. |

O dashboard deve ter dois níveis: uma faixa de situação (período, marca, última execução e confiabilidade) e cartões que levam diretamente à lista filtrada. Sem um contrato de KPI, o painel deve mostrar menos cartões — dados reais têm prioridade sobre uma grade completa com valores sem significado.

## 9. Proposta da aba Oportunidades

### Objetivo

Exibir exclusivamente `classificacao = OPORTUNIDADE`: situações que requerem análise ou ação operacional. Alertas e telemetria não devem aparecer nesta fila.

### Estrutura

1. Cabeçalho com período/marca e total de oportunidades abertas.
2. Filtros de marca, colaborador, severidade, regra e período.
3. Cartões operacionais agrupados por regra/cenário, e não uma lista extensa de ocorrências técnicas.
4. Abertura de cartão leva à lista de registros ou diretamente ao detalhe quando houver um único resultado.
5. Detalhe responde às perguntas operacionais e mantém rastreabilidade como seção recolhível.

### Conteúdo de cada cartão

```text
CHECKOUT NÃO REGISTRADO                         [Alta]
12 ocorrências · 8 colaboradores afetados

Impacto: Jornada / tempo em loja
Responsável: João Silva ou “não atribuído”
Ação: Validar registro de saída na origem

[Abrir ocorrências]
```

Regras de apresentação:

- título usa tradução operacional (`opportunityName`) e preserva o código técnico apenas em contexto secundário;
- a contagem deve informar se representa ocorrências, colaboradores únicos ou lojas; não misturar os conceitos;
- severidade vem do catálogo/snapshot de regra, não de uma cor inventada pelo front-end;
- impacto e ação vêm do contrato de regra/evidência; se ausentes, a tela deve informar a ausência, não inferir;
- responsável somente aparece se houver campo confiável de atribuição. Enquanto não existir, mostrar “Não atribuído”.

### Contratos adicionais necessários

O endpoint v2 atual lista achados e fornece um resumo global, mas não um agregado por regra com contagem de ocorrências/colaboradores. Para evitar repetir o atual N+1 no navegador, propor:

- um resumo paginado de oportunidades por `regra_id`, tipo, marca e severidade;
- total de ocorrências e total de colaboradores distintos, identificados separadamente;
- impacto operacional e orientação efetiva (snapshot da regra quando aplicável);
- detalhe/histórico v2 de uma oportunidade, para não abrir um registro v1 dentro de uma fila v2.

## 10. Proposta da aba Alertas

### Objetivo

Exibir `classificacao = ALERTA` para acompanhamento e qualidade de dados, sem tom de incidente crítico e sem mistura com a fila operacional.

### Conteúdo

- qualidade cadastral (por exemplo, UF não preenchida);
- divergências de cadastro;
- dados incompletos;
- itens de De/Para pendentes;
- quantidade de colaboradores/ocorrências e tratativa recomendada.

Exemplo:

```text
UF DO COLABORADOR NÃO PREENCHIDA
3 colaboradores · BRACELL
Ação recomendada: Atualizar cadastro na origem
```

O agrupamento deve vir da API pela chave definida pelo backend, por exemplo `marca + colaborador + campo pendente`. A página deve reutilizar cartões leves para acompanhamento e permitir abrir ocorrências somente quando necessário.

## 11. Proposta da aba Telemetria

### Objetivo

Dar visibilidade técnica e auditoria sem poluir as filas de operação.

### Formato

Tabela/log com:

- data/hora;
- evento/código;
- severidade técnica;
- marca;
- execução vinculada;
- origem/componente;
- mensagem e contexto recolhível.

Filtros iniciais possíveis: marca, período, execução, evento e severidade. O endpoint v2 já traz código, execução, marca, mensagem, severidade e evidência; para mostrar origem/componente de forma confiável, o contrato deve expor esses campos de maneira explícita, sem depender de JSON de evidência.

## 12. UX futura para Configurações de regras

Esta é uma proposta de experiência; **não habilita edição nesta etapa**.

### Área de Regras

- lista de regras com código, nome operacional, classificação, severidade, ação e vigência;
- detalhe somente leitura com critérios, evidências e impacto;
- rastreabilidade de versão/snapshot em ocorrências já geradas.

### Fallback de checkout

Fluxo futuro seguro:

```text
Consultar regra efetiva
→ informar valor candidato
→ simular impacto sem escrita
→ revisar registros/colaboradores afetados
→ solicitar/aprovar alteração
→ ativar vigência
→ consultar histórico append-only
```

A visualização pode consumir futuramente o resolvedor e a simulação já existentes. Para habilitar alteração, ainda serão necessários endpoints de criação/ativação, histórico de leitura, RBAC, aprovação, validação de horário e auditoria. A tela não pode sugerir que uma simulação altera o cálculo ou o processador protegido.

### Jornada

Modelo de leitura proposto:

```text
Líder (mais específico)
↓
Colaborador
↓
Valor padrão
```

O detalhe deve explicar qual valor venceu, sua origem, vigência e o motivo de precedência. Futura edição exige modelo backend para jornada semanal, horários, tolerâncias, validações de conflito, aprovação e histórico. Sem isso, a UI deverá permanecer somente leitura.

## 13. Fluxo do usuário proposto

```text
Entrar no Dashboard
→ confirmar marca e semana operacional fechada
→ identificar oportunidades abertas ou alertas pendentes
→ abrir a fila correspondente já filtrada
→ analisar o cartão e seu impacto
→ abrir o detalhe do registro
→ conferir regra, dado esperado/encontrado, fallback, tratativa e rastreabilidade
→ consultar a execução vinculada quando necessário
```

No mobile, a mesma sequência deve funcionar com filtros em painel/drawer, cartões em coluna e detalhe como rota integral. No desktop, o detalhe pode continuar em painel lateral, desde que o link direto preserve o estado necessário.

## 14. Ordem de implementação sugerida após aprovação

1. **Contratos e integração v2:** schemas, cliente HTTP/proxy para v2, serviços e testes de equivalência por classificação. Não alterar o processamento.
2. **Navegação e Dashboard:** novo menu, período segunda–sábado centralizado, resumo v2 e saúde de execução com valores reais.
3. **Oportunidades:** cartões operacionais, filtros suportados, detalhe v2 e rastreabilidade contextual.
4. **Alertas e Telemetria:** páginas independentes, sem cruzamento de categorias.
5. **Configurações somente leitura:** regras, resolução/simulação de fallback e hierarquia de jornada quando os contratos de leitura estiverem prontos.
6. **Autonomia controlada:** somente após RBAC, aprovação, endpoints de escrita, histórico e validação de impacto aprovados.

## 15. Decisões necessárias antes de codificar

| Decisão | Motivo |
| --- | --- |
| Definição oficial de PDOH geral, produtividade e jornada | Evita KPI calculado de forma diferente no front-end. |
| Fonte de equipe e região | Não existe nos contratos de consulta atuais. |
| Definição de “responsável” | Colaborador afetado não é necessariamente dono da tratativa. |
| Semântica de contagem | Diferenciar ocorrência, colaborador único, loja e regra. |
| Contrato de agregados e detalhe v2 | Evita N+1 e mistura v1/v2. |
| Regra única para semana operacional segunda–sábado | Evita que Dashboard e listas retornem janelas diferentes. |
| Política de acesso a Configurações | Necessária antes de qualquer escrita/ativação futura. |

## 16. Respostas aos critérios de aceite

1. **Como está o frontend hoje?** Uma aplicação React funcional e responsiva, com consulta real v1, dashboard, oportunidades, detalhe e acompanhamento de execuções. Alertas/telemetria ainda estão acoplados à experiência de oportunidades.
2. **Quais problemas existem?** A classificação é parcialmente refeita no cliente, há múltiplas chamadas para formar resumos, a navegação não reflete os três conceitos do backend v2 e faltam contratos para KPIs e filtros de gestão.
3. **Como deve ficar o novo Painel PDOH?** Um painel com Dashboard, Oportunidades, Alertas e Telemetria como áreas independentes; Configurações fica planejada para evolução controlada.
4. **Como o líder irá acompanhar oportunidades?** Pelo Dashboard, filtrando marca/período e abrindo cartões operacionais por regra; cada cartão leva ao detalhe com impacto, registro afetado, regra, esperado/encontrado e orientação.
5. **Como o líder poderá configurar regras futuramente?** Por uma área com leitura da regra efetiva, simulação antes de alteração, aprovação, vigência e histórico append-only. A edição não deve ser habilitada antes dos contratos e controles de segurança.
6. **Quais telas serão criadas?** Dashboard reorganizado, Oportunidades, Alertas, Telemetria e, posteriormente, Configurações de Regras/Fallbacks/Jornada. Execuções permanece contextual.
7. **Quais componentes serão reutilizados?** Shell de navegação, cabeçalhos, filtros, paginação, estados de consulta, badges, cartões/tabelas, detalhe de oportunidade e acompanhamento de execução.

## 17. Registro de não alteração

Esta análise não aplicou mudanças no front-end, na API, no banco, no processamento PDOH, na Platina, no ETL ou nos processadores protegidos.
