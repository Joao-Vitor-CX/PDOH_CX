import { z } from 'zod';

const countSchema = z.object({ valor: z.string(), quantidade: z.number().int() });
const periodSchema = z.object({ marca: z.string(), periodo_inicio: z.string().nullable(), periodo_fim: z.string().nullable(), quantidade_execucoes: z.number().int() });

export const executionSchema = z.object({
  execution_id: z.string(), marca: z.string(), periodo_inicio: z.string().nullable(), periodo_fim: z.string().nullable(),
  status_execucao: z.string(), componente_atual: z.string().nullable(), etapa_atual: z.string().nullable(),
  iniciado_em: z.string(), finalizado_em: z.string().nullable(), linhas_recebidas: z.number().int(),
  linhas_tratadas: z.number().int(), linhas_geradas: z.number().int(), linhas_persistidas: z.number().int(),
  total_alertas: z.number().int(), total_fallbacks: z.number().int(), houve_persistencia: z.boolean(),
  erro_resumo: z.string().nullable(), versao_aplicacao: z.string().nullable(), atualizado_em: z.string(),
});
export type Execution = z.infer<typeof executionSchema>;
export const executionDetailSchema = executionSchema.extend({
  quantidade_oportunidades: z.number().int(), quantidade_etapas: z.number().int(),
  quantidade_fontes: z.number().int(), quantidade_saidas: z.number().int(),
});

export const stageSchema = z.object({
  id: z.number().int(), execution_id: z.string(), componente: z.string(), etapa: z.string(), status_etapa: z.string(),
  origem: z.string().nullable(), tabela_origem: z.string().nullable(), linhas_recebidas: z.number().int().nullable(),
  linhas_tratadas: z.number().int().nullable(), linhas_geradas: z.number().int().nullable(),
  linhas_persistidas: z.number().int().nullable(), mensagem: z.string().nullable(), contexto: z.unknown().nullable(),
  ocorrido_em: z.string(),
});
export const sourceSchema = z.object({
  id: z.number().int(), execution_id: z.string(), componente: z.string(), schema_origem: z.string(),
  tabela_origem: z.string(), filtro_periodo_inicio: z.string().nullable(), filtro_periodo_fim: z.string().nullable(),
  linhas_recebidas: z.number().int(), linhas_apos_tratamento: z.number().int(),
  duplicatas_identificadas: z.number().int(), query_hash: z.string().nullable(), registrado_em: z.string(),
});
export const lineageSchema = z.object({
  id: z.number().int(), execution_id: z.string(), marca: z.string(), tabela_destino: z.string(),
  colaborador: z.string().nullable(), data_referencia: z.string().nullable(), chave_negocio_hash: z.string(),
  linha_hash: z.string(), acao: z.string(), registrado_em: z.string(),
});

