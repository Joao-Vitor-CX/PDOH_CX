import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  catalogKind,
  evidenceObject,
  evidenceText,
  groupPage,
  opportunityName,
} from '../src/lib/opportunity-presentation.ts';
import {
  opportunityService,
  mapLimited,
} from '../src/services/opportunity-service.ts';
import {
  apiRequest,
  pageSchema,
  ruleSchema,
  type Opportunity,
} from '../src/services/pdoh-api.ts';

test('vocabulário operacional aprovado', () => {
  assert.equal(
    opportunityName('PESQUISA_CAMPOS_NULOS'),
    'Dados obrigatórios incompletos',
  );
  assert.equal(
    opportunityName('CHECKOUT_AUSENTE'),
    'Ausência de registro de saída',
  );
  assert.equal(
    opportunityName('VALOR_SEM_PADRONIZACAO'),
    'Informação sem padronização',
  );
});
test('classificação explícita do catálogo, sem inferência por ação ou volume', () => {
  assert.equal(catalogKind({ classificacao: 'TELEMETRIA' }), 'informativo');
  assert.equal(catalogKind({ classificacao: 'OPORTUNIDADE' }), 'operacional');
  assert.equal(catalogKind({ classificacao: 'ALERTA' }), 'alerta');
  for (const rule of [
    null,
    { classificacao: null },
    { classificacao: 'NOVA_CLASSE' },
  ])
    assert.equal(catalogKind(rule), 'nao_classificado');
});
test('evidências preservam nulo, falso, zero e IDs textuais', () => {
  assert.equal(evidenceText(null), 'Nulo');
  assert.equal(evidenceText(undefined), 'Não informado');
  assert.equal(evidenceText(false), 'Não');
  assert.equal(evidenceText(0), '0');
  assert.equal(evidenceText('001234567890123456789'), '001234567890123456789');
  assert.deepEqual(evidenceObject('{"fallback_usado":false}'), {
    fallback_usado: false,
  });
  assert.deepEqual(evidenceObject('inválido'), {});
});
test('subgrupos contam registros da página, não ocorrências da evidência', () => {
  const items = [
    {
      marca: 'A',
      evidencia: { campo_esperado: 'hora_saida', ocorrencias: 200 },
    },
    { marca: 'B', evidencia: { campo_esperado: 'hora_saida' } },
  ] as Opportunity[];
  assert.equal(groupPage(items, 'campo')[0][1].length, 2);
  assert.equal(groupPage(items, 'marca').length, 2);
});
test('consultas limitadas a quatro simultâneas e ordem preservada', async () => {
  let active = 0;
  let peak = 0;
  const result = await mapLimited([0, 1, 2, 3, 4, 5, 6], async (value) => {
    active++;
    peak = Math.max(peak, active);
    await new Promise((resolve) => setTimeout(resolve, 2));
    active--;
    return value * 2;
  });
  assert.ok(peak <= 4);
  assert.deepEqual(result, [0, 2, 4, 6, 8, 10, 12]);
});
test('resumo separa vínculo operacional, telemetria e ausente com mesmo tipo', async () => {
  const original = globalThis.fetch;
  const base = {
    marca: null, titulo: null, severidade_padrao: null,
    tipo_problema: 'MESMO_TIPO',
    descricao_cenario: '',
    regra_identificacao: '',
    tratamento_esperado: '',
    permite_processamento: true,
    necessita_aprovacao: false,
    prioridade: 1,
    status_regra: 'ATIVA',
    criada_em: '',
    atualizada_em: '',
  };
  const rules = [
    { ...base, regra_id: 'op', classificacao: 'OPORTUNIDADE', acao_aplicacao: 'ALERTAR' },
    { ...base, regra_id: 'info', classificacao: 'TELEMETRIA', acao_aplicacao: 'TELEMETRIA' },
    { ...base, regra_id: 'unknown', classificacao: null, acao_aplicacao: 'IDENTIFICAR' },
  ];
  const calls: URL[] = [];
  globalThis.fetch = async (input) => {
    const url = new URL(String(input), 'http://localhost');
    calls.push(url);
    if (url.pathname.endsWith('/regras'))
      return Response.json({
        items: rules,
        total: 3,
        paginas: 1,
        pagina: 1,
        tamanho: 200,
      });
    const rule = url.searchParams.get('regra');
    const total =
      rule === 'op'
        ? url.searchParams.get('status')?.toUpperCase() === 'ABERTA'
          ? 2
          : 3
        : rule === 'info'
          ? 100
          : rule === 'unknown'
            ? 4
            : 109;
    return Response.json({
      items: [],
      total,
      paginas: total,
      pagina: 1,
      tamanho: 1,
    });
  };
  try {
    const summary = await opportunityService.summary({
      marca: 'A',
      execution_id: 'exact-id',
    });
    assert.equal(summary.operational, 3);
    assert.equal(summary.informative, 100);
    assert.equal(summary.unclassified, 6);
    assert.equal(summary.pending, 2);
    assert.equal(
      summary.total,
      summary.operational + summary.informative + summary.unclassified,
    );
    assert.ok(
      calls
        .filter((url) => url.pathname.endsWith('/oportunidades'))
        .every(
          (url) =>
            url.searchParams.get('marca') === 'A' &&
            url.searchParams.get('execution_id') === 'exact-id',
        ),
    );
    const filtered = await opportunityService.summary({ status: 'aberta' });
    assert.equal(filtered.pending, filtered.operational);
  } finally {
    globalThis.fetch = original;
  }
});
test('erros HTTP e de contrato não viram contagem zero', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response('', { status: 503 });
    await assert.rejects(() => opportunityService.summary({}), /indisponível/);
    globalThis.fetch = async () => Response.json({ items: 'invalido' });
    await assert.rejects(
      () => apiRequest('/regras', pageSchema(ruleSchema)),
      /contrato/,
    );
  } finally {
    globalThis.fetch = original;
  }
});
