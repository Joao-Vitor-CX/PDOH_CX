import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  loadPdohOverview,
  summarizeGroups,
} from '../src/services/findings-service.ts';
import {
  filtersFromSearch,
  groupSchema,
  loadAllGroups,
  loadGroups,
  resolvePeriod,
} from '../src/services/operational-api.ts';

const group = (id: string, count = 12) => ({
  grupo_id: id,
  marca: 'MARCA_TESTE',
  tipo_problema: 'TIPO_DA_API',
  titulo: 'Título entregue pela API',
  colaborador: 'Colaborador de teste',
  quantidade: count,
  registros_historicos: count * 8,
  dias_afetados: 2,
  primeira_ocorrencia: '2026-08-31',
  ultima_ocorrencia: '2026-09-12',
  severidade: 'ALTA',
  impacto: null,
  status_operacional: 'ABERTA',
  responsavel: null,
});
const page = (
  items: unknown[],
  total = items.length,
  pagina = 1,
  paginas = 1,
) => ({ items, total, pagina, paginas, tamanho: 200 });
const finding = (classification: string) => ({
  id: classification,
  origem_registro: 'OPORTUNIDADE_LEGADO',
  classificacao: classification,
  tipo_problema: 'MESMO_TIPO',
  marca: 'MARCA_TESTE',
  descricao: 'Registro de teste',
  registrado_em: '2026-09-12T10:00:00',
  severidade: 'ALTA',
  colaborador: null,
  campo: null,
  tratativa: null,
});
const period = { inicio: '2026-09-07', fim: '2026-09-12' };
const officialUnavailable = {
  disponivel: false,
  motivo: 'Sem consolidacao oficial',
  percentual: null,
  variacao_periodo_anterior: null,
  periodo: period,
};
const alertSummary = (count = 0) => ({
  total: count,
  resumo: {
    periodo: period,
    grupos: count,
    alertas: count,
    ocorrencias_acumuladas: count,
    colaboradores_afetados: count,
    por_regra: count
      ? [
          {
            tipo_problema: 'MESMO_TIPO',
            titulo: 'Titulo cadastrado',
            grupos: count,
            alertas: count,
            ocorrencias_acumuladas: count,
            colaboradores_afetados: count,
            severidade: 'ALTA',
          },
        ]
      : [],
  },
});

