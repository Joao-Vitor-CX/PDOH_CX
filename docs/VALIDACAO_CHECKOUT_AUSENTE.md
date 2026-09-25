# Validação de CHECKOUT_AUSENTE — 23/09/2026

Resultado: ajuste residual do modal concluído; build, lint, testes e simulação isolada aprovados. A validação visual está pendente por ausência de navegador conectado. O resultado solicitado de atualização do sino não foi obtido: não existe sino no frontend atual e a regra vigente não gera notificação para a severidade MÉDIA deste cenário.

## 1. Alterações efetivas

- `frontend/components/platform/rule-settings.tsx`: concluída a limpeza do formulário de criação `CheckoutConfigurator`. Ainda havia JSX de Exceções/Motivo referenciando estados já removidos, causando 15 erros de TypeScript; removidos apenas esses remanescentes e a mensagem de motivo no rodapé. Criado `idPrefix = useId()` para o título acessível.
- `frontend/src/pages/settings-page.tsx`: removida a propriedade obsoleta `templates` da chamada de `CheckoutConfigurator`, além do import e cálculo que só a alimentavam.
- Botão Adicionar jornada mantido visível, desabilitado e acompanhado da explicação existente quando todas as jornadas cadastradas já estão listadas. O caminho de adicionar uma jornada disponível foi preservado.
- Não foram refeitas as funções `calcularPreviaJornada()`, `formatarDuracao()`, o campo Intervalo ou a prévia existentes. `frontend/src/lib/rule-settings.ts` permaneceu byte a byte igual.

## 2. Validações executadas

| Verificação | Resultado |
| --- | --- |
| `npm run build` | Passou após a limpeza residual; aviso de bundle acima de 500 kB |
| `npm run lint` | Passou |
| `npm run test:operational` | 50 testes aprovados |
| `api/.venv311/Scripts/python.exe -B -m unittest api.tests.test_operational_schedule -v` | 7 testes aprovados |
| Funções de prévia reais alimentadas pelo JSON | 660 minutos brutos e 600 líquidos; “11 horas” e “10 horas” |
| Executor + dispatcher + persistência + API | Uma oportunidade ABERTA e um card retornado |
| Reprocessamento da mesma massa | Zero duplicações |
| Proteções | Saída existente, extração anterior às 19h e configuração ausente não confirmam ausência |

O build e o runner de testes Node precisaram da execução aprovada fora do sandbox devido a `spawn EPERM`. O Python utilizado foi o ambiente existente `.venv311`; nenhum pacote foi instalado.

## 3. Massa e evidências no código

JSON criado e depois removido: `mock/opportunity_checkout_absent.json`.

Conteúdo do cenário: COLABORADOR TESTE 44H; jornada 44H; entrada 08:00; checkout nulo; data 2026-09-01; extração 2026-09-02 05:00:00; configuração 08:00–19:00; intervalo de prévia 01:00. A data histórica e a extração posterior ao limite tornam o teste determinístico.

Arquivo consumidor, criado e depois removido: `scripts/validate_checkout_absent_temporary.py`, função `main()`. O consumidor abriu o JSON, converteu entrada/checkout para `hora_entrada/hora_saida` e passou as linhas ao executor pelo leitor injetável `read_json_rows()`.

| Etapa | Código de produção exercitado |
| --- | --- |
| Resolução da jornada por prioridade | [shared/journey.py](../shared/journey.py), função `resolve()`, linhas 50–78 |
| Consulta por colaborador/dia | [bracell/src/regras_configuradas.py](../bracell/src/regras_configuradas.py), `ProvedorDeExcecoes._resolucao()`, linha 233 |
| Tratamento de CHECKOUT_AUSENTE e seleção da configuração 44h | [bracell/src/operational_schedule.py](../bracell/src/operational_schedule.py), `execute()`, linha 24; seleção na linha 57 |
| Limite de saída configurado | [shared/operational_schedule.py](../shared/operational_schedule.py), `checkout_due()`, linha 33; comparação do limite nas linhas 53–64 |
| Criação e registro da oportunidade | [bracell/src/findings.py](../bracell/src/findings.py), `registrar_achado()`, linha 104 |
| Leitura do card operacional | [api/app/findings_repository.py](../api/app/findings_repository.py), `opportunity_summary()`, linha 596; rota `/api/v2/oportunidades/resumo` |
| Consumo no frontend | [frontend/src/services/operational-api.ts](../frontend/src/services/operational-api.ts), linha 192; [OperationalGroupCard](../frontend/components/platform/operational-group-card.tsx), linha 29 |
| Regra de notificação | [bracell/src/findings.py](../bracell/src/findings.py), linhas 234–240: somente ALTA/CRÍTICA entram em `notificacao_outbox` |

Usou-se SQLite em memória, com adaptação de sintaxe MySQL reutilizada de `api/tests/test_findings.py::SQLiteWriter`. O detector, o resolvedor de jornada, o classificador, as portas de evidência e a persistência não foram substituídos por respostas prontas. A massa e as fontes de cadastro eram sintéticas. O catálogo foi copiado de `shared.treatment_catalog.montar_regra()` para o fixture da API, mantendo a severidade original.

