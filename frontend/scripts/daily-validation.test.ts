import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Occurrence, OperationalGroup } from '../src/services/operational-api.ts';
import { pdohDailyRowSchema, pdohSummarySchema, type PdohDailyRow } from '../src/services/pdoh-indicator.ts';
import {
  OPPORTUNITY_COLUMNS, OPPORTUNITY_TYPES, appliesFallback, dayStatusLabel, dedupeRecords, groupFallback,
  loadOpportunityGroups, opportunityGroups, opportunityKey, opportunityRecord, summarizeOpportunities,
  workbookSheets, xlsxFileName, type OpportunityRecord,
} from '../src/services/daily-validation.ts';

const group = (overrides: Partial<OperationalGroup> = {}): OperationalGroup => ({
  grupo_id: 'g-1', marca: 'BRACELL', operacao: 'EXCLUSIVA', tipo_problema: 'CHECKOUT_AUSENTE',
  titulo: 'Checkout ausente', colaborador: 'JOAO SILVA', quantidade: 1, registros_historicos: 1,
  dias_afetados: 1, primeira_ocorrencia: '2026-09-03', ultima_ocorrencia: '2026-09-03', severidade: 'MEDIA',
  impacto: null, status_operacional: 'ABERTA', responsavel: null,
  validacao: { resultado: 'confirmado', rotulo: 'Confirmado', motivo: null, jornada_origem: 'INVOLVES' }, ...overrides,
});

const checkoutProof = (origem: 'FALLBACK' | 'CONFIGURACAO') => ({
  fallback_usado: origem === 'FALLBACK',
  comprovacao: {
    resultado: 'confirmado', fonte: 'Involves', fonte_tabela: 'relatorio_checkin_bracell',
    jornada_origem: origem === 'FALLBACK' ? 'FALLBACK' : undefined,
    configuracao_operacional: { id: 'j', jornada: 44, hora_entrada_padrao: '08:00:00', hora_saida_padrao: '19:00:00', origem },
    monitoramento: { hora_entrada: '08:10:00', hora_saida: null, data: '2026-09-03', evolucao: '2026-09-03 23:00:00' },
    verificacoes: [
      { criterio: 'condicao', rotulo: 'Condição da regra', atendido: true, fonte: 'relatorio_checkin_bracell', campo: 'hora_saida', valor: null },
      { criterio: 'excecao', rotulo: 'Exceção: Atestado válido no período', atendido: true, fonte: null, campo: 'afastado', valor: null },
    ],
  },
});

const occurrence = (evidencia: unknown, overrides: Partial<Occurrence> = {}): Occurrence => ({
  fingerprint: 'f-1', oportunidade_id: 'op-1', execution_id: 'EXEC_1', data_referencia: '2026-09-03',
  tabela_origem: 'relatorio_checkin_bracell', origem: 'Involves', severidade: 'MEDIA', evidencia,
  identificada_em: '2026-09-04T05:00:00', repeticoes: 1, ...overrides,
});

const day = (overrides: Partial<PdohDailyRow> = {}): PdohDailyRow => pdohDailyRowSchema.parse({
  colaborador: 'JOAO SILVA', estado: 'SP', data: '2026-09-03', nome_do_dia: 'Quinta-feira', deslocamento: null,
  ocio: null, produtividade: null, horas_nao_registradas: '00:39:02', horas_programadas: '08:48:00',
  primeiro_checkin: '07:55:00', ultimo_checkout: '17:10:00', visitas: 3, visitas_realizadas: 3, pesquisas: 0,
  pesquisas_realizadas: 0, percentuais: { produtividade: null, visitas: null, pesquisas: null, efetividade: null },
  jornada: { fonte: null, horario_aplicado: null, houve_fallback: false, origem_fallback: null, jornada_aplicada: '36H', origem: 'INVOLVES' },
  justificativa: null,
  validacao: { status: 'VALIDO', considerado: true, fallback_aplicado: false, saida_considerada: null, origem_saida: null, motivo: 'Entrada e saída registradas.' },
  origem_dado: 'produtos_platina.exclusivo_bracell_platina_relatorio_pdoh', ...overrides,
});

