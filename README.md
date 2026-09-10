# PDOH_CX

Aplicação batch independente que replica a esteira BRACELL do PDOH e grava o
resultado em `produtos_platina.exclusivo_bracell_platina_relatorio_pdoh`.
O projeto não se conecta aos bancos/processos de produção e não possui frontend
ou dashboard.

## Garantia de não alteração da regra

Os quatro processadores e as duas bases fixas replicadas continuam protegidos
pelos hashes SHA-256 de `manifesto_replicacao.json`. A nova arquitetura é lateral:

- `src/data_loader.py` observa os DataFrames antes/depois do tratamento existente;
- `src/alch.py` observa tentativa e resultado do mesmo UPSERT Platina;
- `run_observado.py` executa os scripts originais em subprocessos isolados;
- identidade, qualidade, logs, fallbacks e notificações futuras vivem somente em
  `pdoh_controle`.

Nenhum identificador de controle é adicionado aos DataFrames ou à tabela Platina.

## Arquitetura

```text
                                     +---------------------------+
                                     | pdoh_controle             |
                                     | execução, etapas, fontes  |
                                     | eventos e fallbacks       |
                                     | qualidade/oportunidades   |
                                     | identidade em modo sombra |
                                     | histórico, linhagem       |
                                     | outbox pendente           |
                                     +-------------^-------------+
                                                   | observa
involves_bracell --SELECT--> ETL -> tratamento -> PDOH -> UPSERT Platina
       5 tabelas             (mesma lógica BRACELL)        |
                                                           v
                                      produtos_platina.exclusivo_bracell_
                                      platina_relatorio_pdoh
```

O usuário `pdoh_cx_app` possui somente `SELECT` em `involves_bracell` e apenas
`SELECT`, `INSERT` e `UPDATE` nos schemas locais `produtos_platina` e
`pdoh_controle`. O DDL é separado na conta local `pdoh_cx_migrator`.

Detalhes: [docs/arquitetura.md](docs/arquitetura.md).

## CI/CD

A automacao foi separada em dois workflows:

- `CI`: executa em Pull Request para `main`, valida isolamento, compila as
  fontes, executa os testes, valida o Compose sem subir servicos, constroi a
  imagem e confirma o usuario nao-root;
- `CD`: executa depois de atualizacao da `main`, somente em runner Windows
  self-hosted com o rotulo `pdoh-cx-local`. Antes do deploy, exige repositorio
  `PDOH_CX`, PR mesclado e uma execucao aprovada do CI para o SHA do PR.

O deploy constroi e recria exclusivamente o servico `backend` com `--no-deps`.
Ele nao inicia `mysql`, `migrate` ou `pipeline`, nao aplica DDL e nao carrega
dados. Snapshots somente leitura antes/depois devem permanecer identicos.

O remoto do projeto original foi removido e nenhum `origin` esta configurado;
por isso a validacao real por PR permanece pendente ate existir o repositorio
GitHub separado `PDOH_CX`. Configuracao e evidencias:
[docs/ci_cd.md](docs/ci_cd.md).

## Subir e validar o ambiente

Pré-requisito: Docker Desktop com o engine Linux ativo, Compose v2 e um arquivo
`.env` local criado a partir de `.env.example`, com senhas fortes próprias.

```bash
docker compose up -d --build
docker compose logs backend
```

O serviço `migrate` reaplica, de forma idempotente, todos os arquivos de
`docker/mysql/migrations/` inclusive quando o volume já existe. O backend é um
job de verificação e encerra em código `0` depois de imprimir `COMUNICACAO_OK`.
O mapeamento permitido do MySQL está limitado a `127.0.0.1:3307` (porta
configurável em `.env`). Com a rede interna, o runtime atual não publica a porta
em interfaces externas e não fornece saída externa aos containers.

Por segurança, `PDOH_DB_HOST` aceita exclusivamente `mysql`, `localhost` ou
`127.0.0.1`. Qualquer outro valor é recusado antes da criação do engine e gera um
evento JSON `CONEXAO_BANCO_NAO_AUTORIZADA` no log do processo.