test('contagens usam quantidade consolidada, nunca registros históricos; não atribui severidade desconhecida', () => {
  const result = summarizeGroups([
    group('a'),
    { ...group('b', 8), severidade: 'NOVA_SEVERIDADE' },
  ]);
  assert.equal(result.cards, 2);
  assert.equal(result.occurrences, 20);
  assert.deepEqual(result.predominant, ['ALTA', 'NOVA_SEVERIDADE']);
});
test('todos os filtros e a página são enviados à API; ordem e datas retornadas são preservadas', async (t) => {
  let request: URL | undefined;
  const serverOrder = [group('primeiro', 1), group('segundo', 99)];
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    request = new URL(input, 'http://localhost');
    return Response.json(page(serverOrder, 2, 3));
  });
  const filters = {
    marca: 'A',
    colaborador: 'João',
    regra: 'regra-id',
    tipo: 'TIPO',
    severidade: 'ALTA',
    status: 'REABERTA',
    periodo: 'personalizado' as const,
    periodo_inicio: '2026-09-07',
    periodo_fim: '2026-09-12',
  };
  const result = await loadGroups(filters, 3);
  assert.equal(request?.pathname, '/api/v2/oportunidades/resumo');
  for (const [key, value] of Object.entries(filters))
    assert.equal(request?.searchParams.get(key), value);
  assert.equal(request?.searchParams.get('pagina'), '3');
  assert.deepEqual(
    result.items.map((item) => item.grupo_id),
    ['primeiro', 'segundo'],
  );
  assert.equal(result.items[0].primeira_ocorrencia, '2026-08-31');
});
test('dashboard usa exclusivamente grupos v2, toda a fila ativa e a mesma janela resolvida pelo servidor', async (t) => {
  const calls: URL[] = [];
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    const url = new URL(input, 'http://localhost');
    calls.push(url);
    if (url.pathname.endsWith('/findings/resumo'))
      return Response.json({
        periodo: { inicio: '2026-09-07', fim: '2026-09-12' },
      });
    if (url.pathname.endsWith('/oportunidades/resumo'))
      return Response.json(page([group('a'), group('b', 8)]));
    if (url.pathname.endsWith('/alertas/resumo'))
      return Response.json(alertSummary(1));
    if (url.pathname.endsWith('/pdoh/resumo'))
      return Response.json(officialUnavailable);
    return Response.json(page([finding('TELEMETRIA')]));
  });
  const data = await loadPdohOverview({ marca: 'A' });
  assert.equal(data.opportunities.cards, 2);
  assert.equal(data.opportunities.occurrences, 20);
  assert.equal(data.alerts.total, 1);
  // Telemetria é auditoria técnica: o dashboard do líder não a consulta.
  assert.ok(calls.every((url) => !url.pathname.endsWith('/telemetria')));
  assert.ok(calls.every((url) => url.pathname.startsWith('/api/v2/')));
  for (const url of calls.slice(1)) {
    assert.equal(url.searchParams.get('periodo_inicio'), '2026-09-07');
    assert.equal(url.searchParams.get('periodo_fim'), '2026-09-12');
  }
  assert.equal(
    calls
      .find((url) => url.pathname.endsWith('/oportunidades/resumo'))
      ?.searchParams.get('status'),
    null,
  );
});
test('o resultado oficial do PDOH sobrevive à falha de impactadores e alertas', async (t) => {
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    const url = new URL(input, 'http://localhost');
    if (url.pathname.endsWith('/pdoh/resumo')) return Response.json(officialUnavailable);
    return new Response('', { status: 503 });
  });
  const data = await loadPdohOverview({ marca: 'A' });
  assert.ok(data.pdoh, 'o indicador oficial permanece');
  assert.equal(data.impactos, null);
  assert.equal(data.opportunities, null);
  assert.equal(data.alerts, null);
});
test('a falha do próprio PDOH continua sendo falha (nunca vira dashboard vazio)', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 503 }));
  await assert.rejects(loadPdohOverview({ marca: 'A' }), /indisponível/i);
});
test('paginação completa antes de totalizar; alteração de volume e grupos duplicados falham explicitamente', async (t) => {
  let changed = false;
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    const second =
      new URL(input, 'http://localhost').searchParams.get('pagina') === '2';
    return Response.json(
      page([group(second && !changed ? 'b' : 'a')], 2, second ? 2 : 1, 2),
    );
  });
  assert.deepEqual(
    (await loadAllGroups({})).items.map((item) => item.grupo_id),
    ['a', 'b'],
  );
  changed = true;
  await assert.rejects(loadAllGroups({}), /mudaram/);
});
test('falha HTTP ou contrato cruzado não vira indicador zero', async (t) => {
  const mocked = t.mock.method(
    globalThis,
    'fetch',
    async () => new Response('', { status: 503 }),
  );
  await assert.rejects(loadGroups({}), /indisponível/);
  mocked.mock.mockImplementation(async (input: string) => {
    const path = new URL(input, 'http://localhost').pathname;
    if (path.endsWith('/findings/resumo'))
      return Response.json({
        periodo: { inicio: '2026-09-07', fim: '2026-09-12' },
      });
    if (path.endsWith('/oportunidades/resumo')) return Response.json(page([]));
    return Response.json(page([finding('OPORTUNIDADE')]));
  });
  await assert.rejects(loadPdohOverview({}), /contrato da API v2/);
});
test('ação recomendada é opcional e somente aparece quando fornecida', () => {
  assert.equal(groupSchema.parse(group('a')).acao_recomendada, undefined);
  assert.equal(
    groupSchema.parse({ ...group('a'), acao_recomendada: 'Ação da API' })
      .acao_recomendada,
    'Ação da API',
  );
});
test('links com datas usam período personalizado; sem escolha a API recebe o modo automático', async (t) => {
  assert.equal(
    filtersFromSearch(
      new URLSearchParams('periodo_inicio=2026-09-01&periodo_fim=2026-09-12'),
    ).periodo,
    'personalizado',
  );
  let mode = '';
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    mode = new URL(input, 'http://localhost').searchParams.get('periodo') || '';
    return Response.json({
      periodo: { inicio: '2026-09-07', fim: '2026-09-12' },
    });
  });
  assert.deepEqual(await resolvePeriod({}), {
    inicio: '2026-09-07',
    fim: '2026-09-12',
  });
  // O padrão é o período mais recente com dados; a escolha explícita 'semana' continua
  // sendo enviada como tal (coberto em 'sem período escolhido...').
  assert.equal(mode, 'automatico');
});

