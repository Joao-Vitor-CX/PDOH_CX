# CI/CD do PDOH_CX

## Objetivo da etapa

Preparar a entrega automatizada do batch BRACELL sem modificar regras de
negocio, calculos PDOH, tratamento ETL, processadores ou schema Platina. A
esteira nao realiza carga de dados nem migracao automatica.

O documento `REPLICAR_ESTEIRA_CICD.md` foi usado como referencia de fluxo. Os
trechos voltados a Node/Vite, servidor compartilhado, Traefik, URL publica,
MySQL externo e runner `rtdev-org-box` nao foram replicados porque violariam o
escopo local e isolado do PDOH_CX.

## Implementacao realizada

| Arquivo | Responsabilidade |
|---|---|
| `.github/workflows/ci.yml` | CI em PR para `main`: validacao estatica, compilacao, 25 testes, Compose somente leitura, build da imagem e verificacao do UID 10001 |
| `.github/workflows/cd.yml` | CD em push para `main` ou acionamento manual; exige runner local dedicado, repositorio autorizado, PR mesclado e CI aprovado |
| `scripts/validate_cicd.py` | Verifica hashes dos processadores, segredos versionados, hosts locais, isolamento Docker e comandos permitidos no deploy |
| `scripts/deploy-local.ps1` | Constroi e recria apenas o `backend`, com `--no-deps`, e compara snapshots somente leitura antes/depois |
| `tests/test_cicd.py` | Testes de contrato da automacao e das travas contra carga/migracao no CI/CD |
| `.gitattributes` | Normalizacao de fim de linha para evitar falhas entre Windows e Linux |

O CD usa o GitHub Environment `pdoh-cx-local`. Credenciais nao sao gravadas em
arquivo pelo workflow nem aparecem no repositorio; sao injetadas pelo cofre de
secrets do ambiente durante a execucao.

## Travas de seguranca

- o nome completo autorizado vem de `PDOH_CX_GITHUB_REPOSITORY` e deve terminar
  em `/PDOH_CX`;
- qualquer remote `PDOH_EXCLUSIVO` e recusado antes do deploy;
- o job exige os labels `[self-hosted, Windows, pdoh-cx-local]`;
- o commit deve estar associado a PR mesclado em `main`;
- o PR deve ter uma execucao `CI` concluida com sucesso;
- o MySQL `pdoh_cx_mysql` deve estar `healthy` antes do deploy;
- o deploy aceita somente o servico `backend` com `--no-deps`;
- `mysql`, `migrate` e `pipeline` nao sao iniciados pelo CI/CD;
- as contagens dos tres schemas locais sao lidas antes e depois e devem ser
  identicas;
- artefatos JSON de CI e CD registram status, SHA e validacoes sem credenciais.

## Configuracao necessaria no GitHub

No novo repositorio, criar o Environment `pdoh-cx-local` com:

| Tipo | Nome | Finalidade |
|---|---|---|
| Variable | `PDOH_CX_GITHUB_REPOSITORY` | Nome completo, por exemplo `organizacao/PDOH_CX` |
| Variable | `PDOH_DB_USER` | Usuario local da aplicacao |
| Secret | `PDOH_DB_PASSWORD` | Senha local da aplicacao |
| Variable | `PDOH_MIGRATION_USER` | Usuario local de migracao, exigido somente para interpolar o Compose |
| Secret | `PDOH_MIGRATION_PASSWORD` | Senha local do migrador; o CD nao o executa |
| Secret | `MYSQL_ROOT_PASSWORD` | Segredo local exigido pela definicao do Compose; o CD nao usa DDL |
| Variable | `PDOH_MYSQL_PORT` | Porta local, normalmente `3307` |

Tambem e necessario:

1. criar um repositorio independente chamado `PDOH_CX`;
2. trocar o remote `origin` local para esse repositorio;
3. registrar neste computador um runner GitHub Actions Windows com o rotulo
   adicional `pdoh-cx-local` e acesso ao Docker Desktop;
4. proteger `main`, exigindo Pull Request e o check `Validacoes PDOH_CX` antes
   do merge;
5. manter o MySQL local previamente inicializado e saudavel. O CD nao faz o
   bootstrap nem aplica migracoes.

## Evidencias locais de 10/09/2026

| Validacao | Resultado |
|---|---|
| Validador estatico sem acesso a banco | Aprovado |
| Compilacao Python | Aprovada |
| Testes automatizados | 25 aprovados |
| `docker compose --profile pipeline config --quiet` | Aprovado |
| Build `pdoh_cx:ci` | Aprovado |
| Usuario da imagem | UID `10001` confirmado |
| Receita `deploy-local.ps1` com remote local temporario | `DEPLOY_LOCAL_OK` |
| Snapshot antes/depois do deploy local | Identico |
| Estado do MySQL local | `pdoh_cx_mysql` healthy |
| Publicacao do MySQL | Somente `127.0.0.1:3307` |
| Rede do backend | Somente `pdoh_cx_network` |
| Usuario do backend em execucao | `10001:10001` |
| Cinco tabelas de origem | 0 registros em cada tabela |
| Tabela Platina | 0 registros |
| Gate do remote atual | Reprovado corretamente: nenhum `origin` PDOH_CX configurado |
| Carga de dados | Nao executada |
| Migracao pelo CI/CD | Nao executada |
| Pipeline PDOH | Nao executado |

O JSON local do gate esta em `artifacts/remote-gate.json`; esse diretorio e
ignorado pelo Git e, no GitHub, e publicado como artefato temporario do workflow.

## Estado do fluxo controlado

```text
branch -> commit -> Pull Request -> CI -> merge -> CD -> deploy
                       BLOQUEADO NO REPOSITORIO EXTERNO
```

O fluxo remoto nao foi simulado contra o projeto original. O antigo `origin`
apontava para `PDOH_EXCLUSIVO`; esse vinculo foi identificado e removido. Nao
existe remote de fetch ou push ate que o repositorio independente seja
informado. A ferramenta local tambem nao possui GitHub CLI configurado.

Portanto, a Etapa 1 e a receita local de deploy estao implementadas e validadas.
A Etapa 2 remota so pode ser concluida depois da criacao/configuracao do
repositorio e do runner dedicados. Por consequencia, as Etapas 3, 4 e 5
permanecem intencionalmente pendentes: nenhuma massa BRACELL foi carregada e o
PDOH_CX nao foi executado.

## Proxima liberacao

Depois que um PR real concluir o CI, for mesclado e o CD produzir
`DEPLOY_LOCAL_OK`, revisar os artefatos `evidencia-ci-*` e `evidencia-cd-*`.
Somente com essa aprovacao deve ser autorizada a importacao da massa BRACELL nas
cinco tabelas locais de `involves_bracell` e, em seguida, a execucao funcional
para gerar a Platina.