Trecho da saída real do último teste:

```json
{
  "colaborador": "COLABORADOR TESTE 44H",
  "jornada": 44,
  "fonte_jornada": "cadastro_fallback_homologacao",
  "configuracao": {
    "id": "2e6da74c-3101-43b2-b743-e5c9d2bae87e",
    "jornada": 44,
    "hora_entrada_padrao": "08:00",
    "hora_saida_padrao": "19:00"
  },
  "monitoramento": {
    "hora_entrada": "08:00",
    "hora_saida": null,
    "data": "2026-09-01",
    "evolucao": "2026-09-02 05:00:00"
  },
  "processamento": {
    "regra": "CHECKOUT_AUSENTE",
    "avaliadas": 1,
    "confirmadas": 1,
    "criadas": 1
  },
  "reprocessamento": {
    "regra": "CHECKOUT_AUSENTE",
    "avaliadas": 1,
    "confirmadas": 1,
    "criadas": 0
  },
  "antes": {
    "oportunidade": 0,
    "notificacao_outbox": 0
  },
  "depois": {
    "oportunidade": 1,
    "notificacao_outbox": 0
  },
  "oportunidade_id": "787faee8-448b-5eb8-8ed7-38aa9ac334f8",
  "severidade": "MEDIA",
  "api_total": 1,
  "grupos_total": 1,
  "fallback_substituicao_checkout": false,
  "registro_original_preservado": true
}
```

## 4. Evidências visuais

Não produzidas: as consultas do ambiente retornaram `apps: []` e `browsers: []`; tentativas de abrir Chrome e navegador integrado retornaram indisponibilidade. Não há screenshots nem confirmação de renderização, interação, responsividade ou foco.

Por inspeção do código: o modal usa largura expandida `sm:max-w-3xl` e rolagem interna; contém as jornadas 44/36/24, entrada, saída, intervalo, prévia, tempos bruto/líquido e botão Adicionar jornada. Os formulários operacionais não expõem os controles Exceções, Motivo, Campo, Regra, Valor ou Fonte técnica. Isso é uma verificação estrutural, não substitui homologação visual.

Situação das três evidências solicitadas:

1. Modal configurado: código e build conferidos; imagem e interação pendentes.
2. Oportunidade criada: comprovada no banco em memória e nas respostas reais da API; imagem pendente.
3. Sino atualizado: não comprovado; componente inexistente e nenhuma notificação gerada neste cenário.

## 5. Resultado do fallback

A fonte cadastral principal sintética estava sem horas; a segunda fonte continha 44H. O resolvedor real selecionou a segunda fonte, retornando `RESOLVIDA`, jornada 44 e sem conflito. O executor selecionou a configuração 44h, com entrada 08:00 e saída 19:00, e confirmou ausência após o limite.

É necessário distinguir esse fallback cadastral da substituição de checkout: o código atual NÃO grava 19:00 como saída real. `hora_saida` permaneceu nulo e a evidência da oportunidade mantém `fallback_usado=false`, conforme `montar_achado()`. O intervalo 01:00 é exclusivo da prévia visual; não é persistido nem utilizado pelo motor para recalcular PDOH. Não houve alteração dessa semântica.

## 6. Resultado da notificação/sino

Contagem antes/depois: oportunidades 0 → 1; notificações 0 → 0.

CHECKOUT_AUSENTE usa a severidade padrão MÉDIA do catálogo (`shared/treatment_catalog.py`, linha 398). O dispatcher só notifica ALTA ou CRÍTICA. Não foi elevada a severidade nem alterada a regra para forçar aprovação do cenário.

Não existe consumidor de sino/notificações no frontend inspecionado; o cabeçalho em `frontend/components/platform/app-shell.tsx`, linha 143, não contém esse componente. Para cumprir a atualização de sino solicitada, seria necessária uma decisão sobre a política de notificação e implementação da interface correspondente, fora desta validação sem mudanças de negócio.

## 7. Rollback e preservação

- JSON temporário, executor de homologação e pasta `mock/` vazia removidos; ausência confirmada com `Test-Path`.
- Banco SQLite descartado no encerramento do teste. A oportunidade sintética não foi gravada em MySQL.
- Variável de execução e guarda de configuração existiram apenas no processo de teste e foram restauradas pelo contexto de teste. Nenhuma flag foi adicionada à aplicação.
- Nenhuma credencial ou conexão de dados reais foi usada na simulação; nenhum endpoint real recebeu escrita.
- Código de backend, banco/migrações, ETL, regras e cálculos preservados. Comparação SHA-256 agregada de 1608 arquivos selecionados em `api/`, `bracell/`, `shared/`, `sql/`, `docker/`, `config/` e `frontend/src/lib/rule-settings.ts`: mesmo hash antes/depois, `A6117A418AC29930917C50B774BCC194232C9000ACCE05551C56F7EE8C1C163E`.
- Permanecem somente os ajustes de frontend descritos e este relatório de evidências, além do resultado normal do build. Não restaram mocks ou código executável de simulação.

A tarefa não está homologada visualmente nem aprovada ponta a ponta até o sino. Esses dois pontos permanecem explicitamente pendentes.

