import { z } from 'zod';
import { OPERACAO } from '../lib/operacao.ts';
import { apiRequest, pageSchema, queryString } from './pdoh-api.ts';

export type PeriodMode =
  | 'automatico'
  | 'hoje'
  | 'ontem'
  | 'semana'
  | 'ultimos_7_dias'
  | 'ultimos_30_dias'
  | 'mes'
  | 'tres_meses'
  | 'doze_meses'
  | 'personalizado'
  | 'relativo';
export type OperationalFilters = {
  marca?: string;
  operacao?: string;
  periodo?: PeriodMode;
  periodo_inicio?: string;
  periodo_fim?: string;
  colaborador?: string;
  estado?: string;
  periodo_quantidade?: number;
  periodo_unidade?: 'dias' | 'semanas' | 'meses';
  pagina?: number;
  tamanho?: number;
  tipo?: string;
  regra?: string;
  severidade?: string;
  status?: string;
};

/** Prova resumida que o backend anexa a cada card; o navegador só exibe. */
export const evidenceSummarySchema = z.object({
  campo: z.string().nullable(),
  valor_esperado: z.string().nullable(),
  valor_encontrado: z.string().nullable(),
  fonte: z.string().nullable(),
});
export type EvidenceSummary = z.infer<typeof evidenceSummarySchema>;

/** Situação da comprovação. `indisponivel` nunca é lido como aprovado. */
export const validationSchema = z.object({
  resultado: z.enum(['confirmado', 'nao_aplicavel', 'indisponivel']),
  rotulo: z.string(),
  motivo: z.string().nullable(),
  jornada_origem: z.string(),
});
export type OperationalValidation = z.infer<typeof validationSchema>;

export const groupSchema = z.object({
  grupo_id: z.string().min(1),
  marca: z.string(),
  operacao: z.string().optional(),
  campo: z.string().nullable().optional(),
  origem: z.string().nullable().optional(),
  tipo_problema: z.string(),
  titulo: z.string(),
  colaborador: z.string().nullable(),
  quantidade: z.number().int().nonnegative(),
  registros_historicos: z.number().int().nonnegative(),
  dias_afetados: z.number().int().nonnegative(),
  primeira_ocorrencia: z.string().nullable(),
  ultima_ocorrencia: z.string().nullable(),
  severidade: z.string(),
  impacto: z.string().nullable(),
  status_operacional: z.string(),
  responsavel: z.string().nullable(),
  // Contrato futuro: jamais deduzir ação pelo tipo ou pelo impacto.
  acao_recomendada: z.string().nullable().optional(),
  // Comprovação da origem, entregue pronta pelo backend.
  evidencia: evidenceSummarySchema.optional(),
  validacao: validationSchema.optional(),
});
export type OperationalGroup = z.infer<typeof groupSchema>;
export const groupPageSchema = pageSchema(groupSchema);
const findingSchema = z.object({
  id: z.string(),
  origem_registro: z.string(),
  classificacao: z.string(),
  tipo_problema: z.string(),
  marca: z.string(),
  descricao: z.string(),
  registrado_em: z.string(),
  severidade: z.string(),
  colaborador: z.string().nullable(),
  campo: z.string().nullable(),
  tratativa: z.string().nullable(),
});
// Valida o contrato de cada endpoint. Uma categoria cruzada é um erro, não é reclassificada.
export const alertPageSchema = pageSchema(
  findingSchema.extend({ classificacao: z.literal('ALERTA') }),
);
export const telemetryPageSchema = pageSchema(
  findingSchema.extend({ classificacao: z.literal('TELEMETRIA') }),
);
export type Finding = z.infer<typeof findingSchema>;
export const periodSummarySchema = z.object({
  periodo: z.object({ inicio: z.string(), fim: z.string() }),
});
export type ResolvedPeriod = z.infer<typeof periodSummarySchema>['periodo'];

