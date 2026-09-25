/**
 * Lógica pura da tela de Configurações (regras de oportunidade).
 *
 * A tela não decide o que é regra ativa, nem interpreta operador: quem decide é o motor de regras
 * (`shared/rule_engine.py`) e o servidor valida tudo antes de gravar. Aqui ficam apenas:
 * o rascunho de edição, o diff que vira o corpo do PATCH, a checagem imediata de digitação e a
 * leitura humana do histórico.
 */
import type {
  AvailableField,
  GovernanceCondition,
  GovernanceHistoryEvent,
  GovernanceRule,
  RuleCreateBody,
  RuleEditBody,
  ScheduleEdit,
} from '../services/governance-api.ts';

export type RuleDraft = {
  jornadas?: ScheduleEdit[];
  nome: string;
  descricao: string;
  ativa: boolean;
  gerar: boolean;
  /** Texto do campo; só vira número na hora de enviar. */
  tempo: string;
  operador: string;
  valor: string;
  /** ordem da exceção -> marcada (a exceção barra a oportunidade). */
  excecoes: Record<number, boolean>;
};

export type RuleEditPayload = Omit<RuleEditBody, 'usuario' | 'motivo'>;
export type RuleStatusInfo = { label: string; tone: 'green' | 'slate' | 'amber'; detail: string };

const ATIVA = 'ATIVA';
const CONFIRMADO = 'CONFIRMADO';
const DURACAO = /^\s*\d{1,4}:[0-5]?\d(?::[0-5]?\d)?\s*$/;
const OPERADORES_SEM_VALOR = new Set(['IS NULL', 'IS NOT NULL']);
export const MOTIVO_MINIMO = 5;

/** Condição principal: a primeira ativa, ou a primeira cadastrada. */
export function principalCondition(rule: GovernanceRule): GovernanceCondition | null {
  return rule.condicoes.find((item) => item.status === ATIVA) ?? rule.condicoes[0] ?? null;
}

/** As demais condições da regra: só leitura nesta tela. */
export function otherConditions(rule: GovernanceRule): GovernanceCondition[] {
  const main = principalCondition(rule);
  return rule.condicoes.filter((item) => item !== main);
}

export function confirmedTreatment(rule: GovernanceRule) {
  return rule.tratativas.find((item) => item.resultado === CONFIRMADO) ?? null;
}

/** Texto de um valor cadastrado. Objetos nunca viram "[object Object]". */
function scalar(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'bigint') return value.toString();
  if (typeof value === 'boolean') return value ? 'Sim' : 'Não';
  return value === null || value === undefined ? '' : JSON.stringify(value);
}

export function displayValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(scalar).join(', ');
  return scalar(value);
}

export function draftFromRule(rule: GovernanceRule): RuleDraft {
  const main = principalCondition(rule);
  return {
    jornadas: scheduleDrafts(rule.jornadas ?? []),
    nome: rule.nome_regra,
    descricao: rule.descricao,
    ativa: rule.ativa,
    gerar: confirmedTreatment(rule)?.gera_oportunidade ?? false,
    tempo: String(rule.tempo_minimo_minutos),
    operador: main?.operador ?? '',
    valor: displayValue(main?.valor_esperado),
    excecoes: Object.fromEntries(rule.excecoes.map((item) => [item.ordem, item.status === ATIVA])),
  };
}

/** Copia os campos salvos da jornada sem descartar metadados nem preencher horários ausentes. */
export function scheduleDrafts(journeys: GovernanceRule['jornadas']): ScheduleEdit[] {
  return journeys.map(({ disponivel: _disponivel, ...item }) => ({ ...item }));
}

/** Checagem imediata de digitação. O servidor valida de novo e é quem manda. */
export function validateDraft(rule: GovernanceRule, draft: RuleDraft): Record<string, string> {
  const errors: Record<string, string> = {};
  if (draft.nome.trim().length < 3) errors.nome = 'Informe o nome da oportunidade (mínimo 3 caracteres).';
  if (draft.descricao.trim().length < 3) errors.descricao = 'Informe a descrição.';
  const tempo = Number(draft.tempo);
  if (draft.tempo.trim() === '' || !Number.isInteger(tempo) || tempo < 0 || tempo > 1440) {
    errors.tempo = 'Informe minutos inteiros, de 0 a 1440.';
  }
  const main = principalCondition(rule);
  if (rule.modelo_configuracao !== 'JORNADA' && main?.editavel && !OPERADORES_SEM_VALOR.has(draft.operador)) {
    const wasDuration = DURACAO.test(displayValue(main.valor_esperado));
    if (draft.valor.trim() === '') errors.valor = 'Informe o valor da condição.';
    else if (wasDuration && !DURACAO.test(draft.valor)) errors.valor = 'Use o formato HH:MM (por exemplo, 00:30).';
  }
  if (rule.modelo_configuracao === 'JORNADA' && !validSchedules(draft.jornadas ?? [])) errors.jornadas = 'Verifique as jornadas: jornada ativa ou manual exige entrada e saída diferentes; intervalo no formato HH:MM; carga semanal única (até 168h). Jornadas manuais também exigem nome e intervalo.';
  return errors;
}

