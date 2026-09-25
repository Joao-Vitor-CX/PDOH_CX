import assert from 'node:assert/strict';
import test from 'node:test';
import {
  actorName,
  buildCreatePayload,
  buildRuleEdit,
  creationOutcomeText,
  describeHistoryEvent,
  draftFromRule,
  scheduleDrafts,
  emptyCreateDraft,
  exceptionTemplates,
  fallbackStage,
  fieldOptionLabel,
  operatorLabels,
  operatorsForDraft,
  originLabel,
  outcomeText,
  papelCampoKey,
  papelLabel,
  principalCondition,
  statusInfo,
  validateCreateDraft,
  validateDraft,
  validSchedules,
  calcularPreviaJornada,
  scheduleEditableFields,
  scheduleNotice,
} from '../src/lib/rule-settings.ts';
import {
  operationGovernanceSchema, ruleCreateResultSchema, ruleEditResultSchema,
} from '../src/services/governance-api.ts';
import type { AvailableField, GovernanceHistoryEvent, GovernanceRule } from '../src/services/governance-api.ts';

const OPERADORES = [
  { codigo: 'MAIOR_QUE', rotulo: 'Maior que' },
  { codigo: 'MAIOR_IGUAL', rotulo: 'Maior ou igual a' },
];

test('seleção de jornadas preserva todos os campos da API e isola o rascunho', () => {
  const journeys = [44, 36, 24].map((jornada) => ({
    jornada, id: null, nome_jornada: `Operação ${jornada}H`, intervalo: '01:00',
    origem_configuracao: 'CADASTRO_OPERACIONAL' as const, disponivel: true, ativo: true,
    hora_entrada_padrao: '08:00', hora_saida_padrao: '17:00',
  }));
  const drafts = scheduleDrafts(journeys);
  for (let i = 0; i < journeys.length; i++) {
    const { disponivel: _, ...expected } = journeys[i];
    assert.deepEqual(drafts[i], expected);
  }
  drafts[0].nome_jornada = 'Rascunho';
  assert.equal(journeys[0].nome_jornada, 'Operação 44H');
  const missing = scheduleDrafts([{ ...journeys[0], ativo: false, intervalo: null, hora_entrada_padrao: null, hora_saida_padrao: null }])[0];
  assert.equal(missing.hora_entrada_padrao, null);
  assert.equal(missing.hora_saida_padrao, null);
  assert.equal(missing.intervalo, null);
});

test('salvar jornada manual preserva jornadas operacionais e permite reabrir os mesmos dados', () => {
  const operational = { jornada: 44, nome_jornada: 'Operação 44H', origem_configuracao: 'CADASTRO_OPERACIONAL' as const,
    disponivel: true, ativo: false, hora_entrada_padrao: null, hora_saida_padrao: null, intervalo: null };
  const manual = { id: 'manual-40', jornada: 40, nome_jornada: 'Equipe 40H', origem_configuracao: 'MANUAL' as const,
    disponivel: false, ativo: true, hora_entrada_padrao: '08:00', hora_saida_padrao: '17:00', intervalo: '01:00' };
  const rule = horasAusentes({ modelo_configuracao: 'JORNADA', jornadas: [operational, manual] });
  const draft = draftFromRule(rule);
  draft.jornadas![1].hora_saida_padrao = '18:00';
  const saved = buildRuleEdit(rule, draft)!.jornadas!;
  assert.equal(saved.length, 1);
  assert.equal(saved[0].id, 'manual-40');
  assert.equal(saved[0].origem_configuracao, 'MANUAL');
  assert.equal(saved[0].intervalo, '01:00');
  const reopened = draftFromRule({ ...rule, jornadas: [operational, { ...saved[0], disponivel: false }] });
  assert.deepEqual(reopened.jornadas, draft.jornadas);
  assert.equal(validSchedules(reopened.jornadas!), true);
});

