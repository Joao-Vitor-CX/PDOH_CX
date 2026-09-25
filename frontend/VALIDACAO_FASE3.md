# Validação da Fase 3 — 15/09/2026

Registro histórico. A revisão de experiência e classificação de 16/09/2026 está
em `VALIDACAO_OPERACIONAL.md`; a navegação descrita abaixo foi substituída nessa revisão.

Esta entrega evolui o protótipo existente em `frontend/`. O projeto original em
`Downloads/cx-pdoh-platform` não foi alterado. O dashboard, as listas, os detalhes,
os históricos e a rastreabilidade consultam a API v1; não há conexão MySQL no
navegador nem dados demonstrativos nas páginas funcionais.

## Verificações executadas

- `npm run lint`: aprovado.
- `npm run build` (`tsc --noEmit` + Vite): aprovado.
- `npm run test:api` com o Vite local e API da Fase 2: aprovado. Consultou
  dashboard, listas, detalhes, históricos, paginação, filtros, identificadores,
  resposta vazia e erro de filtro inválido.
- Banco de controle (`SELECT`) × API × consulta do front via proxy local:
  29 execuções, 56.770 oportunidades, 23 regras (23 ativas), 11 De/Para e
  312 entidades. Contagens observadas em 15/09/2026; são dinâmicas.
- Browser desktop e móvel: dashboard, execuções, oportunidades, regras,
  De/Para, identificadores e detalhes carregaram IDs, datas e status da API.
  A linhagem da execução observada paginou 288 registros em seis páginas;
  status e links ficaram visíveis na lista móvel.
- Busca sem resultados e período inválido: estado vazio e erro 422 exibidos.
- Inspeção do bundle de produção: não contém token da API, senha MySQL,
  URL direta do MySQL nem chave da sessão local de desenvolvimento.

## Limites de publicação

A sessão local é exclusiva do Vite em modo desenvolvimento, escutando em
`127.0.0.1`, e **não** é autenticação corporativa. Antes de publicar `dist/`,
é necessário configurar um serviço de sessão corporativa e um gateway
autenticado para `/api/v1/*`. O proxy Vite/preview não é uma configuração de
produção. Esta fase implementa visualização e consulta, sem botões de tratativa,
auditoria mutável ou reprocessamento.

Nenhum arquivo do pipeline, regras de cálculo ou Platina foi alterado nesta
fase. As alterações preexistentes nessas áreas na árvore Git permanecem fora
do escopo desta entrega.
