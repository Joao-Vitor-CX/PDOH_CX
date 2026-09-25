# Separação OPORTUNIDADE × ALERTA × TELEMETRIA

Implementação concluída em 17/09/2026, sem alteração do frontend.

## O que mudou

Os detectores agora enviam seus achados para `registrar_achado()`. O dispatcher
consulta exclusivamente `pdoh_controle.regra_tratativa`, considerando a marca
da execução e a precedência regra específica → regra global. O produtor não pode
forçar `classificacao` ou `regra_id`.

| Classificação do catálogo | Destino para novos achados |
| --- | --- |
| `OPORTUNIDADE` | `pdoh_controle.oportunidade` + `oportunidade_historico` |
| `ALERTA` | `pdoh_controle.alerta` |
| `TELEMETRIA` | `pdoh_controle.execucao_evento` |

`achado_roteamento` registra a decisão, snapshot da regra, fingerprint, destino e
ID persistido. Isso congela a classificação de um novo achado mesmo que o catálogo
mude depois. O mesmo fingerprint na mesma execução é idempotente.

O tipo `CONFIGURACAO` não é um destino operacional. Regra inexistente, inativa,
ambígua ou com classificação inválida gera somente evento de diagnóstico
`CLASSIFICACAO_NAO_RESOLVIDA`; nunca é promovida automaticamente a oportunidade.

## Compatibilidade histórica

Nenhum registro antigo foi migrado, atualizado ou excluído. A API v1 mantém os
contratos existentes. A API v2 oferece projeções separadas:

- `GET /api/v2/oportunidades` — somente OPORTUNIDADE;
- `GET /api/v2/alertas` — somente ALERTA;
- `GET /api/v2/telemetria` — somente TELEMETRIA.

Por padrão, as projeções incluem achados legados, identificados como
`OPORTUNIDADE_LEGADO`/`CATALOGO_ATUAL_LEGADO`. Use `incluir_legado=false` para
ver apenas registros gravados pelo novo dispatcher. Não existe cópia física dos
registros antigos.

## Objetos novos

`docker/mysql/migrations/008_roteamento_achados.sql` cria, de forma aditiva:

- `alerta`: qualidade e acompanhamento, com marca, regra, colaborador, campo,
  tratativa, evidência, status e fingerprint;
- `achado_roteamento`: ledger da decisão de classificação e destino.

As FKs referenciam `execucao.execution_id` e `regra_tratativa.regra_id`; não há
colunas ou tabelas específicas de marca. BRACELL, FLORA e outras marcas usam a
mesma estrutura, sempre isoladas por `marca` e pela execução correspondente.

O provisionamento é explícito e separado da inicialização da API:

```powershell
.\api\.venv311\Scripts\python.exe -B api/scripts/provision_findings.py
.\api\.venv311\Scripts\python.exe -B api/scripts/provision_findings.py --apply
```

Não há seed, backfill, rename, UPDATE ou DELETE nesse script.

## Regras validadas

| Tipo | Classificação esperada | Resultado |
| --- | --- | --- |
| `CHECKOUT_AUSENTE` | OPORTUNIDADE | Persistido em oportunidade |
| `PDV_MESMO_NOME_IDS_DISTINTOS` | ALERTA | Persistido em alerta |
| `DATA_FORA_DO_PERIODO` | TELEMETRIA | Persistido em evento |
| `VALOR_SEM_PADRONIZACAO` | ALERTA | Persistido em alerta |
| `REGISTRO_DUPLICADO` | TELEMETRIA | Persistido em evento |
| `CAMPO_OBRIGATORIO_VAZIO` | OPORTUNIDADE | Persistido em oportunidade |

## Testes

- 10 testes do dispatcher/API v2 em `api/tests/test_findings.py`.
- 44 testes da API (incluindo fallback e contratos cadastrais).
- 64 testes da suíte principal, todos aprovados.
- Teste MySQL real transacional: seis tipos roteados, repetição idempotente,
  histórico de oportunidade apenas para OPORTUNIDADE e rollback completo.
- API real: `oportunidades=4.273`, `alertas=6.663`, `telemetria=6.028` na
  projeção legada; `incluir_legado=false` retornou zero, pois nenhum achado novo
  foi persistido.

## Integridade e riscos

As tabelas preexistentes conservaram contagens e hashes; `oportunidade` continuou
com 59.618 registros. A tabela nova `alerta` e o ledger permaneceram vazios após
o rollback dos testes. Os quatro processadores protegidos, cálculo PDOH, Platina,
Gold, ETL e frontend não foram alterados.

O bootstrap histórico ainda contém dados de catálogo para semear regras BRACELL;
isso é seed de configuração, não motor de roteamento. A próxima evolução deve
parametrizar também os produtores hoje específicos de BRACELL (fonte e identidade)
antes de habilitar uma segunda marca em produção. Não se deve unir identidades
entre marcas nem por nome isolado.

## Próxima etapa

Antes de ativar qualquer regra nova, executar a simulação e revisar o snapshot do
catálogo. A autorização individual, aprovação de liderança, edição de regras e
interface de gestão permanecem fora desta entrega. O frontend será tratado no
próximo prompt, conforme solicitado.
