import { z } from 'zod';
import { apiRequest, apiSend } from './pdoh-api.ts';

const operatorOptionSchema = z.object({ codigo: z.string(), rotulo: z.string() });
const scheduleSchema = z.object({
  id: z.string().nullable().optional(), nome_jornada: z.string().nullable().optional(),
  intervalo: z.string().nullable().optional(),
  origem_configuracao: z.enum(['CADASTRO_OPERACIONAL', 'MANUAL']).optional(),
  jornada: z.number(), disponivel: z.boolean(), ativo: z.boolean(),
  hora_entrada_padrao: z.string().nullable(), hora_saida_padrao: z.string().nullable(),
});
const conditionSchema = z.object({
  tipo: z.string(),
  ordem: z.number().int(),
  papel_fonte: z.string(),
  campo_logico: z.string(),
  operador: z.string(),
  valor_esperado: z.unknown().nullable(),
  descricao: z.string(),
  status: z.string(),
  // Vocabulário de negócio vindo do motor de regras; a tela não traduz nada por conta própria.
  campo_rotulo: z.string().nullable().default(null),
  operador_rotulo: z.string().nullable().default(null),
  texto: z.string().nullable().default(null),
  operadores: z.array(operatorOptionSchema).default([]),
  editavel: z.boolean().default(true),
});
const treatmentSchema = z.object({
  resultado: z.string(),
  acao_recomendada: z.string(),
  destino: z.string(),
  gera_oportunidade: z.boolean(),
  status: z.string(),
});
const ruleSourceSchema = z.object({
  papel: z.string(),
  rotulo: z.string(),
  tabela: z.string().nullable().default(null),
  campo: z.string().nullable().default(null),
  campo_rotulo: z.string().nullable().default(null),
});
const governanceRuleSchema = z.object({
  modelo_configuracao: z.string().default('CONDICAO'),
  jornadas: z.array(scheduleSchema).default([]),
  monitoramento: z.object({ fonte: z.string(), campo: z.string(), ultima_atualizacao: z.string().nullable(), colaboradores_analisados: z.number().nullable(), motivo: z.string().nullable() }).nullable().default(null),
  // Jornada padrão do motor (em código) para colaborador sem jornada no cadastro; só leitura.
  jornada_padrao: z.object({ jornada: z.number(), hora_entrada_padrao: z.string(), hora_saida_padrao: z.string(), origem: z.string() }).nullable().default(null),
  configuracao_id: z.string(),
  nome_regra: z.string(),
  codigo_interno: z.string(),
  categoria: z.string(),
  status: z.string(),
  prioridade: z.number().int(),
  tempo_minimo_minutos: z.number().int().default(0),
  // Mesma definição de "ativa" e "gera" que a esteira e a fila usam.
  ativa: z.boolean().default(false),
  gera_oportunidade: z.boolean().default(false),
  motivo_sem_geracao: z.string().nullable().default(null),
  fonte: ruleSourceSchema.nullable().default(null),
  descricao: z.string(),
  comportamento_esperado: z.string(),
  regra_catalogo_id: z.string().nullable(),
  geracao_automatica_ativa: z.boolean(),
  condicoes: z.array(conditionSchema),
  excecoes: z.array(conditionSchema),
  tratativas: z.array(treatmentSchema),
  atualizado_em: z.string(),
});
const semanticSourceSchema = z.object({
  papel: z.string(),
  tipo: z.string(),
  prioridade: z.number().int(),
  schema_fisico: z.string().nullable(),
  tabela_fisica: z.string().nullable(),
  mapeamento_campos: z.record(z.string(), z.unknown()),
  status: z.string(),
  descricao: z.string().nullable(),
});
const availableFieldSchema = z.object({
  papel_fonte: z.string(),
  campo_logico: z.string(),
  rotulo: z.string(),
  tipo: z.string(),
  operadores: z.array(operatorOptionSchema),
});
export type AvailableField = z.infer<typeof availableFieldSchema>;
const journeyPrioritySchema = z.object({
  prioridade: z.number().int(),
  origem_codigo: z.string(),
  papel_fonte: z.string(),
  fallback: z.boolean(),
  status: z.string(),
  aplicado_no_processamento: z.boolean(),
  descricao: z.string(),
});
const governanceHistorySchema = z.object({
  id: z.number().int(),
  entidade_tipo: z.string(),
  codigo_referencia: z.string().nullable(),
  acao: z.string(),
  valor_anterior: z.unknown().nullable(),
  valor_novo: z.unknown().nullable(),
  usuario: z.string(),
  motivo: z.string(),
  registrado_em: z.string(),
});