export function validSchedules(items: ScheduleEdit[]) {
  const hora = /^([01]\d|2[0-3]):[0-5]\d$/;
  return new Set(items.map((s) => s.jornada)).size === items.length && items.every((s) =>
    Number.isFinite(s.jornada) && s.jornada > 0 && s.jornada <= 168
    && Math.abs(s.jornada * 100 - Math.round(s.jornada * 100)) < 0.000001
    && (s.origem_configuracao !== 'MANUAL' || (Boolean(s.nome_jornada?.trim()) && (s.nome_jornada?.length ?? 0) <= 120 && hora.test(s.intervalo ?? '')))
    && (!s.intervalo || hora.test(s.intervalo))
    && ((!s.ativo && s.origem_configuracao !== 'MANUAL') || (hora.test(s.hora_entrada_padrao ?? '') && hora.test(s.hora_saida_padrao ?? '') && s.hora_entrada_padrao !== s.hora_saida_padrao)));
}

const HORA_VALIDA = /^([01]\d|2[0-3]):[0-5]\d$/;

type ScheduleField = 'ativo' | 'nome_jornada' | 'jornada' | 'hora_entrada_padrao' | 'hora_saida_padrao' | 'intervalo';

/**
 * Campos que o usuário pode alterar. Jornada da operação: nome e carga vêm do cadastro, mas
 * horários, intervalo e ativação são configuração da oportunidade (o servidor já os aceita).
 */
export function scheduleEditableFields(item: Pick<ScheduleEdit, 'origem_configuracao'>): ScheduleField[] {
  return item.origem_configuracao === 'MANUAL'
    ? ['ativo', 'nome_jornada', 'jornada', 'hora_entrada_padrao', 'hora_saida_padrao', 'intervalo']
    : ['ativo', 'hora_entrada_padrao', 'hora_saida_padrao', 'intervalo'];
}

export type DefaultJourney = { jornada: number; hora_entrada_padrao: string; hora_saida_padrao: string; origem: string };
export type ScheduleNotice = { tom: 'atencao' | 'info'; texto: string; acao: string; fallback: string | null };

/**
 * Orientação para jornada incompleta: nunca campo vazio sem explicação. Sem horário, o motor não
 * avalia checkout ausente para essa jornada; a jornada padrão (em código) só vale para quem não tem
 * jornada no cadastro — é informada, nunca aplicada pela tela.
 */
export function scheduleNotice(item: ScheduleEdit, padrao: DefaultJourney | null): ScheduleNotice | null {
  const nome = item.nome_jornada?.trim() || (item.jornada ? `Jornada ${item.jornada}h` : 'Nova jornada');
  if (!item.hora_entrada_padrao || !item.hora_saida_padrao) {
    return {
      tom: 'atencao',
      texto: item.origem_configuracao === 'MANUAL'
        ? `${nome} ainda sem horário.`
        : `${nome} veio do cadastro da operação sem horário configurado.`,
      acao: 'Informe entrada e saída (e o intervalo) e salve. Enquanto não houver horário, o checkout ausente não é avaliado para os colaboradores desta jornada.',
      fallback: padrao
        ? `Colaborador sem jornada no cadastro usa a jornada padrão do motor: ${padrao.jornada}h, ${padrao.hora_entrada_padrao}–${padrao.hora_saida_padrao} (definida em código).`
        : null,
    };
  }
  if (!item.intervalo) {
    return { tom: 'info', texto: 'Intervalo não informado: a prévia não desconta intervalo.',
      acao: 'Informe o intervalo para uma prévia precisa (opcional para jornadas da operação).', fallback: null };
  }
  return null;
}

/**
 * Prévia visual do tempo de jornada (Saída - Entrada - Intervalo). Não é o cálculo oficial do
 * PDOH nem é enviada ao servidor: só ajuda quem está configurando a enxergar o resultado.
 */
