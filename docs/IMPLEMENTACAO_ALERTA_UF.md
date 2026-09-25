# Alerta cadastral UF — continuação em 16/09/2026

## Situação da entrega

Implementação local e testes isolados concluídos. **Aceite com dados reais pendente**:
falta acesso autenticado à origem e aprovação da simulação antes de qualquer gravação.
Não foi executado UPDATE/INSERT/DELETE, seed, migração ou pipeline em banco real.
Não houve deploy nesta continuação. O frontend não foi alterado.

## Fonte identificada e configuração

- O carregador atual consulta `colaboradores_ativos_bracell`, antes das validações
  laterais e sem filtro de período para cadastro. Depois utiliza o maior
  `data_evolucao`, usuários `sim` e a referência mais recente. Foi apenas lido.
- A tabela local `involves_bracell.colaboradores_ativos_bracell` está vazia.
- O usuário corrigiu a indicação para **`raw_exclusivo_bracell_colaboradores_ativos`**.
  Esta indicação ainda requer confirmação do schema/colunas e dados via SELECT.
- A conexão externa `137.184.232.133:3306` está cadastrada no DBeaver. A configuração
  da aplicação não contém credenciais da origem; não foram extraídas senhas do DBeaver.
- `.env.cadastro` foi preparado, ignorado pelo Git, para
  `involves_exclusivos.raw_exclusivo_bracell_colaboradores_ativos`. Usuário e senha
  estão vazios. Esta configuração **não é carregada pela ETL/Compose**.
- O modelo sem segredos está em `config/cadastro-origem.example.env`.

Após preencher as credenciais de leitura localmente, executar:

```powershell
python scripts/simulate-cadastral-alerts.py --env-file .env.cadastro
```

O script exige configuração explícita, abre sessão somente leitura e aceita apenas
comandos de consulta. Primeiro verifica as colunas reais; se não corresponderem,
retorna `SCHEMA_REQUER_VALIDACAO`, sem inventar mapeamentos. Limita a leitura a
100.000 linhas; exceder o limite não produz uma contagem final silenciosamente parcial.
Datas inválidas impedem tratar a proposta como quantidade final validada.
O relatório contém dados cadastrais: não publicá-lo em logs abertos.

## Regra implementada — versão 1, sujeita à confirmação da origem

- Tipo específico: `CADASTRO_UF_AUSENTE`, catálogo `ALERTA`, severidade `BAIXA`.
- Evidência: `QUALIDADE_CADASTRAL`, campo `UF`, situação `Não preenchido`,
  tratativa `Atualizar cadastro na origem`, sem fallback.
- Escopo exclusivo BRACELL; `usuario_ativo = sim`, sem inferir atividade de valores
  desconhecidos. Quando a fonte tem coluna `marca`, ela também é conferida.
- Snapshot pelo maior `data_evolucao`; verifica o registro mais recente de cada
  usuário por `data_dimensao`. Cadastro mais recente preenchido/inativo impede
  falso alerta sobre ocorrências antigas. Nenhum DataFrame do cálculo é alterado.
- `uf` e `estado` são aliases de entrada: só identifica ausência se todos os aliases
  presentes estiverem NULL/vazios. Conflito entre valores preenchidos é outro cenário.
- Consolidação: marca + usuário da origem + UF. Sem usuário, nome é referência
  **não confirmada**; sem ambos, as linhas não são fundidas como uma pessoa.
- Conta linhas ausentes do snapshot antes do limite de evidências, preserva uma
  amostra de índices/datas/valores e fingerprint estável por grupo. A restrição já
  existente `(execution_id, fingerprint)` impede duplicar o grupo na mesma execução.
- A evidência não inventa `colaborador_id_interno`. Preserva o usuário de origem
  separadamente para posterior vínculo de identidade validado.
- Sem regra BRACELL ATIVA classificada `ALERTA`, o novo achado não é persistido:
  registra apenas diagnóstico técnico. Isso evita gerar `FALHA_PARAMETRIZACAO`
  operacional para um alerta cadastral ainda não aprovado.

O observador existente reconhece o novo tipo sem mudar a ETL. A consulta da tabela
RAW indicada está separada em dry-run; **não foi conectada silenciosamente à fonte
usada pelo cálculo**. A ativação da emissão sobre essa fonte aguarda sua validação.

## Contrato da API

`GET /api/v1/alertas?marca=BRACELL&campo=UF&execution_id=...`

- Mantém filtro explícito `ALERTA` pelo catálogo vinculado.
- UF aceita filtro `UF` ou `uf` e usa identidade de origem + campo no agrupamento.
- `quantidade_ocorrencias` soma a contagem do novo achado consolidado, não apenas
  o número de linhas persistidas. Só a versão reconhecida desta regra usa esse peso;
  os registros anteriores continuam valendo uma ocorrência cada.
