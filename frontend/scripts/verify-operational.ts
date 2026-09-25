import assert from 'node:assert/strict';
import { opportunityService } from '../src/services/opportunity-service.ts';
const base = process.env.PDOH_FRONTEND_URL || 'http://127.0.0.1:5173';
const nativeFetch = globalThis.fetch;
globalThis.fetch = (input, options) =>
  nativeFetch(new URL(String(input), base), {
    ...options,
    signal: options?.signal || AbortSignal.timeout(30000),
  });
try {
  const summary = await opportunityService.summary({});
  const dashboard = await opportunityService.dashboard({});
  assert.equal(summary.total, dashboard.quantidade_oportunidades);
  assert.equal(
    summary.total,
    summary.operational + summary.alerts + summary.informative + summary.unclassified,
  );
  assert.ok(summary.pending <= summary.operational);
  assert.ok(
    summary.groups
      .filter((group) => group.kind === 'operacional')
      .every((group) => group.rule.classificacao === 'OPORTUNIDADE'),
  );
  const empty = await opportunityService.summary({
    tipo: 'TIPO_INEXISTENTE_TESTE',
  });
  assert.equal(empty.total, 0);
  assert.equal(empty.operational, 0);
  process.stdout.write(
    JSON.stringify(
      {
        status: 'ok',
        captured_at: new Date().toISOString(),
        operational: summary.operational,
        alerts: summary.alerts,
        informative: summary.informative,
        unclassified: summary.unclassified,
        pending: summary.pending,
        raw_total_for_reconciliation_only: summary.total,
        executions: dashboard.total_execucoes,
      },
      null,
      2,
    ) + '\n',
  );
} finally {
  globalThis.fetch = nativeFetch;
}
