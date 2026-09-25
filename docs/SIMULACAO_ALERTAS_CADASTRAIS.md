# Simulação de classificação e diagnóstico de UF — 16/09/2026

**Status: diagnóstico e simulação somente leitura. Aguardando validação.**

Nesta continuação não houve UPDATE, INSERT, DELETE, migração, execução de pipeline
nem nova alteração do frontend. Foram adicionados apenas scripts de inspeção e este
relatório. As alterações da implementação anterior permanecem preservadas.

## 1. Banco de oportunidades

Foram conferidos os 59.618 registros atuais, seus vínculos, marca, tipo, evidência
e origem. A classificação não é uma coluna da tabela `oportunidade`: vem da regra
vinculada em `regra_tratativa.classificacao`. Ela representa o catálogo atual, não
necessariamente a versão histórica aplicada.

- 43.664 registros têm `regra_id` ausente; permanecem sem classificação reconhecida.
- Entre os vinculados, não foram encontrados regra inexistente ou divergência de
  marca/tipo nesta inspeção. Regras globais seriam aceitas apenas para a marca do registro.
- Não foram encontrados marca/origem vazias ou evidências sem estrutura no conjunto inspecionado.
- `oportunidade_historico` mantém 59.618 registros. Nenhuma oportunidade foi removida.

Os filtros da API retornaram, para BRACELL, 6.663 ALERTAS, 5.018 TELEMETRIAS e
4.273 OPORTUNIDADES. Nas amostras de 200 registros por classe, nenhuma classe
divergiu do filtro. `CHECKOUT_AUSENTE` permanece operacional, com 267 registros.

## 2. UF ausente: diagnóstico, não aceite concluído

`GET /api/v1/alertas?marca=BRACELL&campo=uf` retorna **zero** grupos e ocorrências.
A inspeção integral das evidências de oportunidades também não encontrou campo `uf`.
O campo `estado` retorna outros 51 grupos / 1.500 ocorrências e não deve ser tratado
como prova dos três colaboradores com UF nula.

Causa no observador `bracell/src/data_quality.py`:

- As obrigatórias de `colaboradores` são `nome_colaborador`, `usuario_ativo`, `data_evolucao`.
- `uf` não está entre elas.
- A checagem de formato de UF exige `~_vazio(...)`, excluindo explicitamente os NULL/vazios.

Não é apenas um problema de duplicação no frontend: falta geração do achado de UF
ausente. Não há registros de UF nesse conjunto para um UPDATE de reclassificação.

### Fonte real necessária

A tabela local `involves_bracell.colaboradores_ativos_bracell` existe, incluindo
as colunas `uf`, `nome_colaborador` e `usuario`, mas possui **zero linhas**.
Não foi encontrada configuração `PDOH_SOURCE_DB_*` no `.env` nem no ambiente desta tarefa.
Nenhuma outra origem foi presumida ou alterada.

Na coluna `colaborador` do histórico de oportunidades existem 499 registros com
o nome CAMILA RUFINO DE OLIVEIRA e 913 com GERSON DA SILVA GOMES, de tipos variados;
nenhum com EDGARD JOAO CUTRIM DINIZ. Isso **não comprova UF ausente** nesses nomes,
nem a ausência de Edgard na fonte externa.

Para certificar exatamente os três alertas reais, é necessário indicar a fonte de
cadastro usada pela execução ou fornecer uma extração somente leitura com marca,
identificador/usuário, nome, UF e data de referência. Não será usada uma lista fixa
de nomes para fabricar o resultado esperado.

### Correção proposta, ainda não aplicada nesta continuação

1. Detectar UF nula/vazia em camada observacional, sem modificar o DataFrame.
2. Regra específica de qualidade cadastral, classificação `ALERTA`, categoria
   `QUALIDADE_CADASTRAL`, situação `Não preenchido`, orientação de corrigir a UF na origem.
3. Agrupar por marca + referência de colaborador + campo pendente. Quando houver ID,
   preservá-lo; ausência de identidade confirmada deve ser explícita, sem juntar
   pessoas desconhecidas em um único grupo. Não separar o mesmo colaborador apenas por ocorrência/data.
4. Persistir novos achados apenas após validar fonte, quantitativo e estratégia de
   rastreabilidade; não executar a esteira de cálculo para preencher a interface.
5. Ajustar o front somente após validar a resposta real; apenas `OPORTUNIDADE` na
   fila operacional e `ALERTA` na aba cadastral, com marca, campo, ocorrências e tratativa.

## 3. PESQUISA_CAMPOS_NULOS — simulação por evidência

