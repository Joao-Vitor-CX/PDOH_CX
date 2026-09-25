# PDOH_CX — API de consulta (Fase 2)

Serviço FastAPI independente da esteira. Consultas GET e POST de simulação, todos somente leitura.
Consulta exclusivamente `pdoh_controle`; não importa o pipeline, não executa
bootstrap, DDL, carga, atualização de status ou reprocessamento.

### Configuração futura de fallback (Fases 1 e 2)

Antes de iniciar a versão com fallback, provisionar **somente** a estrutura nova:

```powershell
.\api\.venv311\Scripts\python.exe -B api/scripts/provision_fallback.py --apply
```

O comando é administrativo explícito, separado das migrações da esteira. Cria
duas tabelas e sete triggers, sem semear configurações ou alterar tabelas existentes.
Detalhes, contrato, testes e limites em [FALLBACK_CHECKOUT.md](FALLBACK_CHECKOUT.md).

- `GET /api/v1/fallback/resolver`: líder → marca → padrão, com vigência.
- `POST /api/fallback/simular` (também `/api/v1/fallback/simular`): apenas SELECT.
- O fallback efetivo do processador permanece **23:59**, mesmo com configuração ativa.
- Não existem endpoints de edição/ativação de configurações nesta fase.

## Executar neste ambiente

O MySQL existente está na rede `pdoh_cx_network`. A API usa `mysql:3306` nessa
rede e publica HTTP apenas em `127.0.0.1:8000`. Não depende de publicar o MySQL
no Windows. O Compose de consulta é separado do Compose e do CD da esteira.

Na raiz `C:\Users\RT-138\Desktop\PDOH_CX`:

```powershell
# Preparação (uma vez; Python 3.11 ou 3.12):
py -3.11 -m venv api/.venv311
.\api\.venv311\Scripts\python.exe -m pip install -r api/requirements-dev.txt
.\api\.venv311\Scripts\python.exe api/scripts/provision_reader.py

# Iniciar / atualizar exclusivamente a API:
docker compose -f compose.api.yml up -d --build consulta
docker compose -f compose.api.yml ps
```

O provisionamento cria a conta `pdoh_cx_reader` com `SELECT` apenas em
`pdoh_controle.*`. Gera senha e token em `api/.env.api`, ignorado pelo Git e
pelo contexto Docker. Não altera contas existentes nem tabelas. Reexecutá-lo
com esse arquivo presente preserva as credenciais; se a conta já existir sem
o arquivo, exige configuração com a senha existente.

O indicador `GET /api/v2/pdoh/resumo` lê a fonte oficial do PDOH (Platina). Para
habilitá-lo, conceda leitura **somente** na tabela oficial da marca:

```sql
GRANT SELECT ON produtos_platina.exclusivo_bracell_platina_relatorio_pdoh TO 'pdoh_cx_reader'@'%';
```

Sem essa permissão a API continua no ar e o indicador responde "indisponível"
com o motivo. Qualquer outra permissão fora de `pdoh_controle.*` é recusada.

Swagger: <http://127.0.0.1:8000/docs>. OpenAPI: <http://127.0.0.1:8000/openapi.json>.
Clique **Authorize** e informe o valor de `PDOH_API_TOKEN` de `api/.env.api`.
Para copiá-lo sem imprimi-lo no terminal:

```powershell
$tokenLine = Get-Content api/.env.api | Where-Object { $_ -match '^PDOH_API_TOKEN=' }
Set-Clipboard -Value ($tokenLine -replace '^PDOH_API_TOKEN=', '')
Remove-Variable tokenLine
```

Exemplo de consulta no PowerShell:

```powershell
$apiToken = (Get-Content api/.env.api | Where-Object { $_ -match '^PDOH_API_TOKEN=' }) -replace '^PDOH_API_TOKEN=', ''
$apiHeaders = @{ Authorization = "Bearer $apiToken" }
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/dashboard?marca=BRACELL' -Headers $apiHeaders
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/oportunidades?tipo=VALOR_SEM_PADRONIZACAO&tamanho=10' -Headers $apiHeaders
Remove-Variable apiToken, apiHeaders
```