export function calcularPreviaJornada(entrada: string | null, saida: string | null, intervalo: string | null) {
  if (!entrada || !saida || !HORA_VALIDA.test(entrada) || !HORA_VALIDA.test(saida)) return null;
  const paraMinutos = (valor: string) => {
    const [h, m] = valor.split(':').map(Number);
    return h * 60 + m;
  };
  const intervaloMin = intervalo && HORA_VALIDA.test(intervalo) ? paraMinutos(intervalo) : 0;
  const brutoMin = ((paraMinutos(saida) - paraMinutos(entrada)) + 24 * 60) % (24 * 60);
  const liquidoMin = Math.max(0, brutoMin - intervaloMin);
  return { brutoMin, liquidoMin };
}

export function formatarDuracao(minutos: number): string {
  const h = Math.floor(minutos / 60);
  const m = minutos % 60;
  if (m === 0) return `${h} hora${h === 1 ? '' : 's'}`;
  return `${h}h ${String(m).padStart(2, '0')}min`;
}

/** Corpo do PATCH só com o que mudou; `null` quando não há alteração. */
export function buildRuleEdit(rule: GovernanceRule, draft: RuleDraft): RuleEditPayload | null {
  const body: RuleEditPayload = {};
  if (draft.nome.trim() !== rule.nome_regra) body.nome_regra = draft.nome.trim();
  if (draft.descricao.trim() !== rule.descricao) body.descricao = draft.descricao.trim();
  if (draft.ativa !== rule.ativa) body.status = draft.ativa ? 'ATIVA' : 'INATIVA';
  const treatment = confirmedTreatment(rule);
  if (treatment && draft.gerar !== treatment.gera_oportunidade) body.gerar_oportunidade = draft.gerar;
  if (rule.modelo_configuracao !== 'JORNADA' && Number(draft.tempo) !== rule.tempo_minimo_minutos) body.tempo_minimo_minutos = Number(draft.tempo);
  if (rule.modelo_configuracao === 'JORNADA') {
    // Só a(s) jornada(s) realmente tocada(s): reenviar as 3 sempre geraria "alterada" no
    // histórico até para quem não mudou (o servidor grava quem salvou em cada linha).
    const antes = draftFromRule(rule).jornadas ?? [];
    const tocadas = (draft.jornadas ?? []).filter((item) => {
      const original = antes.find((outro) => item.id ? outro.id === item.id : outro.jornada === item.jornada);
      return !original || original.ativo !== item.ativo
        || original.jornada !== item.jornada || original.nome_jornada !== item.nome_jornada
        || original.intervalo !== item.intervalo || original.origem_configuracao !== item.origem_configuracao
        || original.hora_entrada_padrao !== item.hora_entrada_padrao || original.hora_saida_padrao !== item.hora_saida_padrao;
    });
    if (tocadas.length) body.jornadas = tocadas;
  }
  const main = principalCondition(rule);
  if (rule.modelo_configuracao !== 'JORNADA' && main?.editavel) {
    const changedOperator = draft.operador !== main.operador;
    const changedValue = !OPERADORES_SEM_VALOR.has(draft.operador) && draft.valor.trim() !== displayValue(main.valor_esperado);
    if (changedOperator || changedValue) body.condicoes = [{ ordem: main.ordem, operador: draft.operador, valor: draft.valor.trim() }];
  }
  const exceptions = rule.excecoes
    .filter((item) => draft.excecoes[item.ordem] !== undefined && draft.excecoes[item.ordem] !== (item.status === ATIVA))
    .map((item) => ({ ordem: item.ordem, ativa: draft.excecoes[item.ordem] }));
  if (exceptions.length) body.excecoes = exceptions;
  return Object.keys(body).length ? body : null;
}

export function statusInfo(rule: GovernanceRule): RuleStatusInfo {
  if (!rule.ativa) {
    return { label: 'Inativa', tone: 'slate', detail: 'Cadastrada, mas desligada: nenhuma oportunidade é criada.' };
  }
  if (!rule.gera_oportunidade) {
    if (rule.motivo_sem_geracao === 'SEM_JORNADA_ATIVA') return { label: 'Ativa · sem jornada', tone: 'amber', detail: 'Configure e selecione uma jornada para gerar oportunidades.' };
    return { label: 'Ativa · não gera', tone: 'amber', detail: 'A regra roda, mas está configurada para não criar oportunidade.' };
  }
  return { label: 'Ativa', tone: 'green', detail: 'Analisa os dados e cria oportunidade quando os critérios forem atendidos.' };
}

