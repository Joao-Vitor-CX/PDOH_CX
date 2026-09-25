import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { AlertGroup, OperationalGroup } from '../src/services/operational-api.ts';
import {
  alertDetails, alertSubject, loadOpportunityTrace, originLabel, journeyOriginLabel, scenario, traceOccurrence, type AlertRecord,
} from '../src/services/operational-trace.ts';

const alertGroup = (overrides: Partial<AlertGroup> = {}): AlertGroup => ({
  grupo_id: 'g', marca: 'BRACELL', tipo_problema: 'VALOR_SEM_PADRONIZACAO', titulo: 'Valor sem padronização',
  colaborador: null, campo: 'jornada_trabalho', origem: 'colaboradores_ativos_bracell', quantidade_alertas: 2,
  ocorrencias_acumuladas: 2, registros_historicos: 4, dias_afetados: 0, primeira_ocorrencia: null,
  ultima_ocorrencia: null, severidade: 'MEDIA', impacto: null, acao_recomendada: 'Cadastrar a correspondência no De/Para.',
  ...overrides,
});
const alert = (id: string, overrides: Partial<AlertRecord> = {}): AlertRecord => ({
  id, execution_id: 'E1', tipo_problema: 'VALOR_SEM_PADRONIZACAO', colaborador: null, colaborador_id_interno: null,
  campo: 'jornada_trabalho', descricao: 'Valor sem padronizacao cadastrada no De/Para (processo JORNADA, campo jornada_trabalho).',
  tratativa: null, evidencia: { processo: 'JORNADA', campo_origem: 'jornada_trabalho', valor_origem: 'CX - 44H' },
  registrado_em: '2026-09-23T11:37:30', ...overrides,
});

test('alerta de valor: um registro por valor distinto, regravações contam uma vez, sem inventar colaborador', () => {
  const detalhes = alertDetails(alertGroup(), [
    alert('a'),
    alert('b', { execution_id: 'E0', registrado_em: '2026-09-16T11:00:00' }),                       // mesma pendência, antiga
    alert('c', { evidencia: { processo: 'JORNADA', campo_origem: 'jornada_trabalho', valor_origem: 'CX - 24H' } }),
    alert('d', { campo: 'perfil_acesso', evidencia: { processo: 'PERFIL', campo_origem: 'perfil_acesso', valor_origem: 'X' } }),
  ]);
  assert.deepEqual(detalhes.map((d) => [d.valor_encontrado, d.execucao]), [['CX - 24H', 'E1'], ['CX - 44H', 'E1']]);
  assert.equal(detalhes[0].colaborador, null);
  assert.equal(detalhes[0].campo, 'jornada_trabalho');
  assert.deepEqual(detalhes[0].complementos, [{ rotulo: 'Processo De/Para', valor: 'JORNADA' }]);
  assert.match(alertSubject(alertGroup()), /não identifica colaboradores/);
});

test('alerta de pessoa: colaborador e identificadores; registro de outro colaborador (validação) fica fora', () => {
  const grupo = alertGroup({ tipo_problema: 'IDENTIFICACAO_AMBIGUA', colaborador: 'LUCIANE CUNHA VEIGA', campo: null });
  const detalhes = alertDetails(grupo, [
    alert('a', { tipo_problema: 'IDENTIFICACAO_AMBIGUA', colaborador: 'LUCIANE CUNHA VEIGA', campo: null,
      evidencia: { nome_normalizado: 'LUCIANE CUNHA VEIGA', usuarios_normalizados: ['02958986314', '06627095351'] } }),
    alert('b', { tipo_problema: 'IDENTIFICACAO_AMBIGUA', colaborador: 'JOAO', campo: null,
      evidencia: { nome_normalizado: 'JOAO', usuarios_normalizados: ['U.TESTE'] } }),
  ]);
  assert.equal(detalhes.length, 1);
  assert.equal(detalhes[0].colaborador, 'LUCIANE CUNHA VEIGA');
  assert.deepEqual(detalhes[0].identificadores, ['02958986314', '06627095351']);
  assert.equal(alertSubject(grupo), 'LUCIANE CUNHA VEIGA');
  const vazio = alertDetails(alertGroup({ tipo_problema: 'CAMPO_OBRIGATORIO_VAZIO', colaborador: 'ANA', campo: 'hora_entrada' }), [
    alert('x', { tipo_problema: 'CAMPO_OBRIGATORIO_VAZIO', colaborador: 'ANA', campo: null,
      evidencia: { campo: 'hora_entrada', valor: null, dataframe: 'checkin', indice_origem: '1' } })]);
  assert.equal(vazio[0].valor_encontrado, 'Vazio');
  assert.deepEqual(vazio[0].complementos, []);           // chaves técnicas nunca aparecem
  assert.equal(originLabel('colaboradores_ativos_bracell'), 'Cadastro de colaboradores ativos (Involves)');
});

