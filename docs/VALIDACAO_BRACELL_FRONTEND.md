# Validação BRACELL no Front-end PDOH

## Fonte utilizada

O dashboard consulta a saída diária tratada produzida pelo processamento PDOH_CX:

`produtos_platina.exclusivo_bracell_platina_relatorio_pdoh`

Essa estrutura é alimentada pelo processamento que lê as fontes operacionais da BRACELL. Nenhuma tabela Gold participa da consulta. O front-end não acessa banco e não calcula os indicadores; ele consome somente a API de leitura.

Para a rastreabilidade da jornada são consultadas, quando disponíveis, as estruturas de controle existentes `pdoh_controle.jornada_consolidada` e `pdoh_controle.fallback_evento`.

## Consulta e estrutura utilizadas

Foi mantido o endpoint existente `GET /api/v2/pdoh/resumo`. O contrato foi ampliado com:

- filtros `colaborador`, `estado`, período e paginação;
- `detalhes`, com as linhas diárias usadas na conferência;
- `filtros_disponiveis`, com colaboradores e estados presentes na janela;
- auditoria de fonte de jornada e evento de fallback por colaborador.

Não foi criado endpoint, view, tabela, oportunidade ou regra. A consolidação oficial já existente no backend permaneceu responsável pelos cartões; o cliente apenas formata os valores recebidos.

## Componentes alterados

- `frontend/src/pages/pdoh-dashboard-page.tsx`: aplica filtros e exibe a validação diária.
- `frontend/components/platform/operational-filters.tsx`: períodos de validação, colaborador e estado.
- `frontend/components/platform/pdoh-result.tsx`: exibe também a efetividade retornada pela API.
- `frontend/components/platform/pdoh-daily-validation.tsx`: tabela paginada de conferência e auditoria de jornada.
- `frontend/src/services/pdoh-indicator.ts`: contrato tipado da resposta diária.
- `frontend/src/services/findings-service.ts`: usa primeiro a janela resolvida pelo PDOH e repassa a mesma janela às consultas auxiliares.

## Campos exibidos

- colaborador, estado, data e nome do dia;
- deslocamento, ócio, produtividade, horas não registradas e horas programadas;
- primeiro check-in e último checkout;
- visitas previstas/realizadas e pesquisas previstas/realizadas;
- percentuais persistidos de produtividade, visitas, pesquisas e efetividade;
- fonte da jornada, horário aplicado, confirmação de fallback e origem do fallback;
- tabela de origem da linha.

## Períodos disponíveis

Hoje, ontem, semana anterior, últimos 7 dias, últimos 30 dias, mês anterior, 3 meses anteriores, 12 meses anteriores, intervalo fixo e intervalo relativo. A ação “Excluir filtros” remove a seleção aplicada. As janelas são resolvidas pelo backend; o navegador não define datas operacionais.

## Divergências e limites observados

1. A tabela diária possui a jornada aplicada (`horas_programadas`), mas a origem da jornada está em uma estrutura de auditoria separada. Quando não existe vínculo auditável, a tela informa valor ausente.
2. A presença de `JORNADA_PADRAO_44H` comprova que houve fallback. A ausência do evento não comprova o contrário, pois a observabilidade pode ser anterior ou ter sido limitada; por isso a tela mostra “Não identificado”.
3. O endpoint chama a origem de `PLATINA`, nome da camada tratada existente. Ela não é uma tabela Gold.
4. Na janela de 31/08 a 05/09/2026, a fonte real retornou 300 linhas, 50 colaboradores, 6 dias e os estados CE, MA, PA e PI. A origem de jornada foi identificada em 264 linhas; 36 ficaram sem vínculo auditável e são exibidas como não identificadas.
5. A meta oficial do PDOH continua sem cadastro na configuração e permanece ausente, como já ocorria.
6. A fonte disponível contém somente o período de 31/08 a 05/09/2026. A semana anterior ao dia da validação (14/09 a 19/09/2026) retorna corretamente sem dados; a atualização/carga da fonte é uma pendência operacional, não foi mascarada pela interface.

## Pontos para o mapeamento futuro de endpoints

- decidir se o detalhamento paginado continuará no resumo ou será servido por view/contrato específico após a revisão com a liderança;
- definir vínculo temporal canônico entre a linha diária e `jornada_consolidada`;
- decidir se a ausência comprovada de fallback será persistida para permitir exibir “Não” com segurança;
- alinhar a nomenclatura pública da camada tratada para evitar confusão entre Platina e Gold;
- revisar limite máximo, paginação e índices para consultas de 12 meses;
- definir se opções de colaborador/estado devem vir de uma view de dimensões em vez da própria janela diária.

## Verificações executadas

- 127 testes da API aprovados, com 1 teste opcional ignorado por ausência do runtime isolado;
- 15 testes de contrato do front-end aprovados;
- TypeScript e lint aprovados;
- build de produção aprovado;
- testes novos cobrem filtro combinado de colaborador/estado, linhas diárias, percentuais persistidos, paginação, evento de fallback e todas as janelas de data.
- 843 verificações HTTP/SQL contra o MySQL real aprovadas; os hashes das tabelas de controle permaneceram idênticos antes e depois;
- 25 reconciliações específicas do front BRACELL aprovadas: PDOH geral, por Estado e por colaborador conferem com a razão de somas da tabela tratada; paginação e campos diários conferem com o SQL.
- fluxo live do front aprovado por proxy autenticado: contrato com dados e contrato sem dados retornaram HTTP 200 sem converter ausência em zero.
