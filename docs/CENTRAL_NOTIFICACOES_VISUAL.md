# Central visual de oportunidades — 23/09/2026

Implementação frontend concluída e compilada. Testes de contrato, contador e integração com o executor/API aprovados. Homologação visual e interação em navegador permanecem pendentes: a sessão retornou `apps: []` e `browsers: []`, inclusive na verificação final. Não foram produzidas capturas de tela nem declarada aprovação visual.

## Arquivos frontend alterados/criados

| Arquivo | Responsabilidade |
| --- | --- |
| [opportunity-notifications.tsx](../frontend/components/platform/opportunity-notifications.tsx) | Componente `OpportunityNotifications`: sino, badge, modal, estados, lista recente e abertura do detalhe existente |
| [app-shell.tsx](../frontend/components/platform/app-shell.tsx) | Inclusão do sino no header, com instância separada por usuário |
| [use-opportunity-notifications.ts](../frontend/src/hooks/use-opportunity-notifications.ts) | Consulta, atualização a cada minuto, retorno à aba, cancelamento, estado de erro e leitura local |
| [opportunity-notifications.ts](../frontend/src/services/opportunity-notifications.ts) | Consumo das APIs existentes, detecção de novidades e links para a fila operacional |
| [notifications.test.ts](../frontend/scripts/notifications.test.ts) | Oito testes de consumo, paginação, novidades, leitura, isolamento, navegação, vazio e erro |
| [package.json](../frontend/package.json) | Inclusão dos novos testes na suíte `test:operational`; nenhuma dependência adicionada |

O modal `OpportunityDetail` e os contratos de API existentes foram reutilizados, sem alteração. Os ajustes anteriores de CHECKOUT_AUSENTE também foram preservados.

## Estrutura existente e APIs utilizadas

Todas as requisições do sino são GET:

1. `/api/v2/findings/resumo?marca=BRACELL&operacao=EXCLUSIVA&periodo=automatico`: obtém a janela do último processamento concluído, segundo a definição atual do backend.
2. `/api/v2/oportunidades/resumo`: lê todas as páginas de grupos operacionais dessa janela. Sem filtro por severidade. Utiliza o carregador existente `loadAllGroups`, que verifica contagem, paginação e IDs duplicados antes de aceitar o resultado.
3. `/api/v2/oportunidades/{grupo_id}/evidencias`: carrega os detalhes somente quando o usuário abre uma oportunidade, pelo componente existente `OpportunityDetail`.

A estrutura `/api/v2/alertas/resumo` atende alertas cadastrais e permanece separada. A fila `notificacao_outbox` segue sua política atual por severidade e não é usada pelo sino: este exibe diretamente oportunidades existentes. Não foi criado endpoint.

Dados utilizados: `grupo_id`, título de negócio, colaborador, primeira/última ocorrência, quantidade consolidada e status operacional. O título de CHECKOUT_AUSENTE aparece como **Checkout não registrado**, conforme o backend.

## Fluxo e comportamento

Oportunidade existente → API de resumo → consumidor frontend → contador/lista → modal de evidências → link para `/impactadores`, preservando período, tipo e colaborador.

- O contador representa **grupos de oportunidades com novidades**, não a soma de eventos históricos.
- Na primeira visita, os grupos ainda não vistos na janela atual são novidades.
- Um grupo volta a ser novo se a API trouxer mais ocorrências, uma última data posterior ou o status REABERTA após outra situação. A leitura de status apenas controla o aviso visual; não muda o status no servidor.
- Aumento de `registros_historicos` por reprocessamento não aumenta o contador.
- A lista prioriza novidades e, dentro de cada conjunto, a última data de ocorrência. Mostra até dez itens e oferece acesso à fila completa; o contador usa todas as páginas.
- Abrir o sino não marca tudo como visto. Abrir um item marca esse aviso como visto; há também “Marcar todas como vistas”. Os itens continuam disponíveis na lista após a leitura.
- A leitura é uma preferência em `localStorage`, separada por usuário, marca/operação e período. Não é uma baixa da oportunidade, não sincroniza com o servidor nem com outros dispositivos. As abas do mesmo navegador recebem atualizações de storage. Se o armazenamento estiver indisponível, a leitura funciona em memória durante a sessão.
- A janela acompanha o último período concluído que a API informa, assim como o painel atual. Não se trata de notificação push nem de varredura de todo o histórico.
- Há consulta inicial, atualização a cada minuto, ao abrir o sino e ao retornar à aba. Requisições concorrentes são evitadas; em aba oculta a consulta aguarda visibilidade. Requisições são canceladas ao desmontar o componente.

Estados implementados:

- Carregando notificações.
- Nenhuma nova oportunidade encontrada.
- Nova oportunidade disponível / quantidade de novas oportunidades.
- Não foi possível carregar notificações, com Tentar novamente.
- Se uma atualização falhar, a lista anterior é identificada como última consulta bem-sucedida e o badge mostra erro; a falha não é apresentada como zero oportunidades.

