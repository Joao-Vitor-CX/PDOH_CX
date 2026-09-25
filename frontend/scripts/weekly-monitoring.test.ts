import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { OperationalGroup } from '../src/services/operational-api.ts';
import {
  compareReads, csvFileName, journeyFound, loadOccurrences, loadWeeklyMonitoring,
  occurrenceFromEvidence, occurrencesCsv, shiftWeek, summarizeWeek, weekContaining,
} from '../src/services/weekly-monitoring.ts';

const week = { inicio: '2026-08-31', fim: '2026-09-05' };
const group = (id: string, overrides: Partial<OperationalGroup> = {}): OperationalGroup => ({
  grupo_id: id, marca: 'BRACELL', operacao: 'EXCLUSIVA', tipo_problema: 'CHECKOUT_AUSENTE',
  titulo: 'Checkout não registrado', colaborador: `PESSOA ${id}`, quantidade: 2,
  registros_historicos: 6, dias_afetados: 2, primeira_ocorrencia: '2026-09-01',
  ultima_ocorrencia: '2026-09-02', severidade: 'MEDIA', impacto: null,
  status_operacional: 'ABERTA', responsavel: null,
  validacao: { resultado: 'confirmado', rotulo: 'Confirmado', motivo: null, jornada_origem: 'INVOLVES' },
  ...overrides,
});
const page = <T>(items: T[]) => ({ items, total: items.length, pagina: 1, paginas: 1, tamanho: 200 });
const base = {
  colaborador: 'PESSOA', grupo_id: 'g', oportunidade_id: 'o-1', data: '2026-09-01', semana: '2026-08-31 a 2026-09-05',
  regra: 'Checkout não registrado', tipo: 'CHECKOUT_AUSENTE', status: 'ABERTA', execucao: 'EXEC_1',
  identificada_em: '2026-09-02T05:00:00', repeticoes: 1,
};

test('semana operacional vai de segunda a sábado e navega sem sair do calendário', () => {
  assert.deepEqual(weekContaining('2026-09-05'), week);
  assert.deepEqual(weekContaining('2026-08-31'), week);
  assert.deepEqual(shiftWeek(week, 1), { inicio: '2026-09-07', fim: '2026-09-12' });
  assert.deepEqual(shiftWeek(week, -1), { inicio: '2026-08-24', fim: '2026-08-29' });
});

test('card por tipo soma ocorrências deduplicadas, conta pessoas distintas e fallback', () => {
  const cards = summarizeWeek([
    group('a'),
    group('b', { colaborador: 'pessoa a ', quantidade: 1 }),
    group('c', { validacao: { resultado: 'confirmado', rotulo: 'Confirmado', motivo: null, jornada_origem: 'FALLBACK' } }),
    group('h', { tipo_problema: 'HORAS_AUSENTES', titulo: 'Horas ausentes', quantidade: 9, status_operacional: 'RESOLVIDA' }),
  ]);
  // Fallback = checkout esquecido comprovado (todas as ocorrências de CHECKOUT_AUSENTE confirmadas);
  // jornada padrão 44H é só origem da jornada e não conta como fallback.
  assert.deepEqual(cards.map((card) => [card.tipo, card.ocorrencias, card.colaboradores, card.fallback, card.status]), [
    ['HORAS_AUSENTES', 9, 1, 0, 'Tratado'],
    ['CHECKOUT_AUSENTE', 5, 2, 5, 'Em aberto'],
  ]);
  // `registros_historicos` (regravações do reprocessamento) nunca vira ocorrência.
  assert.equal(cards.find((card) => card.tipo === 'CHECKOUT_AUSENTE')?.ocorrencias, 5);
});