export const alertSummarySchema = z.object({
  periodo: z.object({ inicio: z.string(), fim: z.string() }),
  grupos: z.number().int().nonnegative(),
  alertas: z.number().int().nonnegative(),
  ocorrencias_acumuladas: z.number().int().nonnegative(),
  colaboradores_afetados: z.number().int().nonnegative(),
  por_regra: z.array(z.object({ tipo_problema: z.string(), titulo: z.string(),
    grupos: z.number().int().nonnegative(), alertas: z.number().int().nonnegative(),
    ocorrencias_acumuladas: z.number().int().nonnegative(), colaboradores_afetados: z.number().int().nonnegative(),
    severidade: z.string() })),
});

export type AlertCategory = z.infer<typeof alertSummarySchema>['por_regra'][number];

export const alertGroupSchema = z.object({
  grupo_id: z.string().min(1),
  marca: z.string(),
  tipo_problema: z.string(),
  titulo: z.string(),
  colaborador: z.string().nullable(),
  campo: z.string().nullable(),
  origem: z.string().nullable(),
  quantidade_alertas: z.number().int().nonnegative(),
  ocorrencias_acumuladas: z.number().int().nonnegative(),
  registros_historicos: z.number().int().nonnegative(),
  dias_afetados: z.number().int().nonnegative(),
  primeira_ocorrencia: z.string().nullable(),
  ultima_ocorrencia: z.string().nullable(),
  severidade: z.string(),
  impacto: z.string().nullable(),
  acao_recomendada: z.string().nullable(),
  evidencia: evidenceSummarySchema.optional(),
  validacao: validationSchema.optional(),
});
export type AlertGroup = z.infer<typeof alertGroupSchema>;

export function v2Request<T>(
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
) {
  return apiRequest(path, schema, signal, 'v2');
}
export function periodFilters(filters: OperationalFilters): OperationalFilters {
  return {
    marca: filters.marca,
    operacao: filters.operacao,
    periodo:
      filters.periodo ??
      (filters.periodo_inicio || filters.periodo_fim
        ? 'personalizado'
        : 'automatico'),
    periodo_inicio: filters.periodo_inicio,
    periodo_fim: filters.periodo_fim,
    periodo_quantidade: filters.periodo_quantidade,
    periodo_unidade: filters.periodo_unidade,
  };
}
export async function resolvePeriod(
  filters: OperationalFilters,
  signal?: AbortSignal,
) {
  const result = await v2Request(
    `/findings/resumo${queryString(periodFilters(filters))}`,
    periodSummarySchema,
    signal,
  );
  return result.periodo;
}
export function fixedWindow(
  filters: OperationalFilters,
  period: ResolvedPeriod,
): OperationalFilters {
  return {
    ...filters,
    periodo: 'personalizado',
    periodo_inicio: period.inicio,
    periodo_fim: period.fim,
  };
}
export function loadGroups(
  filters: OperationalFilters,
  page = 1,
  size = 12,
  signal?: AbortSignal,
) {
  return v2Request(
    `/oportunidades/resumo${queryString({ ...filters, pagina: page, tamanho: size })}`,
    groupPageSchema,
    signal,
  );
}