Os 2.344 registros atuais deste tipo têm `campo_esperado = ["responsavel"]` e
valor encontrado `(ausente)`, origem `INVOLVES_BRACELL`, tabela
`painel_pesquisas_bracell`. O responsável é usado no agrupamento e vínculo do
indicador de pesquisas ao colaborador. A ausência pode impedir a atribuição;
não foi calculado um delta numérico de PDOH nem executado o cálculo.

Proposta para **esses registros específicos**, sujeita à validação: ALERTA → OPORTUNIDADE.
Não se propõe elevar todos os NULL nem executar UPDATE global na regra genérica.
Outros campos/cenários continuam exigindo avaliação própria.

| Campo / contexto | Registros atuais deste tipo | Classificação sugerida | Fundamento |
| --- | ---: | --- | --- |
| responsavel | 2.344 | OPORTUNIDADE | Atribuição do indicador ao colaborador |
| status | 0 | OPORTUNIDADE | Numerador de pesquisas respondidas |
| data_expiracao | 0 | OPORTUNIDADE | Seleção temporal e agrupamento diário |
| data_solicitacao | 0 | OPORTUNIDADE | Filtro de entrada; universo recebido pelo cálculo |
| id | 0 | ALERTA | Identificação/rastreabilidade; impacto aritmético não comprovado |
| data_conclusao, pesquisa pendente | 0 | TELEMETRIA | NULL pode ser esperado; não gerar problema só por ausência |
| data_conclusao, pesquisa respondida | 0 | OPORTUNIDADE | Já há o cenário DADO_INCOMPLETO |

As quantidades se referem às evidências persistidas do tipo específico, não ao
total de NULL na origem nem a colaboradores únicos. Observadores podem limitar
evidências e repetir achados em execuções diferentes.

Exemplos reais (regra atual `ed31c2a2-652d-5b80-9cd5-e5b411931252`):

| Oportunidade | Registro afetado | Atual | Proposta |
| --- | --- | --- | --- |
| 000ff3f1-931a-4e18-838b-78059ea1cf83 | id=31281109 | ALERTA | OPORTUNIDADE |
| 00234849-3b36-415d-9971-595ad09d5754 | id=31281675 | ALERTA | OPORTUNIDADE |
| 0064f4d9-38bb-4a05-a966-2e8e2b6496a5 | id=31220267 | ALERTA | OPORTUNIDADE |

### Impacto simulado no dashboard

| Classe | Atual | Após proposta de pesquisa | Diferença |
| --- | ---: | ---: | ---: |
| OPORTUNIDADE | 4.273 | 6.617 | +2.344 |
| ALERTA | 6.663 | 4.319 | -2.344 |
| TELEMETRIA | 5.018 | 5.018 | 0 |
| Sem classificação | 43.664 | 43.664 | 0 |
| Total de registros | 59.618 | 59.618 | 0 |

Os três alertas de UF não estão incluídos nessa projeção: faltam evidências reais
e o número de ocorrências N de cada colaborador. Classificação dos 43.664 registros
sem vínculo não foi inferida apenas pelo nome do tipo.

Se a proposta for aprovada, antes de aplicar deverá ser definido um mecanismo
auditável por campo/registro, com IDs afetados, classe anterior/nova, motivo,
responsável, data e versão da regra. Mudar a classificação da regra genérica
afetaria também outros cenários futuros; isso não é equivalente à proposta segmentada.

## 4. Testes e evidências

- 20 testes automatizados existentes de API/consolidação: aprovados em SQLite isolado.
- Reproduzido em memória: três nomes, três ocorrências de UF nula por nome e um
  cadastro válido com `CE`. O código atual gerou **zero**, quando se esperam três
  grupos. O DataFrame permaneceu inalterado. Logo, esse critério ainda falha.
- Cadastro válido não gerou achado de UF nesse teste.
- A consolidação genérica por colaborador/campo está coberta por testes, mas não
  comprova os três alertas reais quando a origem e os achados ainda faltam.
- Oportunidade real preservada: 267 CHECKOUT_AUSENTE no filtro OPORTUNIDADE.
- Nenhuma nova validação de frontend foi usada para encobrir inconsistência na fonte.

## 5. Próximas decisões

1. Validar a proposta segmentada dos 2.344 registros de pesquisa e o mecanismo de auditoria.
2. Indicar a fonte/snapshot real dos três colaboradores com UF ausente.
3. Somente então concluir geração, consolidação, conferência banco × API e ajustes de front.

Não houve commit. Cálculo PDOH, processadores, ETL, Gold e Platina não foram alterados
nesta continuação. Esta etapa não está marcada como concluída.