// ------------------------------------------------------------------ contrato da API
test('resumo aceita o status do dia e o consolidado da validação (campos novos, opcionais)', () => {
  const row = day();
  assert.equal(row.validacao?.status, 'VALIDO');
  assert.equal(row.validacao?.gerou_oportunidade, false);   // API anterior: campo ausente = não gerou
  assert.equal(day({ validacao: { ...row.validacao!, gerou_oportunidade: true } }).validacao?.gerou_oportunidade, true);
  const antigo = pdohDailyRowSchema.parse({ ...row, validacao: undefined, justificativa: undefined });
  assert.equal(antigo.validacao, null);
  const summary = pdohSummarySchema.parse({
    disponivel: true, motivo: null, percentual: 70, variacao_periodo_anterior: null,
    periodo: { inicio: '2026-08-31', fim: '2026-09-05' },
    validacao: { dias: 3, considerados: 2, validos: 1, checkout_esquecido: 1, fallback_aplicado: 1,
      desconsiderados: 1, sem_atividade_prevista: 0, colaboradores: 2, justificativas: { FERIADO: 1 } },
  });
  assert.equal(summary.validacao?.fallback_aplicado, 1);
  assert.equal(pdohSummarySchema.parse({ ...summary, validacao: undefined }).validacao, null);
});

test('rótulo do status do dia é de negócio, nunca o código', () => {
  assert.equal(dayStatusLabel('CHECKOUT_ESQUECIDO'), 'Checkout esquecido · fallback');
  assert.equal(dayStatusLabel('DESCONSIDERADO'), 'Desconsiderado');
  assert.equal(dayStatusLabel(null), 'Não informado');
});

// ------------------------------------------------------------------ fallback = checkout esquecido
test('fallback só existe para checkout esquecido', () => {
  assert.equal(appliesFallback('CHECKOUT_AUSENTE'), true);
  assert.equal(appliesFallback('HORAS_AUSENTES'), false);
});

test('checkout esquecido: motivo, jornada, origem, fallback e evidência vêm da prova', () => {
  const record = opportunityRecord(group(), occurrence(checkoutProof('FALLBACK')), null);
  assert.deepEqual({
    id: record.id, colaborador: record.colaborador, data: record.data, regra: record.regra,
    jornada: record.jornada, origem_jornada: record.origem_jornada, fallback: record.fallback,
    saida_considerada: record.saida_considerada, checkin: record.checkin, checkout: record.checkout,
  }, {
    id: 'op-1', colaborador: 'JOAO SILVA', data: '2026-09-03', regra: 'CHECKOUT_AUSENTE', jornada: '44H',
    origem_jornada: 'Jornada padrão 44H (cadastro sem jornada)', fallback: 'Sim', saida_considerada: '19:00',
    checkin: '08:10', checkout: null,
  });
  assert.equal(record.motivo, 'Entrada registrada às 08:10 sem checkout informado; saída considerada às 19:00 pela jornada 44H.');
  assert.equal(record.cenario, 'Checkout esquecido (entrada sem saída)');
  assert.equal(record.evidencia, 'Check-in às 08:10 sem checkout · Relatório de check-in (Involves)');
  assert.equal(record.evidencias.length, 2);
  assert.equal(record.evidencias[1].verificacao, 'Exceção: Atestado válido no período');
});

test('jornada do cadastro não é rotulada como jornada padrão', () => {
  const record = opportunityRecord(group(), occurrence(checkoutProof('CONFIGURACAO')), null);
  assert.equal(record.origem_jornada, 'Configuração da operação');
  assert.equal(record.fallback, 'Sim');
});

test('horas ausentes: fallback não se aplica e check-in/checkout vêm do dia da Platina', () => {
  const proof = { comprovacao: {
    resultado: 'confirmado', fonte: 'PDOH Platina', fonte_tabela: 'exclusivo_bracell_platina_relatorio_pdoh',
    jornada_origem: 'INVOLVES', jornada_semanal: 36, esperado: 'Horas não registradas maior que 00:00', encontrado: '00:39:02',
    verificacoes: [{ criterio: 'condicao', rotulo: 'Condição da regra', atendido: true, campo: 'horas_nao_registradas', valor: '00:39:02', fonte: 'exclusivo_bracell_platina_relatorio_pdoh' }],
  } };
  const record = opportunityRecord(group({ tipo_problema: 'HORAS_AUSENTES', titulo: 'Horas ausentes' }), occurrence(proof), day());
  assert.equal(record.fallback, 'Não se aplica');
  assert.equal(record.saida_considerada, null);
  assert.equal(record.jornada, '36H');
  assert.equal(record.origem_jornada, 'Cadastro Involves');
  assert.deepEqual([record.checkin, record.checkout], ['07:55', '17:10']);
  assert.equal(record.motivo, 'Horas não registradas maior que 00:00 — encontrado 00:39:02.');
  assert.equal(record.cenario, 'Horas ausentes');
  assert.equal(record.evidencia, 'Horas não registradas: 00:39:02 · PDOH Platina');
});