const base = { data_referencia: '2026-09-02', identificada_em: '2026-09-24T10:55:43', execution_id: 'EX', repeticoes: 1 };

test('checkout por fallback: jornada, origem, motivo e horário vêm da prova', () => {
  const trace = traceOccurrence({ ...base, evidencia: { fallback_usado: true, comprovacao: {
    resultado: 'confirmado', fonte: 'Involves', fonte_tabela: 'status_day_operacao_bracell', jornada_origem: 'FALLBACK',
    motivo_fallback: 'Jornada não encontrada no cadastro de origem; aplicada a jornada padrão 44H.',
    configuracao_operacional: { jornada: 44, hora_entrada_padrao: '08:00:00', hora_saida_padrao: '19:00:00', origem: 'FALLBACK' },
    monitoramento: { hora_entrada: '08:03:00', hora_saida: null } } } }, null);
  assert.deepEqual([trace.jornada, trace.jornada_origem, trace.fallback, trace.referencia_jornada], ['44H', 'FALLBACK', true, 'prova']);
  assert.match(trace.motivo ?? '', /padrão 44H/);
  assert.equal(trace.cenario, 'Entrada registrada às 08:03 e nenhum checkout até a saída esperada das 19:00.');
  assert.equal(trace.fonte_evidencia, 'Involves · Status do dia da operação (Involves)');
});

test('prova sem horas usa a resolução oficial da data, sinalizada; sem nada, não inventa jornada', () => {
  const evidencia = { comprovacao: { resultado: 'confirmado', fonte: 'PDOH Platina', jornada_origem: 'INVOLVES',
    esperado: 'Horas não registradas maior que 00:00', encontrado: '00:39:02' } };
  const resolucao = { fonte: 'Cadastro Involves (colaboradores_ativos_bracell.nome_pai)', horario_aplicado: '08:00:00',
    houve_fallback: false, origem_fallback: null, jornada_aplicada: '44H', origem: 'INVOLVES', motivo: null,
    status_resolucao: 'RESOLVIDA', data_resolucao: '2026-09-02', fallback_processador_pdoh: null };
  const comResolucao = traceOccurrence({ ...base, evidencia }, resolucao);
  assert.deepEqual([comResolucao.jornada, comResolucao.fallback, comResolucao.referencia_jornada, comResolucao.motivo],
    ['44H', false, 'resolucao_da_data', 'Jornada encontrada no cadastro.']);
  assert.equal(comResolucao.cenario, 'Horas não registradas maior que 00:00 — encontrado 00:39:02.');
  // Jornada padrão na resolução da data é origem da jornada, não fallback (fallback = checkout esquecido).
  const padrao = traceOccurrence({ ...base, evidencia }, { ...resolucao, houve_fallback: true, origem: 'FALLBACK' });
  assert.equal(padrao.fallback, false);
  assert.equal(journeyOriginLabel('FALLBACK'), 'Jornada padrão 44H (cadastro sem jornada)');
  const semNada = traceOccurrence({ ...base, evidencia }, null);
  assert.equal(semNada.fallback, false);
  assert.equal(semNada.jornada, null);
  assert.match(semNada.motivo ?? '', /horas não registradas na prova/);
  const comHoras = traceOccurrence({ ...base, evidencia: { comprovacao: { ...evidencia.comprovacao, jornada_semanal: 36 } } }, resolucao);
  assert.deepEqual([comHoras.jornada, comHoras.referencia_jornada], ['36H', 'prova']);
  assert.equal(scenario({}), 'Prova sem descrição do cenário.');
});

