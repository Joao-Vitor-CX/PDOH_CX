# Teste isolado da Central — CHECKOUT_AUSENTE via JSON

## Resultado
Aprovado no executor/dispatcher/API e consumidor TypeScript: contador **0 → 1 → 0**.
**Validação visual não realizada**: a ferramenta retornou apps/browsers vazios. Não há screenshots nem comprovação de clique real. Portanto o aceite visual solicitado permanece pendente.

## Massa única utilizada
Arquivo temporário: `mock/opportunity_checkout_absent.json` (removido ao finalizar).

```json
{"colaborador":"COLABORADOR TESTE 44H","jornada":44,"hora_entrada":"08:00","hora_saida":null,"horario_configurado":"19:00"}
```

O harness acrescentou data histórica 2026-09-01, extração 2026-09-02 05:00 e intervalo configurado 01:00 para observar o limite vencido sem depender da hora corrente. Somente esse colaborador e esse registro de monitoramento foram processados. As duas fontes cadastrais sintéticas representam o mesmo colaborador, não duas oportunidades.

## Isolamento
- SQLite novo em memória, sem conexão ao banco definitivo.
- Nenhuma limpeza/descarte de notificações reais. O estado de leitura do consumidor começou em memória com {}.
- Consulta inicial real da API: total 0, items [].
- Nenhuma consulta à carga real, importação de histórico ou oportunidade anterior.
- A regra foi preparada exclusivamente no fixture. A adição da configuração manual à regra existente preservou integralmente tabelas de regras, condições e tratamentos.
- O teste usou resolvedor, executor, dispatcher e endpoints reais, com adaptação de sintaxe SQL já usada nos testes do projeto.
- O consumidor frontend recebeu respostas capturadas dessa API via fetch substituído para o teste; não se conectou ao backend real.

## Evidências
- ID da oportunidade: `32dad46d-ead2-57e6-abef-ed77120cb8b0`.
- Grupo exibido pela Central: `QlJBQ0VMTB9DSEVDS09VVF9BVVNFTlRFHx9DT0xBQk9SQURPUiBURVNURSA0NEgfc3RhdHVzX2RheR9ob3JhX3NhaWRh`.
- **Não existe ID de registro separado de notificação nesta implementação.** A Central usa um aviso por grupo e a seguinte chave de leitura:
  `["2026-09-01","2026-09-01","QlJBQ0VMTB9DSEVDS09VVF9BVVNFTlRFHx9DT0xBQk9SQURPUiBURVNURSA0NEgfc3RhdHVzX2RheR9ob3JhX3NhaWRh"]`.
- Fonte principal: horas nulas; fonte secundária: 44H. Resolvedor retornou `RESOLVIDA`, jornada 44, fonte `secundaria`.
- Horário esperado comprovado: 19:00. Checkout observado permaneceu null.
- Oportunidades criadas: 1. Reprocessamento do mesmo JSON: 0 novas.
- API de resumo: exatamente um grupo, quantidade 1, COLABORADOR TESTE 44H, CHECKOUT_AUSENTE, severidade MEDIA.
- API de detalhes: confirmado, horário esperado 19:00.
- Antes: zero grupos/avisos. Depois: um grupo/aviso. Após leitura e atualização: zero avisos pendentes.
- Rastreamento das respostas consumidas: **um único grupo distinto**; antes nenhum, depois apenas o grupo acima, após leitura apenas o mesmo. Nenhum outro grupo/oportunidade foi carregado.

## Limites do comportamento comprovado
O sino é uma projeção visual das oportunidades, não um envio para uma outbox nova. Marcar como visto remove o estado pendente e zera o contador; a oportunidade continua na lista recente. Exclusão do item da lista não é o comportamento atual e não foi implementada neste teste.

O serviço de produção consulta a janela de oportunidades da API. O isolamento aqui decorreu do banco em memória conter apenas a massa controlada; o teste **não demonstra** que apontar esse serviço ao banco real excluiria oportunidades antigas. Não foi usado o banco real.

A evidência técnica da jornada 44H está na resolução e na comprovação do executor; sem navegador, não se afirma que todos os campos solicitados foram visualmente exibidos.

## Preservação e limpeza
Nenhuma alteração em código de produção, motor CHECKOUT_AUSENTE, regras de negócio, severidade, PDOH ou banco definitivo. Apenas arquivos temporários de teste foram criados e removidos:
- `mock/opportunity_checkout_absent.json`
- `scripts/notification_isolated_temporary.py`
- `frontend/scripts/notification-isolated-temporary.ts`

O SQLite foi descartado no cleanup. A substituição de fetch foi restaurada; variáveis do processo não alteraram a aplicação. Permanece somente este relatório como evidência, não uma massa ativa.