O modal usa os componentes acessíveis existentes: abertura por teclado, descrição, fechamento/Escape e foco controlado. Há foco explícito ao alternar entre lista e detalhes, badge com descrição acessível e região de status. O layout limita a altura à viewport com rolagem interna. Esses comportamentos estão implementados; sua inspeção no navegador ainda precisa ser feita.

## Testes executados

| Validação | Resultado |
| --- | --- |
| `npm run build` | Aprovado; aviso existente de bundle acima de 500 kB |
| `npm run lint` | Aprovado |
| `npm run test:operational` | 58 testes aprovados, incluindo oito novos |
| JSON → resolvedor → executor → dispatcher → SQLite/API reais | Uma CHECKOUT_AUSENTE criada; reprocessamento criou zero duplicações |
| Respostas reais da API → consumidor TypeScript do sino | Contador 0 → 1; CHECKOUT_AUSENTE MÉDIA incluída |
| Consumidor de detalhes e validação do contrato | Resultado confirmado, colaborador correto, saída esperada às 19:00 |
| Marcar leitura e atualizar novamente | Contador 1 → 0 e permaneceu 0, sem remover a oportunidade |
| Regra/backend/ETL/PDOH | Preservados; hashes agregados iguais antes/depois |
| Capturas, cliques e inspeção visual | Pendentes: navegador indisponível |

### Cenário controlado

Foi criado `mock/opportunity_checkout_absent.json`, com COLABORADOR TESTE 44H, jornada 44H, entrada 08:00, checkout nulo e saída configurada 19:00. Usou-se a data histórica 2026-09-01 e extração 2026-09-02 05:00 para comprovar que o limite configurado já foi alcançado, sem depender da hora corrente.

O consumidor temporário `scripts/validate_notifications_temporary.py::main()` utilizou `FixtureDatabase` em SQLite na memória e uma adaptação de sintaxe SQL já usada pelos testes do projeto. O motor, o resolvedor, o dispatcher, as portas de evidência e os endpoints FastAPI reais foram exercitados, sem conexão MySQL. A fonte cadastral principal sintética tinha horas nulas; a secundária tinha 44H. O resolvedor existente selecionou a secundária.

O catálogo de CHECKOUT_AUSENTE foi carregado da função real `shared.treatment_catalog.montar_regra()`, preservando a severidade MÉDIA. Após a geração, a execução sintética foi concluída no banco em memória para que a API de período automático a selecionasse, como ocorre no fluxo normal.

As respostas de resumo, lista e evidências foram capturadas em `mock/notification-api-responses.json` e consumidas por `frontend/scripts/validate-notifications-temporary.ts`. Esse teste usou o serviço TypeScript de produção e os validadores de contrato existentes, com um transporte `fetch` de teste que entregava as respostas reais capturadas. Portanto, comprovou a integração API/consumidor e a lógica do contador; **não foi um teste de navegador nem de clique real**.

Resultado observado:

```json
{
  "resultado": "APROVADO_API_E_CONSUMIDOR",
  "oportunidadesCriadas": 1,
  "jornada": 44,
  "saida": "19:00",
  "contadorAntes": 0,
  "contadorDepois": 1,
  "contadorAposLeitura": 0,
  "checkout": "CHECKOUT_AUSENTE",
  "severidadePreservada": "MEDIA",
  "detalhes": "confirmado",
  "totalDetalhes": 1,
  "outboxPreservada": 0,
  "visual": "PENDENTE_NAVEGADOR_INDISPONIVEL"
}
```

O checkout observado permaneceu nulo: o horário esperado de 19:00 não foi gravado como saída real. O cálculo PDOH não foi executado ou alterado pelo novo componente.

## Limpeza e preservação

Removidos após o teste: os dois JSONs temporários, os dois executores de homologação e a pasta `mock/` vazia. Existência dos caminhos conferida após a remoção. O SQLite foi descartado e as variáveis/guardas do processo foram restauradas. Nenhuma flag de simulação foi adicionada ao frontend de produção. Permanecem os testes de regressão do frontend e este relatório.

Os 1608 arquivos selecionados de backend, ETL, shared, SQL/migrações, configuração e a biblioteca de prévia mantiveram o mesmo hash SHA-256 agregado: `A6117A418AC29930917C50B774BCC194232C9000ACCE05551C56F7EE8C1C163E`.

Não houve alteração de dados reais, severidade, regra de oportunidade, motor de geração, banco, ETL ou cálculo PDOH.

## Pendência para aceite visual

Com um navegador conectado, abrir o sino e conferir: estado vazio, contador 1 no cenário isolado, item Checkout não registrado, colaborador/data, modal de evidências, link para a fila, leitura local, erro/retry e teclado/mobile. A implementação e os testes disponíveis foram concluídos, mas a evidência visual obrigatória não foi produzida nesta sessão.