test('jornada manual persiste metadados no diff e preserva identidade ao editar carga', () => {
  const schedule = { id: 'manual-40', jornada: 40, nome_jornada: 'Equipe 40H', intervalo: '01:00',
    origem_configuracao: 'MANUAL' as const, disponivel: false, ativo: true,
    hora_entrada_padrao: '08:00', hora_saida_padrao: '19:00' };
  const rule = horasAusentes({ modelo_configuracao: 'JORNADA', jornadas: [schedule] });
  const draft = draftFromRule(rule);
  assert.equal(buildRuleEdit(rule, draft), null);
  draft.jornadas![0] = { ...draft.jornadas![0], jornada: 42, nome_jornada: 'Equipe 42H', intervalo: '00:30' };
  assert.deepEqual(buildRuleEdit(rule, draft)?.jornadas, draft.jornadas);
  assert.equal(draft.jornadas![0].id, 'manual-40');
  assert.equal(validSchedules(draft.jornadas!), true);
  assert.deepEqual(calcularPreviaJornada('08:00', '19:00', '01:00'), { brutoMin: 660, liquidoMin: 600 });
});

test('jornadas manuais exigem nome, carga única, entrada, saída e intervalo', () => {
  const item = { jornada: 44, nome_jornada: 'Equipe 44H', intervalo: '01:00', origem_configuracao: 'MANUAL' as const,
    ativo: true, hora_entrada_padrao: '08:00', hora_saida_padrao: '19:00' };
  assert.equal(validSchedules([item]), true);
  for (const patch of [{ nome_jornada: ' ' }, { jornada: 0 }, { jornada: 169 }, { intervalo: '' },
    { hora_entrada_padrao: null }, { hora_saida_padrao: '08:00' }]) {
    assert.equal(validSchedules([{ ...item, ...patch }]), false);
  }
  assert.equal(validSchedules([item, { ...item, nome_jornada: 'Duplicada' }]), false);
});
const excecao = (ordem: number, descricao: string, status = 'ATIVA') => ({
  tipo: 'BLOQUEIO', ordem, papel_fonte: 'colaborador', campo_logico: 'afastado', operador: 'CONTEM',
  valor_esperado: 'ATESTADO', descricao, status, campo_rotulo: null, operador_rotulo: null, texto: null,
  operadores: [], editavel: true,
});

function horasAusentes(overrides: Partial<GovernanceRule> = {}): GovernanceRule {
  return {
    modelo_configuracao: 'CONDICAO', jornadas: [], monitoramento: null,
    configuracao_id: 'cfg', nome_regra: 'Horas ausentes', codigo_interno: 'HORAS_AUSENTES', categoria: 'Jornada',
    status: 'ATIVA', prioridade: 1, tempo_minimo_minutos: 0, ativa: true, gera_oportunidade: true,
    motivo_sem_geracao: null,
    fonte: { papel: 'pdoh', rotulo: 'PDOH Platina', tabela: 'exclusivo_bracell_platina_relatorio_pdoh', campo: 'horas_nao_registradas', campo_rotulo: 'Horas não registradas' },
    descricao: 'Horas sem registro no PDOH.', comportamento_esperado: 'x', regra_catalogo_id: null,
    geracao_automatica_ativa: true,
    condicoes: [{
      tipo: 'CONDICAO', ordem: 1, papel_fonte: 'pdoh', campo_logico: 'horas_nao_registradas', operador: 'MAIOR_QUE',
      valor_esperado: '00:00', descricao: 'Horas não registradas maior que 00:00', status: 'ATIVA',
      campo_rotulo: 'Horas não registradas', operador_rotulo: 'Maior que', texto: 'Horas não registradas maior que 00:00',
      operadores: OPERADORES, editavel: true,
    }],
    excecoes: [excecao(1, 'Atestado'), excecao(2, 'Afastamento'), excecao(3, 'Sem jornada'), excecao(4, 'Sem roteiro')],
    tratativas: [{ resultado: 'CONFIRMADO', acao_recomendada: 'Validar', destino: 'OPORTUNIDADE', gera_oportunidade: true, status: 'ATIVO' }],
    atualizado_em: '2026-09-21T12:00:00',
    ...overrides,
  };
}

test('rascunho fiel à regra: sem alteração, nada é enviado', () => {
  const rule = horasAusentes();
  const draft = draftFromRule(rule);
  assert.equal(draft.nome, 'Horas ausentes');
  assert.equal(draft.tempo, '0');
  assert.equal(draft.valor, '00:00');
  assert.deepEqual(draft.excecoes, { 1: true, 2: true, 3: true, 4: true });
  assert.equal(buildRuleEdit(rule, draft), null);
  assert.deepEqual(validateDraft(rule, draft), {});
});