test('PDOH sem fonte oficial fica indisponível e nunca é derivado das oportunidades', async (t) => {
  const {
    pdohIndicatorState,
    pdohSummarySchema,
    PDOH_UNAVAILABLE_MESSAGE,
    PDOH_SUMMARY_PATH,
  } = await import('../src/services/pdoh-indicator.ts');
  const semDados = pdohSummarySchema.parse({
    ...officialUnavailable,
    indicadores: null,
    evolucao: null,
  });
  assert.equal(semDados.indicadores, null);
  assert.equal(semDados.evolucao, null);
  const state = pdohIndicatorState(null);
  // Sem resposta alguma não há como afirmar a causa: fica "aguardando", sem intervalo.
  assert.deepEqual(state, {
    status: 'indisponivel',
    message: PDOH_UNAVAILABLE_MESSAGE,
    motivo: 'aguardando',
    disponivel: null,
  });
  assert.equal(
    PDOH_UNAVAILABLE_MESSAGE,
    'Dados de PDOH indisponíveis para o período selecionado',
  );
  assert.equal(PDOH_SUMMARY_PATH, '/pdoh/resumo');

  // Mesmo com cards e ocorrências, o painel respeita a indisponibilidade oficial.
  const paths: string[] = [];
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    const url = new URL(input, 'http://localhost');
    paths.push(url.pathname);
    if (url.pathname.endsWith('/findings/resumo'))
      return Response.json({
        periodo: { inicio: '2026-09-07', fim: '2026-09-12' },
      });
    if (url.pathname.endsWith('/oportunidades/resumo'))
      return Response.json({
        items: [group('g1', 40)],
        total: 1,
        pagina: 1,
        tamanho: 200,
        paginas: 1,
      });
    if (url.pathname.endsWith('/alertas/resumo'))
      return Response.json(alertSummary());
    if (url.pathname.endsWith('/pdoh/resumo'))
      return Response.json(officialUnavailable);
    return Response.json({
      items: [],
      total: 0,
      pagina: 1,
      tamanho: 200,
      paginas: 0,
    });
  });
  const overview = await loadPdohOverview({});
  assert.equal(overview.pdoh.disponivel, false);
  assert.equal(overview.opportunities.occurrences, 40);
  assert.ok(paths.some((path) => path.includes('/pdoh/')));
});

test('PDOH com resumo oficial exibe exatamente o percentual e a variação do backend', async () => {
  const { pdohIndicatorState } =
    await import('../src/services/pdoh-indicator.ts');
  assert.deepEqual(
    pdohIndicatorState({
      disponivel: true,
      motivo: null,
      percentual: 93.5,
      variacao_periodo_anterior: 2.1,
      periodo: { inicio: '2026-09-07', fim: '2026-09-12' },
    }),
    { status: 'disponivel', percentual: 93.5, variacao: 2.1 },
  );
  assert.deepEqual(
    pdohIndicatorState({
      disponivel: true,
      motivo: null,
      percentual: 88,
      variacao_periodo_anterior: null,
      periodo: { inicio: '2026-09-07', fim: '2026-09-12' },
    }),
    { status: 'disponivel', percentual: 88, variacao: null },
  );
});

