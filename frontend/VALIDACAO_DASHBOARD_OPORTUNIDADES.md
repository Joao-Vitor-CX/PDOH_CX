# Validação do monitoramento PDOH — 24/09/2026

## Escopo

Frontend React e consumo dos contratos v2 existentes. A API, o banco, o motor e as regras não foram alterados. O proxy local do Vite encaminhou as consultas à API de homologação saudável em `127.0.0.1:8000`, com credencial mantida no servidor. Não foram usados dados mockados na validação live.

## Contratos consumidos

- `GET /api/v2/pdoh/resumo` e demais leituras v2 já usadas pela Dashboard.
- `GET /api/v2/oportunidades/resumo`: grupos por janela, incluindo encerradas, com todas as páginas conferidas.
- `GET /api/v2/oportunidades/{grupo_id}/detalhes`: ocorrências consolidadas pelo backend por fingerprint, com paginação e repetições.
- `GET /api/v2/oportunidades/{grupo_id}/evidencias`: comprovação no modal existente.
- `GET /api/v2/alertas/resumo`: alertas cadastrais separados das oportunidades.

O CSV usa o detalhe consolidado da API e preserva origem, jornada, fallback, horário esperado, evidência e histórico de execução. A consulta recusa resultado com páginas incompletas ou fingerprints duplicados.

## Evidência de testes

| Verificação | Resultado |
| --- | --- |
| `npm.cmd run lint` | Aprovado |
| `npm.cmd run build` | Aprovado; aviso de bundle acima de 500 kB |
| `npm.cmd run test:operational` | 67 testes aprovados |
| `npm.cmd run test:v2:live` | Aprovado contra homologação; período automático 14–19/09 sem grupos |
| `node --experimental-transform-types scripts/verify-weekly-live.ts` | Semana 31/08–05/09: 38 grupos, 1 card, 100 ocorrências, 100 linhas de detalhe, 1 aviso consolidado, 8 grupos de alertas |
| Mesmo script com `PDOH_WEEK_START=2026-09-01` e `PDOH_WEEK_END=2026-09-01` | Dia 01/09: 12 grupos, 1 card, 12 ocorrências, 12 linhas de detalhe, 1 aviso consolidado, 8 grupos de alertas |

Os números são um retrato da homologação nessa data. O script confere IDs únicos de grupo e de ocorrência, igualdade entre total dos cards e total dos grupos, presença dos tipos de card no sino e quantidade de linhas do CSV. Não altera dados.

## Dependências e limite da validação

`api/app/main.py` não expõe endpoint para iniciar o reprocessamento da esteira. Por isso o botão **Reprocessar oportunidades** permanece visível e indisponível; **Atualizar dados** relê os resultados já gravados. A execução real depende de contrato e autorização implementados no backend.

A ferramenta de navegador não disponibilizou Chrome, Edge ou navegador integrado nesta sessão. A navegação visual, a interação com o botão da sidebar, a abertura dos modais, o download físico e a marcação de notificações como vistas ainda precisam ser conferidos no navegador de homologação. Build, testes de componentes/serviços e consultas live não substituem essa inspeção.