Para repetir a verificação dos três schemas:

```bash
docker compose run --rm backend python -m src.healthcheck --wait
```

## Executar a esteira observada

Faça o bootstrap com `docker compose up -d --build` ao menos uma vez em cada
volume novo. Depois de importar dados de homologação apenas nas cinco tabelas
locais de `involves_bracell`, execute:

```bash
docker compose --profile pipeline run --rm pipeline
```

Isso executa, na mesma ordem atual, promotores e líderes com um único
`execution_id`. O log completo fica em `bracell/logs/<execution_id>.log`. O
pipeline depende diretamente do MySQL, e não da migração de controle, para que
uma indisponibilidade da telemetria não bloqueie o processamento principal.

Para reprocessar somente o processador Platina em um período explícito:

```bash
docker compose --profile pipeline run --rm pipeline python run_observado.py --script pdoh_bracell_sem_atestados_e_declaracoes_medicas.py --data-inicio 2026-09-01 --data-fim 2026-09-06
```

O script atual de líderes mantém seu período interno e não persiste na Platina;
por isso ele não é incluído automaticamente no exemplo de período explícito.

## O que a camada observa

- execução, marca, período, início/fim, componentes e etapas;
- linhas recebidas, tratadas, geradas e persistidas por fonte;
- falhas técnicas que os scripts legados registram em arquivo mesmo retornando `0`;
- campos obrigatórios vazios, duplicidades, datas/horas inválidas, intervalos
  inconsistentes, valores fora de padrão e divergências cadastrais;
- fallbacks legados observáveis: jornada de 44h, saída às 23:59, data padrão de
  pesquisa e avisos de ausência de ócio;
- aliases e ID interno de colaborador, ancorado em usuário quando disponível,
  sem participar dos joins/cálculos atuais;
- oportunidades, evidência mínima, histórico e linhagem das chaves Platina;
- outbox `PENDENTE` para oportunidades/fallbacks de alta severidade. Não existe
  worker de envio nesta fase, portanto nenhum e-mail, webhook ou mensagem sai.

Toda gravação de controle é *fail-open*: se `pdoh_controle` falhar, o erro é
emitido em JSON e a chamada não interrompe o cálculo nem o UPSERT Platina.

## Consultas operacionais

```sql
SELECT *
FROM pdoh_controle.execucao
ORDER BY iniciado_em DESC;

SELECT componente, etapa, status_etapa, tabela_origem,
       linhas_recebidas, linhas_tratadas, ocorrido_em
FROM pdoh_controle.execucao_etapa
WHERE execution_id = 'BRACELL_...'
ORDER BY id;

SELECT tipo_problema, severidade, status_oportunidade,
       tabela_origem, colaborador, descricao_detalhada
FROM pdoh_controle.oportunidade
WHERE execution_id = 'BRACELL_...';
```

## Validação e testes

O smoke test usa DataFrames sintéticos, escreve somente em `pdoh_controle` e
confirma que a quantidade de linhas da Platina não mudou:

```bash
docker compose run --rm backend python -m src.validate_observability
docker compose run --rm backend python -m src.validate_persistence
```

O segundo comando usa a chave reservada
`(__PDOH_CX_VALIDACAO_PERSISTENCIA__, 2099-12-31)`, confirma UPSERT e linhagem e
reverte a linha sintética na própria transação. Ele aborta sem alterar nada se a
chave já existir.

Testes locais:

```bash
python scripts/validate_cicd.py
python -m unittest discover -s tests -v
python -m compileall -q bracell tests
docker compose config --quiet
```

As tabelas de origem nascem vazias. Com origem vazia, os processadores replicados
atingem uma falha já existente ao operar um DataFrame sem índice; o executor agora
classifica corretamente o caso como `FALHA_TECNICA`, mas não altera essa regra ou
mascara o problema.