test('checkout utiliza jornada sem enviar condição genérica e valida horários', () => {
  const rule = horasAusentes({ codigo_interno: 'CHECKOUT_AUSENTE', modelo_configuracao: 'JORNADA', jornadas: [
    { jornada: 44, disponivel: true, ativo: false, hora_entrada_padrao: null, hora_saida_padrao: null },
  ] });
  const draft = draftFromRule(rule);
  draft.operador = 'MENOR_QUE';
  draft.valor = '';
  assert.equal(buildRuleEdit(rule, draft), null);
  draft.jornadas = [{ jornada: 44, ativo: true, hora_entrada_padrao: '08:00', hora_saida_padrao: null }];
  assert.ok(validateDraft(rule, draft).jornadas);
  draft.jornadas[0].hora_saida_padrao = '19:00';
  assert.deepEqual(validateDraft(rule, draft), {});
  assert.deepEqual(buildRuleEdit(rule, draft), { jornadas: draft.jornadas });
});

// ----------------------------------------------------- modal de jornada (correção 25/09/2026)
const OPERACAO_MINIMA = {
  marca: 'BRACELL', operacao: 'EXCLUSIVA', descricao: 'x', somente_leitura: true, jornada: [], fallback: [],
  fontes_semanticas: [], prioridade_jornada: [], historico_governanca: [], atualizado_em: null,
  regras_governanca: [{
    configuracao_id: 'c', nome_regra: 'Checkout ausente', codigo_interno: 'CHECKOUT_AUSENTE', categoria: 'Jornada',
    status: 'ATIVA', prioridade: 2, descricao: 'd', comportamento_esperado: 'c', regra_catalogo_id: null,
    geracao_automatica_ativa: true, modelo_configuracao: 'JORNADA',
    condicoes: [{ tipo: 'CONDICAO', ordem: 1, papel_fonte: 'checkout', campo_logico: 'hora_saida', operador: 'IS NULL', valor_esperado: null, descricao: 'd', status: 'ATIVA' }],
    excecoes: [], tratativas: [], atualizado_em: '2026-09-25T00:00:00',
  }],
};
const operacional = (patch = {}) => ({ jornada: 36, id: null, nome_jornada: 'Jornada 36h', intervalo: null,
  origem_configuracao: 'CADASTRO_OPERACIONAL' as const, disponivel: true, ativo: false,
  hora_entrada_padrao: null, hora_saida_padrao: null, ...patch });

test('jornada da operação é configurável (ativa, entrada, saída, intervalo); nome e carga seguem do cadastro', () => {
  assert.deepEqual(scheduleEditableFields(operacional()),
    ['ativo', 'hora_entrada_padrao', 'hora_saida_padrao', 'intervalo']);
  assert.deepEqual(scheduleEditableFields(operacional({ origem_configuracao: 'MANUAL' })),
    ['ativo', 'nome_jornada', 'jornada', 'hora_entrada_padrao', 'hora_saida_padrao', 'intervalo']);
});

test('jornada da operação sem horário: não quebra e orienta a ação; com horário: nada a corrigir', () => {
  const padrao = { jornada: 44, hora_entrada_padrao: '08:00', hora_saida_padrao: '19:00', origem: 'CODIGO' };
  const aviso = scheduleNotice(operacional(), padrao)!;
  assert.equal(aviso.tom, 'atencao');
  assert.match(aviso.texto, /sem horário/i);
  assert.match(aviso.acao, /Informe entrada e saída/);
  assert.match(aviso.fallback!, /44h.*08:00.*19:00.*código/);
  // Horário completo e intervalo informado: sem aviso.
  assert.equal(scheduleNotice(operacional({ hora_entrada_padrao: '08:00', hora_saida_padrao: '16:00', intervalo: '01:00' }), padrao), null);
  // Horário completo sem intervalo: prévia continua, com orientação.
  assert.match(scheduleNotice(operacional({ hora_entrada_padrao: '08:00', hora_saida_padrao: '16:00' }), padrao)!.texto, /Intervalo não informado/);
});

