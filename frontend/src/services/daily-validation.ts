import { z } from 'zod';
import { displayLabel } from '../lib/operational-display.ts';
import { formatDate, formatDateTime } from '../lib/pdoh-format.ts';
import { apiRequest, opportunityHistorySchema, pageSchema, queryString } from './pdoh-api.ts';
import {
  loadAllGroups, loadGroupDetails, v2Request,
  type Occurrence, type OperationalFilters, type OperationalGroup,
} from './operational-api.ts';
import { originLabel } from './operational-trace.ts';
import {
  PDOH_SUMMARY_PATH, pdohSummarySchema,
  type DayStatus, type PdohDailyRow, type ValidationSummary,
} from './pdoh-indicator.ts';

/**
 * Validação diária do PDOH e oportunidades da mesma janela. Uma única estrutura
 * (`OpportunityRecord`) alimenta a tabela, o modal e o XLSX: o que a tela mostra é o que o
 * arquivo leva. Tudo é lido do que a esteira e a API já gravaram; nada é recalculado.
 *
 * Fallback (decisão de 25/09/2026) = checkout esquecido: entrada registrada sem saída, com a
 * saída considerada pela jornada. Jornada padrão 44H é só a ORIGEM da jornada, não o fallback.
 */

/**
 * Único tipo que é oportunidade (decisão de 25/09/2026): check-in real, sem checkout, fallback aplicado.
 * Horas não registradas, atestado, feriado, FTJ, férias e dia sem atividade impactam só o PDOH;
 * os registros já gravados ficam intactos no banco — aqui apenas não são apresentados como oportunidade.
 */
export const OPPORTUNITY_TYPES: readonly string[] = ['CHECKOUT_AUSENTE'];
export const isOpportunityType = (tipo: string | null | undefined) => !!tipo && OPPORTUNITY_TYPES.includes(tipo);
export const opportunityGroups = <T extends Pick<OperationalGroup, 'tipo_problema'>>(groups: T[]) =>
  groups.filter((group) => isOpportunityType(group.tipo_problema));

/**
 * Grupos de oportunidade da janela, pedindo ao servidor só os tipos que são oportunidade: a consulta
 * sem filtro de tipo varre todas as regras e, concorrente, chegava a 16 s. O filtro local permanece
 * como defesa caso o servidor ignore o parâmetro.
 */
export async function loadOpportunityGroups(window: OperationalFilters, signal?: AbortSignal, includeClosed = false) {
  const pages = await Promise.all(OPPORTUNITY_TYPES.map((tipo) => loadAllGroups({ ...window, tipo }, signal, includeClosed)));
  return opportunityGroups(pages.flatMap((page) => page.items));
}

/** Única regra em que existe fallback: checkout esquecido com saída considerada pela jornada. */
export const FALLBACK_RULE = 'CHECKOUT_AUSENTE';
export const appliesFallback = (tipo: string | null | undefined) => tipo === FALLBACK_RULE;
/** Ocorrências do grupo com fallback: checkout esquecido com prova confirmada; sem prova não conta. */
export const groupFallback = (group: Pick<OperationalGroup, 'tipo_problema' | 'quantidade' | 'validacao'>) =>
  appliesFallback(group.tipo_problema) && group.validacao?.resultado === 'confirmado' ? group.quantidade : 0;

const DAY_STATUS: Record<DayStatus, string> = {
  VALIDO: 'Válido',
  CHECKOUT_ESQUECIDO: 'Checkout esquecido · fallback',
  DESCONSIDERADO: 'Desconsiderado',
  SEM_ATIVIDADE_PREVISTA: 'Sem atividade prevista',
};
export const dayStatusLabel = (status: DayStatus | null | undefined) => (status ? DAY_STATUS[status] : 'Não informado');

// Status em que a oportunidade ainda pede tratativa.
export const OPEN_STATUS = new Set(['ABERTA', 'REABERTA', 'EM_TRATAMENTO', 'EM_ANDAMENTO']);

