import { OPERACAO } from '../lib/operacao.ts';
import {
  loadAlerts,
  type OperationalFilters, type OperationalGroup, type ResolvedPeriod,
} from './operational-api.ts';
import { OPEN_STATUS, appliesFallback, groupFallback, loadGroupOccurrences, loadOpportunityGroups } from './daily-validation.ts';

/**
 * Monitoramento semanal da Dashboard. Somente leitura das APIs v2 já existentes:
 * a esteira gera, valida e deduplica as oportunidades; aqui só se agrupa para exibir.
 */
export type MonitoringMode = 'semana' | 'dia';

const DAY = 86_400_000;
const isoDay = (value: Date) => value.toISOString().slice(0, 10);
const utcDay = (iso: string) => new Date(`${iso.slice(0, 10)}T00:00:00Z`);

/** Semana operacional de segunda a sábado que contém a data informada. */
export function weekContaining(iso: string): ResolvedPeriod {
  const day = utcDay(iso);
  const monday = new Date(day.getTime() - ((day.getUTCDay() + 6) % 7) * DAY);
  return { inicio: isoDay(monday), fim: isoDay(new Date(monday.getTime() + 5 * DAY)) };
}

export function shiftWeek(week: ResolvedPeriod, weeks: number): ResolvedPeriod {
  return weekContaining(isoDay(new Date(utcDay(week.inicio).getTime() + weeks * 7 * DAY)));
}

/** Janela enviada à API: a semana escolhida ou o período do painel, sempre fixa em datas. */
export function monitoringWindow(period: ResolvedPeriod, colaborador?: string): OperationalFilters {
  return {
    marca: OPERACAO.marca, operacao: 'EXCLUSIVA', colaborador,
    periodo: 'personalizado', periodo_inicio: period.inicio, periodo_fim: period.fim,
  };
}

// Rótulos de origem da jornada gravados pelo motor (shared/evidence_config.py).
// FALLBACK aqui é a jornada padrão 44H (cadastro sem jornada): origem, não o fallback de checkout.
const JORNADA_ENCONTRADA = new Set(['INVOLVES', 'RAW', 'CONFIGURACAO']);
export const JORNADA_PADRAO = 'FALLBACK';

export function journeyFound(origem: string | null | undefined): 'sim' | 'fallback' | 'nao' {
  const value = (origem ?? '').toUpperCase();
  return JORNADA_ENCONTRADA.has(value) ? 'sim' : value === JORNADA_PADRAO ? 'fallback' : 'nao';
}

export type WeeklyCard = {
  tipo: string;
  titulo: string;
  severidade: string;
  ocorrencias: number;
  colaboradores: number;
  fallback: number;
  grupos: number;
  abertos: number;
  status: 'Em aberto' | 'Tratado';
};

/**
 * Um card por tipo de oportunidade. Ocorrências somam `quantidade` (ocorrências distintas já
 * deduplicadas pelo backend, nunca `registros_historicos`). Fallback conta as ocorrências de
 * checkout esquecido comprovadas (`groupFallback`), a mesma regra da validação diária.
 */
export function summarizeWeek(groups: OperationalGroup[]): WeeklyCard[] {
  const cards = new Map<string, WeeklyCard & { pessoas: Set<string> }>();
  for (const group of groups) {
    const card = cards.get(group.tipo_problema) ?? {
      tipo: group.tipo_problema, titulo: group.titulo, severidade: group.severidade,
      ocorrencias: 0, colaboradores: 0, fallback: 0, grupos: 0, abertos: 0,
      status: 'Tratado' as const, pessoas: new Set<string>(),
    };
    card.grupos += 1;
    card.ocorrencias += group.quantidade;
    if (group.colaborador) card.pessoas.add(group.colaborador.trim().toLocaleUpperCase('pt-BR'));
    card.fallback += groupFallback(group);
    if (OPEN_STATUS.has(group.status_operacional)) card.abertos += 1;
    cards.set(group.tipo_problema, card);
  }
  return [...cards.values()]
    .map(({ pessoas, ...card }) => ({
      ...card, colaboradores: pessoas.size, status: card.abertos ? 'Em aberto' as const : 'Tratado' as const,
    }))
    .sort((a, b) => b.ocorrencias - a.ocorrencias || a.titulo.localeCompare(b.titulo, 'pt-BR'));
}