/** Indicadores só são exibidos após ler todas as páginas. A fila usa paginação no servidor. */
export async function loadAllPages<T>(
  path: string,
  filters: Record<string, string | number | undefined>,
  schema: z.ZodType<T>,
  identity: (item: T) => string,
  signal?: AbortSignal,
) {
  const contract = pageSchema(schema);
  const first = await v2Request(
    `${path}${queryString({ ...filters, pagina: 1, tamanho: 200 })}`,
    contract,
    signal,
  );
  if (first.paginas > 100)
    throw new Error(
      'O período possui muitos registros para o resumo completo. Refine a marca ou as datas.',
    );
  const pages = [first];
  for (let start = 2; start <= first.paginas; start += 4) {
    signal?.throwIfAborted();
    const batch = await Promise.all(
      Array.from(
        { length: Math.min(4, first.paginas - start + 1) },
        (_, offset) =>
          v2Request(
            `${path}${queryString({ ...filters, pagina: start + offset, tamanho: 200 })}`,
            contract,
            signal,
          ),
      ),
    );
    pages.push(...batch);
  }
  const items = pages.flatMap((page) => page.items);
  if (
    pages.some(
      (page) => page.total !== first.total || page.paginas !== first.paginas,
    ) ||
    items.length !== first.total ||
    new Set(items.map(identity)).size !== items.length
  ) {
    throw new Error(
      'Os dados mudaram durante a consulta. Atualize para obter o resumo completo.',
    );
  }
  return { ...first, items };
}
export function loadAllGroups(
  filters: OperationalFilters,
  signal?: AbortSignal,
  includeClosed = false,
) {
  return loadAllPages(
    '/oportunidades/resumo',
    { ...filters, ...(includeClosed ? { incluir_encerradas: 'true' } : {}) },
    groupSchema,
    (item) => item.grupo_id,
    signal,
  );
}
export function loadAlerts(filters: OperationalFilters, signal?: AbortSignal) {
  return v2Request(`/alertas/resumo${queryString({ ...filters, tamanho: 1 })}`,
    z.object({ total: z.number().int().nonnegative(), resumo: alertSummarySchema }), signal);
}
/** Página de pendências cadastrais; o bloco `resumo` cobre todo o filtro, não só a página. */
export function loadAlertGroups(
  filters: OperationalFilters,
  page = 1,
  size = 12,
  signal?: AbortSignal,
) {
  return v2Request(
    `/alertas/resumo${queryString({ ...filters, pagina: page, tamanho: size })}`,
    pageSchema(alertGroupSchema).extend({ resumo: alertSummarySchema }),
    signal,
  );
}

export function loadTelemetry(
  filters: OperationalFilters,
  signal?: AbortSignal,
) {
  return v2Request(
    `/telemetria${queryString({ ...periodFilters(filters), tamanho: 3 })}`,
    telemetryPageSchema,
    signal,
  );
}
export function filtersFromSearch(
  search: URLSearchParams,
  brand?: string,
): OperationalFilters {
  const result: OperationalFilters = {};
  for (const field of [
    'marca',
    'operacao',
    'colaborador',
    'estado',
    'tipo',
    'regra',
    'severidade',
    'status',
    'periodo_inicio',
    'periodo_fim',
  ] as const) {
    const value = search.get(field);
    if (value) result[field] = value;
  }
  for (const field of ['periodo_quantidade', 'pagina', 'tamanho'] as const) {
    const value = Number(search.get(field));
    if (Number.isInteger(value) && value > 0) result[field] = value;
  }
  const unidade = search.get('periodo_unidade');
  if (unidade === 'dias' || unidade === 'semanas' || unidade === 'meses')
    result.periodo_unidade = unidade;
  // A operação atendida define a marca; a interface não oferece seletor.
  result.marca = brand || result.marca || OPERACAO.marca;
  const mode = search.get('periodo');
  const modes: PeriodMode[] = [
    'automatico', 'hoje', 'ontem', 'semana', 'ultimos_7_dias', 'ultimos_30_dias', 'mes',
    'tres_meses', 'doze_meses', 'personalizado', 'relativo',
  ];
  result.periodo =
    modes.includes(mode as PeriodMode)
      ? (mode as PeriodMode)
      : result.periodo_inicio || result.periodo_fim
        ? 'personalizado'
        // Sem escolha do usuário a API abre no período mais recente com dados.
        : 'automatico';
  return result;
}
export function groupDetailsPath(groupId: string) {
  return `/oportunidades/${encodeURIComponent(groupId)}/detalhes`;
}

export const occurrenceSchema = z.object({
  fingerprint: z.string(),
  oportunidade_id: z.string(),
  execution_id: z.string(),
  data_referencia: z.string().nullable(),
  tabela_origem: z.string(),
  origem: z.string(),
  severidade: z.string(),
  evidencia: z.unknown().nullable(),
  identificada_em: z.string(),
  // Regravações do mesmo achado pelo reprocessamento; o backend já consolidou.
  repeticoes: z.number().int().nonnegative(),
});
export type Occurrence = z.infer<typeof occurrenceSchema>;