test('monitoramento lê a semana fixa por GET, incluindo encerradas; alertas falhos não derrubam os cards', async (t) => {
  const urls: URL[] = [];
  t.mock.method(globalThis, 'fetch', async (input: string, init: RequestInit) => {
    assert.equal(init.method ?? 'GET', 'GET');
    const url = new URL(input, 'http://localhost');
    urls.push(url);
    if (url.pathname.endsWith('/alertas/resumo')) return new Response('', { status: 503 });
    return Response.json(page([group('a')]));
  });
  const data = await loadWeeklyMonitoring(week);
  assert.equal(data.cards.length, 1);
  assert.equal(data.alerts, null);
  const groups = urls.find((url) => url.pathname === '/api/v2/oportunidades/resumo');
  assert.equal(groups?.searchParams.get('periodo_inicio'), week.inicio);
  assert.equal(groups?.searchParams.get('periodo_fim'), week.fim);
  assert.equal(groups?.searchParams.get('incluir_encerradas'), 'true');
});

test('ocorrência lê jornada, horário e fallback da prova gravada, sem inventar padrão', () => {
  const checkout = occurrenceFromEvidence({ fallback_usado: false, origem: 'Involves', comprovacao: {
    jornada_origem: 'INVOLVES', resultado: 'confirmado', fonte: 'Involves', encontrado: 'Checkout ausente',
    configuracao_operacional: { jornada: 44, hora_entrada_padrao: '08:00:00', hora_saida_padrao: '19:00:00' },
  } }, base);
  assert.equal(checkout.jornada_aplicada, '44H');
  assert.equal(checkout.horario_esperado, '08:00 - 19:00');
  assert.equal(checkout.jornada_encontrada, 'sim');
  // Checkout esquecido com saída considerada pela jornada: é o fallback.
  assert.equal(checkout.fallback, true);
  assert.equal(checkout.motivo_fallback, 'Checkout não informado; saída considerada às 19:00 pela jornada 44H.');
  assert.equal(checkout.evidencia, 'Involves: Checkout ausente');

  // Jornada padrão sem saída considerada na prova: origem da jornada, não fallback.
  const padrao = occurrenceFromEvidence({ comprovacao: { jornada_origem: 'FALLBACK', resultado: 'confirmado' } }, base);
  assert.equal(padrao.fallback, false);
  assert.equal(padrao.jornada_encontrada, 'fallback');
  assert.equal(padrao.motivo_fallback, null);

  const horas = occurrenceFromEvidence({ comprovacao: { jornada_origem: 'INVOLVES', resultado: 'confirmado' } },
    { ...base, tipo: 'HORAS_AUSENTES' });
  assert.equal(horas.fallback, false);

  const legado = occurrenceFromEvidence({ fallback_usado: true, fallback_valor: '23:59' }, base);
  assert.equal(legado.fallback, true);
  assert.equal(legado.horario_esperado, '23:59');
  assert.equal(legado.jornada_origem, 'INDISPONIVEL');
  assert.equal(legado.jornada_aplicada, null);

  const semProva = occurrenceFromEvidence(null, base);
  assert.equal(semProva.jornada_encontrada, 'nao');
  assert.equal(semProva.fallback, false);
  assert.equal(semProva.horario_esperado, null);
  assert.equal(journeyFound('RAW'), 'sim');
});

