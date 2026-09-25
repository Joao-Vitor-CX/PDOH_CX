# Fechamento técnico da integração Front-end PDOH

Data: 24/09/2026. Janela reconciliada: 31/08/2026 a 05/09/2026, inclusive.

## Status

**Escopo implementado: entrega técnica finalizada, com integração validada por contratos, testes e consultas reais. Aceite integral pendente das ressalvas abaixo.**

Não é possível atestar, sem ressalvas, a conclusão de toda a experiência solicitada ou ausência universal de perdas entre processamento e interface. As evidências comprovam a reconciliação da janela consultada e dos serviços testados.

## Ambiente e método

Consultas reais por `http://127.0.0.1:5173`, frontend existente, com proxy para a API de homologação em `127.0.0.1:8000`. A reconciliação live não utilizou mocks, fixtures ou interceptação de respostas. Foram executadas somente leituras nesta etapa de fechamento.

A fonte informada pela API de PDOH foi `produtos_platina.exclusivo_bracell_platina_relatorio_pdoh`. Não houve auditoria independente por SQL do banco ou do processamento de origem. Testes automatizados de unidade/contrato complementam, mas não substituem, as consultas reais nem o aceite visual.

## Resultado da reconciliação

| Verificação | Resultado observado |
| --- | --- |
| Registros PDOH no período | 330 retornados e 330 lidos em todas as páginas |
| Identidade colaborador/data | 330 combinações distintas |
| Colaboradores PDOH | 55 distintos, conforme cobertura da API |
| Jornada 44H / INVOLVES | 216 registros |
| Jornada 24H / INVOLVES | 78 registros |
| Jornada 36H / INVOLVES | 18 registros |
| Jornada 44H / FALLBACK | 6 registros |
| Jornada ausente | 12 registros, preservados como ausentes |
| Grupos de oportunidades | 38 identificadores distintos |
| Ocorrências nos cards | 100 |
| Ocorrências no detalhamento/exportação | 100 |
| Cards por regra e avisos semanais calculados | 1 card e 1 aviso consolidado |
| Grupos de alertas cadastrais | 8 |

O verificador semanal conferiu paginação, consistência dos totais, identidades únicas e quantidade de linhas do CSV. Não encontrou perda ou duplicidade nesse caminho de consumo. O aviso foi verificado no serviço de consolidação; isso não equivale a abrir e marcar o sino no navegador.

O total PDOH difere do registro anterior de 312 linhas/52 colaboradores: o novo snapshot da API informa 330/55. Não foi atribuída causa à atualização da fonte. As 100 oportunidades da janela permaneceram reconciliadas. Totais de PDOH e oportunidades representam entidades diferentes e não devem ser igualados.

## Integração e rastreabilidade

São consumidos contratos existentes, sem API paralela:

- PDOH: `/api/v2/pdoh/resumo`, composição e evolução; os indicadores vêm do backend.
- Oportunidades: `/api/v2/oportunidades/resumo`, `/{grupo_id}/detalhes` e `/{grupo_id}/evidencias`.
- Alertas cadastrais: `/api/v2/alertas/resumo`, separados de oportunidades.
- Parametrizações: contratos existentes de configurações da operação e regras, com validação de resposta e payloads tipados.
- Contratos v1 de execuções, oportunidades, histórico, regras, de-para e entidades: verificados pelo script de integração; disponibilidade da API não significa exposição integral nas telas ativas.

| Informação | Tratamento no frontend |
| --- | --- |
| Identificador e vínculo | IDs de grupo, ocorrência e execução preservados nas estruturas consumidas e detalhes/exportação correspondentes |
| Regra e cenário | Regra retornada pelo backend e cenário descrito pela comprovação |
| Data e dados impactados | Data de referência, colaborador e dados disponíveis na evidência |
| Jornada e fallback | Prova registrada ou resolução oficial da data, com indicação de origem; sem inventar jornada ausente |
| Evidências | Comprovação fornecida pela API |
| Histórico | Identificação, execução e repetições disponíveis; não equivale ao histórico completo de tratativas humanas |
| Status | Valor disponibilizado pelo backend |

## Evolução operacional registrada

