# Revisão operacional — 16/09/2026

Evolução do frontend existente, preservando shell, identidade visual e componentes.
Referência: ZIP de mockups aprovado pelo usuário; navegação técnica do protótipo
foi adaptada para Oportunidades, Dashboard e Execuções. O original em Downloads
permaneceu inalterado. Backend, pipeline e Platina não foram editados nesta revisão.

## Conferência banco × API × interface

Consulta de leitura no banco local, com a conta da API e transação read-only:

| Classificação pelo vínculo atual | Banco | API/serviço do front | Interface |
| --- | ---: | ---: | ---: |
| Operacionais (`ALERTAR`/`REGISTRAR`) | 8.088 | 8.088 | 8.088 |
| Informativos (`TELEMETRIA`) | 5.018 | 5.018 | 5.018 |
| Sem regra vinculada (`regra_id IS NULL`) | 43.664 | 43.664 sem classificação | Aviso separado |

Total bruto 56.770 utilizado somente para reconciliação. Não é o indicador principal.
29 execuções, 23 regras, 11 De/Para e 312 entidades conferidos pelo teste de contrato.
Contagens são um retrato desta verificação e podem mudar.

A primeira tentativa de conferir o banco foi bloqueada pelo isolamento; a execução
subsequente foi autorizada e a consulta SELECT confirmou os números acima.
Nenhum vínculo ausente foi preenchido, nenhuma regra foi aplicada retroativamente.

## Verificações

- Sete testes unitários aprovados: vocabulário, classificação pelo catálogo, evidências nulas/falsas/zero,
  IDs textuais, subgrupos parciais, concorrência limitada, vínculo por regra, erros de API.
- Teste live: soma das classes reconciliada com dashboard e retorno vazio preservado.
- Teste de contrato: listas/detalhes/históricos, IDs e datas preservados, filtros e erro 422.
- Navegador: operacional separado de telemetria; seleção de grupo e registro;
  fallback real `1999-01-01`; orientação real; histórico; rastreabilidade; consulta contextual
  de padronização sem correspondência fictícia; viewport móvel de 390 × 844 sem overflow horizontal.
- Build de produção e lint aprovados durante a revisão; o build Windows requer permissão
  para subprocessos nativos do Vite. A sessão local não substitui autenticação corporativa.
- Bundle final inspecionado: valores do token da API e da senha do banco ausentes.
- Etapas/fontes reais da execução verificadas no navegador; período inválido exibiu erro
  de filtros, sem transformar a falha em contagem zero.

## Limitações explícitas

- Os 43.664 registros sem vínculo não podem ser classificados com segurança pela regra
  atual apenas usando o tipo. Continuam acessíveis na consulta completa, com identificação
  da classificação por registro. Não existe filtro de regra nula na API desta fase.
- Os totais refletem registros, não pessoas ou problemas únicos; repetições entre execuções
  permanecem preservadas. Não há estimativa de impacto ausente na evidência.
- Catálogo atual não comprova versão historicamente aplicada. Consultas HTTP múltiplas
  não compartilham uma transação, apesar da conferência de totais antes/depois.
- Subgrupos por campo/fonte são relativos à página, não agregações globais.
- Esta entrega é somente leitura. Sem edição, tratativa, reprocessamento ou publicação externa.