test('salvar jornada da operação envia horários e intervalo; intervalo é opcional, mas se vier precisa ser válido', () => {
  const rule = horasAusentes({ codigo_interno: 'CHECKOUT_AUSENTE', modelo_configuracao: 'JORNADA', jornadas: [operacional()] });
  const draft = draftFromRule(rule);
  draft.jornadas = [{ ...draft.jornadas![0], hora_entrada_padrao: '08:00', hora_saida_padrao: '16:00', intervalo: '01:00' }];
  assert.deepEqual(validateDraft(rule, draft), {});
  assert.deepEqual(buildRuleEdit(rule, draft)!.jornadas, [draft.jornadas[0]]);
  assert.equal(validSchedules([{ ...draft.jornadas[0], intervalo: null }]), true);
  assert.equal(validSchedules([{ ...draft.jornadas[0], intervalo: '25:00' }]), false);
  // Ativar sem horário continua bloqueado, com mensagem que vale para qualquer origem.
  draft.jornadas = [{ ...operacional(), ativo: true }];
  assert.doesNotMatch(validateDraft(rule, draft).jornadas ?? '', /manuais\./);
  assert.ok(validateDraft(rule, draft).jornadas);
});

test('contrato expõe a jornada padrão do motor (fallback em código)', () => {
  const base = operationGovernanceSchema.parse(OPERACAO_MINIMA);
  const regra = { ...base.regras_governanca[0], jornada_padrao: { jornada: 44, hora_entrada_padrao: '08:00', hora_saida_padrao: '19:00', origem: 'CODIGO' } };
  const lida = operationGovernanceSchema.parse({ ...OPERACAO_MINIMA, regras_governanca: [regra] });
  assert.equal(lida.regras_governanca[0].jornada_padrao?.hora_saida_padrao, '19:00');
  assert.equal(operationGovernanceSchema.parse(OPERACAO_MINIMA).regras_governanca[0].jornada_padrao, null);
});

test('PATCH de jornada leva só a jornada tocada, não as 3 de novo (evita ruído no histórico)', () => {
  const rule = horasAusentes({ codigo_interno: 'CHECKOUT_AUSENTE', modelo_configuracao: 'JORNADA', jornadas: [
    { jornada: 44, disponivel: true, ativo: true, hora_entrada_padrao: '08:00', hora_saida_padrao: '19:00' },
    { jornada: 36, disponivel: true, ativo: false, hora_entrada_padrao: null, hora_saida_padrao: null },
    { jornada: 24, disponivel: true, ativo: false, hora_entrada_padrao: null, hora_saida_padrao: null },
  ] });
  const draft = draftFromRule(rule);
  // Nada mudou: mesmo reenviando o array inteiro (como o formulário sempre faz), não há diff.
  assert.equal(buildRuleEdit(rule, draft), null);
  // Só a 44h muda de horário: só ela entra no corpo, 36h/24h não são tocadas.
  draft.jornadas = draft.jornadas!.map((item) => item.jornada === 44 ? { ...item, hora_saida_padrao: '18:30' } : item);
  assert.deepEqual(buildRuleEdit(rule, draft), { jornadas: [
    { jornada: 44, ativo: true, hora_entrada_padrao: '08:00', hora_saida_padrao: '18:30' },
  ] });
});

test('o corpo do PATCH leva só o que mudou', () => {
  const rule = horasAusentes();
  const draft = { ...draftFromRule(rule), ativa: false, tempo: '30', excecoes: { 1: false, 2: true, 3: true, 4: true } };
  assert.deepEqual(buildRuleEdit(rule, draft), {
    status: 'INATIVA', tempo_minimo_minutos: 30, excecoes: [{ ordem: 1, ativa: false }],
  });
  const onlyCondition = { ...draftFromRule(rule), operador: 'MAIOR_IGUAL', valor: '0:30' };
  assert.deepEqual(buildRuleEdit(rule, onlyCondition), { condicoes: [{ ordem: 1, operador: 'MAIOR_IGUAL', valor: '0:30' }] });
  const generate = { ...draftFromRule(rule), gerar: false };
  assert.deepEqual(buildRuleEdit(rule, generate), { gerar_oportunidade: false });
});