- Dashboard organizada em cabeçalho/filtros, indicadores PDOH, evolução, monitoramento de oportunidades e alertas cadastrais.
- Oportunidades resumidas em cards, com filtro Semana/Dia, detalhamento sob interação e CSV compatível com Excel.
- Sidebar recolhível, identificação por ícones/tooltips e navegação principal organizada.
- Validação diária separada em Horário geral e Oportunidades.
- Modal de jornada preserva nome, carga, horários, intervalo e origem recebidos. Jornada operacional permanece bloqueada; manual permanece editável. Campos nulos na API são apresentados como não informados.
- Central de Notificações preservada, com consolidação por regra/semana e estado de leitura existente.
- Atualização de dados por leitura das APIs. Reprocessamento continua dependente de endpoint do backend e não é simulado pelo frontend.
- Serviços tipados, componentes reutilizados e testes de contratos oferecem base para as próximas evoluções.

Arquivos centrais da evolução: `frontend/src/pages/pdoh-dashboard-page.tsx`; `frontend/components/platform/{app-shell,weekly-monitoring,pdoh-daily-validation,daily-opportunities,rule-settings,opportunity-detail-modal}.tsx`; `frontend/src/services/{operational-api,weekly-monitoring,opportunity-notifications,operational-trace}.ts`; `frontend/src/lib/rule-settings.ts`; testes em `frontend/scripts/`.

## Testes repetidos no fechamento

| Comando | Resultado |
| --- | --- |
| `npm.cmd run build` | Aprovado; aviso de bundle JS de 962,40 kB, acima de 500 kB |
| `npm.cmd run lint` | Aprovado |
| `npm.cmd run test:operational` | 74 aprovados, zero falhas |
| `npm.cmd run test:api` | Aprovado via porta 5173 |
| `node --experimental-transform-types scripts/verify-weekly-live.ts` | Aprovado; 38 grupos, 100 ocorrências e 100 detalhes |

O teste de API v1 retornou 45 execuções, 60.219 oportunidades, 24 regras (24 ativas), 38 de-para e 315 entidades. Esses totais pertencem ao universo consultado pelo script v1, não à janela semanal v2. Foram verificados contratos e vínculos de detalhes/histórico amostrados; não foi realizada inspeção individual de todos os registros.

## Ressalvas para o aceite integral

1. **Validação visual real não concluída.** A ferramenta de controle do navegador interrompeu o acesso por não conseguir determinar a URL com segurança. Não há evidências visuais novas nem comprovação de interação completa de sidebar, modal, download, sino/leitura e responsividade na aplicação oficial.
2. **Execuções e tratativas completas.** As rotas `/processamentos/*` e `/oportunidades/*` de consulta anterior exibem componente explicativo. A interface ativa não oferece consulta integral de execuções e histórico completo de tratativas humanas. O histórico de identificação/execução apresentado não substitui essas funcionalidades.
3. **Limite do rastreio no modal.** `loadOpportunityTrace` consulta até 200 ocorrências e até 200 linhas de resolução diária na primeira página. A exportação semanal percorre todas as páginas, mas não se pode estender sua garantia de completude a esse modal para volumes maiores.
4. **Persistência de configuração.** Preservação dos campos e payload de jornada manual foram testados automaticamente; não foi efetuada alteração real de configuração em homologação para confirmar gravação/releitura nesta validação.
5. **Origem e motor.** A correspondência foi validada contra respostas das APIs existentes. Não foi comprovada independentemente a completude do motor em relação a todas as tabelas de origem.

## Proteção de escopo

Este fechamento alterou somente este registro documental. As intervenções frontend descritas não implementam processamento PDOH nem alteram regras de negócio, motor, tabelas ou contratos do backend. O workspace contém alterações de backend feitas em outra frente; este registro não certifica a autoria ou o conteúdo dessas alterações.

O status solicitado — “Entrega finalizada — Front-end PDOH integrado, validado e preparado para evolução das próximas etapas operacionais” — aplica-se ao escopo técnico implementado e às verificações expressamente registradas. **A certificação integral sem ressalvas permanece pendente**, pelos itens acima.

Este registro atualiza as contagens e os testes de `frontend/VALIDACAO_DASHBOARD_OPORTUNIDADES.md`, preservando o documento anterior como evidência histórica.