`scripts/start.ps1` é uma alternativa para executar Python diretamente no
Windows, somente quando o MySQL estiver acessível na porta configurada.
Não altere o banco para viabilizar essa alternativa; o Compose funciona na rede interna.

## Contratos v1

Modelos tipados em `app/models.py`; JSON Schema e exemplos de formato no OpenAPI.
Listas usam `{items, total, pagina, tamanho, paginas}`. Paginação começa em 1,
tamanho padrão 50, máximo 200; página máxima 10000. Página além do resultado:
`items: []`, mantendo `total`. Não há fallback para dados demonstrativos.

| Endpoint GET (`/api/v1`) | Filtros / conteúdo |
|---|---|
| `/dashboard` | marca, periodo_inicio, periodo_fim, status da execução; totais, distribuições, últimas 10 execuções; pagina/tamanho controlam a lista marcas_periodos sem alterar totais |
| `/execucoes` | marca, periodo_inicio, periodo_fim, status, pagina, tamanho |
| `/execucoes/{id}` | Cabeçalho e contagens de oportunidades, etapas, fontes e saídas |
| `/execucoes/{id}/etapas` | Eventos por data/ID crescente; pagina, tamanho |
| `/execucoes/{id}/fontes` | Origem, janela, contagens e hash de consulta; pagina, tamanho |
| `/execucoes/{id}/linhagem` | Linhas rastreadas, hashes, ação e destino; pagina, tamanho |
| `/oportunidades` | marca, periodo_inicio, periodo_fim, tipo, status, regra (regra_id), execution_id, pagina, tamanho |
| `/oportunidades/{id}` | Ocorrência + execução + regra_atual + identidade_colaborador + ultima_tratativa |
| `/oportunidades/{id}/historico` | Histórico existente, inclusive responsável e status; pagina, tamanho |
| `/regras` | marca, incluir_globais, status, tipo, pagina, tamanho |
| `/de-para` | marca, incluir_globais, processo, campo_origem, status, pagina, tamanho |
| `/de-para/{id}/historico` | Histórico de valores/status/responsável; pagina, tamanho |
| `/colaboradores/{id}` | Identidade por colaborador_id_interno |
| `/entidades` | marca, tipo_entidade, status, pagina, tamanho |
| `/entidades/{id}` | Identidade por identificador_id (distinto de identificador_interno) |
| `/health` | Prontidão: executa SELECT 1; exige autenticação |

### Semântica dos dados

- Período filtra **sobreposição inclusiva da janela processada da execução**:
  `periodo_inicio_da_execucao <= filtro_fim` e `periodo_fim_da_execucao >= filtro_inicio`.
  Datas são `YYYY-MM-DD`; extremos podem ser omitidos. Execuções sem janela
  completa não entram quando houver filtro de período. Oportunidades usam a
  execução relacionada; não usam `identificada_em` para esse filtro.
- `identificada_em`, `data_referencia` e período processado são campos distintos.
  DATETIME preserva o horário local armazenado, sem sufixo UTC artificial.
  A sessão MySQL usa `-03:00`; o contexto é America/Sao_Paulo.
- Status são strings reais, incluindo INICIADA, CONCLUIDA_COM_ALERTAS,
  CONCLUIDA_SEM_RESULTADO e FALHA_TECNICA. Um status desconhecido filtra para
  zero resultados; nunca é traduzido silenciosamente para outro status.
- Execuções e oportunidades ordenam por data decrescente e ID decrescente.
  Históricos ordenam por data crescente e ID crescente. Regras por prioridade
  crescente e ID; De/Para por processo, campo e ID; entidades por ID.
- A paginação é estável em dados estáticos. Alterações concorrentes entre
  requisições podem deslocar páginas; cada resposta usa um único snapshot SQL.