test('a condição não editável (detector próprio) nunca entra no corpo', () => {
  const rule = horasAusentes();
  rule.condicoes[0] = { ...rule.condicoes[0], editavel: false, operadores: [{ codigo: 'MAIOR_QUE', rotulo: 'Maior que' }] };
  const draft = { ...draftFromRule(rule), valor: '01:00' };
  assert.equal(buildRuleEdit(rule, draft), null);
  assert.deepEqual(validateDraft(rule, draft), {});
});

test('regra sem tratativa CONFIRMADO não oferece mudança de "gerar"', () => {
  const rule = horasAusentes({ tratativas: [] });
  const draft = { ...draftFromRule(rule), gerar: true };
  assert.equal(buildRuleEdit(rule, draft), null);
});

test('digitação inválida é apontada antes de enviar', () => {
  const rule = horasAusentes();
  const base = draftFromRule(rule);
  assert.match(validateDraft(rule, { ...base, nome: 'ab' }).nome, /nome/i);
  for (const tempo of ['', '-1', '1.5', 'abc', '1441']) {
    assert.ok(validateDraft(rule, { ...base, tempo }).tempo, `tempo ${tempo}`);
  }
  assert.equal(validateDraft(rule, { ...base, tempo: '1440' }).tempo, undefined);
  assert.match(validateDraft(rule, { ...base, valor: 'abc' }).valor, /HH:MM/);
  assert.match(validateDraft(rule, { ...base, valor: '  ' }).valor, /valor/i);
  assert.equal(validateDraft(rule, { ...base, valor: '00:30' }).valor, undefined);
  assert.equal(validateDraft(rule, { ...base, operador: 'IS NULL', valor: '' }).valor, undefined);
});

test('estado da regra usa a definição do servidor (ativa e gera)', () => {
  assert.deepEqual([statusInfo(horasAusentes()).label, statusInfo(horasAusentes()).tone], ['Ativa', 'green']);
  assert.deepEqual(
    [statusInfo(horasAusentes({ ativa: false, gera_oportunidade: false })).label, statusInfo(horasAusentes({ ativa: false, gera_oportunidade: false })).tone],
    ['Inativa', 'slate'],
  );
  assert.equal(statusInfo(horasAusentes({ gera_oportunidade: false })).label, 'Ativa · não gera');
});

test('o resultado descreve o rascunho, não a regra salva', () => {
  const rule = horasAusentes();
  const draft = draftFromRule(rule);
  assert.match(outcomeText(rule, draft), /analisa horas não registradas e cria a oportunidade/i);
  assert.match(outcomeText(rule, { ...draft, ativa: false }), /nenhuma oportunidade é criada/i);
  assert.match(outcomeText(rule, { ...draft, gerar: false }), /não gerar/i);
});

test('a condição principal é a primeira ativa', () => {
  const rule = horasAusentes();
  const second = { ...rule.condicoes[0], ordem: 2, campo_logico: 'outra' };
  rule.condicoes = [{ ...rule.condicoes[0], status: 'INATIVA' }, second];
  assert.equal(principalCondition(rule)?.ordem, 2);
});

test('usuário enviado ao servidor só tem caracteres aceitos', () => {
  assert.equal(actorName('Consulta local', 'x'), 'Consulta local');
  assert.equal(actorName("Ana <script>'", null), 'Ana script');
  assert.equal(actorName('', 'ana@cx.com.br'), 'ana@cx.com.br');
  assert.equal(actorName('  ', '  '), 'operador');
  assert.equal(actorName('João D’Ávila', null), 'João D Ávila');
});

test('rótulos da fallback: origem principal e fallbacks em ordem', () => {
  assert.deepEqual([0, 1, 2, 3].map(fallbackStage), ['Origem principal', 'Fallback 1', 'Fallback 2', 'Fallback 3']);
  assert.equal(originLabel('INVOLVES'), 'Involves');
  assert.equal(originLabel('RAW_OPERACIONAL'), 'RAW operacional');
  assert.equal(originLabel('NOVA_ORIGEM'), 'Nova origem');
});