test('visão geral soma por regra e por colaborador sem inventar pessoa nem reordenar por nome', async () => {
  const { impactosPorColaborador, impactosPorRegra } =
    await import('../src/services/findings-service.ts');
  const groups = [
    {
      ...group('a', 6),
      colaborador: 'ANA',
      tipo_problema: 'SEM_CHECKOUT',
      titulo: 'Checkout',
    },
    {
      ...group('b', 2),
      colaborador: 'ANA',
      tipo_problema: 'HORARIO',
      titulo: 'Horário',
      severidade: 'MEDIA',
    },
    {
      ...group('c', 9),
      colaborador: 'BRUNO',
      tipo_problema: 'SEM_CHECKOUT',
      titulo: 'Checkout',
    },
    {
      ...group('d', 4),
      colaborador: null,
      tipo_problema: 'SEM_CHECKOUT',
      titulo: 'Checkout',
    },
  ];

  const porRegra = impactosPorRegra(groups);
  assert.deepEqual(
    porRegra.map((regra) => [
      regra.tipo,
      regra.ocorrencias,
      regra.colaboradores,
      regra.grupos,
    ]),
    [
      ['SEM_CHECKOUT', 19, 2, 3],
      ['HORARIO', 2, 1, 1],
    ],
  );

  const porPessoa = impactosPorColaborador(groups);
  assert.deepEqual(
    porPessoa.map((pessoa) => [
      pessoa.colaborador,
      pessoa.ocorrencias,
      pessoa.causas,
    ]),
    [
      ['BRUNO', 9, 1],
      ['ANA', 8, 2],
    ],
  );
  // A severidade exibida é a do primeiro grupo da pessoa, na ordem entregue pela API.
  assert.equal(porPessoa[1].severidade, 'ALTA');
  assert.equal(porPessoa[1].principal, 'Checkout');
});

test('modal consome a API de evidências e nunca trata indisponível como aprovado', async (t) => {
  const { loadGroupEvidence } =
    await import('../src/services/operational-api.ts');
  const corpo = {
    oportunidade: {
      grupo_id: 'g1',
      regra: 'CHECKOUT_AUSENTE',
      titulo: 'Checkout não registrado',
      impacto: 'Tempo em loja',
      colaborador: 'ANA',
      campo: 'hora_saida',
      origem: 'relatorio_checkin_bracell',
      quantidade: 6,
      status_operacional: 'ABERTA',
      periodo: { inicio: '2026-08-31', fim: '2026-09-05' },
    },
    validacao: {
      resultado: 'indisponivel',
      rotulo: 'Evidência indisponível',
      motivo: 'Registro identificado antes da camada de comprovação.',
      jornada_origem: 'INDISPONIVEL',
      justificativa: null,
      atestado: null,
      ocorrencias_comprovadas: 0,
      ocorrencias_avaliadas: 6,
    },
    fonte: {
      papel: 'checkin',
      tabela: 'relatorio_checkin_bracell',
      campo: 'hora_saida',
      valor_esperado: 'Check-out real apos a entrada registrada',
      criterios: [
        'colaborador_vigente',
        'dia_trabalhado',
        'houve_entrada',
        'sem_abono',
      ],
    },
    evidencias: [
      {
        fonte: 'relatorio_checkin_bracell',
        campo: 'hora_saida',
        valor_encontrado: null,
        valor_esperado: 'Check-out real',
        validacao: 'houve_entrada',
        atendido: null,
      },
    ],
    tratamento: {
      acao_recomendada: 'Validar a saída com o colaborador',
      responsavel: 'Líder',
    },
    ocorrencias: [
      {
        regra: 'CHECKOUT_AUSENTE',
        colaborador: 'ANA',
        data: '2026-09-05',
        resultado_validacao: 'indisponivel',
        fonte: 'relatorio_checkin_bracell',
        campo: 'hora_saida',
        valor_esperado: null,
        valor_encontrado: null,
        motivo: 'Sem comprovação.',
        impacto: 'Tempo em loja',
        tratativa: 'Validar',
        jornada_origem: 'INDISPONIVEL',
      },
    ],
  };
  let caminho = '';
  t.mock.method(globalThis, 'fetch', async (input: string) => {
    caminho = input;
    return Response.json(corpo);
  });
  const resultado = await loadGroupEvidence('g1', { marca: 'BRACELL' });
  assert.ok(caminho.includes('/oportunidades/g1/evidencias'));
  assert.equal(resultado.validacao.resultado, 'indisponivel');
  assert.equal(resultado.validacao.ocorrencias_comprovadas, 0);
  // Critério não verificável chega como null — nunca como false nem true.
  assert.equal(resultado.evidencias[0].atendido, null);
  assert.equal(
    resultado.tratamento.acao_recomendada,
    'Validar a saída com o colaborador',
  );
});

