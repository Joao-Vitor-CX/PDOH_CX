# Evidência local — Fase 2

Validação realizada em 15/09/2026, contra o contêiner `pdoh_cx_mysql` existente.

## Resultado

- 15 testes determinísticos da API aprovados (SQLite em memória).
- 44 testes existentes do PDOH_CX aprovados.
- 710 verificações de HTTP/ASGI, contratos e SQL real aprovadas.
- API publicada em `127.0.0.1:8000`, contêiner saudável; Swagger HTTP 200.
- Chamada HTTP real do Windows ao dashboard autenticado retornou 200.
- Conta da API validada com somente `SELECT` em `pdoh_controle.*`; sessão READ ONLY.
- Conteúdo das 16 tabelas de controle idêntico antes/depois (SHA-256 por tabela).
- Checksums da Platina e das cinco tabelas de entrada idênticos antes/depois.
- Nenhum processamento, migração, alteração de regra ou escrita em tabela de
  negócio foi executado nesta fase. A alteração administrativa foi criar a
  conta dedicada `pdoh_cx_reader` e conceder leitura no schema de controle.

## Dados encontrados

| Estrutura | Registros |
|---|---:|
| execucao | 28 |
| execucao_etapa | 288 |
| oportunidade | 53.161 |
| oportunidade_historico | 53.161 |
| regra_tratativa | 21 |
| de_para | 11 |
| de_para_historico | 11 |
| colaborador_identidade | 90 |
| identificador_entidade | 312 |
| saida_linhagem | 2.079 |

Estados reais de execução: 12 FALHA_TECNICA, 5 CONCLUIDA_COM_ALERTAS,
5 CONCLUIDA_SEM_RESULTADO, 3 CONCLUIDA e 3 INICIADA.
Todas as oportunidades presentes estavam ABERTA. Os testes isolados também
cobrem status diferentes, período invertido, limites de paginação e ausência
de dados/relacionamentos. Não foram criadas ocorrências artificiais no MySQL.

Há execuções com janela em 2099, registros sem regra vinculada e oportunidades
sem identidade individual. Foram preservados, não corrigidos ou ocultados.

## Preservação de origem e Platina

`CHECKSUM TABLE ... EXTENDED`, antes e depois:

| Tabela | Antes | Depois |
|---|---:|---:|
| produtos_platina.exclusivo_bracell_platina_relatorio_pdoh | 726494464 | 726494464 |
| involves_bracell.status_day_operacao_bracell | 0 | 0 |
| involves_bracell.colaboradores_ativos_bracell | 0 | 0 |
| involves_bracell.relatorio_checkin_bracell | 0 | 0 |
| involves_bracell.gerencial_visitas_bracell | 0 | 0 |
| involves_bracell.painel_pesquisas_bracell | 0 | 0 |

Esses valores são checksums, não contagens de linhas. Para controle, o
relatório JSON contém contagens e hashes SHA-256 de todo o conteúdo.

## Artefatos e limites

- `artifacts/api-validation.json`: verificações, schema real, relacionamentos,
  contagens, hashes antes/depois e resumo do dashboard.
- `artifacts/api-openapi.json`: contratos gerados pela aplicação validada.
- A validação real usa TestClient HTTP/ASGI com o mesmo código da API e conta
  de leitura; a publicação TCP foi verificada adicionalmente pelo Windows.
- CI específico criado, mas execução remota no GitHub ainda não realizada.
- Token local é autenticação para homologação. Sessão corporativa e autorização
  por usuário/marca continuam pendentes para uma entrega multiusuário.
- Fase 3 (telas funcionais) não iniciada.

As evidências descrevem o estado observado nessa execução, não garantem que
os mesmos totais continuem iguais após novos processamentos.
