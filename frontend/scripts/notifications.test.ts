import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  currentNotificationWeek, isNewNotification, loadOpportunityNotifications,
  markNotificationsSeen, notificationDetailUrl, notificationMessage, notificationStorageKey,
  parseSeenOpportunities, weeklyNotifications,
} from '../src/services/opportunity-notifications.ts';
import type { OperationalGroup } from '../src/services/operational-api.ts';

const period = { inicio: '2026-09-21', fim: '2026-09-26' };
const group = (id = 'checkout-44', overrides: Partial<OperationalGroup> = {}): OperationalGroup => ({
  grupo_id: id, marca: 'BRACELL', operacao: 'EXCLUSIVA', tipo_problema: 'CHECKOUT_AUSENTE',
  titulo: 'Checkout não registrado', colaborador: 'COLABORADOR TESTE 44H', quantidade: 1,
  registros_historicos: 1, dias_afetados: 1, primeira_ocorrencia: '2026-09-23',
  ultima_ocorrencia: '2026-09-23', severidade: 'MEDIA', impacto: 'Tempo em loja',
  status_operacional: 'ABERTA', responsavel: null,
  validacao: { resultado: 'confirmado', rotulo: 'Confirmado', motivo: null,
    jornada_origem: 'INVOLVES' }, ...overrides,
});
const page = (items: OperationalGroup[], total = items.length, pagina = 1, paginas = 1) =>
  ({ items, total, pagina, paginas, tamanho: 200 });

test('semana vigente usa o calendário de São Paulo, de segunda a sábado', () => {
  assert.deepEqual(currentNotificationWeek(new Date('2026-09-28T01:00:00Z')), period);
  assert.deepEqual(currentNotificationWeek(new Date('2026-09-28T03:00:00Z')),
    { inicio: '2026-09-28', fim: '2026-10-03' });
});

test('sino consome todas as regras da semana vigente, em todas as páginas, somente por GET', async (t) => {
  const requests: URL[] = [];
  const first = Array.from({ length: 200 }, (_, i) => group(`item-${i}`, {
    colaborador: `PESSOA ${i}`, ultima_ocorrencia: '2026-09-22',
  }));
  t.mock.method(globalThis, 'fetch', async (input: string, init: RequestInit) => {
    assert.equal(init.method ?? 'GET', 'GET');
    const url = new URL(input, 'http://localhost');
    requests.push(url);
    assert.equal(url.pathname, '/api/v2/oportunidades/resumo');
    // Só o tipo que é oportunidade é pedido ao servidor (carga leve).
    assert.equal(url.searchParams.get('tipo'), 'CHECKOUT_AUSENTE');
    assert.equal(url.searchParams.get('periodo'), 'personalizado');
    assert.equal(url.searchParams.get('periodo_inicio'), period.inicio);
    assert.equal(url.searchParams.get('periodo_fim'), period.fim);
    assert.equal(url.searchParams.get('marca'), 'BRACELL');
    assert.equal(url.searchParams.get('incluir_encerradas'), 'true');
    return Response.json(url.searchParams.get('pagina') === '1'
      ? page(first, 201, 1, 2) : page([group('horas', { tipo_problema: 'HORAS_AUSENTES', titulo: 'Horas ausentes' })], 201, 2, 2));
  });
  const result = await loadOpportunityNotifications(undefined, new Date('2026-09-24T12:00:00Z'));
  assert.equal(requests.length, 2);
  // Horas ausentes não é oportunidade: lida na página 2, mas não vira aviso.
  assert.deepEqual(result.notifications.map((item) => [item.tipo, item.ocorrencias, item.colaboradores]),
    [['CHECKOUT_AUSENTE', 200, 200]]);
});

