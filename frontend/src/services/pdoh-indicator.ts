import { z } from 'zod';

/** Rota oficial de leitura da Platina. Disponibilidade e motivo vêm da API. */
export const PDOH_SUMMARY_PATH = '/pdoh/resumo';

/** Um indicador oficial: valor e variação são calculados pelo backend, nunca aqui. */
export const indicadorSchema = z.object({
  valor: z.number(),
  unidade: z.string().default('%'),
  variacao_periodo_anterior: z.number().nullable(),
});
export type Indicador = z.infer<typeof indicadorSchema>;

export const pdohDailyRowSchema = z.object({
  colaborador: z.string(),
  estado: z.string().nullable(),
  data: z.string(),
  nome_do_dia: z.string().nullable(),
  deslocamento: z.string().nullable(),
  ocio: z.string().nullable(),
  produtividade: z.string().nullable(),
  horas_nao_registradas: z.string().nullable(),
  horas_programadas: z.string().nullable(),
  primeiro_checkin: z.string().nullable(),
  ultimo_checkout: z.string().nullable(),
  visitas: z.number().int(),
  visitas_realizadas: z.number().int(),
  pesquisas: z.number().int(),
  pesquisas_realizadas: z.number().int(),
  percentuais: z.object({
    produtividade: z.number().nullable(),
    visitas: z.number().nullable(),
    pesquisas: z.number().nullable(),
    efetividade: z.number().nullable(),
  }),
  jornada: z.object({
    fonte: z.string().nullable(),
    horario_aplicado: z.string().nullable(),
    houve_fallback: z.boolean().nullable(),
    origem_fallback: z.string().nullable(),
    // Resolução oficial vigente na data da linha; o fallback do processador PDOH vem à parte.
    jornada_aplicada: z.string().nullable().default(null),
    origem: z.string().nullable().default(null),
    motivo: z.string().nullable().default(null),
    status_resolucao: z.string().nullable().default(null),
    data_resolucao: z.string().nullable().default(null),
    fallback_processador_pdoh: z.boolean().nullable().default(null),
  }),
  // Validação diária (somente exibição): justificativa do dia e status decidido pela API.
  justificativa: z.string().nullable().default(null),
  validacao: z.object({
    status: z.enum(['VALIDO', 'CHECKOUT_ESQUECIDO', 'DESCONSIDERADO', 'SEM_ATIVIDADE_PREVISTA']),
    considerado: z.boolean(),
    fallback_aplicado: z.boolean(),
    saida_considerada: z.string().nullable(),
    origem_saida: z.enum(['CONFIGURACAO', 'JORNADA_PADRAO']).nullable(),
    motivo: z.string(),
    gerou_oportunidade: z.boolean().default(false),
  }).nullable().default(null),
  origem_dado: z.string(),
});
export type PdohDailyRow = z.infer<typeof pdohDailyRowSchema>;
export type DayStatus = NonNullable<PdohDailyRow['validacao']>['status'];

/** Contagem da validação no período inteiro (todas as páginas). */
export const validationSummarySchema = z.object({
  dias: z.number().int().nonnegative(),
  considerados: z.number().int().nonnegative(),
  validos: z.number().int().nonnegative(),
  checkout_esquecido: z.number().int().nonnegative(),
  fallback_aplicado: z.number().int().nonnegative(),
  desconsiderados: z.number().int().nonnegative(),
  sem_atividade_prevista: z.number().int().nonnegative(),
  colaboradores: z.number().int().nonnegative(),
  oportunidades: z.number().int().nonnegative().default(0),
  justificativas: z.record(z.string(), z.number().int().nonnegative()),
});
export type ValidationSummary = z.infer<typeof validationSummarySchema>;

/**
 * Contrato de GET /api/v2/pdoh/resumo.
 *
 * `percentual` e `motivo` já são entregues hoje. `indicadores` e `evolucao` são os
 * campos previstos para a composição do PDOH (produtividade, ócio, deslocamento,
 * horas não registradas) e para a curva semanal: enquanto o backend não os publicar,
 * chegam ausentes e a tela mostra o estado "aguardando fonte oficial". Em nenhuma
 * hipótese o navegador estima esses números.
 */
export const pdohSummarySchema = z.object({
  marca: z.string().nullable().optional(),
  disponivel: z.boolean(),
  motivo: z.string().nullable(),
  percentual: z.number().nullable(),
  variacao_periodo_anterior: z.number().nullable(),
  periodo: z.object({ inicio: z.string(), fim: z.string() }),
  fonte: z.string().nullable().optional(),
  cobertura: z.object({
    tabela: z.string().nullable(),
    acessivel: z.boolean(),
    registros_no_periodo: z.number().int().nonnegative(),
    colaboradores_no_periodo: z.number().int().nonnegative(),
    dias_no_periodo: z.number().int().nonnegative(),
    indicadores_disponiveis: z.array(z.string()),
    // O que a fonte oficial cobre, independentemente do período pedido.
    disponivel_de: z.string().nullable().optional(),
    disponivel_ate: z.string().nullable().optional(),
  }).optional(),
  // True quando a API escolheu o período (semana mais recente com dados).
  periodo_automatico: z.boolean().default(false),
  efetividade: indicadorSchema.nullable().optional(),
  indicadores: z
    .object({
      produtividade: indicadorSchema.nullable().optional(),
      ocio: indicadorSchema.nullable().optional(),
      deslocamento: indicadorSchema.nullable().optional(),
      horas_nao_registradas: indicadorSchema.nullable().optional(),
    })
    .nullable()
    .optional(),
  evolucao: z
    .array(z.object({ data: z.string(), percentual: z.number() }))
    .nullable()
    .optional(),
  detalhes: z.object({
    items: z.array(pdohDailyRowSchema),
    total: z.number().int().nonnegative(),
    pagina: z.number().int().positive(),
    tamanho: z.number().int().positive(),
    paginas: z.number().int().nonnegative(),
  }).default({ items: [], total: 0, pagina: 1, tamanho: 50, paginas: 0 }),
  filtros_disponiveis: z.object({
    colaboradores: z.array(z.string()),
    estados: z.array(z.string()),
  }).default({ colaboradores: [], estados: [] }),
  validacao: validationSummarySchema.nullable().default(null),
});
export type PdohSummary = z.infer<typeof pdohSummarySchema>;