export const opportunitySchema = z.object({
  oportunidade_id: z.string(), execution_id: z.string(), marca: z.string(), data_referencia: z.string().nullable(),
  origem: z.string(), tabela_origem: z.string(), colaborador: z.string().nullable(),
  colaborador_id_interno: z.string().nullable(), tipo_problema: z.string(), regra_id: z.string().nullable(),
  descricao_detalhada: z.string(), severidade: z.string(), status_oportunidade: z.string(),
  fingerprint: z.string(), evidencia: z.unknown().nullable(), identificada_em: z.string(), atualizada_em: z.string(),
});
export type Opportunity = z.infer<typeof opportunitySchema>;
export const opportunityHistorySchema = z.object({
  id: z.number().int(), oportunidade_id: z.string(), execution_id: z.string(), status_anterior: z.string().nullable(),
  status_novo: z.string(), acao: z.string(), observacao: z.string().nullable(), responsavel: z.string().nullable(),
  contexto: z.unknown().nullable(), registrado_em: z.string(),
});
export const ruleSchema = z.object({
  classificacao: z.string().nullable(), titulo: z.string().nullable(), severidade_padrao: z.string().nullable(),
  regra_id: z.string(), marca: z.string().nullable(), tipo_problema: z.string(), descricao_cenario: z.string(),
  regra_identificacao: z.string(), tratamento_esperado: z.string(), acao_aplicacao: z.string(),
  permite_processamento: z.boolean(), necessita_aprovacao: z.boolean(), prioridade: z.number().int(),
  status_regra: z.string(), criada_em: z.string(), atualizada_em: z.string(),
});
export type Rule = z.infer<typeof ruleSchema>;
export const alertGroupSchema = z.object({
  chave_grupo: z.string(), classificacao: z.literal('ALERTA'), marca: z.string(),
  colaborador: z.string().nullable(), colaborador_id_interno: z.string().nullable(), referencia: z.string(),
  criterio_agrupamento: z.string(), quantidade_ocorrencias: z.number().int(), primeira_data: z.string().nullable(), ultima_data: z.string().nullable(),
  campos: z.array(z.object({ campo: z.string(), tipo: z.string(), situacao: z.string(), quantidade_ocorrencias: z.number().int(), amostra_ids: z.array(z.string()) })),
});
export const mappingSchema = z.object({
  de_para_id: z.string(), marca: z.string().nullable(), processo: z.string(), campo_origem: z.string(),
  valor_origem: z.string(), valor_padronizado: z.string(), descricao: z.string().nullable(), status: z.string(),
  criado_em: z.string(), atualizado_em: z.string(), responsavel: z.string().nullable(),
});
export type Mapping = z.infer<typeof mappingSchema>;
export const mappingHistorySchema = z.object({
  id: z.number().int(), de_para_id: z.string(), acao: z.string(), valor_padronizado_anterior: z.string().nullable(),
  valor_padronizado_novo: z.string().nullable(), status_anterior: z.string().nullable(), status_novo: z.string().nullable(),
  responsavel: z.string().nullable(), observacao: z.string().nullable(), registrado_em: z.string(),
});
export const collaboratorSchema = z.object({
  colaborador_id_interno: z.string(), marca: z.string(), chave_identidade: z.string(), usuario_referencia: z.string().nullable(),
  nome_referencia: z.string().nullable(), nome_normalizado: z.string().nullable(), primeira_execucao_id: z.string(),
  ultima_execucao_id: z.string(), primeira_observacao_em: z.string(), ultima_observacao_em: z.string(),
  quantidade_observacoes: z.number().int(),
});
export const opportunityDetailSchema = opportunitySchema.extend({
  diagnostico_campos: z.array(z.object({campo:z.string(), classificacao_sugerida:z.enum(['OPORTUNIDADE','ALERTA','TELEMETRIA']), impacto:z.string()})).default([]),
  execucao: executionSchema, regra_atual: ruleSchema.nullable(), identidade_colaborador: collaboratorSchema.nullable(),
  ultima_tratativa: opportunityHistorySchema.nullable(),
});
export const entitySchema = z.object({
  identificador_id: z.string(), tipo_entidade: z.string(), identificador_interno: z.string(), chave_identidade: z.string(),
  nome_original: z.string().nullable(), nome_normalizado: z.string().nullable(), origem_dado: z.string(), marca: z.string(),
  primeira_execucao_id: z.string(), ultima_execucao_id: z.string(), quantidade_observacoes: z.number().int(),
  data_criacao: z.string(), data_atualizacao: z.string(), status: z.string(),
});

export const pageSchema = <T extends z.ZodType>(item: T) => z.object({
  items: z.array(item), total: z.number().int(), pagina: z.number().int(), tamanho: z.number().int(), paginas: z.number().int(),
});
export const dashboardSchema = z.object({
  total_execucoes: z.number().int(), quantidade_oportunidades: z.number().int(),
  status_execucoes: z.array(countSchema), status_oportunidades: z.array(countSchema),
  distribuicao_por_tipo: z.array(countSchema), marcas_periodos: pageSchema(periodSchema),
  ultimas_execucoes: z.array(executionSchema), fuso_horario: z.string(),
});
export type Dashboard = z.infer<typeof dashboardSchema>;