test('prova sem jornada usa a jornada do dia e nunca inventa', () => {
  const semJornada = opportunityRecord(group({ tipo_problema: 'HORAS_AUSENTES' }), occurrence({ comprovacao: {} }), null);
  assert.equal(semJornada.jornada, null);
  assert.equal(semJornada.origem_jornada, null);
  const doDia = opportunityRecord(group({ tipo_problema: 'HORAS_AUSENTES' }), occurrence({ comprovacao: {} }), day());
  assert.equal(doDia.jornada, '36H');
});

// ------------------------------------------------------------------ card de oportunidades
test('oportunidade real é somente checkout ausente; horas ausentes impactam só o PDOH', () => {
  assert.deepEqual(OPPORTUNITY_TYPES, ['CHECKOUT_AUSENTE']);
  const kept = opportunityGroups([group(), group({ grupo_id: 'h', tipo_problema: 'HORAS_AUSENTES' }),
    group({ grupo_id: 'r', tipo_problema: 'REGISTRO_DUPLICADO' })]);
  assert.deepEqual(kept.map((g) => g.grupo_id), ['g-1']);
});

test('card soma ocorrências reais, colaboradores, tipo e fallback; ignora horas ausentes', () => {
  const summary = summarizeOpportunities([
    group({ quantidade: 2 }),
    group({ grupo_id: 'g-2', colaborador: 'MARIA', quantidade: 3, status_operacional: 'RESOLVIDA' }),
    group({ grupo_id: 'g-3', tipo_problema: 'HORAS_AUSENTES', titulo: 'Horas ausentes', quantidade: 5 }),
    // Checkout sem prova confirmada não conta como fallback.
    group({ grupo_id: 'g-4', quantidade: 4, validacao: { resultado: 'indisponivel', rotulo: 'Sem prova', motivo: null, jornada_origem: 'INDISPONIVEL' } }),
  ]);
  assert.deepEqual(summary, {
    total: 9, colaboradores: 2, fallback: 5, pendencias: 6,
    tipos: [{ tipo: 'CHECKOUT_AUSENTE', titulo: 'Checkout ausente', quantidade: 9 }],
  });
  assert.equal(groupFallback(group({ quantidade: 3 })), 3);
  assert.equal(groupFallback(group({ tipo_problema: 'HORAS_AUSENTES', quantidade: 3 })), 0);
});

test('carga inicial pede ao servidor só os tipos de oportunidade, sem ocorrências nem histórico', async (t) => {
  const urls: URL[] = [];
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    const url = new URL(input, 'http://localhost');
    urls.push(url);
    // Servidor antigo que ignorasse o filtro: a tela continua filtrando.
    return Response.json({ items: [group(), group({ grupo_id: 'h', tipo_problema: 'HORAS_AUSENTES' })], total: 2, pagina: 1, paginas: 1, tamanho: 200 });
  });
  const groups = await loadOpportunityGroups({ marca: 'BRACELL', periodo: 'personalizado', periodo_inicio: '2026-08-31', periodo_fim: '2026-09-05' });
  assert.deepEqual(groups.map((g) => g.grupo_id), ['g-1']);
  assert.deepEqual(urls.map((url) => [url.pathname, url.searchParams.get('tipo'), url.searchParams.get('incluir_encerradas')]),
    [['/api/v2/oportunidades/resumo', 'CHECKOUT_AUSENTE', null]]);
});

