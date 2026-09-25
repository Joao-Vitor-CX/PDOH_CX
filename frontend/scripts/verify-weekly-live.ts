import assert from 'node:assert/strict';
import { loadWeeklyMonitoring, loadOccurrences, occurrencesCsv } from '../src/services/weekly-monitoring.ts';
import { weeklyNotifications } from '../src/services/opportunity-notifications.ts';

const base = process.env.PDOH_FRONTEND_URL || 'http://127.0.0.1:5173';
const period = {
  inicio: process.env.PDOH_WEEK_START || '2026-08-31',
  fim: process.env.PDOH_WEEK_END || '2026-09-05',
};
const nativeFetch = globalThis.fetch;
globalThis.fetch = (input, init) => nativeFetch(new URL(String(input), base), init);

try {
  const data = await loadWeeklyMonitoring(period);
  assert.equal(data.groups.length, new Set(data.groups.map((group) => group.grupo_id)).size);
  assert.equal(data.cards.reduce((sum, card) => sum + card.ocorrencias, 0),
    data.groups.reduce((sum, group) => sum + group.quantidade, 0));
  const notices = weeklyNotifications(data.groups, period);
  assert.deepEqual(new Set(notices.map((item) => item.tipo)), new Set(data.cards.map((card) => card.tipo)));
  const rows = await loadOccurrences(data.groups, data.window);
  assert.equal(rows.length, new Set(rows.map((row) => `${row.grupo_id}|${row.oportunidade_id}`)).size);
  assert.equal(occurrencesCsv(rows).split('\r\n').length, rows.length + 1);
  console.log(JSON.stringify({ period, groups: data.groups.length, cards: data.cards.length,
    card_occurrences: data.cards.reduce((sum, card) => sum + card.ocorrencias, 0),
    notifications: notices.length, detail_rows: rows.length, alerts: data.alerts?.grupos ?? null,
    source: 'GET /api/v2/oportunidades/resumo, /detalhes, /alertas/resumo' }, null, 2));
} finally {
  globalThis.fetch = nativeFetch;
}
