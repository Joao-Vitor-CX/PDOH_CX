# CHECKOUT_AUSENTE — Fases 1 e 2

Entrega e validacao local: **17/09/2026**.

## Resultado e limites

Configuracao futura, historico append-only, resolvedor e simulacao de abrangencia implementados.
A API foi atualizada isoladamente no Docker e validada por HTTP em `http://127.0.0.1:8000`.

**O processador continua usando 23:59.** Nenhum processador importa este servico e
nenhuma configuracao e aplicada ao calculo. PDOH, Platina, Gold, ETL e frontend nao foram alterados.
Nao existem endpoints para criar, editar, aprovar ou ativar configuracoes nesta fase.

A simulacao conta ocorrencias observadas de CHECKOUT_AUSENTE; nao calcula diferenca
de minutos, produtividade ou valor PDOH. Ela nao cobre automaticamente todas as
linhas `hora_saida NULL` do processador: o catalogo exclui, por exemplo, casos sem check-in.

## Arquivos desta entrega

| Arquivo | Acao | Finalidade |
| --- | --- | --- |
| `api/app/fallback.py` | Criado | Resolucao e simulacao somente leitura |
| `api/app/fallback_models.py` | Criado | Contratos tipados e validacao de entradas |
| `api/app/main.py` | Alterado | Rotas autenticadas e CORS para POST de simulacao |
| `api/app/database.py` | Alterado | Reflexao das tabelas novas e eventos; conta SELECT preservada |
| `api/app/models.py` | Alterado | Modelo de evento para identificar avisos de truncamento |
| `api/migrations/001_regra_fallback.sql` | Criado | DDL isolado, constraints e sete triggers |
| `api/scripts/provision_fallback.py` | Criado | Provisionamento administrativo explicito, sem seed |
| `api/scripts/validate_fallback.py` | Criado | Conferencia SQL/HTTP/hashes e teste transacional do historico |
| `api/tests/test_fallback.py` | Criado | 21 testes automatizados da nova funcionalidade |
| `api/tests/test_api.py` | Alterado | Contrato OpenAPI permite apenas GET e POST de simulacao |
| `api/README.md` | Alterado | Provisionamento e documentacao das rotas |
| `api/FALLBACK_CHECKOUT.md` | Criado | Relatorio de entrega e contrato |
| `artifacts/fallback-validation-2026-09-17.json` | Criado | Retornos reais e hashes antes/depois |

## Estrutura criada no MySQL local

Schema: `pdoh_controle`.

### regra_fallback_config

Campos: `id` (UUID), `marca`, `regra`, `escopo`, `chave`, `valor_fallback`,
`vigencia_inicio`, `vigencia_fim`, `status`, `usuario_alteracao`, `data_alteracao`.

- Nesta fase, regra admitida: `CHECKOUT_AUSENTE`.
- Marca em maiusculas; escopo `LIDER` ou `MARCA`.
- `LIDER`: chave e identificador estavel do lider, nao nome de exibicao.
- `MARCA`: chave canonica `*`.
- Horario estrito `HH:MM`, entre `00:00` e `23:59`.
- Vigencia DATE inclusiva, em contexto America/Sao_Paulo; fim nulo significa sem termino.
- Status `ATIVO` ou `INATIVO`; valor inicial da coluna e `INATIVO`.
- Identidade (`id`, marca, regra, escopo, chave) imutavel.
- Configuracoes nao podem ser excluidas; futuramente devem ser inativadas.
- Sobreposicao ativa no mesmo escopo/data gera HTTP 409 na resolucao, nunca escolha arbitraria.

### regra_fallback_historico

Campos: `id`, `config_id`, `acao`, `valor_anterior`, `novo_valor`,
`usuario_alteracao`, `data_alteracao`, `regra`, `marca`, `escopo`, `chave`,
`estado_anterior`, `estado_novo`.

Triggers registram INSERT/UPDATE da configuracao atomicamente, incluindo snapshots
completos de valores, status, vigencias e usuario. UPDATE e DELETE do historico
sao rejeitados pelo MySQL; o processo nao substitui linhas anteriores.
Horarios de alteracao sao definidos pelo banco.

O usuario de alteracao e um campo obrigatorio. A autenticacao individual e a
aprovacao por lider deverao ser implementadas antes de expor uma API de escrita;
um operador administrativo pode declarar esse usuario via SQL hoje. O token atual
e de consulta compartilhada local, nao constitui RBAC de lideranca.

As duas tabelas permaneceram com **zero registros** apos os testes. Nenhuma configuracao foi ativada.

## Provisionamento e rollback de implantacao

```powershell
.\api\.venv311\Scripts\python.exe -B api/scripts/provision_fallback.py
.\api\.venv311\Scripts\python.exe -B api/scripts/provision_fallback.py --apply
docker compose -f compose.api.yml up -d --no-deps --build consulta
```