test('resultado de validação fora do contrato é erro, não vira "confirmado"', async () => {
  const { groupEvidenceSchema } =
    await import('../src/services/operational-api.ts');
  const invalido = {
    resultado: 'ok',
    rotulo: 'x',
    motivo: null,
    jornada_origem: 'INVOLVES',
    justificativa: null,
    atestado: null,
    ocorrencias_comprovadas: 0,
    ocorrencias_avaliadas: 0,
  };
  assert.equal(
    groupEvidenceSchema.safeParse({ validacao: invalido }).success,
    false,
  );
});

test('a curva do PDOH aceita apenas a série oficial, em qualquer granularidade', async () => {
  const { pdohTrendSchema } = await import('../src/services/pdoh-indicator.ts');
  const oficial = pdohTrendSchema.parse({
    marca: 'BRACELL',
    periodo: { inicio: '2026-08-31', fim: '2026-09-05' },
    granularidade: 'semana',
    disponivel: true,
    motivo: null,
    fonte: 'PLATINA',
    pontos: [
      {
        periodo: '2026-08-31',
        inicio: '2026-08-31',
        fim: '2026-09-05',
        pdoh: 72.83,
      },
    ],
  });
  assert.equal(oficial.pontos[0].pdoh, 72.83);
  // Indisponível chega com pontos vazios e motivo; a tela não inventa curva.
  const vazio = pdohTrendSchema.parse({
    marca: 'BRACELL',
    periodo: { inicio: '2026-08-31', fim: '2026-09-05' },
    granularidade: 'dia',
    disponivel: false,
    motivo: 'Sem registros oficiais.',
    pontos: [],
  });
  assert.equal(vazio.pontos.length, 0);
  assert.equal(vazio.motivo, 'Sem registros oficiais.');
  assert.equal(
    pdohTrendSchema.safeParse({ granularidade: 'trimestre' }).success,
    false,
  );
});

test('card operacional expõe a validação da origem sem exigir dado técnico', async () => {
  const { groupSchema } = await import('../src/services/operational-api.ts');
  const card = groupSchema.parse({
    grupo_id: 'g1',
    marca: 'BRACELL',
    tipo_problema: 'CHECKOUT_AUSENTE',
    titulo: 'Checkout',
    colaborador: 'ANA',
    campo: 'hora_saida',
    origem: 'relatorio_checkin_bracell',
    quantidade: 6,
    registros_historicos: 6,
    dias_afetados: 6,
    primeira_ocorrencia: '2026-08-31',
    ultima_ocorrencia: '2026-09-05',
    severidade: 'MEDIA',
    impacto: 'Tempo em loja',
    status_operacional: 'ABERTA',
    responsavel: null,
    evidencia: {
      campo: 'hora_saida',
      valor_esperado: 'check-out real',
      valor_encontrado: '(ausente)',
      fonte: 'relatorio_checkin_bracell',
    },
    validacao: {
      resultado: 'confirmado',
      rotulo: 'Confirmado na fonte oficial',
      motivo: null,
      jornada_origem: 'INVOLVES',
    },
  });
  assert.equal(card.validacao?.resultado, 'confirmado');
  assert.equal(card.evidencia?.fonte, 'relatorio_checkin_bracell');
  // Card antigo, sem os blocos novos, continua válido: o contrato é aditivo.
  const semProva = groupSchema.parse({
    ...card,
    evidencia: undefined,
    validacao: undefined,
  });
  assert.equal(semProva.validacao, undefined);
});

