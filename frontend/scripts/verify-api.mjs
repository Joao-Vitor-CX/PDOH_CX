import assert from 'node:assert/strict';

const baseUrl = process.env.PDOH_FRONTEND_URL || 'http://127.0.0.1:5173';
const url = (path) => `${baseUrl}/api/v1${path}`;

async function request(path) {
  const response = await fetch(url(path), { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(15000) });
  assert.equal(response.status, 200, `GET ${path}: HTTP ${response.status}`);
  return response.json();
}

function assertPage(page, label) {
  assert.ok(Array.isArray(page.items), `${label}: items deve ser lista`);
  for (const name of ['total', 'pagina', 'tamanho', 'paginas']) assert.ok(Number.isInteger(page[name]), `${label}: ${name} deve ser inteiro`);
  assert.ok(page.items.length <= page.tamanho, `${label}: página maior que o tamanho solicitado`);
}

const dashboardBefore = await request('/dashboard?tamanho=200');
const [executions, opportunities, rules, activeRules, mappings, entities] = await Promise.all([
  request('/execucoes?tamanho=2'), request('/oportunidades?tamanho=2'), request('/regras?tamanho=2'),
  request('/regras?status=ATIVA&tamanho=1'), request('/de-para?tamanho=2'), request('/entidades?tamanho=2'),
]);
for (const [label, page] of Object.entries({ executions, opportunities, rules, activeRules, mappings, entities })) assertPage(page, label);
const dashboardAfter = await request('/dashboard?tamanho=200');
if (dashboardBefore.total_execucoes === dashboardAfter.total_execucoes && dashboardBefore.quantidade_oportunidades === dashboardAfter.quantidade_oportunidades) {
  assert.equal(executions.total, dashboardAfter.total_execucoes, 'Execuções: dashboard x lista');
  assert.equal(opportunities.total, dashboardAfter.quantidade_oportunidades, 'Oportunidades: dashboard x lista');
} else {
  process.stdout.write('Aviso: contagens mudaram durante o teste; comparação entre consultas não atômicas ignorada.\n');
}

if (executions.items.length) {
  const execution = executions.items[0];
  const encoded = encodeURIComponent(execution.execution_id);
  const [detail, stages, sources, lineage] = await Promise.all([
    request(`/execucoes/${encoded}`), request(`/execucoes/${encoded}/etapas?tamanho=2`),
    request(`/execucoes/${encoded}/fontes?tamanho=2`), request(`/execucoes/${encoded}/linhagem?tamanho=2`),
  ]);
  assert.equal(detail.execution_id, execution.execution_id, 'ID de execução preservado');
  assert.equal(detail.status_execucao, execution.status_execucao, 'Status de execução preservado');
  assert.equal(detail.iniciado_em, execution.iniciado_em, 'Data de execução preservada');
  assert.equal(detail.quantidade_etapas, stages.total, 'Etapas: detalhe x página');
  assert.equal(detail.quantidade_fontes, sources.total, 'Fontes: detalhe x página');
  assert.equal(detail.quantidade_saidas, lineage.total, 'Linhagem: detalhe x página');
  for (const [label, page] of Object.entries({ stages, sources, lineage })) assertPage(page, label);
}

if (opportunities.items.length) {
  const opportunity = opportunities.items[0];
  const encoded = encodeURIComponent(opportunity.oportunidade_id);
  const [detail, history] = await Promise.all([
    request(`/oportunidades/${encoded}`), request(`/oportunidades/${encoded}/historico?tamanho=2`),
  ]);
  assert.equal(detail.oportunidade_id, opportunity.oportunidade_id, 'ID de oportunidade preservado');
  assert.equal(detail.execution_id, opportunity.execution_id, 'Vínculo de execução preservado');
  assert.equal(detail.status_oportunidade, opportunity.status_oportunidade, 'Status de oportunidade preservado');
  assertPage(history, 'opportunityHistory');
  const byType = await request(`/oportunidades?tipo=${encodeURIComponent(opportunity.tipo_problema)}&tamanho=2`);
  assert.ok(byType.items.every((item) => item.tipo_problema === opportunity.tipo_problema), 'Filtro tipo');
}

if (mappings.items.length) {
  const history = await request(`/de-para/${encodeURIComponent(mappings.items[0].de_para_id)}/historico?tamanho=2`);
  assertPage(history, 'mappingHistory');
}
if (entities.items.length) {
  const entity = await request(`/entidades/${encodeURIComponent(entities.items[0].identificador_id)}`);
  assert.equal(entity.identificador_id, entities.items[0].identificador_id, 'ID de entidade preservado');
}

const empty = await request('/oportunidades?tipo=TIPO_INEXISTENTE_TESTE&tamanho=2');
assert.equal(empty.total, 0, 'Filtro sem resultados');
const invalid = await fetch(url('/oportunidades?periodo_inicio=2026-09-10&periodo_fim=2026-09-01'), { signal: AbortSignal.timeout(15000) });
assert.equal(invalid.status, 422, 'Período inválido deve retornar HTTP 422');

process.stdout.write(JSON.stringify({
  status: 'ok', via: baseUrl, total_execucoes: executions.total, total_oportunidades: opportunities.total,
  total_regras: rules.total, regras_ativas: activeRules.total, total_de_para: mappings.total, total_entidades: entities.total,
}, null, 2) + '\n');
