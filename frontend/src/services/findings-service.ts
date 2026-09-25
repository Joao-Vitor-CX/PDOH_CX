import {
  fixedWindow,
  loadAlerts,
  loadAllGroups,
  v2Request,
  type OperationalFilters,
  type OperationalGroup,
} from './operational-api.ts';
import { PDOH_SUMMARY_PATH, pdohSummarySchema } from './pdoh-indicator.ts';
import { queryString } from './pdoh-api.ts';

export type { PeriodMode } from './operational-api.ts';
export type PdohFilters = OperationalFilters;
export type ImpactRow = {
  tipo: string;
  titulo: string;
  quantidade: number;
  severidade: string;
  impacto: string;
};

export type ImpactoPorRegra = {
  tipo: string;
  titulo: string;
  severidade: string;
  impacto: string | null;
  acao_recomendada: string | null;
  colaboradores: number;
  ocorrencias: number;
  grupos: number;
};

/**
 * Impactadores consolidados por regra, somando os grupos que a API já consolidou.
 * Não classifica, não deduplica e não reconta ocorrências — apenas soma o que veio.
 */
export function impactosPorRegra(groups: OperationalGroup[]): ImpactoPorRegra[] {
  const porRegra = new Map<string, ImpactoPorRegra & { pessoas: Set<string> }>();
  for (const group of groups) {
    const atual = porRegra.get(group.tipo_problema) || {
      tipo: group.tipo_problema,
      titulo: group.titulo,
      severidade: group.severidade,
      impacto: group.impacto,
      acao_recomendada: group.acao_recomendada ?? null,
      colaboradores: 0,
      ocorrencias: 0,
      grupos: 0,
      pessoas: new Set<string>(),
    };
    atual.grupos += 1;
    atual.ocorrencias += group.quantidade;
    if (group.colaborador) atual.pessoas.add(group.colaborador);
    porRegra.set(group.tipo_problema, atual);
  }
  return [...porRegra.values()]
    .map(({ pessoas, ...regra }) => ({ ...regra, colaboradores: pessoas.size }))
    .sort((a, b) => b.ocorrencias - a.ocorrencias);
}

export type ImpactoPorColaborador = {
  colaborador: string;
  severidade: string;
  ocorrencias: number;
  causas: number;
  principal: string;
};

/**
 * Ranking de colaboradores dentro do período. A severidade exibida é a do primeiro
 * grupo da pessoa: a API entrega a fila ordenada por severidade, então é a mais grave.
 * Grupos sem colaborador vinculado ficam de fora — não há a quem atribuir a tratativa.
 */
export function impactosPorColaborador(
  groups: OperationalGroup[],
): ImpactoPorColaborador[] {
  const porPessoa = new Map<string, ImpactoPorColaborador>();
  for (const group of groups) {
    if (!group.colaborador) continue;
    const atual = porPessoa.get(group.colaborador) || {
      colaborador: group.colaborador,
      severidade: group.severidade,
      ocorrencias: 0,
      causas: 0,
      principal: group.titulo,
    };
    atual.causas += 1;
    atual.ocorrencias += group.quantidade;
    porPessoa.set(group.colaborador, atual);
  }
  return [...porPessoa.values()].sort((a, b) => b.ocorrencias - a.ocorrencias);
}

/** Soma grupos já consolidados pela API. Não resolve regras nem deduplica ocorrências. */
export function summarizeGroups(groups: OperationalGroup[]) {
  const severities = new Map<string, number>();
  let occurrences = 0;
  for (const group of groups) {
    occurrences += group.quantidade;
    severities.set(
      group.severidade,
      (severities.get(group.severidade) || 0) + 1,
    );
  }
  const peak = Math.max(0, ...severities.values());
  return {
    cards: groups.length,
    occurrences,
    severities: [...severities].map(([name, count]) => ({ name, count })),
    predominant: [...severities]
      .filter(([, count]) => count === peak)
      .map(([name]) => name),
  };
}

export async function loadPdohOverview(
  filters: OperationalFilters,
  signal?: AbortSignal,
) {
  const pdoh = await v2Request(
    `${PDOH_SUMMARY_PATH}${queryString(filters)}`,
    pdohSummarySchema,
    signal,
  );
  const period = pdoh.periodo;
  const fixed = fixedWindow(filters, period);
  const window: OperationalFilters = {
    marca: fixed.marca,
    operacao: fixed.operacao,
    colaborador: fixed.colaborador,
    periodo: 'personalizado',
    periodo_inicio: period.inicio,
    periodo_fim: period.fim,
  };
  // Telemetria é auditoria técnica: a tela do líder não a exibe, então não é consultada aqui.
  // O resultado oficial do PDOH (Platina) nunca depende das causas: se impactadores ou alertas
  // falharem, o indicador continua na tela e só essas seções avisam a indisponibilidade.
  const [groupsResult, alertsResult] = await Promise.allSettled([
    loadAllGroups(window, signal),
    loadAlerts(window, signal),
  ]);
  signal?.throwIfAborted();
  const groups = groupsResult.status === 'fulfilled' ? groupsResult.value : null;
  const alerts = alertsResult.status === 'fulfilled' ? alertsResult.value : null;
  return {
    period,
    pdoh,
    groups,
    impactos: groups ? impactosPorRegra(groups.items) : null,
    opportunities: groups ? summarizeGroups(groups.items) : null,
    alerts: alerts
      ? {
          total: alerts.resumo.grupos,
          colaboradores: alerts.resumo.colaboradores_afetados,
          // Categorias já consolidadas pela API, na ordem que ela entregou.
          categorias: alerts.resumo.por_regra,
        }
      : null,
  };
}
export type PdohOverview = Awaited<ReturnType<typeof loadPdohOverview>>;