test('contrato PDOH preserva o detalhamento diário e as opções de filtro entregues pela API', async () => {
  const { pdohSummarySchema } =
    await import('../src/services/pdoh-indicator.ts');
  const resumo = pdohSummarySchema.parse({
    disponivel: true,
    motivo: null,
    percentual: 75,
    variacao_periodo_anterior: null,
    periodo: { inicio: '2026-08-31', fim: '2026-09-05' },
    detalhes: {
      total: 1,
      pagina: 1,
      tamanho: 50,
      paginas: 1,
      items: [
        {
          colaborador: 'ANA',
          estado: 'SP',
          data: '2026-08-31',
          nome_do_dia: 'SEGUNDA',
          deslocamento: '00:30:00',
          ocio: '00:15:00',
          produtividade: '03:00:00',
          horas_nao_registradas: '00:15:00',
          horas_programadas: '04:00:00',
          primeiro_checkin: '08:00:00',
          ultimo_checkout: '12:00:00',
          visitas: 2,
          visitas_realizadas: 2,
          pesquisas: 10,
          pesquisas_realizadas: 5,
          percentuais: {
            produtividade: 0.75,
            visitas: 1,
            pesquisas: 0.5,
            efetividade: 0.65,
          },
          jornada: {
            fonte: 'colaboradores_ativos_bracell',
            horario_aplicado: '04:00:00',
            houve_fallback: true,
            origem_fallback: 'JORNADA_PADRAO_44H',
          },
          origem_dado:
            'produtos_platina.exclusivo_bracell_platina_relatorio_pdoh',
        },
      ],
    },
    filtros_disponiveis: { colaboradores: ['ANA'], estados: ['SP'] },
  });
  assert.equal(resumo.detalhes.items[0].percentuais.produtividade, 0.75);
  assert.equal(
    resumo.detalhes.items[0].jornada.origem_fallback,
    'JORNADA_PADRAO_44H',
  );
  assert.deepEqual(resumo.filtros_disponiveis.estados, ['SP']);
});

test('governança permanece somente leitura e não ativa oportunidade nas regras cadastradas', async () => {
  const { operationGovernanceSchema } =
    await import('../src/services/governance-api.ts');
  const config = operationGovernanceSchema.parse({
    marca: 'BRACELL',
    operacao: 'EXCLUSIVA',
    descricao: 'Piloto',
    somente_leitura: true,
    jornada: [],
    fallback: [],
    atualizado_em: '2026-09-21T10:00:00',
    regras_governanca: [
      {
        configuracao_id: 'cfg',
        nome_regra: 'Entrada não registrada',
        codigo_interno: 'CHECKIN_ENTRADA_AUSENTE',
        categoria: 'Jornada',
        status: 'EM_VALIDACAO',
        prioridade: 1,
        descricao: 'Entrada ausente',
        comportamento_esperado: 'Comprovar contexto',
        regra_catalogo_id: null,
        geracao_automatica_ativa: false,
        atualizado_em: '2026-09-21T10:00:00',
        condicoes: [
          {
            tipo: 'CONDICAO',
            ordem: 1,
            papel_fonte: 'checkin',
            campo_logico: 'hora_entrada',
            operador: 'IS NULL',
            valor_esperado: null,
            descricao: 'Entrada ausente',
            status: 'ATIVA',
          },
        ],
        excecoes: [],
        tratativas: [
          {
            resultado: 'CONFIRMADO',
            acao_recomendada: 'Validar na origem',
            destino: 'OPORTUNIDADE_FUTURA',
            gera_oportunidade: false,
            status: 'ATIVO',
          },
        ],
      },
    ],
    fontes_semanticas: [
      {
        papel: 'checkin',
        tipo: 'PRINCIPAL',
        prioridade: 1,
        schema_fisico: 'involves_bracell',
        tabela_fisica: 'relatorio_checkin_bracell',
        mapeamento_campos: { hora_entrada: 'hora_entrada' },
        status: 'MAPEADA',
        descricao: null,
      },
    ],
    prioridade_jornada: [
      {
        prioridade: 1,
        origem_codigo: 'INVOLVES',
        papel_fonte: 'jornada',
        fallback: false,
        status: 'EM_VALIDACAO',
        aplicado_no_processamento: false,
        descricao: 'Origem atual',
      },
    ],
    historico_governanca: [],
  });
  assert.equal(config.somente_leitura, true);
  assert.equal(config.regras_governanca[0].geracao_automatica_ativa, false);
  assert.equal(
    config.regras_governanca[0].tratativas[0].gera_oportunidade,
    false,
  );
  assert.equal(config.fontes_semanticas[0].papel, 'checkin');
});