O primeiro comando apenas descreve o plano. O segundo cria objetos novos no MySQL
local existente; nao executa migracoes antigas nem altera grants. DDL e feito
explicitamente pela conta administrativa via Docker; nunca pela API e nunca na
inicializacao. O SQL usa IF NOT EXISTS, sem substituir tabelas ou triggers.

A migracao fica em `api/migrations`, fora da esteira, pois seus triggers precisam
de privilegios que a conta de migracao do pipeline nao possui. Nao se ampliaram
os privilegios dessa conta.

Para rollback de implantacao, reimplantar a versao anterior apenas da API e manter
as tabelas/historicos. Nao executar DROP nem apagar historico. Nao ha alteracao
de calculo para reverter. A criacao de objetos MySQL nao e rollback transacional;
se houver falha parcial de DDL, revisar objetos existentes antes de nova tentativa.

## Endpoints

Todos exigem o Bearer token ja existente em `api/.env.api`. Nenhuma senha ou token
foi adicionado a codigo, frontend ou exemplos. A conta continua possuindo somente
SELECT em `pdoh_controle.*`, com sessao READ ONLY e bloqueio adicional de SQL de escrita.

### GET /api/v1/fallback/resolver

Parametros: `marca` obrigatoria; `regra=CHECKOUT_AUSENTE`, `lider_id` e
`data_referencia=YYYY-MM-DD` opcionais. Data omitida usa a data local atual.

Prioridade: lider ativo/vigente → marca ativa/vigente → DEFAULT 23:59.
Configuracoes expiradas, futuras ou inativas sao ignoradas. Vigencias conflitantes
no escopo vencedor geram 409.

```json
{
  "regra": "CHECKOUT_AUSENTE",
  "origem": "DEFAULT",
  "valor": "23:59",
  "config_id": null,
  "data_referencia": "2026-09-17",
  "aplicado_no_processador": false,
  "fallback_efetivo_processador": "23:59"
}
```

### POST /api/fallback/simular

Alias versionado: `POST /api/v1/fallback/simular`. Os dois usam o mesmo handler.

```json
{
  "regra": "CHECKOUT_AUSENTE",
  "marca": "BRACELL",
  "novo_valor": "18:00",
  "execution_id": "BRACELL_20260915_144924_10D14EA7",
  "periodo_inicio": "2026-08-31",
  "periodo_fim": "2026-09-05"
}
```

`execution_id` e datas sao opcionais. A simulacao e por marca; nao aceita filtro de
lider porque nao ha vinculo historico de equipe validado nesta fonte. O resolvedor
de configuracao por lider e independente desse limite.

- Seleciona UMA execucao concluida, com marca e periodo compativeis, excluindo validacoes sinteticas.
- Sem execution_id, escolhe a mais recente **com evidencias** e declara o criterio no retorno.
  Pode haver execucao posterior sem evidencias: nao se infere que ela tem impacto zero.
- Datas filtram `data_referencia` das oportunidades dentro da janela da execucao.
- Exige evidencia de `hora_saida`, fallback usado `23:59`, ocorrencias positivas e indices de origem.
- Soma `evidencia.ocorrencias`, nao COUNT(*) da tabela de oportunidades.
- Nao soma reprocessamentos. Evidencias identicas do mesmo grupo sao descontadas;
  grupos/indices conflitantes, homonimos com IDs diferentes ou evidencias invalidas geram 409.
- IDs de origem podem ser amostras de ate 20 itens; nesses casos a quantidade vem
  da contagem explicita do grupo, nao do comprimento da lista.
- Colaboradores sao contados por ID quando disponivel; senao, nome normalizado.
  Homonimos sem ID nao podem ser separados; grupos sem identificacao ficam explicitados.
- Truncamento observado na execucao gera aviso. O endpoint nao promete cobertura
  de todas as linhas da origem nem converte ausencia de evidencias em zero.
- Sem execucao elegivel: 404. Recorte sem evidencias ou dados ambiguos: 409.
  Entrada invalida/campos desconhecidos/limite de 100.000 grupos: 422.
- Mesmo novo valor 23:59: registros e colaboradores afetados = 0;
  os campos `*_identificados` preservam o tamanho do conjunto examinado.
- `configuracao_marca` resolve o valor configurado na data atual. Nao representa
  a configuracao usada no processamento historico; `fallback_atual` permanece 23:59.
- Nao grava oportunidade, historico, simulacao ou execucao. Nao recalcula PDOH.

## Validacao realizada

### Testes automatizados

**44 testes da API aprovados, sem skips**, incluindo 21 novos testes de fallback.
**15 testes de contrato/preservacao aprovados**, incluindo hashes dos quatro
processadores protegidos e das duas bases de calculo.

Cobertura dos cinco cenarios obrigatorios:

