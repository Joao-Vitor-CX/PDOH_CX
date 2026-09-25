# PDOH_CX — Front-end de consulta (Fase 3)

Este diretório é uma evolução do protótipo `cx-pdoh-platform` em
`C:\Users\RT-138\Downloads\produto_pdoh_exclusivo_rt-main\produto_pdoh_exclusivo_rt-main\cx-pdoh-platform`.
O protótipo original permanece inalterado. Foram mantidos React 19, TypeScript,
Vite, Tailwind/shadcn, shell de navegação, cartões, tabelas e identidade visual.
Os dados demonstrativos foram retirados das páginas funcionais.

## Executar localmente

Requer Node.js 22.13+ e a API da Fase 2 saudável em `127.0.0.1:8000`.
Na pasta `frontend`:

```powershell
npm ci
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm run dev
```

Abra `http://127.0.0.1:5173`. `npm run lint`, `npm run build`, `npm run test:api`,
`npm run test:operational` e `npm run test:operational:live` validam a interface,
os contratos e a classificação. Para os testes de API/live, mantenha o Vite em execução.
O relatório da revisão atual está em `VALIDACAO_OPERACIONAL.md`; `VALIDACAO_FASE3.md`
preserva o registro histórico da integração inicial.

## Integração e segurança

O navegador solicita `/api/v1/*` e `/api/v2/*` à própria origem do Vite. O proxy de desenvolvimento
encaminha à API de consulta e adiciona o token no servidor, carregando-o de
`../api/.env.api` ou `PDOH_API_TOKEN`. `PDOH_CONSULTA_URL` pode mudar o endereço
da API para o proxy. Nenhum token ou senha deve entrar em `VITE_*` ou no bundle.
O MySQL é acessado somente pela API com `pdoh_cx_reader` (`SELECT`).

`VITE_CX_PDOH_DEMO_AUTH=true` permite sessão **apenas em `npm run dev` e em
`127.0.0.1`**. Não é autenticação corporativa. O build desabilita esta sessão;
para publicar `dist/`, a aplicação hospedeira deve fornecer sessão corporativa
e um gateway autenticado para `/api/v1/*` e `/api/v2/*`. Não exponha o proxy de desenvolvimento
ou o preview como ambiente de produção.

## Telas

### Central de Notificações definitiva

A entrada oficial `src/main.tsx` carrega `CxPdohApp`, que monta `AppShell` para a sessão
autenticada. O header do shell já contém `OpportunityNotifications`; a homologação visual
aprovada pelo usuário reutilizou esses mesmos componentes, estilos e modal de detalhe.
Não existe flag de preview necessária para a Central funcionar.

- Componente: `components/platform/opportunity-notifications.tsx`.
- Atualização e leitura local: `src/hooks/use-opportunity-notifications.ts`.
- Consumo: `src/services/opportunity-notifications.ts` e `src/services/operational-api.ts`.
- Detalhes: `components/platform/opportunity-detail-modal.tsx`.

A integração usa somente GETs existentes: `/api/v2/findings/resumo` resolve o período,
`/api/v2/oportunidades/resumo` carrega os grupos e
`/api/v2/oportunidades/{grupo_id}/evidencias` fornece o detalhe ao abrir um item.
Requer sessão autenticada, API disponível e o gateway/proxy configurado acima. Não exige
novas dependências npm, endpoints ou contratos temporários.

Sem pendências, o sino fica sem badge. Cada grupo com novidade adiciona uma unidade;
abrir o detalhe marca o aviso como visto e reduz o contador. A oportunidade continua na
lista recente. A leitura é salva no navegador por usuário e período, com alternativa em
memória se o armazenamento estiver indisponível. Há atualização a cada minuto e ao retornar
à aplicação ou abrir a Central. O consumidor inclui os grupos reais retornados pela API;
o cenário de teste 0 → 1 → 0 não força esse estado no ambiente oficial.

Os arquivos de interceptação, fixture e Vite visual foram removidos após a aprovação.
Build oficial, lint e os oito testes existentes da Central foram aprovados na conferência
da integração definitiva. A publicação do bundle depende do processo de implantação do
frontend; gerar `dist/` não publica automaticamente a aplicação hospedada.

- `/oportunidades`: entrada principal, grupos operacionais e informativos em abas separadas;
- `/oportunidades/:opportunityId`: problema, registro, evidência, regra, orientação, fallback e histórico;
- `/oportunidades/registros`: conferência completa, com classificação identificada em cada registro;
- `/dashboard` e `/marcas/:brandId/dashboard`: indicadores operacionais e acompanhamento;
- `/processamentos` e `/processamentos/:executionId`: acompanhamento de execuções, etapas e fontes;
- `/operacoes` redireciona para o dashboard; módulos técnicos não integram a navegação.

Todas as páginas são somente leitura. Filtros e páginas importantes permanecem na URL.
Datas sem offset são exibidas como horário local retornado pela API, sem converter fuso.

## Critério operacional e limites

`src/services/opportunity-service.ts` concentra o consumo do catálogo e as contagens.
O vínculo real `oportunidade.regra_id` e o tipo correspondente determinam o grupo:
`ALERTAR`/`REGISTRAR` são operacionais; `TELEMETRIA` é informativo. Sem vínculo
reconhecido, o registro permanece sem classificação e não compõe o card operacional.
Não classificamos históricos apenas pelo nome do tipo nem recriamos a resolução de regras.
`src/lib/opportunity-presentation.ts` concentra nomes operacionais e apresentação de evidências.

As contagens dos grupos consultam os totais da API, com até quatro requisições simultâneas.
Não baixam todos os registros. Subgrupos por campo/fonte/marca/data usam apenas os 50
registros da página, explicitamente identificados como parciais. A API atual não oferece
um snapshot único entre requisições: a checagem do total antes/depois detecta variações
de volume, mas não toda alteração concorrente de classificação/status. Catálogo e orientação
são atuais, não uma reconstrução da versão histórica aplicada.

Ausência de evidência não vira valor presumido, impacto estimado ou fallback falso.
Padronizações são consultadas no contexto de processo/campo/valor da oportunidade;
correspondência atual não comprova aplicação no processamento. Não há comandos de escrita,
edição de regras, De/Para, tratativa nem reprocessamento. Autenticação corporativa e
agregação transacional são evoluções separadas, não implementadas nesta entrega.