export const groupDetailSchema = z.object({
  grupo_id: z.string(),
  marca: z.string(),
  tipo_problema: z.string(),
  titulo: z.string(),
  colaborador: z.string().nullable(),
  colaborador_id_interno: z.string().nullable(),
  campo: z.string().nullable(),
  origem: z.string().nullable(),
  quantidade: z.number().int().nonnegative(),
  impacto: z.string().nullable(),
  acao_recomendada: z.string().nullable(),
  status_operacional: z.string(),
  periodo: z.object({ inicio: z.string(), fim: z.string() }),
  ocorrencias: pageSchema(occurrenceSchema),
});
export type GroupDetail = z.infer<typeof groupDetailSchema>;

const evidenceLineSchema = z.object({
  fonte: z.string().nullable(),
  campo: z.string().nullable(),
  valor_encontrado: z.string().nullable(),
  valor_esperado: z.string().nullable(),
  validacao: z.string(),
  atendido: z.boolean().nullable(),
});
export type EvidenceLine = z.infer<typeof evidenceLineSchema>;

const evidenceOccurrenceSchema = z.object({
  regra: z.string(),
  colaborador: z.string().nullable(),
  data: z.string().nullable(),
  resultado_validacao: z.string(),
  fonte: z.string().nullable(),
  campo: z.string().nullable(),
  valor_esperado: z.string().nullable(),
  valor_encontrado: z.string().nullable(),
  motivo: z.string().nullable(),
  impacto: z.string().nullable(),
  tratativa: z.string().nullable(),
  jornada_origem: z.string(),
});
export type EvidenceOccurrence = z.infer<typeof evidenceOccurrenceSchema>;

export const groupEvidenceSchema = z.object({
  oportunidade: z.object({
    grupo_id: z.string(),
    regra: z.string(),
    titulo: z.string(),
    impacto: z.string().nullable(),
    colaborador: z.string().nullable(),
    campo: z.string().nullable(),
    origem: z.string().nullable(),
    quantidade: z.number().int().nonnegative(),
    status_operacional: z.string(),
    periodo: z.object({ inicio: z.string(), fim: z.string() }),
  }),
  validacao: validationSchema.extend({
    justificativa: z.boolean().nullable(),
    atestado: z.boolean().nullable(),
    ocorrencias_comprovadas: z.number().int().nonnegative(),
    ocorrencias_avaliadas: z.number().int().nonnegative(),
  }),
  fonte: z.object({
    papel: z.string().nullable(),
    tabela: z.string().nullable(),
    campo: z.string().nullable(),
    valor_esperado: z.string().nullable(),
    criterios: z.array(z.string()),
  }),
  // Regra configurável que gerou a oportunidade: a fonte com nome de negócio e a configuração usada.
  regra_aplicada: z
    .object({
      codigo: z.string(),
      nome: z.string().nullable(),
      fonte: z.string().nullable(),
      fonte_tabela: z.string().nullable(),
      campo: z.string().nullable(),
      esperado: z.string().nullable(),
      encontrado: z.string().nullable(),
      resultado: z.string().nullable(),
    })
    .nullable()
    .default(null),
  evidencias: z.array(evidenceLineSchema),
  tratamento: z.object({
    acao_recomendada: z.string().nullable(),
    responsavel: z.string().nullable(),
  }),
  ocorrencias: z.array(evidenceOccurrenceSchema).default([]),
});
export type GroupEvidence = z.infer<typeof groupEvidenceSchema>;

/** Comprovação da oportunidade. A janela é a mesma da fila; nada é recalculado aqui. */
export function loadGroupEvidence(
  groupId: string,
  window: OperationalFilters,
  signal?: AbortSignal,
) {
  return v2Request(
    `/oportunidades/${encodeURIComponent(groupId)}/evidencias${queryString(window)}`,
    groupEvidenceSchema,
    signal,
  );
}

/** Detalhe do grupo operacional. A janela é a mesma da fila; nada é recalculado aqui. */
export function loadGroupDetails(
  groupId: string,
  window: OperationalFilters,
  signal?: AbortSignal,
  size = 50,
  page = 1,
) {
  return v2Request(
    `${groupDetailsPath(groupId)}${queryString({ ...window, pagina: page, tamanho: size })}`,
    groupDetailSchema,
    signal,
  );
}