/** Frase do "Resultado" do painel: o que acontece com a regra do jeito que está no rascunho. */
export function outcomeText(rule: GovernanceRule, draft: RuleDraft): string {
  if (rule.modelo_configuracao === 'JORNADA') return !draft.ativa || !draft.gerar
    ? 'Geração desligada: nenhuma oportunidade será criada.'
    : 'Com jornada configurada e ativa, o sistema verifica se houve entrada e se o checkout está ausente após a saída esperada. Exceções e monitoramento suficiente são obrigatórios. Sem configuração ativa, não gera oportunidade.';
  const main = principalCondition(rule);
  const what = main?.campo_rotulo ?? 'os dados da fonte';
  if (!draft.ativa) return 'Regra inativa: nada é analisado e nenhuma oportunidade é criada.';
  if (!draft.gerar) return `Regra ativa, mas configurada para não gerar: ${what} é analisado e nenhuma oportunidade é criada.`;
  return `Regra ativa: o sistema analisa ${what.toLowerCase()} e cria a oportunidade quando a regra for atendida e nenhuma exceção marcada se aplicar.`;
}

/** Nome aceito pelo servidor para `usuario` (letras, dígitos, ponto, @, espaço e hífen). */
export function actorName(name: string | null | undefined, email: string | null | undefined): string {
  const clean = (value: string | null | undefined) => (value ?? '').replace(/[^\p{L}\p{N}_.@ -]/gu, ' ').replace(/\s+/g, ' ').trim();
  const candidates = [clean(name), clean(email)];
  return candidates.find((item) => item.length >= 3) ?? 'operador';
}

// ---------------------------------------------------------------------------- rótulos de negócio
const ORIGIN_LABELS: Record<string, string> = {
  INVOLVES: 'Involves',
  RAW_OPERACIONAL: 'RAW operacional',
  CONFIGURACAO_OPERACAO: 'Configuração da operação',
  JORNADA_PADRAO: 'Jornada padrão',
};
const STATUS_LABELS: Record<string, string> = {
  ATIVA: 'Ativa', ATIVO: 'Ativo', INATIVA: 'Inativa', INATIVO: 'Inativo', EM_VALIDACAO: 'Em validação',
  MAPEADA: 'Mapeada', PENDENTE_MAPEAMENTO: 'Pendente de mapeamento',
};
const ENTITY_LABELS: Record<string, string> = {
  JORNADA_OPERACAO: 'Horários da jornada',
  REGRA: 'Regra', CONDICAO: 'Condição', BLOQUEIO: 'Exceção', TRATAMENTO: 'Tratativa', FONTE: 'Fonte',
  JORNADA_PRIORIDADE: 'Jornada', CATALOGO: 'Catálogo',
};
const FIELD_LABELS: Record<string, string> = {
  nome_jornada: 'Nome da jornada', intervalo: 'Intervalo', origem_configuracao: 'Origem',
  jornada: 'Jornada (horas)', hora_entrada_padrao: 'Entrada padrão', hora_saida_padrao: 'Saída padrão', ativo: 'Jornada ativa',
  nome_regra: 'Nome', descricao: 'Descrição', status: 'Status', tempo_minimo_minutos: 'Tempo mínimo (min)',
  operador: 'Regra', valor_esperado: 'Valor', gera_oportunidade: 'Gerar oportunidade', prioridade: 'Prioridade',
};

const PAPEL_LABELS: Record<string, string> = {
  pdoh: 'PDOH Platina', colaborador: 'Cadastro de colaboradores', checkin: 'Check-in',
  checkout: 'Checkout', jornada: 'Jornada', visitas: 'Visitas', pesquisas: 'Pesquisas',
};
export const papelLabel = (papel: string) => PAPEL_LABELS[papel] ?? papel.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

export const originLabel = (code: string) => ORIGIN_LABELS[code] ?? code.replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase());
export const statusLabel = (code: string) => STATUS_LABELS[code] ?? code.replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase());
export const entityLabel = (code: string) => ENTITY_LABELS[code] ?? code;

/** Etapa da ordem de resolução da jornada: a primeira é a origem principal, as demais são fallbacks. */
export function fallbackStage(index: number): string {
  return index === 0 ? 'Origem principal' : `Fallback ${index}`;
}