/** Granularidade da curva. A API agrupa; o navegador só escolhe a janela. */
export type Granularidade = 'dia' | 'semana' | 'mes';
export const GRANULARIDADES: { valor: Granularidade; rotulo: string }[] = [
  { valor: 'dia', rotulo: 'Dia' },
  { valor: 'semana', rotulo: 'Semana' },
  { valor: 'mes', rotulo: 'Mês' },
];

export const PDOH_TREND_PATH = '/pdoh/evolucao';

/** Contrato de GET /api/v2/pdoh/evolucao. Sem série oficial, `pontos` vem vazio. */
export const pdohTrendSchema = z.object({
  marca: z.string().nullable(),
  periodo: z.object({ inicio: z.string(), fim: z.string() }),
  granularidade: z.enum(['dia', 'semana', 'mes']),
  disponivel: z.boolean(),
  motivo: z.string().nullable(),
  fonte: z.string().nullable().optional(),
  pontos: z.array(
    z.object({
      periodo: z.string(),
      inicio: z.string(),
      fim: z.string(),
      pdoh: z.number(),
    }),
  ),
});
export type PdohTrend = z.infer<typeof pdohTrendSchema>;

export const PDOH_UNAVAILABLE_MESSAGE =
  'Dados de PDOH indisponíveis para o período selecionado';
export const INDICADOR_UNAVAILABLE_MESSAGE = 'Aguardando fonte oficial';

/**
 * Por que não há número. São três situações diferentes e a tela não pode confundi-las:
 * - `sem_periodo`: a fonte existe e está acessível, mas não tem linhas neste período;
 * - `sem_fonte`: a fonte oficial não está acessível para a marca;
 * - `aguardando`: resposta sem o indicador (contrato ainda não publicado).
 */
export type PdohMotivoIndisponivel = 'sem_periodo' | 'sem_fonte' | 'aguardando';

export type PdohIndicatorState =
  | {
      status: 'indisponivel';
      message: string;
      motivo: PdohMotivoIndisponivel;
      /** Intervalo que a fonte cobre, para oferecer o atalho "ver dados disponíveis". */
      disponivel: { de: string; ate: string } | null;
    }
  | { status: 'disponivel'; percentual: number; variacao: number | null };

export const ROTULO_SEM_PERIODO = 'Sem registros no período';
export const ROTULO_SEM_FONTE = 'Fonte oficial indisponível';

/**
 * Sem fonte oficial o estado é sempre indisponível. Nunca usa média de cards,
 * contagem de impactadores, valor fixo ou mock para preencher o layout.
 */
export function pdohIndicatorState(summary: PdohSummary | null): PdohIndicatorState {
  if (!summary?.disponivel || summary.percentual === null) {
    const cobertura = summary?.cobertura;
    const disponivel =
      cobertura?.disponivel_de && cobertura?.disponivel_ate
        ? { de: cobertura.disponivel_de, ate: cobertura.disponivel_ate }
        : null;
    const motivo: PdohMotivoIndisponivel = !summary
      ? 'aguardando'
      : cobertura && !cobertura.acessivel
        ? 'sem_fonte'
        : cobertura && cobertura.registros_no_periodo === 0
          ? 'sem_periodo'
          : 'aguardando';
    return {
      status: 'indisponivel',
      message: summary?.motivo || PDOH_UNAVAILABLE_MESSAGE,
      motivo,
      disponivel,
    };
  }
  return {
    status: 'disponivel',
    percentual: summary.percentual,
    variacao: summary.variacao_periodo_anterior,
  };
}

/** Texto curto para o cartão de indicador sem valor, conforme o motivo real. */
export function rotuloIndicadorVazio(state: PdohIndicatorState): string {
  if (state.status === 'disponivel') return INDICADOR_UNAVAILABLE_MESSAGE;
  if (state.motivo === 'sem_periodo') return ROTULO_SEM_PERIODO;
  if (state.motivo === 'sem_fonte') return ROTULO_SEM_FONTE;
  return INDICADOR_UNAVAILABLE_MESSAGE;
}

export type ComposicaoPdoh = {
  chave: 'produtividade' | 'ocio' | 'deslocamento' | 'horas_nao_registradas';
  rotulo: string;
  descricao: string;
  indicador: Indicador | null;
};

const COMPOSICAO: Omit<ComposicaoPdoh, 'indicador'>[] = [
  { chave: 'produtividade', rotulo: 'Produtividade', descricao: 'Tempo aplicado na operação' },
  { chave: 'ocio', rotulo: 'Ócio', descricao: 'Tempo sem atividade registrada' },
  { chave: 'deslocamento', rotulo: 'Deslocamento', descricao: 'Tempo entre pontos de venda' },
  { chave: 'horas_nao_registradas', rotulo: 'Horas não registradas', descricao: 'Jornada sem registro correspondente' },
];

/** Composição do PDOH na ordem de leitura. Indicador nulo = sem fonte, não é zero. */
export function composicaoPdoh(summary: PdohSummary | null): ComposicaoPdoh[] {
  return COMPOSICAO.map((item) => ({
    ...item,
    indicador: summary?.indicadores?.[item.chave] ?? null,
  }));
}
