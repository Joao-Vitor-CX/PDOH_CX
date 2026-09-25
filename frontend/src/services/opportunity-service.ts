import {
  apiRequest,
  dashboardSchema,
  opportunitySchema,
  pageSchema,
  queryString,
  ruleSchema,
  type Rule,
} from './pdoh-api.ts';
import {
  catalogKind,
  type OpportunityKind,
} from '../lib/opportunity-presentation.ts';

export type OpportunityFilters = {
  marca?: string;
  periodo_inicio?: string;
  periodo_fim?: string;
  status?: string;
  execution_id?: string;
  tipo?: string;
};
export type OpportunityGroup = {
  id: string;
  rule: Rule;
  kind: OpportunityKind;
  total: number;
  open: number;
};
export async function mapLimited<T, U>(
  items: T[],
  task: (item: T) => Promise<U>,
): Promise<U[]> {
  const output: U[] = [];
  let cursor = 0;
  await Promise.all(
    Array.from({ length: Math.min(4, items.length) }, async () => {
      while (cursor < items.length) {
        const index = cursor++;
        output[index] = await task(items[index]);
      }
    }),
  );
  return output;
}
export async function loadCatalog(signal?: AbortSignal) {
  const first = await apiRequest(
    '/regras?tamanho=200',
    pageSchema(ruleSchema),
    signal,
  );
  const rest = await mapLimited(
    Array.from({ length: Math.max(0, first.paginas - 1) }, (_, i) => i + 2),
    (pagina) =>
      apiRequest(
        `/regras${queryString({ tamanho: 200, pagina })}`,
        pageSchema(ruleSchema),
        signal,
      ),
  );
  const rules = [first, ...rest].flatMap((page) => page.items);
  if (
    rules.length !== first.total ||
    new Set(rules.map((rule) => rule.regra_id)).size !== rules.length
  ) {
    throw new Error(
      'O catálogo mudou durante a consulta. Atualize para conferir a classificação.',
    );
  }
  return rules;
}
export const opportunityService = {
  list(
    filters: OpportunityFilters & {
      regra?: string;
      pagina?: number;
      tamanho?: number;
    },
    signal?: AbortSignal,
  ) {
    return apiRequest(
      `/oportunidades${queryString(filters)}`,
      pageSchema(opportunitySchema),
      signal,
    );
  },
  async summary(filters: OpportunityFilters, signal?: AbortSignal) {
    const [rules, before] = await Promise.all([
      loadCatalog(signal),
      this.list({ ...filters, tamanho: 1 }, signal),
    ]);
    const groups = await mapLimited(
      rules.filter(
        (rule) => !filters.tipo || rule.tipo_problema === filters.tipo,
      ),
      async (rule) => {
        // Contagem por vínculo real. Não resolve precedência de regra no navegador.
        const query = {
          ...filters,
          regra: rule.regra_id,
          tipo: rule.tipo_problema,
          tamanho: 1,
        };
        const page = await this.list(query, signal);
        const kind = catalogKind(rule);
        const open =
          kind === 'operacional' && page.total > 0
            ? filters.status
              ? filters.status.toUpperCase() === 'ABERTA'
                ? page.total
                : 0
              : (await this.list({ ...query, status: 'ABERTA' }, signal)).total
            : 0;
        return { id: rule.regra_id, rule, kind, total: page.total, open };
      },
    );
    const after = await this.list({ ...filters, tamanho: 1 }, signal);
    if (before.total !== after.total)
      throw new Error(
        'Os registros mudaram durante a consulta. Atualize para obter contagens consistentes.',
      );
    const linked = groups.reduce((sum, group) => sum + group.total, 0);
    if (linked > after.total)
      throw new Error(
        'As contagens mudaram durante a consulta. Tente atualizar.',
      );
    return {
      groups: groups
        .filter((group) => group.total > 0)
        .sort((a, b) => b.total - a.total),
      operational: groups
        .filter((g) => g.kind === 'operacional')
        .reduce((sum, g) => sum + g.total, 0),
      alerts: groups.filter((g) => g.kind === 'alerta').reduce((sum, g) => sum + g.total, 0),
      informative: groups
        .filter((g) => g.kind === 'informativo')
        .reduce((sum, g) => sum + g.total, 0),
      unclassified:
        after.total -
        linked +
        groups
          .filter((g) => g.kind === 'nao_classificado')
          .reduce((sum, g) => sum + g.total, 0),
      pending: groups.reduce((sum, group) => sum + group.open, 0),
      total: after.total,
    };
  },
  dashboard(filters: OpportunityFilters, signal?: AbortSignal) {
    const { marca, periodo_inicio, periodo_fim } = filters;
    return apiRequest(
      `/dashboard${queryString({ marca, periodo_inicio, periodo_fim, tamanho: 200 })}`,
      dashboardSchema,
      signal,
    );
  },
};
export type OpportunitySummaryData = Awaited<
  ReturnType<typeof opportunityService.summary>
>;
