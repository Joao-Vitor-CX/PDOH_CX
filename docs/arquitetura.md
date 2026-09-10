# Arquitetura de controle e observabilidade do PDOH_CX

## Princípio de isolamento

A esteira de negócio continua sendo BRACELL: mesmas cinco fontes, tratamentos,
processadores e cálculos. Os quatro arquivos monolíticos não foram editados. A
camada nova apenas lê os mesmos DataFrames ou recebe o resultado da persistência.
Ela nunca devolve dados modificados ao processador.

Existem três schemas locais:

- `involves_bracell`: entrada; o usuário da aplicação tem somente `SELECT`;
- `produtos_platina`: saída consolidada do UPSERT;
- `pdoh_controle`: telemetria, qualidade, auditoria e preparação de notificações.

Não há FK de controle para as tabelas de origem ou para a Platina. A linhagem usa
hash da chave `(colaborador, data)` e preserva o contrato do destino.

## Ciclo de uma execução

1. `run_observado.py` cria um ID não sequencial, por exemplo
   `BRACELL_20260908_153312_D4B272CA`, abre o arquivo de log e inicia a execução.
2. Cada processador é chamado como subprocesso, preservando o isolamento do shell
   anterior. O mesmo ID segue em `PDOH_EXECUTION_ID`.
3. O loader confirma a conexão com `SELECT 1`, registra período, consulta e
   contagens das cinco fontes.
4. Qualidade e identidade observam o frame bruto. Exceções desses observadores são
   capturadas e não chegam ao pipeline.
5. O tratamento atual ocorre sem mudança e suas contagens são registradas.
6. O processador calcula normalmente. Linhas `AVISO:` já emitidas pelo legado são
   reconhecidas como fallback, sem interceptar ou substituir a tratativa.
7. `src/alch.py` realiza o UPSERT direto com `SELECT`, `INSERT` e `UPDATE`,
   registra geração, tentativa, commit/rollback e escreve a linhagem lateral. A
   transação do controle nunca é a transação da Platina.
8. O executor verifica retorno e `Erro na automação.txt` após cada subprocesso.
   Isso impede falso sucesso na telemetria quando o `try/except` legado absorve
   a exceção; o código de saída do processo continua preservando o comportamento
   legado.
9. A execução termina como `CONCLUIDA`, `CONCLUIDA_COM_ALERTAS`,
   `CONCLUIDA_SEM_RESULTADO` ou `FALHA_TECNICA`.

## Modelo de controle

| Tabela | Responsabilidade |
|---|---|
| `execucao` | Cabeçalho, período, status, totais e início/fim |
| `execucao_etapa` | Eventos de ETL, tratamento, processamento e persistência |
| `execucao_fonte` | Fonte, filtro, hash da consulta e contagem antes/depois |
| `execucao_evento` | Logs estruturados técnicos, operacionais e de qualidade |
| `fallback_evento` | Motivo, contexto, severidade e impacto do fluxo alternativo |
| `colaborador_identidade` | ID estável em modo sombra |
| `colaborador_alias` | Histórico de nomes brutos por fonte |
| `oportunidade` | Ocorrência classificada com evidência mínima |
| `oportunidade_historico` | Criação e futuras mudanças de status append-only |
| `notificacao_outbox` | Mensagens relevantes aguardando um worker futuro |
| `saida_linhagem` | Relação lateral entre execução e chave/versão da linha Platina |

## Qualidade de dados

As verificações ocorrem antes da deduplicação do loader, para que o problema não
desapareça da evidência. São observados:

- coluna/campo obrigatório ausente ou vazio;
- duplicidade conforme a mesma seleção de colunas do tratamento existente;
- data/hora inválida ou fora da janela;
- checkout/conclusão/expiração anterior ao início;
- pesquisa respondida sem conclusão;
- UF e flags fora do padrão conhecido;
- espaços externos no nome e divergências entre usuário, nome e alias.

A evidência é mínima e limitada por regra (`PDOH_OBS_MAX_EVIDENCIAS_POR_REGRA`,
padrão 500) para não transformar controle em causa de indisponibilidade. Ao
atingir o limite, uma oportunidade/evento agregado registra a quantidade total.

## Identidade em modo sombra

Quando `usuario` está disponível no cadastro, o UUID determinístico é ancorado
nessa chave. Sem usuário, usa-se o nome normalizado apenas como chave provisória.
Variações de caixa, acento e espaços ficam no histórico bruto. Um usuário com
nomes diferentes ou um nome ligado a usuários distintos gera oportunidade; não
há fuzzy merge automático. O `colaborador_id_interno` não substitui o nome atual.

## Fallback e notificações

Condições que ativam defaults existentes são registradas sem reaplicar o default:

- jornada ausente/não numérica que o legado transforma em 44h;
- `hora_saida` ausente que o legado transforma em 23:59;
- nulos de pesquisa que o legado transforma na data/hora de 1999;
- avisos legados de ausência de dados de ócio.

Oportunidades e fallbacks de severidade alta ou crítica geram uma linha na outbox
com marca, problema, data, impacto e `execution_id`. A outbox é somente preparação
arquitetural: nenhum entregador ou integração externa foi criado.

## Migrações e resiliência

`docker/mysql/init/001_bancos_e_tabelas.sql` inicializa origem e Platina somente
quando o volume nasce. No bootstrap `docker compose up -d --build`, o serviço
`migrate` executa em ordem todos os scripts de `docker/mysql/migrations/`, cobrindo
também volumes existentes. O pipeline depende apenas do MySQL saudável: assim,
depois do bootstrap, uma indisponibilidade de `pdoh_controle` não impede a esteira
de negócio nem a persistência Platina.

O bootstrap cria duas contas separadas. `pdoh_cx_app` tem leitura na origem e
somente `SELECT`, `INSERT` e `UPDATE` em controle e Platina. A conta
`pdoh_cx_migrator` recebe apenas os privilégios DDL necessários nos schemas
locais e não é entregue ao backend ou ao pipeline.

## Isolamento local

- a porta MySQL é publicada somente em `127.0.0.1`;
- a rede `pdoh_cx_network` é interna;
- o backend e o pipeline executam com UID/GID `10001`, sem root e com
  `no-new-privileges`;
- `.env` é ignorado pelo Git e pelo contexto de build;
- nenhum segredo possui valor padrão no Compose;
- a criação do engine recusa qualquer host diferente de `mysql`, `localhost` e
  `127.0.0.1` antes de tentar a conexão.

Todas as funções públicas de observabilidade capturam falhas, emitem um registro
JSON `OBSERVABILIDADE_INDISPONIVEL` e retornam ao chamador. A única exceção é a
própria falha técnica do pipeline/Platina, que é registrada como tal, mantendo o
mesmo comportamento de retorno do legado.