| Cenario | Resultado |
| --- | --- |
| Sem configuracao ativa | DEFAULT 23:59 |
| Configuracao de lider ativa | Valor do lider, antes da marca |
| Somente marca ativa | Valor da marca |
| Expirada | Marca vigente ou DEFAULT; datas-limite inclusivas |
| Simulacao | Contagens corretas, somente SELECT, snapshots identicos |

Cobertura adicional: inatividade/futuro, isolamento de marca, sobreposicao,
configuracao nao aplicada ao processador, periodo, repeticoes, dados sinteticos,
evidencia incompleta, amostras, homonimos, truncamento, token, CORS e injecao SQL.

No MySQL real, uma transacao de teste exclusivamente nas tabelas novas validou:

- Historico automatico de criacao e alteracao, com valores e vigencias anteriores/novos.
- Quatro bloqueios por trigger: UPDATE/DELETE do historico, DELETE da configuracao,
  alteracao da identidade da configuracao.
- Quatro CHECKs: horario invalido, vigencia invertida, usuario vazio, status invalido.
- ROLLBACK confirmado: nenhum registro de teste persistido. Sequencias auto_increment
  podem consumir numeros em rollback; isso nao altera dados historicos.

### Simulacao com dados reais: antes/depois

Execucao: `BRACELL_20260915_144924_10D14EA7`.
Periodo: **31/08/2026 a 05/09/2026**. Conjunto observado: **267 grupos**,
**1.473 ocorrencias**, **51 nomes normalizados**, nenhum grupo sem nome.

| Medida | Valor igual: 23:59 | Valor simulado: 18:00 |
| --- | ---: | ---: |
| Registros identificados | 1.473 | 1.473 |
| Registros com mudanca hipotetica de horario | 0 | 1.473 |
| Colaboradores identificados por nome | 51 | 51 |
| Colaboradores com mudanca hipotetica | 0 | 51 |
| Fallback efetivo do processador | 23:59 | 23:59 |
| Dados alterados | Nao | Nao |
| PDOH recalculado | Nao | Nao |

Esses numeros nao representam perda/ganho de PDOH e nao provam cobertura integral
da origem. A resposta inclui avisos de amostragem, identificacao por nome e
truncamento da execucao. Existe execucao posterior sem evidencias CHECKOUT_AUSENTE;
o endpoint declara explicitamente a execucao historica utilizada.

Consulta SQL independente confirmou ocorrencias, colaboradores e grupos do retorno.
Os endpoints de health, resolucao e simulacao responderam HTTP 200 tambem pela
API implantada em `127.0.0.1:8000`, com `Cache-Control: no-store`.

### Integridade

- As 16 tabelas preexistentes de controle conservaram contagem e hash dos dados
  desde antes do provisionamento. As 18 tabelas (incluindo as duas novas) tambem
  conservaram seus hashes antes/depois dos testes e da simulacao.
- Oportunidades: **59.618 → 59.618**.
- Historico de oportunidades: **59.618 → 59.618**.
- Execucoes: **30 → 30**; nenhuma nova execucao.
- Configuracoes de fallback: **0 → 0**; historico novo: **0 → 0**.
- Platina local: **300 → 300** linhas, hash identico:
  `9fac902a5e13ef8e7a8120ba8090538e29a65495208df2ed8a298ed8b7ca4831`.
- **151 arquivos** de bracell, frontend, sql e config com hashes antes/depois
  identicos (excluidos dependencias, caches e build). Nenhuma alteracao de ETL/Gold/frontend.

Evidencias completas: `artifacts/fallback-validation-2026-09-17.json`.

## Reexecutar verificacoes

```powershell
$env:PDOH_TEST_OBSERVER_PYTHON=(Get-Command python).Source
try { .\api\.venv311\Scripts\python.exe -B -m unittest discover -s api/tests -v }
finally { Remove-Item Env:PDOH_TEST_OBSERVER_PYTHON }
.\api\.venv311\Scripts\python.exe -B -m unittest discover -s tests -p test_contrato_replicacao.py -v
.\api\.venv311\Scripts\python.exe -B api/scripts/validate_fallback.py
# Opcional: testar triggers com registros novos e rollback; conferir a Platina por SELECT.
.\api\.venv311\Scripts\python.exe -B api/scripts/validate_fallback.py --test-history --check-platina
```

O runtime indicado em PDOH_TEST_OBSERVER_PYTHON deve possuir pandas. Sem ele,
um teste preexistente de cadastro e ignorado; os testes de fallback nao dependem dele.
O validador real usa credenciais locais sem imprimi-las. A opcao de historico
usa conta administrativa somente para os testes transacionais das tabelas novas.

## Fase 3 nao implementada

Permanecem futuros: telas, edicao, aprovacao individual, autorizacao por lider,
historico na interface e integracao efetiva com calculo. Mesmo essas telas nao
autorizarao alterar o processador protegido sem uma etapa especifica aprovada.