export async function loadWeeklyMonitoring(period: ResolvedPeriod, signal?: AbortSignal) {
  const window = monitoringWindow(period);
  // Alertas cadastrais: apenas monitoramento. Não geram oportunidade nem entram no sino.
  const [groups, alerts] = await Promise.allSettled([
    loadOpportunityGroups(window, signal, true),
    loadAlerts(window, signal),
  ]);
  signal?.throwIfAborted();
  if (groups.status === 'rejected') throw groups.reason;
  // Só oportunidades reais (checkout ausente); horas ausentes aparecem em "Principais impactadores".
  const items = groups.value;
  return {
    period, window, groups: items, cards: summarizeWeek(items),
    alerts: alerts.status === 'fulfilled' ? alerts.value.resumo : null,
  };
}
export type WeeklyMonitoring = Awaited<ReturnType<typeof loadWeeklyMonitoring>>;

// --------------------------------------------------------------- linhas por ocorrência
export type OccurrenceRow = {
  colaborador: string;
  grupo_id: string;
  oportunidade_id: string;
  data: string | null;
  semana: string;
  regra: string;
  tipo: string;
  jornada_aplicada: string | null;
  jornada_origem: string;
  jornada_encontrada: 'sim' | 'fallback' | 'nao';
  fallback: boolean;
  motivo_fallback: string | null;
  horario_esperado: string | null;
  status: string;
  validacao: string;
  evidencia: string | null;
  execucao: string;
  origem?: string;
  identificada_em: string;
  repeticoes: number;
};

type Proof = Record<string, unknown>;
const record = (value: unknown): Proof | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Proof) : null;
const text = (value: unknown): string | null => {
  if (value === null || value === undefined || value === '') return null;
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value) : JSON.stringify(value);
};
const hhmm = (value: unknown) => text(value)?.slice(0, 5) ?? null;

function hours(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? `${Number.isInteger(number) ? number : number.toFixed(1)}H` : null;
}

/**
 * Lê a evidência que a esteira gravou em cada ocorrência. Nada é recalculado: jornada, horário
 * e fallback só aparecem quando estão na prova; ausência vira "não informado", nunca um padrão.
 */
export function occurrenceFromEvidence(
  evidence: unknown, base: Omit<OccurrenceRow, 'jornada_aplicada' | 'jornada_origem' | 'jornada_encontrada'
    | 'fallback' | 'motivo_fallback' | 'horario_esperado' | 'validacao' | 'evidencia'>,
): OccurrenceRow {
  const root = record(evidence) ?? {};
  const proof = record(root.comprovacao) ?? {};
  const schedule = record(proof.configuracao_operacional);
  const origem = (text(proof.jornada_origem) ?? 'INDISPONIVEL').toUpperCase();
  const inicio = hhmm(schedule?.hora_entrada_padrao);
  const fim = hhmm(schedule?.hora_saida_padrao);
  const jornada = hours(schedule?.jornada) ?? hours(proof.jornada_semanal);
  // Fallback = checkout esquecido com saída considerada (jornada ou, no legado, o valor gravado).
  const saida = fim ?? (root.fallback_usado === true ? hhmm(root.fallback_valor) : null);
  const fallback = appliesFallback(base.tipo) && !!saida;
  return {
    ...base,
    jornada_aplicada: jornada,
    jornada_origem: origem,
    jornada_encontrada: journeyFound(origem),
    fallback,
    motivo_fallback: fallback
      ? `Checkout não informado; saída considerada às ${saida}${jornada ? ` pela jornada ${jornada}` : ''}.` : null,
    horario_esperado: inicio && fim ? `${inicio} - ${fim}` : fim ?? hhmm(root.fallback_valor),
    validacao: text(proof.resultado) ?? 'indisponivel',
    evidencia: [text(proof.fonte) ?? text(root.origem), text(proof.encontrado) ?? text(root.valor_encontrado)]
      .filter(Boolean).join(': ') || null,
  };
}