- `quantidade_registros` e `total_registros` explicitam o número de achados persistidos.
- Retorna categoria e tratativa nos campos; mantém os IDs/detalhes/históricos acessíveis.
- Execuções distintas mantêm seu histórico e suas ocorrências. Para ver um snapshot,
  usar `execution_id`; somar execuções não equivale a ocorrências únicas na origem.
- A fila operacional continua sendo `/oportunidades?classificacao=OPORTUNIDADE`.

## Testes e preservação

- 64 testes de observabilidade/contratos: aprovados, incluindo 8 novos de UF.
- 23 testes de API: aprovados. O teste de cadeia executa o observador sobre dados
  sintéticos, captura os parâmetros reais de persistência/histórico e consulta
  esses registros em SQLite por HTTP. **Não equivale a homologação no MySQL real.**
- Fixture: três usuários fictícios com 10/1/1 ocorrências → três alertas / 12 ocorrências.
  Cadastro válido e inativo não geram alerta UF; homônimos com usuários distintos não
  são fundidos. Testados snapshot corrigido, aliases, regra ausente/incorreta,
  preservação entre execuções e contagens malformadas.
- Hashes do manifesto dos processadores/arquivos protegidos aprovados. Também
  conferidos sem mudança nesta continuação: ETL, conexão do cálculo, identidade,
  fallbacks legados e todos os arquivos de `frontend/src`.
- Banco real conferido novamente somente por SELECT:

| Estrutura / classificação | Antes | Depois |
| --- | ---: | ---: |
| oportunidade | 59.618 | 59.618 |
| oportunidade_historico | 59.618 | 59.618 |
| de_para_historico | 38 | 38 |
| execucao | 30 | 30 |
| OPORTUNIDADE | 4.273 | 4.273 |
| ALERTA | 6.663 | 6.663 |
| TELEMETRIA | 5.018 | 5.018 |
| Sem classificação vinculada | 43.664 | 43.664 |

## PESQUISA_CAMPOS_NULOS — recomendação, sem reclassificação

Os 2.344 achados continuam classificados como ALERTA. Nesta etapa **não aplicar**
a proposta numérica do relatório anterior; ela não recebeu aprovação para mudança.
Exemplo reconfirmado: oportunidade `000ff3f1-931a-4e18-838b-78059ea1cf83`,
execução `BRACELL_20260915_144924_10D14EA7`, pesquisa `id=31281109`, responsável ausente.

A leitura de `pdoh_bracell.py` mostra que `responsavel` vira `Responsável` e depois
`Colaborador`. É usado no agrupamento e merge do percentual de pesquisas, e nas
pesquisas respondidas usadas para produtividade. Há fallback amplo para data técnica
de 1999. Isso sustenta **risco de perda de atribuição**, não comprova sozinho a perda
numérica de PDOH desses 2.344 registros. São achados históricos, não necessariamente
2.344 pesquisas únicas; podem repetir entre execuções.

Recomendação: manter a classificação atual até conferir na origem os IDs únicos,
status, duração, datas e possibilidade de identificar o responsável; cruzar com
período e colaborador de saída em consulta isolada. Propor reclassificação segmentada
somente para registros com impacto demonstrado e auditável. Não classificar todos
os NULL como oportunidade, nem alterar a regra genérica por UPDATE global.

## Próximo ponto de aprovação e rollback

**Mudanças reais aplicadas ao banco: zero. Quantidade real de novos alertas: ainda
desconhecida. Não afirmar três colaboradores reais com base na fixture.**

1. Validar acesso, tabela RAW, campos e snapshot, executando o dry-run.
2. Apresentar grupos/ocorrências reais e exemplos com referência de origem;
   comparar cada fingerprint com a execução alvo para não duplicar alertas.
3. Proposta de aplicação deve enumerar a nova regra específica (se ausente), IDs de
   novos alertas/históricos e qualquer contador de execução afetado, sem reclassificar
   oportunidades antigas. Não executar o bootstrap amplo como atalho.
4. Impacto esperado: fila operacional +0, telemetria +0; alertas +N novos grupos
   persistidos (N a apurar), ocorrências conforme evidência. Catálogo +1 regra apenas
   se ainda não cadastrada. Dashboard deve distinguir grupos e ocorrências.
5. Rollback atual é somente de código/configuração destes novos trechos; preservar
   as alterações anteriores do usuário. Não há rollback de banco a executar.
   Antes de uma aplicação futura, guardar os IDs/snapshot e estado da regra; em caso
   de reversão, interromper a emissão e registrar correção auditada por esses IDs,
   preservando histórico. Nunca excluir registros ou restaurar toda a base.
6. **Aguardar aprovação da proposta concreta** antes de persistir ou atualizar;
   validar MySQL → API real e somente então evoluir o frontend.
