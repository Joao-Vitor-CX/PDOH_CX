import assert from 'node:assert/strict';
import { loadPdohOverview } from '../src/services/findings-service.ts';
import { fixedWindow, loadGroups } from '../src/services/operational-api.ts';

// Somente GET pelo proxy local autenticado. Não conecta ao MySQL nem executa pipeline.
const base = process.env.PDOH_FRONTEND_URL || 'http://127.0.0.1:5173';
const originalFetch = globalThis.fetch;
const paths: string[] = [];
globalThis.fetch = (input, init) => {
  const url = new URL(String(input), base);
  assert.ok(url.pathname.startsWith('/api/v2/'));
  assert.ok(!init?.method || init.method === 'GET');
  paths.push(url.pathname);
  return originalFetch(url, init);
};
try {
  const data = await loadPdohOverview({});
  assert.equal(new Date(data.period.inicio + 'T12:00:00').getDay(), 1);
  assert.equal(new Date(data.period.fim + 'T12:00:00').getDay(), 6);
  const window = fixedWindow({}, data.period);
  const raw = await originalFetch(
    new URL(
      '/api/v2/oportunidades/resumo?' +
        new URLSearchParams({ ...window, status: 'ABERTA', tamanho: '200' }),
      base,
    ),
  ).then((response) => response.json());
  assert.equal(data.opportunities.cards, raw.total);
  assert.equal(
    data.opportunities.occurrences,
    data.groups.items.reduce((sum, group) => sum + group.quantidade, 0),
  );
  const first = await loadGroups(window, 1, 12);
  assert.deepEqual(
    first.items.map((item) => item.grupo_id),
    data.groups.items.slice(0, 12).map((item) => item.grupo_id),
  );
  if (first.paginas > 1) {
    const second = await loadGroups(window, 2, 12);
    assert.ok(
      second.items.every(
        (item) =>
          !first.items.some((other) => other.grupo_id === item.grupo_id),
      ),
    );
  }
  const example = data.groups.items[0];
  if (example) {
    const filtered = await loadGroups({
      ...window,
      marca: example.marca,
      colaborador: example.colaborador || undefined,
      tipo: example.tipo_problema,
      severidade: example.severidade,
      status: example.status_operacional,
    });
    assert.ok(
      filtered.items.some((item) => item.grupo_id === example.grupo_id),
    );
    assert.ok(
      filtered.items.every(
        (item) =>
          item.tipo_problema === example.tipo_problema &&
          item.severidade === example.severidade &&
          item.marca === example.marca,
      ),
    );
  }
  const empty = await loadGroups({
    ...window,
    colaborador: '__VALIDACAO_SEM_RESULTADO__',
  });
  assert.equal(empty.total, 0);
  const invalid = await originalFetch(
    new URL(
      '/api/v2/oportunidades/resumo?periodo=personalizado&periodo_inicio=2026-09-12&periodo_fim=2026-09-07',
      base,
    ),
  );
  assert.equal(invalid.status, 422);
  console.log(
    JSON.stringify(
      {
        periodo: data.period,
        cards_abertos: data.opportunities.cards,
        ocorrencias: data.opportunities.occurrences,
        severidade_predominante: data.opportunities.predominant,
        alertas: data.alerts,
        grupos_primeira_pagina: first.items.length,
        paginas: first.paginas,
        filtros_paginacao_vazio_datas_invalidas: 'aprovados',
        endpoints: [...new Set(paths)],
        somente_get_v2: true,
      },
      null,
      2,
    ),
  );
} finally {
  globalThis.fetch = originalFetch;
}