/** Ocorrências já consolidadas por fingerprint no detalhe do backend. */
export async function loadOccurrences(
  groups: OperationalGroup[], window: OperationalFilters, signal?: AbortSignal,
) {
  if (!groups.length) return [];
  const details = await loadGroupOccurrences(groups, window, signal);
  const semana = `${window.periodo_inicio} a ${window.periodo_fim}`;
  return details.flatMap(({ group, items }) => items.map((record) => occurrenceFromEvidence(record.evidencia, {
    colaborador: group.colaborador ?? 'Não informado', grupo_id: group.grupo_id,
    oportunidade_id: record.oportunidade_id, data: record.data_referencia, semana,
    regra: group.titulo, tipo: group.tipo_problema, status: group.status_operacional,
    execucao: record.execution_id, identificada_em: record.identificada_em, repeticoes: record.repeticoes,
    origem: record.origem,
  }))).sort((a, b) => a.colaborador.localeCompare(b.colaborador, 'pt-BR') || (a.data ?? '').localeCompare(b.data ?? ''));
}

// --------------------------------------------------------------------------- CSV
const CSV_COLUMNS: [string, (row: OccurrenceRow) => string | number | null][] = [
  ['Colaborador', (r) => r.colaborador],
  ['Identificador da oportunidade', (r) => r.oportunidade_id],
  ['Grupo', (r) => r.grupo_id],
  ['Data', (r) => r.data],
  ['Semana', (r) => r.semana],
  ['Regra', (r) => r.regra],
  ['Origem', (r) => r.origem ?? null],
  ['Tipo da ocorrência', (r) => r.tipo],
  ['Jornada aplicada', (r) => r.jornada_aplicada],
  ['Origem da jornada', (r) => r.jornada_origem],
  ['Utilizou fallback', (r) => (r.fallback ? 'Sim' : 'Não')],
  ['Motivo do fallback', (r) => r.motivo_fallback],
  ['Horário esperado', (r) => r.horario_esperado],
  ['Status', (r) => r.status],
  ['Validação', (r) => r.validacao],
  ['Evidências disponíveis', (r) => r.evidencia],
  ['Histórico', (r) => `${r.repeticoes} registro(s); execução ${r.execucao}; identificado em ${r.identificada_em}`],
];

function csvCell(value: string | number | null) {
  const raw = value === null ? '' : String(value);
  // Evita que o Excel interprete texto como fórmula.
  const safe = /^[=+\-@]/.test(raw) ? `'${raw}` : raw;
  return /[;"\n\r]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

/** CSV em UTF-8 com BOM e `;`, que o Excel em português abre sem assistente. */
export function occurrencesCsv(rows: OccurrenceRow[]) {
  const lines = [CSV_COLUMNS.map(([name]) => name), ...rows.map((row) => CSV_COLUMNS.map(([, get]) => get(row)))];
  return '﻿' + lines.map((line) => line.map(csvCell).join(';')).join('\r\n');
}

export function csvFileName(period: ResolvedPeriod, tipo?: string) {
  return `oportunidades_${tipo ? `${tipo.toLowerCase()}_` : ''}${period.inicio}_a_${period.fim}.csv`;
}

// ------------------------------------------------------------------ reprocessamento
export type ReprocessResult = { processadas: number; novas: number; atualizadas: number; duplicadas: number };

/** Identidade de negócio da oportunidade na semana: colaborador + regra + janela. */
export function weeklyIdentity(group: OperationalGroup, period: ResolvedPeriod) {
  return JSON.stringify([group.colaborador?.trim().toLocaleUpperCase('pt-BR') ?? '', group.tipo_problema,
    period.inicio, period.fim]);
}

/** Compara duas leituras da mesma janela. Duplicada = mesma identidade de negócio repetida. */
export function compareReads(
  before: OperationalGroup[], after: OperationalGroup[], period: ResolvedPeriod,
): ReprocessResult {
  const previous = new Map(before.map((group) => [weeklyIdentity(group, period), group]));
  const seen = new Set<string>();
  const result: ReprocessResult = { processadas: after.length, novas: 0, atualizadas: 0, duplicadas: 0 };
  for (const group of after) {
    const key = weeklyIdentity(group, period);
    if (seen.has(key)) { result.duplicadas += 1; continue; }
    seen.add(key);
    const old = previous.get(key);
    if (!old) result.novas += 1;
    else if (old.quantidade !== group.quantidade || old.ultima_ocorrencia !== group.ultima_ocorrencia
      || old.status_operacional !== group.status_operacional
      || old.validacao?.jornada_origem !== group.validacao?.jornada_origem) result.atualizadas += 1;
  }
  return result;
}

/** Avisa o sino e demais consumidores que uma nova leitura foi feita. */
export const OPPORTUNITIES_REFRESHED = 'pdoh:oportunidades-atualizadas';