test('histórico legível: status, exceção, tempo e cadastro', () => {
  const rule = horasAusentes();
  const labels = operatorLabels([rule]);
  assert.equal(labels.MAIOR_IGUAL, 'Maior ou igual a');
  const event = (overrides: Partial<GovernanceHistoryEvent>): GovernanceHistoryEvent => ({
    id: 1, entidade_tipo: 'REGRA', codigo_referencia: 'HORAS_AUSENTES', acao: 'ALTERACAO', valor_anterior: null,
    valor_novo: null, usuario: 'ana', motivo: 'ajuste', registrado_em: '2026-09-21T12:00:00', ...overrides,
  });
  const status = describeHistoryEvent(event({
    valor_anterior: { status: 'ATIVA', geracao_automatica_ativa: true, tempo_minimo_minutos: 0 },
    valor_novo: { status: 'INATIVA', geracao_automatica_ativa: false, tempo_minimo_minutos: 30 },
  }), labels);
  assert.equal(status.title, 'Regra alterada');
  assert.deepEqual(status.details, ['Status: Ativa → Inativa', 'Tempo mínimo (min): 0 → 30']);
  const blocker = describeHistoryEvent(event({
    entidade_tipo: 'BLOQUEIO', valor_anterior: { status: 'ATIVA', descricao: 'Atestado' }, valor_novo: { status: 'INATIVA', descricao: 'Atestado' },
  }), labels);
  assert.equal(blocker.title, 'Exceção alterada');
  assert.match(blocker.details[0], /Atestado: desmarcada/);
  const operator = describeHistoryEvent(event({
    entidade_tipo: 'CONDICAO', valor_anterior: { operador: 'MAIOR_QUE', valor_esperado: '00:00' }, valor_novo: { operador: 'MAIOR_IGUAL', valor_esperado: '00:30' },
  }), labels);
  assert.deepEqual(operator.details, ['Regra: Maior que → Maior ou igual a', 'Valor: 00:00 → 00:30']);
  const treatment = describeHistoryEvent(event({
    entidade_tipo: 'TRATAMENTO', valor_anterior: { gera_oportunidade: 1 }, valor_novo: { gera_oportunidade: 0 },
  }), labels);
  assert.deepEqual(treatment.details, ['Gerar oportunidade: Sim → Não']);
  const created = describeHistoryEvent(event({ acao: 'CADASTRO', valor_novo: { nome_regra: 'Horas ausentes' } }), labels);
  assert.deepEqual([created.title, created.details], ['Regra cadastrada', ['Horas ausentes']]);
});

test('histórico de jornada nomeia a jornada (44h/36h/24h), não só "cadastrada/alterada"', () => {
  const event = (overrides: Partial<GovernanceHistoryEvent>): GovernanceHistoryEvent => ({
    id: 1, entidade_tipo: 'JORNADA_OPERACAO', codigo_referencia: 'CHECKOUT_AUSENTE', acao: 'ALTERACAO',
    valor_anterior: null, valor_novo: null, usuario: 'ana', motivo: 'ajuste', registrado_em: '2026-09-22T12:00:00',
    ...overrides,
  });
  // O banco serializa DECIMAL como texto ("44.00") e booleano como 0/1 (nunca true/false).
  const cadastro = describeHistoryEvent(event({ acao: 'CADASTRO', valor_novo: { jornada: '44.00', ativo: 0 } }));
  assert.deepEqual([cadastro.title, cadastro.details], ['Jornada 44h cadastrada', []]);
  const alterada = describeHistoryEvent(event({
    valor_anterior: { jornada: '44.00', hora_entrada_padrao: null, hora_saida_padrao: null, ativo: 0 },
    valor_novo: { jornada: '44.00', hora_entrada_padrao: '08:00', hora_saida_padrao: '19:00', ativo: 1 },
  }));
  assert.equal(alterada.title, 'Jornada 44h alterada');
  assert.deepEqual(alterada.details, [
    'Entrada padrão: — → 08:00', 'Saída padrão: — → 19:00', 'Jornada ativa: Não → Sim',
  ]);
  const outra = describeHistoryEvent(event({
    valor_anterior: { jornada: '36.00', hora_entrada_padrao: '07:00', hora_saida_padrao: '15:00', ativo: 1 },
    valor_novo: { jornada: '36.00', hora_entrada_padrao: '07:00', hora_saida_padrao: '16:00', ativo: 1 },
  }));
  assert.equal(outra.title, 'Jornada 36h alterada');
  assert.deepEqual(outra.details, ['Saída padrão: 15:00 → 16:00']);
});