test('rastreio da oportunidade usa só GETs existentes e casa a jornada pelo nome exato e pela data', async (t) => {
  const paths: string[] = [];
  t.mock.method(globalThis, 'fetch', async (input: string, init: RequestInit) => {
    assert.equal(init.method ?? 'GET', 'GET');
    const url = new URL(input, 'http://localhost');
    paths.push(url.pathname);
    if (url.pathname.endsWith('/detalhes')) return Response.json({
      grupo_id: 'g', marca: 'BRACELL', tipo_problema: 'HORAS_AUSENTES', titulo: 'Horas ausentes', colaborador: 'ANA',
      colaborador_id_interno: null, campo: null, origem: null, quantidade: 1, impacto: null, acao_recomendada: null,
      status_operacional: 'ABERTA', periodo: { inicio: '2026-08-31', fim: '2026-09-05' },
      ocorrencias: { items: [{ fingerprint: 'f', oportunidade_id: 'o', execution_id: 'EX', data_referencia: '2026-09-02',
        tabela_origem: 't', origem: 'o', severidade: 'MEDIA', identificada_em: '2026-09-23T11:50:45', repeticoes: 3,
        evidencia: { comprovacao: { resultado: 'confirmado', jornada_origem: 'INVOLVES' } } }],
        total: 1, pagina: 1, tamanho: 200, paginas: 1 },
    });
    assert.equal(url.searchParams.get('colaborador'), 'ANA');
    const linha = (colaborador: string, jornada: string) => ({
      colaborador, estado: 'SP', data: '2026-09-02', nome_do_dia: 'QUARTA', deslocamento: null, ocio: null,
      produtividade: null, horas_nao_registradas: null, horas_programadas: '08:00:00', primeiro_checkin: null,
      ultimo_checkout: null, visitas: 0, visitas_realizadas: 0, pesquisas: 0, pesquisas_realizadas: 0,
      percentuais: { produtividade: null, visitas: null, pesquisas: null, efetividade: null },
      jornada: { fonte: 'Cadastro Involves (colaboradores_ativos_bracell.nome_pai)', horario_aplicado: '08:00:00',
        houve_fallback: false, origem_fallback: null, jornada_aplicada: jornada, origem: 'INVOLVES' },
      origem_dado: 'produtos_platina.exclusivo_bracell_platina_relatorio_pdoh' });
    // LIKE no backend: "ANA" também traz "ANAIRA"; a tela casa pelo nome exato.
    return Response.json({ disponivel: true, motivo: null, percentual: 70, variacao_periodo_anterior: null,
      periodo: { inicio: '2026-08-31', fim: '2026-09-05' },
      detalhes: { total: 2, pagina: 1, tamanho: 200, paginas: 1, items: [linha('ANAIRA', '24H'), linha('ANA', '44H')] } });
  });
  const grupo = { grupo_id: 'g', colaborador: 'ANA' } as OperationalGroup;
  const window = { marca: 'BRACELL', periodo: 'personalizado' as const, periodo_inicio: '2026-08-31', periodo_fim: '2026-09-05' };
  const [trace] = await loadOpportunityTrace(grupo, window);
  assert.deepEqual(paths, ['/api/v2/oportunidades/g/detalhes', '/api/v2/pdoh/resumo']);
  assert.deepEqual([trace.jornada, trace.jornada_origem, trace.fallback, trace.referencia_jornada],
    ['44H', 'INVOLVES', false, 'resolucao_da_data']);
  assert.equal(trace.historico.repeticoes, 3);
});