type Json = Record<string, unknown>;
const record = (value: unknown): Json | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : null;
const text = (value: unknown): string | null => {
  if (value === null || value === undefined || value === '') return null;
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value) : JSON.stringify(value);
};
const hhmm = (value: unknown) => text(value)?.slice(0, 5) ?? null;
function hours(value: unknown) {
  const number = Number(value);
  return value !== null && value !== undefined && value !== '' && Number.isFinite(number) && number > 0
    ? `${Number.isInteger(number) ? number : number.toFixed(1)}H` : null;
}
// Mesma normalização da API (`chave_dia`): espaços colapsados e maiúsculas.
const person = (value: string | null | undefined) => value?.trim().replace(/\s+/g, ' ').toLocaleUpperCase('pt-BR') ?? '';

const ORIGEM_JORNADA: Record<string, string> = {
  INVOLVES: 'Cadastro Involves', RAW: 'Cadastro RAW', CONFIGURACAO: 'Configuração da operação',
};
function journeyOrigin(origem: string | null, jornada: string | null) {
  if (!origem || origem === 'INDISPONIVEL') return null;
  if (origem === 'FALLBACK') return `Jornada padrão ${jornada ?? '44H'} (cadastro sem jornada)`;
  return ORIGEM_JORNADA[origem] ?? displayLabel(origem);
}

const CENARIOS: Record<string, string> = { CHECKOUT_AUSENTE: 'Checkout esquecido (entrada sem saída)' };

// ------------------------------------------------------------------------ ocorrência
export type EvidenceLine = {
  criterio: string; verificacao: string; atendido: boolean | null;
  fonte: string | null; campo: string | null; valor: string | null;
};

export type OpportunityRecord = {
  id: string;
  grupo_id: string;
  colaborador: string;
  data: string | null;
  regra: string;
  titulo: string;
  cenario: string;
  motivo: string;
  jornada: string | null;
  origem_jornada: string | null;
  fallback: 'Sim' | 'Não' | 'Não se aplica';
  saida_considerada: string | null;
  checkin: string | null;
  checkout: string | null;
  evidencia: string | null;
  evidencias: EvidenceLine[];
  status: string;
  status_dia: DayStatus | null;
  execucao: string;
  identificada_em: string;
  repeticoes: number;
};

/** Uma ocorrência explicada a partir da prova; `day` é a linha da Platina do mesmo colaborador/data. */
export function opportunityRecord(group: OperationalGroup, item: Occurrence, day: PdohDailyRow | null): OpportunityRecord {
  const root = record(item.evidencia) ?? {};
  const proof = record(root.comprovacao) ?? {};
  const schedule = record(proof.configuracao_operacional);
  const monitor = record(proof.monitoramento);
  const origemProva = (text(schedule?.origem) ?? text(proof.jornada_origem))?.toUpperCase() ?? null;
  const jornadaProva = hours(schedule?.jornada) ?? hours(proof.jornada_semanal) ?? hours(proof.jornada_aplicada);
  const jornada = jornadaProva ?? day?.jornada.jornada_aplicada ?? null;
  const origem = jornadaProva ? origemProva : day?.jornada.jornada_aplicada ? day.jornada.origem?.toUpperCase() ?? null : origemProva;
  const saida = schedule ? hhmm(schedule.hora_saida_padrao) : null;
  const checkin = monitor ? hhmm(monitor.hora_entrada) : hhmm(day?.primeiro_checkin);
  const checkout = monitor ? hhmm(monitor.hora_saida) : hhmm(day?.ultimo_checkout);
  const fonte = originLabel(text(proof.fonte_tabela)) ?? text(proof.fonte);
  const esperado = text(proof.esperado);
  const encontrado = text(proof.encontrado);
  const verificacoes = Array.isArray(proof.verificacoes) ? proof.verificacoes : [];
  const campo = text(proof.campo)
    ?? text(verificacoes.map(record).find((line) => line?.criterio === 'condicao')?.campo);
  const checkoutCase = appliesFallback(group.tipo_problema) && monitor && saida;
  const motivo = checkoutCase
    ? `Entrada registrada às ${checkin ?? 'horário não informado'} sem checkout informado; saída considerada às ${saida} pela jornada ${jornada ?? 'não informada'}.`
    : esperado || encontrado ? `${esperado ?? 'Critério da regra'}${encontrado ? ` — encontrado ${encontrado}` : ''}.`
      : 'Prova sem descrição do cenário.';
  const evidencia = checkoutCase
    ? `Check-in às ${checkin ?? '—'} sem checkout${fonte ? ` · ${fonte}` : ''}`
    : [encontrado ? `${campo ? displayLabel(campo) : 'Valor encontrado'}: ${encontrado}` : null,
      text(proof.fonte)].filter(Boolean).join(' · ') || null;
  return {
    id: item.oportunidade_id,
    grupo_id: group.grupo_id,
    colaborador: group.colaborador ?? 'Não informado',
    data: item.data_referencia,
    regra: group.tipo_problema,
    titulo: group.titulo,
    cenario: CENARIOS[group.tipo_problema] ?? group.titulo,
    motivo,
    jornada,
    origem_jornada: journeyOrigin(origem, jornada),
    fallback: !appliesFallback(group.tipo_problema) ? 'Não se aplica' : checkoutCase ? 'Sim' : 'Não',
    saida_considerada: checkoutCase ? saida : null,
    checkin,
    checkout,
    evidencia,
    evidencias: verificacoes.map((raw) => {
      const line = record(raw) ?? {};
      return {
        criterio: text(line.criterio) ?? '—',
        verificacao: text(line.rotulo) ?? text(line.descricao) ?? '—',
        atendido: typeof line.atendido === 'boolean' ? line.atendido : null,
        fonte: originLabel(text(line.fonte)),
        campo: text(line.campo) ? displayLabel(text(line.campo) as string) : null,
        valor: text(line.valor),
      };
    }),
    status: group.status_operacional,
    status_dia: day?.validacao?.status ?? null,
    execucao: item.execution_id,
    identificada_em: item.identificada_em,
    repeticoes: item.repeticoes,
  };
}