/** {código do operador -> rótulo} reunido das próprias regras (o servidor é quem nomeia). */
export function operatorLabels(rules: GovernanceRule[]): Record<string, string> {
  const labels: Record<string, string> = {};
  for (const rule of rules) {
    for (const item of [...rule.condicoes, ...rule.excecoes]) {
      for (const option of item.operadores) labels[option.codigo] = option.rotulo;
      if (item.operador_rotulo) labels[item.operador] = item.operador_rotulo;
    }
  }
  return labels;
}

function formatHistoryValue(field: string, value: unknown, labels: Record<string, string>): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Sim' : 'Não';
  // MySQL guarda o "sim/não" como 0/1 no histórico (confirmado em `ativo` e `gera_oportunidade`).
  if (field === 'gera_oportunidade' || field === 'ativo') return value ? 'Sim' : 'Não';
  if (field === 'status') return statusLabel(scalar(value));
  if (field === 'operador') return labels[scalar(value)] ?? scalar(value);
  return displayValue(value);
}

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;

/** "44.00" (Decimal serializado como texto) ou 44 -> "44h"; sem valor válido, null. */
function journeyLabel(value: unknown): string | null {
  const hours = Number(value);
  return Number.isFinite(hours) && hours > 0 ? `Jornada ${hours}h` : null;
}

/** Leitura humana de um evento do histórico: o que mudou, sem mostrar JSON ao líder. */
export function describeHistoryEvent(event: GovernanceHistoryEvent, labels: Record<string, string> = {}): { title: string; details: string[] } {
  const before = asRecord(event.valor_anterior);
  const after = asRecord(event.valor_novo);
  // Horários por jornada: o título nomeia a jornada (44h/36h/24h), não só "cadastrada/alterada".
  if (event.entidade_tipo === 'JORNADA_OPERACAO') {
    const nome = journeyLabel(after?.jornada ?? before?.jornada) ?? entityLabel(event.entidade_tipo);
    if (event.acao === 'CADASTRO') return { title: `${nome} cadastrada`, details: [] };
    if (event.acao === 'EXCLUSAO') return { title: `${nome} removida`, details: [] };
    if (!before || !after) return { title: `${nome} · ${event.acao.toLowerCase()}`, details: [] };
    const details = ['nome_jornada', 'jornada', 'hora_entrada_padrao', 'hora_saida_padrao', 'intervalo', 'origem_configuracao', 'ativo']
      .filter((field) => JSON.stringify(before[field]) !== JSON.stringify(after[field]))
      .map((field) => `${FIELD_LABELS[field]}: ${formatHistoryValue(field, before[field], labels)} → ${formatHistoryValue(field, after[field], labels)}`);
    return { title: `${nome} alterada`, details };
  }
  const entity = entityLabel(event.entidade_tipo);
  if (event.acao === 'CADASTRO') {
    const name = typeof after?.nome_regra === 'string' ? after.nome_regra : typeof after?.descricao === 'string' ? after.descricao : null;
    return { title: `${entity} cadastrada`, details: name ? [name] : [] };
  }
  if (event.acao === 'EXCLUSAO') {
    const name = typeof before?.nome_regra === 'string' ? before.nome_regra : null;
    return { title: `${entity} removida da configuração`, details: name ? [name] : [] };
  }
  if (!before || !after) return { title: `${entity} · ${event.acao.toLowerCase()}`, details: [] };
  if (event.entidade_tipo === 'BLOQUEIO' && before.status !== after.status) {
    const name = typeof after.descricao === 'string' ? after.descricao : 'Exceção';
    return { title: 'Exceção alterada', details: [`${name}: ${after.status === ATIVA ? 'marcada (passa a barrar a oportunidade)' : 'desmarcada (deixa de barrar)'}`] };
  }
  const details = Object.keys(FIELD_LABELS)
    .filter((field) => field in after && JSON.stringify(before[field]) !== JSON.stringify(after[field]))
    .map((field) => `${FIELD_LABELS[field]}: ${formatHistoryValue(field, before[field], labels)} → ${formatHistoryValue(field, after[field], labels)}`);
  return { title: `${entity} alterada`, details };
}

// ============================================================================================
// Criação de oportunidade ("+ Nova oportunidade"). Sem essa configuração a oportunidade não
// existe: o formulário só grava o que o motor de regras (`shared/rule_engine.py`) sabe avaliar.
// ============================================================================================
export type CreateDraft = {
  nome: string;
  descricao: string;
  papelCampo: string;                 // "papel:campo", chave única de uma opção de `campos_disponiveis`
  operador: string;
  valor: string;
  excecoes: Record<number, boolean>;  // ordem do template -> marcada (barra a oportunidade)
  ativa: boolean;
  gerar: boolean;
};