// Resumo agregado do dashboard (v2). O período é resolvido pela API, nunca pelo navegador.
export const findingsSummarySchema = z.object({
  oportunidades: z.object({
    total: z.number().int(), critica: z.number().int(), alta: z.number().int(),
    media: z.number().int(), baixa: z.number().int(),
  }),
  alertas: z.object({ total: z.number().int() }),
  telemetria: z.object({ total: z.number().int() }),
  periodo: z.object({ inicio: z.string().nullable(), fim: z.string().nullable() }),
});
export type FindingsSummary = z.infer<typeof findingsSummarySchema>;

export class PdohApiError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}

// O navegador chama somente a origem do frontend. O proxy local adiciona o token no servidor.
export async function apiRequest<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal, version: 'v1' | 'v2' = 'v1'): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api/${version}${path}`, { headers: { Accept: 'application/json' }, signal }); }
  catch (reason) {
    if (signal?.aborted) throw reason;
    throw new PdohApiError('Não foi possível conectar à API de consulta.', 503);
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: 'A consulta não foi autorizada. Verifique a configuração do servidor da API.',
      404: 'Registro não encontrado no PDOH_CX.',
      422: 'Filtros inválidos para a consulta.',
      503: 'A API de consulta ou o banco está indisponível.',
    };
    throw new PdohApiError(messages[response.status] ?? `Consulta falhou (HTTP ${response.status}).`, response.status);
  }
  try { return schema.parse(await response.json()); }
  catch { throw new PdohApiError(`O formato recebido não corresponde ao contrato da API ${version}.`, 502); }
}

// Única escrita da plataforma: criação (POST) e alteração auditada (PATCH) de regra. O corpo leva
// `usuario` e `motivo`; o servidor valida tudo antes de gravar e responde com a mensagem que o
// líder lê (422). Sem essa escrita a oportunidade simplesmente não existe.
export async function apiSend<T>(
  path: string, body: unknown, schema: z.ZodType<T>, signal?: AbortSignal,
  version: 'v1' | 'v2' = 'v2', method: 'PATCH' | 'POST' = 'PATCH',
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/${version}${path}`, {
      method, headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal,
    });
  } catch (reason) {
    if (signal?.aborted) throw reason;
    throw new PdohApiError('Não foi possível conectar à API. Nada foi gravado.', 503);
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const detail = (payload as { detail?: unknown } | null)?.detail;
    const specific = typeof detail === 'string' ? detail
      : Array.isArray(detail) && typeof (detail[0] as { msg?: unknown } | undefined)?.msg === 'string' ? String((detail[0] as { msg: string }).msg) : null;
    const messages: Record<number, string> = {
      401: 'A operação não foi autorizada. Verifique a configuração do servidor da API.',
      404: method === 'POST' ? 'Registro não encontrado no PDOH_CX.' : 'Regra não encontrada. Esta área não cria regras pela edição.',
      422: 'A operação foi recusada pela validação.',
      503: method === 'POST' ? 'A criação de oportunidades não está habilitada neste ambiente.' : 'A edição de regras não está habilitada neste ambiente.',
    };
    throw new PdohApiError(specific ?? messages[response.status] ?? `A operação falhou (HTTP ${response.status}).`, response.status);
  }
  try { return schema.parse(await response.json()); }
  catch { throw new PdohApiError(`A operação foi enviada, mas a resposta não corresponde ao contrato da API ${version}. Recarregue a página.`, 502); }
}

export function queryString(filters: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value !== null && value !== undefined && value !== '') query.set(key, String(value));
  return query.size ? `?${query.toString()}` : '';
}