test('detalhe usa ocorrências consolidadas pelo backend e confere todas as páginas', async (t) => {
  const urls: URL[] = [];
  const record = (id: string, data: string, repeticoes: number) => ({
    fingerprint: id, oportunidade_id: id, execution_id: 'E2', data_referencia: data,
    tabela_origem: 'origem', origem: 'INVOLVES', severidade: 'MEDIA', identificada_em: '2026-09-03T05:00:00', repeticoes,
    evidencia: { comprovacao: { jornada_origem: 'INVOLVES', resultado: 'confirmado' } },
  });
  t.mock.method(globalThis, 'fetch', async (input: string, init: RequestInit) => {
    assert.equal(init.method ?? 'GET', 'GET');
    const url = new URL(input, 'http://localhost');
    urls.push(url);
    const pagina = Number(url.searchParams.get('pagina'));
    return Response.json({ grupo_id: 'a', marca: 'BRACELL', tipo_problema: 'CHECKOUT_AUSENTE',
      titulo: 'Checkout não registrado', colaborador: 'PESSOA a', colaborador_id_interno: null,
      campo: null, origem: 'INVOLVES', quantidade: 2, impacto: null, acao_recomendada: null,
      status_operacional: 'ABERTA', periodo: week,
      ocorrencias: { items: [pagina === 1 ? record('a1', '2026-09-01', 2) : record('a2', '2026-09-02', 1)],
        total: 2, pagina, paginas: 2, tamanho: 200 } });
  });
  const window = { periodo: 'personalizado' as const, periodo_inicio: week.inicio, periodo_fim: week.fim };
  const rows = await loadOccurrences([group('a')], window);
  assert.equal(urls.length, 2);
  assert.equal(urls[0].pathname, '/api/v2/oportunidades/a/detalhes');
  assert.equal(urls[0].searchParams.get('periodo_inicio'), week.inicio);
  assert.deepEqual(rows.map((row) => [row.data, row.oportunidade_id, row.repeticoes, row.execucao]), [
    ['2026-09-01', 'a1', 2, 'E2'],
    ['2026-09-02', 'a2', 1, 'E2'],
  ]);
  assert.equal(urls[1].searchParams.get('pagina'), '2');
  await assert.rejects(loadOccurrences([group('a', { quantidade: 3 })], window), /não conferem/);
  assert.deepEqual(await loadOccurrences([], window), []);
});

test('CSV traz as colunas obrigatórias, BOM para Excel e protege contra fórmula', () => {
  const row = occurrenceFromEvidence({ comprovacao: { jornada_origem: 'FALLBACK', encontrado: '=1+1', fonte: 'A;B' } }, base);
  const csv = occurrencesCsv([row]);
  assert.ok(csv.startsWith('﻿'));
  const [header, line] = csv.slice(1).split('\r\n');
  for (const column of ['Colaborador', 'Identificador da oportunidade', 'Data', 'Semana', 'Regra',
    'Tipo da ocorrência', 'Jornada aplicada', 'Origem da jornada', 'Utilizou fallback',
    'Horário esperado', 'Status', 'Evidências disponíveis'])
    assert.ok(header.split(';').includes(column), column);
  assert.ok(line.includes('"A;B: =1+1"'));
  assert.ok(line.includes(';Não;'));    // jornada padrão sem saída considerada não é fallback
  assert.equal(csvFileName(week, 'CHECKOUT_AUSENTE'), 'oportunidades_checkout_ausente_2026-08-31_a_2026-09-05.csv');
});

test('reprocessamento conta novas e atualizadas pela identidade colaborador + regra + semana', () => {
  const before = [group('a'), group('b')];
  const after = [group('a'), group('b', { quantidade: 3 }), group('c')];
  assert.deepEqual(compareReads(before, after, week), { processadas: 3, novas: 1, atualizadas: 1, duplicadas: 0 });
  assert.deepEqual(compareReads(after, after, week), { processadas: 3, novas: 0, atualizadas: 0, duplicadas: 0 });
  const duplicated = [...after, group('outro-id', { colaborador: 'pessoa a' })];
  assert.equal(compareReads(after, duplicated, week).duplicadas, 1);
});

test('monitoramento exibe somente oportunidades reais (checkout ausente); horas ausentes impactam só o PDOH', async (t) => {
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    const url = new URL(input, 'http://localhost');
    if (url.pathname.endsWith('/alertas/resumo')) return new Response('', { status: 503 });
    return Response.json(page([group('a'), group('x', { tipo_problema: 'REGISTRO_DUPLICADO', titulo: 'Duplicado' }),
      group('h', { tipo_problema: 'HORAS_AUSENTES', titulo: 'Horas ausentes' })]));
  });
  const data = await loadWeeklyMonitoring(week);
  assert.deepEqual(data.cards.map((card) => card.tipo), ['CHECKOUT_AUSENTE']);
  assert.deepEqual(data.groups.map((item) => item.grupo_id), ['a']);
});