// ------------------------------------------------------------------ card de oportunidades
export type OpportunitySummary = {
  total: number; colaboradores: number; fallback: number; pendencias: number;
  tipos: { tipo: string; titulo: string; quantidade: number }[];
};

/** Contagem pelos grupos (ocorrências já deduplicadas pelo backend em `quantidade`). */
export function summarizeOpportunities(groups: OperationalGroup[]): OpportunitySummary {
  const tipos = new Map<string, { tipo: string; titulo: string; quantidade: number }>();
  const pessoas = new Set<string>();
  let total = 0, fallback = 0, pendencias = 0;
  for (const group of opportunityGroups(groups)) {
    total += group.quantidade;
    if (group.colaborador) pessoas.add(person(group.colaborador));
    fallback += groupFallback(group);
    if (OPEN_STATUS.has(group.status_operacional)) pendencias += group.quantidade;
    const tipo = tipos.get(group.tipo_problema) ?? { tipo: group.tipo_problema, titulo: group.titulo, quantidade: 0 };
    tipo.quantidade += group.quantidade;
    tipos.set(group.tipo_problema, tipo);
  }
  return {
    total, colaboradores: pessoas.size, fallback, pendencias,
    tipos: [...tipos.values()].sort((a, b) => b.quantidade - a.quantidade || a.titulo.localeCompare(b.titulo, 'pt-BR')),
  };
}

// --------------------------------------------------------------- colunas da tela = XLSX
export const OPPORTUNITY_COLUMNS: [string, (row: OpportunityRecord) => string][] = [
  ['ID', (r) => r.id],
  ['Colaborador', (r) => r.colaborador],
  ['Data', (r) => formatDate(r.data)],
  ['Tipo da oportunidade', (r) => r.titulo],
  ['Regra', (r) => r.regra],
  ['Motivo', (r) => r.motivo],
  ['Jornada aplicada', (r) => r.jornada ?? 'Não informada'],
  ['Origem da jornada', (r) => r.origem_jornada ?? 'Não informada'],
  ['Fallback', (r) => r.fallback],
  ['Evidências disponíveis', (r) => r.evidencia ?? 'Não informada'],
  ['Status', (r) => displayLabel(r.status)],
  ['Check-in', (r) => r.checkin ?? 'Não informado'],
  ['Checkout', (r) => r.checkout ?? 'Não informado'],
  ['Saída considerada', (r) => r.saida_considerada ?? '—'],
];

/** Identidade da ocorrência tratável: colaborador + data + tipo da oportunidade + regra aplicada. */
export const opportunityKey = (r: Pick<OpportunityRecord, 'colaborador' | 'data' | 'titulo' | 'regra'>) =>
  [person(r.colaborador), (r.data ?? '').slice(0, 10), r.titulo, r.regra].join('|');