test('sem período escolhido o painel pede o período mais recente com dados', async () => {
  const { filtersFromSearch, periodFilters } = await import('../src/services/operational-api.ts');
  assert.equal(filtersFromSearch(new URLSearchParams('')).periodo, 'automatico');
  assert.equal(periodFilters({}).periodo, 'automatico');
  // Escolha explícita nunca é substituída, nem quando o período está vazio.
  assert.equal(filtersFromSearch(new URLSearchParams('periodo=semana')).periodo, 'semana');
  assert.equal(
    filtersFromSearch(new URLSearchParams('periodo_inicio=2026-08-31&periodo_fim=2026-09-05')).periodo,
    'personalizado',
  );
});

test('a tela distingue período sem registros, fonte indisponível e contrato pendente', async () => {
  const { pdohIndicatorState, rotuloIndicadorVazio, pdohSummarySchema } = await import(
    '../src/services/pdoh-indicator.ts'
  );
  const base = {
    disponivel: false, motivo: 'Não há registros oficiais do PDOH no período selecionado.',
    percentual: null, variacao_periodo_anterior: null,
    periodo: { inicio: '2026-09-14', fim: '2026-09-19' },
  };
  const semPeriodo = pdohIndicatorState(pdohSummarySchema.parse({
    ...base,
    cobertura: { tabela: 'produtos_platina.x', acessivel: true, registros_no_periodo: 0,
      colaboradores_no_periodo: 0, dias_no_periodo: 0, indicadores_disponiveis: [],
      disponivel_de: '2026-08-31', disponivel_ate: '2026-09-05' },
  }));
  assert.equal(semPeriodo.status, 'indisponivel');
  if (semPeriodo.status !== 'indisponivel') return;
  assert.equal(semPeriodo.motivo, 'sem_periodo');
  assert.deepEqual(semPeriodo.disponivel, { de: '2026-08-31', ate: '2026-09-05' });
  assert.equal(rotuloIndicadorVazio(semPeriodo), 'Sem registros no período');

  const semFonte = pdohIndicatorState(pdohSummarySchema.parse({
    ...base, motivo: 'Não há fonte oficial do PDOH acessível para esta marca.',
    cobertura: { tabela: null, acessivel: false, registros_no_periodo: 0,
      colaboradores_no_periodo: 0, dias_no_periodo: 0, indicadores_disponiveis: [] },
  }));
  if (semFonte.status !== 'indisponivel') throw new Error('esperado indisponível');
  assert.equal(semFonte.motivo, 'sem_fonte');
  assert.equal(semFonte.disponivel, null);
  assert.equal(rotuloIndicadorVazio(semFonte), 'Fonte oficial indisponível');

  // Sem o bloco de cobertura (contrato antigo) volta ao rótulo histórico, sem inventar causa.
  const antigo = pdohIndicatorState(pdohSummarySchema.parse(base));
  if (antigo.status !== 'indisponivel') throw new Error('esperado indisponível');
  assert.equal(antigo.motivo, 'aguardando');
  assert.equal(rotuloIndicadorVazio(antigo), 'Aguardando fonte oficial');
  assert.equal(pdohSummarySchema.parse(base).periodo_automatico, false);
});