export const papelCampoKey = (papel: string, campo: string) => `${papel}:${campo}`;

/** As 4 exceções-modelo: da regra cadastrada com mais exceções (hoje, HORAS_AUSENTES). */
export function exceptionTemplates(rules: GovernanceRule[]): GovernanceCondition[] {
  const modelo = [...rules].sort((a, b) => b.excecoes.length - a.excecoes.length)[0];
  return modelo?.excecoes ?? [];
}

export function emptyCreateDraft(fields: AvailableField[], templates: GovernanceCondition[]): CreateDraft {
  const primeiro = fields[0];
  return {
    nome: '', descricao: '', papelCampo: primeiro ? papelCampoKey(primeiro.papel_fonte, primeiro.campo_logico) : '',
    operador: primeiro?.operadores[0]?.codigo ?? '', valor: '',
    excecoes: Object.fromEntries(templates.map((item) => [item.ordem, true])),
    ativa: false, gerar: true,
  };
}

export function fieldOptionLabel(field: AvailableField): string {
  return `${papelLabel(field.papel_fonte)} · ${field.rotulo}`;
}

function selectedField(draft: CreateDraft, fields: AvailableField[]): AvailableField | null {
  return fields.find((field) => papelCampoKey(field.papel_fonte, field.campo_logico) === draft.papelCampo) ?? null;
}

export function operatorsForDraft(draft: CreateDraft, fields: AvailableField[]) {
  return selectedField(draft, fields)?.operadores ?? [];
}

export function validateCreateDraft(draft: CreateDraft, fields: AvailableField[]): Record<string, string> {
  const errors: Record<string, string> = {};
  if (draft.nome.trim().length < 3) errors.nome = 'Informe o nome da oportunidade (mínimo 3 caracteres).';
  if (draft.descricao.trim().length < 3) errors.descricao = 'Informe a descrição.';
  const field = selectedField(draft, fields);
  if (!field) { errors.campo = 'Selecione o campo analisado.'; return errors; }
  if (!field.operadores.some((option) => option.codigo === draft.operador)) errors.operador = 'Selecione a regra.';
  if (!OPERADORES_SEM_VALOR.has(draft.operador)) {
    if (draft.valor.trim() === '') errors.valor = 'Informe o valor da condição.';
    else if (field.tipo === 'duracao' && !DURACAO.test(draft.valor)) errors.valor = 'Use o formato HH:MM (por exemplo, 00:30).';
    else if (field.tipo === 'numero' || field.tipo === 'percentual') {
      if (Number.isNaN(Number(draft.valor.replace(',', '.')))) errors.valor = 'Informe um número válido.';
    }
  }
  return errors;
}

export function buildCreatePayload(draft: CreateDraft, fields: AvailableField[], actor: string, motivo: string): RuleCreateBody | null {
  const field = selectedField(draft, fields);
  if (!field || Object.keys(validateCreateDraft(draft, fields)).length) return null;
  return {
    usuario: actor, motivo,
    nome_regra: draft.nome.trim(), descricao: draft.descricao.trim(),
    papel_fonte: field.papel_fonte, campo_logico: field.campo_logico, operador: draft.operador,
    valor: OPERADORES_SEM_VALOR.has(draft.operador) ? null : draft.valor.trim(),
    excecoes: Object.entries(draft.excecoes).filter(([, marcada]) => marcada).map(([ordem]) => Number(ordem)),
    status: draft.ativa ? 'ATIVA' : 'INATIVA', gerar_oportunidade: draft.gerar,
  };
}

/** Frase do "Resultado" enquanto o usuário monta a oportunidade nova. */
export function creationOutcomeText(draft: CreateDraft, fields: AvailableField[]): string {
  const field = selectedField(draft, fields);
  const what = field?.rotulo ?? 'o campo selecionado';
  if (!draft.ativa) return 'Oportunidade cadastrada inativa: fica guardada até ser ativada; nada é analisado.';
  if (!draft.gerar) return `Oportunidade ativa, mas configurada para não gerar: ${what.toLowerCase()} é analisado e nenhuma oportunidade é criada.`;
  return `Oportunidade ativa: o sistema analisa ${what.toLowerCase()} e cria a oportunidade quando a condição for atendida e nenhuma exceção marcada se aplicar.`;
}