test('contrato: a leitura antiga (sem os campos novos) continua válida e o PATCH é tipado', () => {
  const legacy = {
    marca: 'BRACELL', operacao: 'EXCLUSIVA', descricao: 'x', somente_leitura: true, jornada: [], fallback: [],
    fontes_semanticas: [], prioridade_jornada: [], historico_governanca: [], atualizado_em: null,
    regras_governanca: [{
      configuracao_id: 'c', nome_regra: 'n', codigo_interno: 'X', categoria: 'Jornada', status: 'INATIVA', prioridade: 2,
      descricao: 'd', comportamento_esperado: 'c', regra_catalogo_id: null, geracao_automatica_ativa: false,
      condicoes: [{ tipo: 'CONDICAO', ordem: 1, papel_fonte: 'checkin', campo_logico: 'hora_entrada', operador: 'IS NULL', valor_esperado: null, descricao: 'd', status: 'ATIVA' }],
      excecoes: [], tratativas: [], atualizado_em: '2026-09-21T00:00:00',
    }],
  };
  const parsed = operationGovernanceSchema.parse(legacy);
  assert.equal(parsed.regras_governanca[0].ativa, false);
  assert.equal(parsed.regras_governanca[0].tempo_minimo_minutos, 0);
  assert.deepEqual(parsed.regras_governanca[0].condicoes[0].operadores, []);
  const result = ruleEditResultSchema.parse({ alterado: true, alteracoes: [{ entidade: 'REGRA', referencia: 'X', campo: 'Status', antes: 'ATIVA', depois: 'INATIVA' }], regra: horasAusentes() });
  assert.equal(result.alterado, true);
  assert.throws(() => ruleEditResultSchema.parse({ alterado: true }));
});

// ============================================================================================
// Criação de oportunidade ("+ Nova oportunidade")
// ============================================================================================
const CAMPOS: AvailableField[] = [
  { papel_fonte: 'pdoh', campo_logico: 'ocio', rotulo: 'Ócio', tipo: 'duracao', operadores: [
    { codigo: 'MAIOR_QUE', rotulo: 'Maior que' }, { codigo: 'MENOR_QUE', rotulo: 'Menor que' } ] },
  { papel_fonte: 'colaborador', campo_logico: 'afastado', rotulo: 'Afastamento ou atestado', tipo: 'texto', operadores: [
    { codigo: 'CONTEM', rotulo: 'Contém' }, { codigo: 'IS NULL', rotulo: 'Está vazio' } ] },
];

test('rascunho de criação começa com o primeiro campo e todas as exceções marcadas', () => {
  const templates = horasAusentes().excecoes;
  const draft = emptyCreateDraft(CAMPOS, templates);
  assert.equal(draft.papelCampo, papelCampoKey('pdoh', 'ocio'));
  assert.equal(draft.operador, 'MAIOR_QUE');
  assert.equal(draft.ativa, false);
  assert.equal(draft.gerar, true);
  assert.deepEqual(draft.excecoes, { 1: true, 2: true, 3: true, 4: true });
});

test('exceptionTemplates usa a regra com mais exceções cadastradas', () => {
  const semExcecoes = horasAusentes({ codigo_interno: 'OUTRA', excecoes: [] });
  assert.deepEqual(exceptionTemplates([semExcecoes, horasAusentes()]), horasAusentes().excecoes);
  assert.deepEqual(exceptionTemplates([]), []);
});

test('validação da criação: nome, descrição, campo, operador e valor', () => {
  const base = emptyCreateDraft(CAMPOS, []);
  assert.deepEqual(Object.keys(validateCreateDraft({ ...base, nome: 'Nova oportunidade', descricao: 'Descrição válida.', valor: '01:00' }, CAMPOS)), []);
  assert.match(validateCreateDraft({ ...base, nome: 'ab' }, CAMPOS).nome, /nome/i);
  assert.match(validateCreateDraft({ ...base, nome: 'Nova oportunidade', descricao: '' }, CAMPOS).descricao, /descrição/i);
  assert.match(validateCreateDraft({ ...base, nome: 'Nova oportunidade', descricao: 'Descrição válida.', valor: 'abc' }, CAMPOS).valor, /HH:MM/);
  assert.match(validateCreateDraft({ ...base, nome: 'Nova oportunidade', descricao: 'Descrição válida.', valor: '' }, CAMPOS).valor, /valor/i);
  // Campo texto (CONTEM) não exige o formato de duração.
  const textual = { ...base, nome: 'Nova oportunidade', descricao: 'Descrição válida.', papelCampo: papelCampoKey('colaborador', 'afastado'), operador: 'CONTEM', valor: 'ATESTADO' };
  assert.deepEqual(validateCreateDraft(textual, CAMPOS), {});
  // IS NULL não exige valor.
  const semValor = { ...textual, operador: 'IS NULL', valor: '' };
  assert.deepEqual(validateCreateDraft(semValor, CAMPOS), {});
});