- `tipo_problema` é o nome técnico da regra; `descricao_cenario` sua descrição.
  `regra_atual` não é uma versão histórica da regra. Uma referência ausente
  retorna `null`, sem inferir que a regra vigente foi aplicada anteriormente.
- `marca: null` em regras/De/Para significa global. Filtrar uma marca inclui
  globais por padrão; `incluir_globais=false` restringe à marca exata.
  A consulta não resolve prioridade nem reaplica regras do pipeline.
- `ultima_tratativa.responsavel` é o autor do último registro, não atribuição
  atual da oportunidade. Pode ser nulo, inclusive em criação automática.
- PDV não tem FK direta na oportunidade. Evidências são preservadas como JSON;
  `/entidades` oferece consulta separada, sem inventar vínculos por nome.
- Linhagem relaciona execução e hashes de saída; não é cópia histórica da Platina.
- Total de oportunidades conta ocorrências persistidas, não pessoas/linhas
  distintas. Contadores recebidos/tratados/gerados/persistidos são separados.
- Identificadores vazios/inválidos, páginas inválidas, datas invertidas e
  parâmetros desconhecidos retornam 422; registro ausente retorna 404;
  histórico vazio de registro existente retorna 200 com lista vazia.

## Segurança e operação

- Bearer token local para homologação; todas as consultas exigem autenticação.
  Token ausente/incorreto: 401. Métodos de escrita: 405; POST é permitido exclusivamente na simulação sem escrita.
- Nenhuma credencial de banco ou token compartilhado deve entrar em `VITE_*`,
  bundle, repositório ou exemplos. A integração de sessão corporativa/RBAC
  não faz parte desta fase; antes de uso multiusuário, substituir o token local
  por autenticação de usuário com autorização correspondente. O token desta
  fase permite leitura de todas as marcas presentes no schema.
- CORS aceita somente origens explicitamente configuradas; respostas não são
  armazenadas em cache. O serviço HTTP está restrito ao computador local.
- Inicialização confere campos e privilégios reais. Conta com escrita, roles,
  GRANT OPTION ou SELECT em outros schemas é recusada — a única exceção é
  `SELECT` nas tabelas oficiais do PDOH listadas em `PLATINA_PDOH`, uma a uma.
  Não usa root nem a conta do processamento em runtime.
- Sessões READ ONLY, consultas parametrizadas, limite de 10 segundos por SELECT,
  pool limitado. Falhas SQL retornam 503 e identificador de erro, sem SQL/senha.
- Banco inacessível ou schema incompatível impede a inicialização; nenhuma
  migração automática é executada. A API precisa ser reiniciada após recuperar
  uma falha de inicialização.

## Validação

```powershell
# Casos determinísticos: SQLite em memória, sem tocar MySQL.
.\api\.venv311\Scripts\python.exe -m unittest discover -s api/tests -v

# Integração real: container temporário somente leitura na rede do banco.
docker build -f api/Dockerfile --target validation -t pdoh_cx_consulta:validation .
docker run --rm --network pdoh_cx_network --env-file api/.env.api -e PDOH_API_DB_HOST=mysql -e PDOH_API_DB_PORT=3306 --mount "type=bind,source=C:\Users\RT-138\Desktop\PDOH_CX\artifacts,target=/reports" pdoh_cx_consulta:validation
```

A validação compara HTTP/ASGI com SQL real: campos, totais, filtros, paginação,
relações, histórico, autenticação, erros e bloqueio de métodos de escrita.
Calcula hashes de todas as tabelas de controle antes/depois. Se outro processo
alterar dados durante a validação, a evidência falha e deve ser repetida em
janela estável (sem parar automaticamente o pipeline).

Arquivos gerados: `artifacts/api-validation.json` e `artifacts/api-openapi.json`.
Não contêm senhas nem amostras de nomes de colaboradores. O CI específico
`api-ci.yml` executa testes isolados e build; não provisiona usuário ou banco.

Documentação técnica utilizada:
[modelos de query FastAPI](https://fastapi.tiangolo.com/tutorial/query-param-models/)
e [transações SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/connections/).
