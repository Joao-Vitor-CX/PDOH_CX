# Configuração operacional de oportunidades

Entrega de 22/09/2026. Disponível em `/configuracoes`.

## Estrutura e reaproveitamento

A leitura continua em `GET /api/v2/configuracoes/operacao`; cadastro e edição usam
`POST /api/v2/configuracoes/regras` e `PATCH /api/v2/configuracoes/regras/{codigo}`.
Nenhum endpoint adicional foi necessário. `rule_admin`, `Repository`, fontes semânticas,
resolução oficial de jornada, exceções e histórico de governança foram reutilizados.

`configuracao_operacao` guarda fontes e perfis; `jornada_consolidada` guarda a jornada
observada; `jornada_prioridade_configuracao` guarda prioridades. Nenhuma delas armazenava
horários esperados. Foi adicionada **somente** `configuracao_jornada_operacao`, com FK para
`regra_configuracao`, marca, operação, jornada, entrada/saída padrão, ativo, autor e datas.
Há uma linha por configuração de oportunidade e jornada, garantida por chave única.
O histórico antes/depois permanece em `governanca_configuracao_historico`, na mesma transação.

As opções vêm da última resolução registrada de cada identidade em `jornada_consolidada`.
Só jornadas elegíveis, vigentes e resolvidas são oferecidas. No ambiente local: 44, 36 e 24 horas.
A API rejeita valores inventados e permite desativar uma jornada que saiu do cadastro.
O cadastro depende da atualização dessa observação pela esteira; não é uma consulta online ao Involves.

## Frontend

- `components/platform/rule-settings.tsx`: seleção explícita do tipo na criação;
  `RuleEditor` dinâmico e `ScheduleFields` compartilhado, horários independentes,
  status, exceções, motivo, salvar/cancelar e monitoramento somente leitura.
- `src/lib/rule-settings.ts`: rascunho, validação HH:MM, PATCH somente com diferenças,
  descrição do resultado e histórico legível de horários.
- `src/services/governance-api.ts`: contratos tipados de jornadas e monitoramento.
- `src/pages/settings-page.tsx`: fornece jornadas disponíveis ao formulário.

`HORAS_AUSENTES` continua usando condição/valor. `CHECKOUT_AUSENTE` utiliza o modelo
`JORNADA`; a API recusa alterações de condição genérica e tempo mínimo nesse tipo.
Para criar: Nova oportunidade → Check-out ausente · jornada → selecionar jornadas,
preencher horários, exceções, status e motivo. O deploy não cadastra nem ativa oportunidades.

## Backend e fluxo de geração

`api/app/schedule_config.py` concentra leitura e gravação; `shared/operational_schedule.py`
contém a decisão pura; `bracell/src/operational_schedule.py` executa a validação no fluxo
existente de `executar_regras`. A conta `pdoh_cx_config` recebe INSERT/SELECT e UPDATE
somente dos horários, status e autor da nova tabela, além de SELECT na resolução de jornada.

1. O usuário cadastra a oportunidade e os horários por jornada.
2. Nos próximos processamentos, regra e geração precisam estar ativas.
3. O executor resolve a jornada oficial de cada colaborador/dia e procura configuração ativa.
4. Consulta somente a fonte Involves mapeada com entrada, último checkout e instante de extração.
   Reutiliza os mapas de checkout, check-in e colaborador da mesma tabela; não lê horários
   de fallback da Platina como se fossem monitoramento real.
5. Seleciona a extração mais recente por colaborador/dia. Dados ambíguos, entrada ausente,
   jornada não resolvida e extração anterior à saída esperada bloqueiam a geração.
6. Checkout real preenchido, inclusive anterior ao esperado, não significa ausência.
   Ausência só é candidata após o horário esperado, com entrada real e extração suficiente.
   Saída menor que entrada representa término no dia seguinte; horários iguais são recusados.
7. Avalia as exceções já configuradas (afastamento, atestado, jornada, roteiro). Dado insuficiente
   para verificar exceção não autoriza oportunidade.
8. O dispatcher exige prova confirmada e revalida a configuração ativa e seus horários antes
   da persistência. Caminhos legados sem prova operacional não conseguem criar checkout.

A evidência conserva separadamente `configuracao_operacional` e `monitoramento`. Não há
substituição do horário observado. O PDOH, bases fixas, origem, histórico existente e fallback
legado continuam preservados. Salvar configuração não executa nem reprocessa a esteira.

## Monitoramento e limites

Fonte e campo são identificados como Involves / Último checkout. Última atualização e
quantidade de colaboradores vêm da avaliação real registrada em `JORNADA_MONITORAMENTO`,
não do relógio da tela nem da quantidade de configurações. Antes da primeira avaliação,
a interface informa a indisponibilidade, sem inventar números. O timestamp é o da extração.

Horários são um padrão por jornada; calendários por dia da semana, feriados, vigências e
múltiplos turnos não foram solicitados e não estão implementados. Saída antecipada exige
um tipo de oportunidade próprio. A vinculação por nome segue o executor existente: colisões
detectadas são bloqueadas; evolução para ID de origem é recomendada.

## Instalação e validação

`api/scripts/provision_operational_schedule.py` aplica apenas a migração 017 e os privilégios
restritos. Não reaplica a migração geral que já apresentava falha neste ambiente.
Depois, reconstruir a API e a imagem da esteira. O frontend de desenvolvimento recarrega automaticamente.

`api/scripts/validate_operational_schedule.py` valida INSERT, UPDATE e auditoria na conta real
do MySQL e reverte toda a transação. Recusa executar se já existir checkout cadastrado.
Testes sintéticos cobrem API, validação, rollback, jornadas distintas, ausência de configuração,
saída real preservada, extração insuficiente, virada de dia e integração com executor/dispatcher.
Nenhum processamento real foi disparado durante esta entrega.

Pendências operacionais: cadastrar os horários desejados e ativar a oportunidade quando
aprovada pela operação; os metadados de monitoramento aparecerão na próxima avaliação elegível.