test('operadores oferecidos seguem o campo selecionado', () => {
  const base = emptyCreateDraft(CAMPOS, []);
  assert.deepEqual(operatorsForDraft(base, CAMPOS).map((o) => o.codigo), ['MAIOR_QUE', 'MENOR_QUE']);
  const outro = { ...base, papelCampo: papelCampoKey('colaborador', 'afastado') };
  assert.deepEqual(operatorsForDraft(outro, CAMPOS).map((o) => o.codigo), ['CONTEM', 'IS NULL']);
});

test('payload de criação só é montado quando o rascunho é válido, com as exceções marcadas', () => {
  const draft = { ...emptyCreateDraft(CAMPOS, horasAusentes().excecoes), nome: 'Nova oportunidade', descricao: 'Descrição válida.', valor: '01:00', excecoes: { 1: true, 2: false, 3: true, 4: false } };
  const payload = buildCreatePayload(draft, CAMPOS, 'joao.vitor', 'Motivo da criação.');
  assert.deepEqual(payload, {
    usuario: 'joao.vitor', motivo: 'Motivo da criação.', nome_regra: 'Nova oportunidade', descricao: 'Descrição válida.',
    papel_fonte: 'pdoh', campo_logico: 'ocio', operador: 'MAIOR_QUE', valor: '01:00',
    excecoes: [1, 3], status: 'INATIVA', gerar_oportunidade: true,
  });
  assert.equal(buildCreatePayload({ ...draft, nome: 'ab' }, CAMPOS, 'x', 'Motivo da criação.'), null);
});

test('resultado da criação descreve o rascunho enquanto o usuário configura', () => {
  const draft = { ...emptyCreateDraft(CAMPOS, []), ativa: true, gerar: true };
  assert.match(creationOutcomeText(draft, CAMPOS), /Oportunidade ativa: o sistema analisa ócio/i);
  assert.match(creationOutcomeText({ ...draft, gerar: false }, CAMPOS), /configurada para não gerar/i);
  assert.match(creationOutcomeText({ ...draft, ativa: false }, CAMPOS), /inativa/i);
});

test('rótulo do campo combina o papel e o nome de negócio; papeis desconhecidos viram texto legível', () => {
  assert.equal(fieldOptionLabel(CAMPOS[0]), 'PDOH Platina · Ócio');
  assert.equal(fieldOptionLabel(CAMPOS[1]), 'Cadastro de colaboradores · Afastamento ou atestado');
  assert.equal(papelLabel('novo_papel'), 'Novo papel');
});

test('contrato: resposta da criação é tipada e a leitura expõe os campos disponíveis', () => {
  const resultado = ruleCreateResultSchema.parse({ criado: true, alteracoes: [], regra: horasAusentes() });
  assert.equal(resultado.criado, true);
  const leitura = operationGovernanceSchema.parse({
    marca: 'BRACELL', operacao: 'EXCLUSIVA', descricao: 'x', somente_leitura: true, jornada: [], fallback: [],
    regras_governanca: [], fontes_semanticas: [], campos_disponiveis: CAMPOS, prioridade_jornada: [],
    historico_governanca: [], atualizado_em: null,
  });
  assert.equal(leitura.campos_disponiveis.length, 2);
  // Sem o campo (leitura antiga), a lista fica vazia em vez de quebrar a tela de criação.
  const antiga = operationGovernanceSchema.parse({ ...leitura, campos_disponiveis: undefined });
  assert.deepEqual(antiga.campos_disponiveis, []);
});