test('um aviso por regra e semana inclui todos os grupos devolvidos pela API', () => {
  const groups = [
    group('a', { quantidade: 3 }),
    group('b', { colaborador: 'OUTRA PESSOA', quantidade: 2, validacao: {
      resultado: 'confirmado', rotulo: 'Confirmado', motivo: null, jornada_origem: 'FALLBACK' } }),
    group('sem-prova', { colaborador: 'TERCEIRA', validacao: {
      resultado: 'indisponivel', rotulo: 'Indisponível', motivo: null, jornada_origem: 'INDISPONIVEL' } }),
    group('antigo', { colaborador: 'PESSOA ANTIGA', ultima_ocorrencia: '2026-09-20' }),
  ];
  groups.push(group('fora-da-central', { colaborador: 'QUARTA', tipo_problema: 'REGISTRO_DUPLICADO' }));
  const items = weeklyNotifications(groups, period);
  assert.equal(items.length, 2);
  const item = items.find((entry) => entry.tipo === 'CHECKOUT_AUSENTE')!;
  // Fallback = checkout esquecido comprovado: 3 + 2 + 1 (antigo); o grupo sem prova não conta.
  assert.deepEqual(item, { tipo: 'CHECKOUT_AUSENTE', titulo: 'Checkout não registrado', ocorrencias: 7,
    colaboradores: 4, fallback: 6, ultima_ocorrencia: '2026-09-23' });
  assert.equal(notificationMessage(item),
    'Identificadas 7 ocorrências CHECKOUT_AUSENTE. 6 com fallback de checkout (saída considerada pela jornada).');
  assert.equal(notificationMessage({ ...item, fallback: 1, ocorrencias: 25 }),
    'Identificadas 25 ocorrências CHECKOUT_AUSENTE. 1 com fallback de checkout (saída considerada pela jornada).');
  assert.equal(notificationMessage({ ...item, fallback: 0 }),
    'Identificadas 7 ocorrências CHECKOUT_AUSENTE. Nenhuma com fallback de checkout.');
  // Fora do checkout, fallback não se aplica: a frase não o menciona.
  assert.equal(notificationMessage({ ...item, tipo: 'HORAS_AUSENTES', fallback: 0 }),
    'Identificadas 7 ocorrências HORAS_AUSENTES.');
});

test('aviso volta a ser novo só quando a semana ganha ocorrências; outra semana é outro aviso', () => {
  const [item] = weeklyNotifications([group('a', { quantidade: 2 })], period);
  const seen = markNotificationsSeen({}, [item], period);
  assert.equal(isNewNotification(item, period, seen), false);
  assert.equal(isNewNotification({ ...item, ocorrencias: 3 }, period, seen), true);
  assert.equal(isNewNotification(item, { inicio: '2026-09-28', fim: '2026-10-03' }, seen), true);
});

test('leitura é local por usuário; estado corrompido não marca avisos como lidos', () => {
  assert.notEqual(notificationStorageKey('pessoa-a'), notificationStorageKey('pessoa-b'));
  const [item] = weeklyNotifications([group()], period);
  const seen = markNotificationsSeen({}, [item], period);
  assert.equal(isNewNotification(item, period, parseSeenOpportunities(JSON.stringify(seen))), false);
  for (const raw of [null, 'invalid', 'null', '[]', '{"bad":false}', '{"bad":true}', '{"bad":-1}'])
    assert.deepEqual(parseSeenOpportunities(raw), {});
});

test('abrir o aviso leva ao detalhamento semanal da Dashboard na regra do aviso', () => {
  const url = new URL(notificationDetailUrl(period, 'CHECKOUT_AUSENTE'), 'http://localhost');
  assert.equal(url.pathname, '/dashboard');
  assert.equal(url.searchParams.get('semana'), period.inicio);
  assert.equal(url.searchParams.get('detalhe'), 'CHECKOUT_AUSENTE');
  assert.equal(url.searchParams.get('monitor'), 'semana');
  assert.equal(new URL(notificationDetailUrl(period), 'http://localhost').searchParams.get('detalhe'), null);
});

test('API sem ocorrências gera lista vazia; falhas não viram contagem zero', async (t) => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(page([])));
  assert.deepEqual((await loadOpportunityNotifications(undefined, new Date('2026-09-24T12:00:00Z'))).notifications, []);
  fetch.mock.mockImplementation(async () => new Response('', { status: 503 }));
  await assert.rejects(loadOpportunityNotifications(undefined, new Date('2026-09-24T12:00:00Z')));
  fetch.mock.mockImplementation(async () => Response.json(page([group()], 2)));
  await assert.rejects(loadOpportunityNotifications(undefined, new Date('2026-09-24T12:00:00Z')), /dados mudaram/i);
});