/** Uma linha por identidade; em regravação, vale a identificação mais recente. */
export function dedupeRecords(records: OpportunityRecord[]) {
  const byKey = new Map<string, OpportunityRecord>();
  for (const record of records) {
    const key = opportunityKey(record);
    const previous = byKey.get(key);
    if (!previous || record.identificada_em > previous.identificada_em) byKey.set(key, record);
  }
  return records.filter((record) => byKey.get(opportunityKey(record)) === record);
}

// ------------------------------------------------------------------------------ carga
export type OpportunityHistory = z.infer<typeof opportunityHistorySchema>;

/** Ocorrências de cada grupo, todas as páginas; confere com a contagem do resumo. */
export async function loadGroupOccurrences(groups: OperationalGroup[], window: OperationalFilters, signal?: AbortSignal) {
  const details: { group: OperationalGroup; items: Occurrence[] }[] = [];
  for (let start = 0; start < groups.length; start += 4) {
    signal?.throwIfAborted();
    details.push(...await Promise.all(groups.slice(start, start + 4).map(async (group) => {
      const first = await loadGroupDetails(group.grupo_id, window, signal, 200);
      const pages = [first.ocorrencias];
      for (let pagina = 2; pagina <= first.ocorrencias.paginas; pagina++) {
        signal?.throwIfAborted();
        pages.push((await loadGroupDetails(group.grupo_id, window, signal, 200, pagina)).ocorrencias);
      }
      const items = pages.flatMap((page) => page.items);
      if (items.length !== first.ocorrencias.total || new Set(items.map((item) => item.fingerprint)).size !== items.length
        || first.quantidade !== group.quantidade)
        throw new Error('As ocorrências não conferem com o resumo da janela. Atualize e tente novamente.');
      return { group, items };
    })));
  }
  return details;
}

/** Todas as linhas diárias da janela (a tabela da tela é paginada; o cruzamento não pode ser). */
export async function loadDailyRows(window: OperationalFilters, signal?: AbortSignal) {
  const request = (pagina: number) => v2Request(`${PDOH_SUMMARY_PATH}${queryString({
    marca: window.marca, operacao: window.operacao, colaborador: window.colaborador, periodo: 'personalizado',
    periodo_inicio: window.periodo_inicio, periodo_fim: window.periodo_fim, pagina, tamanho: 200,
  })}`, pdohSummarySchema, signal);
  const first = await request(1);
  const rows = [...first.detalhes.items];
  for (let pagina = 2; pagina <= first.detalhes.paginas; pagina++) rows.push(...(await request(pagina)).detalhes.items);
  return { rows, validacao: first.validacao };
}

const dayKey = (colaborador: string | null | undefined, data: string | null | undefined) =>
  `${person(colaborador)}|${(data ?? '').slice(0, 10)}`;

/** Uma linha por ocorrência, cruzada com o dia da Platina, ordenada por colaborador e data. */
export async function loadOpportunityRecords(groups: OperationalGroup[], window: OperationalFilters, signal?: AbortSignal) {
  const [details, daily] = await Promise.all([
    loadGroupOccurrences(opportunityGroups(groups), window, signal), loadDailyRows(window, signal),
  ]);
  const days = new Map(daily.rows.map((row) => [dayKey(row.colaborador, row.data), row]));
  const records = dedupeRecords(details.flatMap(({ group, items }) => items.map((item) =>
    opportunityRecord(group, item, days.get(dayKey(group.colaborador, item.data_referencia)) ?? null))));
  records.sort((a, b) => a.colaborador.localeCompare(b.colaborador, 'pt-BR') || (a.data ?? '').localeCompare(b.data ?? ''));
  return { records, validacao: daily.validacao };
}

const historyPage = pageSchema(opportunityHistorySchema);
export async function loadHistory(id: string, signal?: AbortSignal) {
  const page = await apiRequest(`/oportunidades/${encodeURIComponent(id)}/historico${queryString({ tamanho: 200 })}`, historyPage, signal);
  return page.items;
}

