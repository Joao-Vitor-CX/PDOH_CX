import { OPERACAO } from '../lib/operacao.ts';
import { queryString } from './pdoh-api.ts';
import {
  type OperationalFilters, type OperationalGroup, type ResolvedPeriod,
} from './operational-api.ts';
import { weekContaining } from './weekly-monitoring.ts';
import { appliesFallback, groupFallback, loadOpportunityGroups } from './daily-validation.ts';

/** Um aviso por regra e semana: resumo consolidado, nunca uma notificação por ocorrência. */
export type WeeklyNotification = {
  tipo: string;
  titulo: string;
  ocorrencias: number;
  colaboradores: number;
  fallback: number;
  ultima_ocorrencia: string | null;
};
export type NotificationSnapshot = {
  notifications: WeeklyNotification[];
  period: ResolvedPeriod;
  window: OperationalFilters;
};
/** Quantas ocorrências de cada regra/semana o usuário já viu. */
export type SeenOpportunities = Record<string, number>;

/** Janela civil vigente em São Paulo. O servidor continua responsável pela ocorrência e pela validação. */
export function currentNotificationWeek(now = new Date()): ResolvedPeriod {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now);
  const value = (name: string) => Number(parts.find((part) => part.type === name)?.value);
  const day = new Date(Date.UTC(value('year'), value('month') - 1, value('day')));
  if (day.getUTCDay() === 0) day.setUTCDate(day.getUTCDate() - 1);
  return weekContaining(day.toISOString().slice(0, 10));
}

function notificationKey(tipo: string, period: ResolvedPeriod) {
  return JSON.stringify([OPERACAO.marca, 'EXCLUSIVA', tipo, period.inicio, period.fim]);
}

/**
 * A API confirma o achado e a jornada aplicada; aqui só se consolida por regra na semana.
 * Entram apenas oportunidades comprovadas com ocorrência dentro da semana.
 */
export function weeklyNotifications(groups: OperationalGroup[], _period: ResolvedPeriod): WeeklyNotification[] {
  const byType = new Map<string, WeeklyNotification & { pessoas: Set<string> }>();
  for (const group of groups) {
    if (group.quantidade < 1) continue;
    const item = byType.get(group.tipo_problema) ?? {
      tipo: group.tipo_problema, titulo: group.titulo, ocorrencias: 0, colaboradores: 0,
      fallback: 0, ultima_ocorrencia: null, pessoas: new Set<string>(),
    };
    item.ocorrencias += group.quantidade;
    if (group.colaborador) item.pessoas.add(group.colaborador.trim().toLocaleUpperCase('pt-BR'));
    item.fallback += groupFallback(group);
    if (group.ultima_ocorrencia && (!item.ultima_ocorrencia || group.ultima_ocorrencia > item.ultima_ocorrencia))
      item.ultima_ocorrencia = group.ultima_ocorrencia;
    byType.set(group.tipo_problema, item);
  }
  return [...byType.values()]
    .map(({ pessoas, ...item }) => ({ ...item, colaboradores: pessoas.size }))
    .sort((a, b) => b.ocorrencias - a.ocorrencias || a.tipo.localeCompare(b.tipo));
}

/** Frase do aviso, no formato combinado com a operação. */
export function notificationMessage(item: WeeklyNotification) {
  const ocorrencias = item.ocorrencias === 1 ? '1 ocorrência' : `${item.ocorrencias} ocorrências`;
  const resumo = `Identificadas ${ocorrencias} ${item.tipo}.`;
  // Fallback só existe no checkout esquecido; nas demais regras a frase não o menciona.
  if (!appliesFallback(item.tipo)) return resumo;
  return `${resumo} ${item.fallback
    ? `${item.fallback} com fallback de checkout (saída considerada pela jornada).`
    : 'Nenhuma com fallback de checkout.'}`;
}

/** Apenas GETs das oportunidades efetivas já geradas pelo backend. */
export async function loadOpportunityNotifications(signal?: AbortSignal, now = new Date()): Promise<NotificationSnapshot> {
  const period = currentNotificationWeek(now);
  const window: OperationalFilters = {
    marca: OPERACAO.marca, operacao: 'EXCLUSIVA',
    periodo: 'personalizado', periodo_inicio: period.inicio, periodo_fim: period.fim,
  };
  // Só oportunidades reais (checkout ausente) viram aviso.
  const groups = await loadOpportunityGroups(window, signal, true);
  return { notifications: weeklyNotifications(groups, period), period, window };
}

export function notificationStorageKey(user: string) {
  return `pdoh:opportunity-notifications:v3:${OPERACAO.marca}:EXCLUSIVA:${encodeURIComponent(user)}`;
}

/** Nova quando surgiram ocorrências além das já vistas para a regra na semana. */
export function isNewNotification(item: WeeklyNotification, period: ResolvedPeriod, seen: SeenOpportunities) {
  return item.ocorrencias > (seen[notificationKey(item.tipo, period)] ?? 0);
}

export function markNotificationsSeen(
  seen: SeenOpportunities, items: WeeklyNotification[], period: ResolvedPeriod,
): SeenOpportunities {
  const next = { ...seen };
  for (const item of items) next[notificationKey(item.tipo, period)] = item.ocorrencias;
  return next;
}

export function parseSeenOpportunities(raw: string | null): SeenOpportunities {
  try {
    const parsed: unknown = JSON.parse(raw ?? '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter(([, value]) =>
      typeof value === 'number' && Number.isInteger(value) && value >= 0));
  } catch { return {}; }
}

/** Abre o detalhamento semanal da Dashboard na semana e regra do aviso. */
export function notificationDetailUrl(period: ResolvedPeriod, tipo?: string) {
  return `/dashboard${queryString({ monitor: 'semana', semana: period.inicio, detalhe: tipo })}`;
}