export const operationGovernanceSchema = z.object({
  jornadas_disponiveis: z.array(scheduleSchema).default([]),
  marca: z.string(),
  operacao: z.string(),
  descricao: z.string(),
  somente_leitura: z.boolean(),
  jornada: z.array(
    z.object({
      tabela: z.string(),
      prioridade: z.number().int(),
      campo_jornada: z.string().nullable(),
      campo_perfil: z.string().nullable(),
      campo_horas: z.string().nullable(),
    }),
  ),
  perfis_operacionais: z.array(z.string()).default([]),
  fallback: z.array(
    z.object({
      regra: z.string(),
      escopo: z.string(),
      chave: z.string(),
      valor_fallback: z.string(),
      vigencia_inicio: z.string(),
      vigencia_fim: z.string().nullable(),
      status: z.string(),
    }),
  ),
  regras_governanca: z.array(governanceRuleSchema),
  fontes_semanticas: z.array(semanticSourceSchema),
  // Vocabulário que a tela de criação oferece no "Campo analisado": só o que já tem fonte mapeada.
  campos_disponiveis: z.array(availableFieldSchema).default([]),
  prioridade_jornada: z.array(journeyPrioritySchema),
  historico_governanca: z.array(governanceHistorySchema),
  parametros: z.object({ semana_operacional: z.string() }).nullable().default(null),
  atualizado_em: z.string().nullable(),
});

export type OperationGovernance = z.infer<typeof operationGovernanceSchema>;
export type GovernanceRule = z.infer<typeof governanceRuleSchema>;
export type GovernanceCondition = z.infer<typeof conditionSchema>;
export type GovernanceHistoryEvent = z.infer<typeof governanceHistorySchema>;
export type GovernanceTab =
  | 'regras'
  | 'jornada'
  | 'fallback'
  | 'fontes'
  | 'tratativas'
  | 'historico';

export function loadOperationGovernance(signal?: AbortSignal) {
  return apiRequest(
    '/configuracoes/operacao?marca=BRACELL&operacao=EXCLUSIVA',
    operationGovernanceSchema,
    signal,
    'v2',
  );
}

// ---------------------------------------------------------------------------- edição de regra
export type RuleEditBody = {
  jornadas?: ScheduleEdit[];
  usuario: string;
  motivo: string;
  nome_regra?: string;
  descricao?: string;
  status?: 'ATIVA' | 'INATIVA';
  gerar_oportunidade?: boolean;
  tempo_minimo_minutos?: number;
  condicoes?: Array<{ ordem: number; operador: string; valor: unknown }>;
  excecoes?: Array<{ ordem: number; ativa: boolean }>;
};

const ruleChangeSchema = z.object({
  entidade: z.string(),
  referencia: z.string().nullable(),
  campo: z.string(),
  antes: z.unknown().nullable(),
  depois: z.unknown().nullable(),
});
export const ruleEditResultSchema = z.object({
  alterado: z.boolean(),
  alteracoes: z.array(ruleChangeSchema),
  regra: governanceRuleSchema,
});
export type RuleEditResult = z.infer<typeof ruleEditResultSchema>;

/** PATCH da regra CADASTRADA. Não existe criação de regra por esta rota. */
export function updateRule(codigo: string, body: RuleEditBody, signal?: AbortSignal) {
  return apiSend(
    `/configuracoes/regras/${encodeURIComponent(codigo)}?marca=BRACELL&operacao=EXCLUSIVA`,
    body,
    ruleEditResultSchema,
    signal,
    'v2',
    'PATCH',
  );
}

// ---------------------------------------------------------------------------- criação de oportunidade
export type RuleCreateBody = {
  tipo_oportunidade?: 'CONDICAO' | 'CHECKOUT_AUSENTE';
  jornadas?: ScheduleEdit[];
  usuario: string;
  motivo: string;
  nome_regra: string;
  descricao: string;
  papel_fonte: string;
  campo_logico: string;
  operador: string;
  valor: unknown;
  excecoes: number[];
  status: 'ATIVA' | 'INATIVA';
  gerar_oportunidade: boolean;
};

export type ScheduleEdit = {
  id?: string | null; nome_jornada?: string | null; intervalo?: string | null;
  origem_configuracao?: 'CADASTRO_OPERACIONAL' | 'MANUAL';
  jornada: number; ativo: boolean; hora_entrada_padrao: string | null; hora_saida_padrao: string | null;
};

export const ruleCreateResultSchema = z.object({
  criado: z.boolean(),
  alteracoes: z.array(ruleChangeSchema),
  regra: governanceRuleSchema,
});
export type RuleCreateResult = z.infer<typeof ruleCreateResultSchema>;

/** POST: cadastra a oportunidade que o usuário configurou. Sem isso, ela não existe. */
export function createRule(body: RuleCreateBody, signal?: AbortSignal) {
  return apiSend(
    '/configuracoes/regras?marca=BRACELL&operacao=EXCLUSIVA',
    body,
    ruleCreateResultSchema,
    signal,
    'v2',
    'POST',
  );
}