/** Histórico de várias ocorrências, 8 por vez (cada chamada é leve). */
export async function loadHistories(ids: string[], signal?: AbortSignal) {
  const result = new Map<string, OpportunityHistory[]>();
  for (let start = 0; start < ids.length; start += 8) {
    signal?.throwIfAborted();
    const batch = await Promise.all(ids.slice(start, start + 8).map(async (id) => [id, await loadHistory(id, signal)] as const));
    for (const [id, items] of batch) result.set(id, items);
  }
  return result;
}

// ------------------------------------------------------------------------------ XLSX
export type Sheet = { sheet: string; rows: (string | number)[][] };

export function workbookSheets({ periodo, validacao, records, historicos }: {
  periodo: { inicio: string; fim: string };
  validacao: ValidationSummary | null;
  records: OpportunityRecord[];
  historicos: Map<string, OpportunityHistory[]>;
}): Sheet[] {
  const regras = new Map<string, number>();
  for (const r of records) regras.set(r.regra, (regras.get(r.regra) ?? 0) + 1);
  const resumo: (string | number)[][] = [
    ['Indicador', 'Valor'],
    ['Período', `${formatDate(periodo.inicio)} a ${formatDate(periodo.fim)}`],
    ['Total de oportunidades', records.length],
    ['Colaboradores', new Set(records.map((r) => person(r.colaborador))).size],
    ['Regras', [...regras].sort(([a], [b]) => a.localeCompare(b)).map(([regra, n]) => `${regra} (${n})`).join('; ') || '—'],
    ['Quantidade de fallback', records.filter((r) => r.fallback === 'Sim').length],
    ['Pendências', records.filter((r) => OPEN_STATUS.has(r.status)).length],
  ];
  if (validacao) resumo.push(
    ['Dias analisados', validacao.dias],
    ['Dias considerados', validacao.considerados],
    ['Dias com checkout esquecido', validacao.checkout_esquecido],
    ['Dias desconsiderados (justificados)', validacao.desconsiderados],
    ['Dias sem atividade prevista', validacao.sem_atividade_prevista],
  );
  const evidencias: (string | number)[][] = [['ID', 'Colaborador', 'Data', 'Regra', 'Critério', 'Verificação', 'Resultado', 'Fonte', 'Campo', 'Valor']];
  const historico: (string | number)[][] = [['ID', 'Data/hora', 'Ação', 'Status anterior', 'Status novo', 'Responsável', 'Observação', 'Execução']];
  for (const r of records) {
    for (const e of r.evidencias) evidencias.push([r.id, r.colaborador, formatDate(r.data), r.regra, displayLabel(e.criterio),
      e.verificacao, e.atendido === null ? 'Não verificável' : e.atendido ? 'Atendido' : 'Não atendido',
      e.fonte ?? '', e.campo ?? '', e.valor ?? '']);
    for (const h of historicos.get(r.id) ?? []) historico.push([r.id, formatDateTime(h.registrado_em), h.acao,
      h.status_anterior ?? '', h.status_novo, h.responsavel ?? '', h.observacao ?? '', h.execution_id]);
  }
  return [
    { sheet: 'Resumo', rows: resumo },
    { sheet: 'Oportunidades', rows: [OPPORTUNITY_COLUMNS.map(([label]) => label), ...records.map((r) => OPPORTUNITY_COLUMNS.map(([, get]) => get(r)))] },
    { sheet: 'Evidências', rows: evidencias },
    { sheet: 'Histórico', rows: historico },
  ];
}

export const xlsxFileName = (periodo: { inicio: string; fim: string }) =>
  `oportunidades_${periodo.inicio}_a_${periodo.fim}.xlsx`;

/** Gera o arquivo no navegador; a biblioteca só é baixada quando o usuário exporta. */
export async function workbookBlob(sheets: Sheet[]) {
  const { default: writeExcelFile } = await import('write-excel-file/browser');
  return writeExcelFile(sheets.map(({ sheet, rows }) => ({
    sheet,
    data: rows.map((row, index) => row.map((value) => ({
      value, type: typeof value === 'number' ? Number : String, ...(index === 0 ? { fontWeight: 'bold' as const } : {}),
    }))),
    columns: rows[0].map((_, column) => ({ width: Math.min(60, Math.max(10, ...rows.map((row) => String(row[column] ?? '').length + 2))) })),
  }))).toBlob();
}