test('deduplicação por colaborador + data + tipo + regra mantém a gravação mais recente', () => {
  const antigo = opportunityRecord(group(), occurrence(checkoutProof('FALLBACK'), { oportunidade_id: 'op-antigo', identificada_em: '2026-09-04T05:00:00' }), null);
  const recente = opportunityRecord(group({ grupo_id: 'g-9', colaborador: ' joao  silva ' }),
    occurrence(checkoutProof('FALLBACK'), { oportunidade_id: 'op-recente', identificada_em: '2026-09-05T05:00:00' }), null);
  const outroDia = opportunityRecord(group(), occurrence(checkoutProof('FALLBACK'), { oportunidade_id: 'op-dia', data_referencia: '2026-09-04' }), null);
  assert.equal(opportunityKey(antigo), opportunityKey(recente));
  // Preserva a ordem de entrada; a lista é ordenada depois por colaborador e data.
  assert.deepEqual(dedupeRecords([antigo, outroDia, recente]).map((r) => r.id), ['op-dia', 'op-recente']);
});

// ------------------------------------------------------------------ XLSX = tela
const record = (): OpportunityRecord => opportunityRecord(group(), occurrence(checkoutProof('FALLBACK')), null);

test('aba Oportunidades usa exatamente as colunas da tabela da tela', () => {
  const sheets = workbookSheets({
    periodo: { inicio: '2026-08-31', fim: '2026-09-05' }, validacao: null, records: [record()], historicos: new Map(),
  });
  assert.deepEqual(sheets.map((sheet) => sheet.sheet), ['Resumo', 'Oportunidades', 'Evidências', 'Histórico']);
  const oportunidades = sheets[1].rows;
  assert.deepEqual(oportunidades[0], OPPORTUNITY_COLUMNS.map(([label]) => label));
  // Colunas obrigatórias do XLSX (§8), na ordem da tela.
  assert.deepEqual(oportunidades[0].slice(0, 11), ['ID', 'Colaborador', 'Data', 'Tipo da oportunidade', 'Regra', 'Motivo',
    'Jornada aplicada', 'Origem da jornada', 'Fallback', 'Evidências disponíveis', 'Status']);
  assert.equal(oportunidades[1][3], 'Checkout ausente');
  assert.deepEqual(oportunidades[1], OPPORTUNITY_COLUMNS.map(([, get]) => get(record())));
});

test('resumo traz período, totais, colaboradores, regras e fallback; evidências e histórico por ocorrência', () => {
  const horas = opportunityRecord(group({ grupo_id: 'g-2', colaborador: 'MARIA', tipo_problema: 'HORAS_AUSENTES', titulo: 'Horas ausentes' }),
    occurrence({ comprovacao: {} }, { oportunidade_id: 'op-2' }), null);
  const sheets = workbookSheets({
    periodo: { inicio: '2026-08-31', fim: '2026-09-05' },
    validacao: { dias: 10, considerados: 8, validos: 7, checkout_esquecido: 1, fallback_aplicado: 1,
      desconsiderados: 2, sem_atividade_prevista: 0, colaboradores: 2, justificativas: { FERIADO: 2 } },
    records: [record(), horas],
    historicos: new Map([['op-1', [{ id: 1, oportunidade_id: 'op-1', execution_id: 'EXEC_1', status_anterior: null,
      status_novo: 'ABERTA', acao: 'IDENTIFICADA', observacao: 'Novo achado', responsavel: null, contexto: null,
      registrado_em: '2026-09-04T05:00:00' }]]]),
  });
  const resumo = Object.fromEntries(sheets[0].rows.slice(1).map(([k, v]) => [k, v]));
  assert.equal(resumo['Período'], '31/08/2026 a 05/09/2026');
  assert.equal(resumo['Total de oportunidades'], 2);
  assert.equal(resumo['Colaboradores'], 2);
  assert.equal(resumo['Regras'], 'CHECKOUT_AUSENTE (1); HORAS_AUSENTES (1)');
  assert.equal(resumo['Quantidade de fallback'], 1);
  assert.equal(resumo['Dias desconsiderados (justificados)'], 2);
  const evidencias = sheets[2].rows;
  assert.equal(evidencias.length, 1 + 2);   // cabeçalho + 2 verificações do checkout; horas sem verificação
  assert.equal(evidencias[1][0], 'op-1');
  const historico = sheets[3].rows;
  assert.deepEqual(historico[1].slice(0, 4), ['op-1', '04/09/2026 05:00', 'IDENTIFICADA', '']);
});

test('nome do arquivo identifica a semana', () => {
  assert.equal(xlsxFileName({ inicio: '2026-08-31', fim: '2026-09-05' }), 'oportunidades_2026-08-31_a_2026-09-05.xlsx');
});
