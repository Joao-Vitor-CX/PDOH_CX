import { z } from 'zod';
import { displayLabel } from '../lib/operational-display.ts';
import { queryString } from './pdoh-api.ts';
import { PDOH_SUMMARY_PATH, pdohSummarySchema, type PdohDailyRow } from './pdoh-indicator.ts';
import {
  loadAllPages, loadGroupDetails, v2Request,
  type AlertGroup, type OperationalFilters, type OperationalGroup,
} from './operational-api.ts';

/**
 * Rastreabilidade para o usuário operacional. Só lê e explica o que a esteira já gravou
 * (registros de alerta, prova da oportunidade, resolução oficial de jornada): nada é
 * recalculado, deduzido por nome de regra ou inventado quando falta.
 */

const person = (value: string | null | undefined) => value?.trim().toLocaleUpperCase('pt-BR') ?? '';
type Json = Record<string, unknown>;
const record = (value: unknown): Json | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : null;
function text(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (Array.isArray(value)) return value.map((item) => text(item)).filter(Boolean).join(', ') || null;
  return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    ? String(value) : JSON.stringify(value);
}

// Nomes de negócio das fontes físicas mais comuns; o restante usa o rótulo genérico.
const ORIGENS: Record<string, string> = {
  colaboradores_ativos_bracell: 'Cadastro de colaboradores ativos (Involves)',
  raw_exclusivo_bracell_colaboradores_ativos: 'Cadastro RAW de colaboradores',
  identificador_entidade: 'Cadastro de PDVs (identificador da entidade)',
  status_day_operacao_bracell: 'Status do dia da operação (Involves)',
  relatorio_checkin_bracell: 'Relatório de check-in (Involves)',
  exclusivo_bracell_platina_relatorio_pdoh: 'PDOH Platina',
};
export function originLabel(origin: string | null | undefined) {
  if (!origin) return null;
  return ORIGENS[origin] ?? displayLabel(origin);
}

// ------------------------------------------------------------------------------ alertas
const alertRecordSchema = z.object({
  id: z.string(),
  execution_id: z.string(),
  tipo_problema: z.string(),
  colaborador: z.string().nullable(),
  colaborador_id_interno: z.string().nullable(),
  campo: z.string().nullable(),
  descricao: z.string(),
  tratativa: z.string().nullable(),
  evidencia: z.unknown().nullable(),
  registrado_em: z.string(),
});
export type AlertRecord = z.infer<typeof alertRecordSchema>;

/** Registros individuais da categoria na janela (rota existente `GET /api/v2/alertas`). */
export async function loadAlertRecords(tipo: string, window: OperationalFilters, signal?: AbortSignal) {
  const page = await loadAllPages('/alertas', { ...window, tipo }, alertRecordSchema, (item) => item.id, signal);
  return page.items;
}

export type AlertDetail = {
  colaborador: string | null;
  identificadores: string[];
  campo: string | null;
  valor_encontrado: string | null;
  valor_esperado: string | null;
  complementos: { rotulo: string; valor: string }[];
  problema: string;
  identificado_em: string;
  execucao: string;
};

// Chaves que já viram coluna própria ou que são internas do processamento.
const CHAVES_TRATADAS = new Set(['campo', 'campo_origem', 'valor', 'valor_origem', 'valor_encontrado',
  'valor_esperado', 'usuarios_normalizados', 'usuario_normalizado', 'nome_normalizado', 'perfil_acesso',
  'dataframe', 'indice_origem', 'indices', 'registro_afetado', 'fingerprint', 'execution_id']);
const ROTULOS: Record<string, string> = {
  processo: 'Processo De/Para',
  nomes_normalizados: 'Nomes encontrados para o mesmo usuário',
  ocorrencias: 'Registros afetados na execução',
};

function alertField(item: AlertRecord, evidence: Json) {
  return item.campo ?? text(evidence.campo_origem) ?? text(evidence.campo)
    ?? (evidence.perfil_acesso !== undefined ? 'perfil_acesso' : null);
}

/** Uma linha por pendência distinta; regravações de outras execuções contam uma vez (a mais recente). */
export function alertDetails(group: AlertGroup, records: AlertRecord[]): AlertDetail[] {
  const latest = new Map<string, AlertRecord>();
  for (const item of records) {
    const evidence = record(item.evidencia) ?? {};
    if (item.tipo_problema !== group.tipo_problema || person(item.colaborador) !== person(group.colaborador)
      || (group.campo ?? null) !== alertField(item, evidence)) continue;
    const identity = JSON.stringify(Object.entries(evidence).filter(([key]) => key !== 'indice_origem' && key !== 'ocorrencias')
      .sort(([a], [b]) => a.localeCompare(b)));
    const previous = latest.get(identity);
    if (!previous || item.registrado_em > previous.registrado_em) latest.set(identity, item);
  }
  return [...latest.values()].map((item) => {
    const evidence = record(item.evidencia) ?? {};
    const usuarios = [evidence.usuarios_normalizados, evidence.usuario_normalizado].flat()
      .map((value) => text(value)).filter((value): value is string => !!value);
    const encontrado = 'valor' in evidence && evidence.valor === null ? 'Vazio'
      : text(evidence.valor_origem) ?? text(evidence.valor_encontrado) ?? text(evidence.valor) ?? text(evidence.perfil_acesso);
    return {
      colaborador: item.colaborador ?? text(evidence.nome_normalizado),
      identificadores: [...new Set(usuarios)],
      campo: alertField(item, evidence),
      valor_encontrado: encontrado,
      valor_esperado: text(evidence.valor_esperado),
      complementos: Object.entries(evidence).filter(([key, value]) => !CHAVES_TRATADAS.has(key) && text(value))
        .map(([key, value]) => ({ rotulo: ROTULOS[key] ?? displayLabel(key), valor: text(value) ?? '' })),
      problema: item.descricao,
      identificado_em: item.registrado_em,
      execucao: item.execution_id,
    };
  }).sort((a, b) => (a.colaborador ?? '').localeCompare(b.colaborador ?? '', 'pt-BR')
    || (a.valor_encontrado ?? '').localeCompare(b.valor_encontrado ?? '', 'pt-BR'));
}

/** Texto do campo "Colaborador" quando o alerta é sobre um valor/registro de cadastro, não sobre uma pessoa. */
export function alertSubject(group: AlertGroup) {
  if (group.colaborador) return group.colaborador;
  if (group.campo) return `Pendência no valor do campo ${displayLabel(group.campo)} — o registro não identifica colaboradores`;
  return 'Pendência no registro de cadastro — o registro não identifica colaboradores';
}

// ------------------------------------------------------------------------ oportunidades
export type OccurrenceTrace = {
  data: string | null;
  cenario: string;
  jornada: string | null;
  jornada_origem: string | null;
  fallback: boolean | null;
  motivo: string | null;
  fonte_jornada: string | null;
  referencia_jornada: 'prova' | 'resolucao_da_data' | null;
  fonte_evidencia: string | null;
  validacao: string;
  historico: { identificada_em: string; execucao: string; repeticoes: number };
};

const ORIGEM_JORNADA: Record<string, string> = {
  INVOLVES: 'Cadastro Involves', RAW: 'Cadastro RAW', CONFIGURACAO: 'Configuração da operação',
  FALLBACK: 'Jornada padrão 44H (cadastro sem jornada)', INDISPONIVEL: 'Não apurada',
};
export const journeyOriginLabel = (origem: string | null | undefined) =>
  origem ? ORIGEM_JORNADA[origem.toUpperCase()] ?? displayLabel(origem) : null;

function hours(value: unknown) {
  const number = Number(value);
  return value !== null && value !== undefined && Number.isFinite(number) && number > 0 ? `${number}H` : null;
}
const hhmm = (value: unknown) => text(value)?.slice(0, 5) ?? null;

/** Frase do cenário a partir do que a prova registrou (esperado x encontrado, monitoramento real). */
export function scenario(proof: Json): string {
  const monitor = record(proof.monitoramento);
  const schedule = record(proof.configuracao_operacional);
  if (monitor && schedule) {
    const entrada = hhmm(monitor.hora_entrada);
    const saida = hhmm(monitor.hora_saida);
    return `Entrada registrada${entrada ? ` às ${entrada}` : ''} e ${saida ? `saída às ${saida}` : 'nenhum checkout'} até a saída esperada das ${hhmm(schedule.hora_saida_padrao)}.`;
  }
  const esperado = text(proof.esperado);
  const encontrado = text(proof.encontrado);
  if (esperado || encontrado) return `${esperado ?? 'Critério da regra'}${encontrado ? ` — encontrado ${encontrado}` : ''}.`;
  return 'Prova sem descrição do cenário.';
}

/**
 * Explica uma ocorrência. Jornada: primeiro a registrada na própria prova (configuração
 * operacional/fallback ou jornada semanal); se a prova for anterior a esse registro, a resolução
 * oficial da data (`/pdoh/resumo`), sinalizada como tal.
 */
export function traceOccurrence(
  item: { data_referencia: string | null; evidencia: unknown; identificada_em: string; execution_id: string; repeticoes: number },
  resolution: PdohDailyRow['jornada'] | null,
): OccurrenceTrace {
  const root = record(item.evidencia) ?? {};
  const proof = record(root.comprovacao) ?? {};
  const schedule = record(proof.configuracao_operacional);
  const origemProva = text(proof.jornada_origem)?.toUpperCase() ?? null;
  // Jornada padrão (cadastro sem jornada) é a origem da jornada; fallback é o checkout esquecido
  // com saída considerada pela jornada, que só existe na prova de checkout.
  const jornadaPadrao = root.fallback_usado === true || origemProva === 'FALLBACK';
  const fallback = !!hhmm(schedule?.hora_saida_padrao);
  const daProva = hours(schedule?.jornada) ?? hours(proof.jornada_semanal) ?? hours(proof.jornada_aplicada);
  const base = {
    data: item.data_referencia, cenario: scenario(proof),
    fonte_evidencia: [...new Set([text(proof.fonte), originLabel(text(proof.fonte_tabela))].filter(Boolean))].join(' · ') || null,
    validacao: text(proof.resultado) ?? 'indisponivel',
    historico: { identificada_em: item.identificada_em, execucao: item.execution_id, repeticoes: item.repeticoes },
  };
  if (daProva) {
    return {
      ...base, jornada: daProva, jornada_origem: origemProva, fallback, referencia_jornada: 'prova',
      motivo: jornadaPadrao ? text(proof.motivo_fallback) ?? 'Jornada não encontrada na origem; aplicada a jornada padrão.'
        : 'Jornada encontrada no cadastro.',
      fonte_jornada: jornadaPadrao ? 'Jornada padrão definida em código'
        : origemProva === 'INVOLVES' ? 'Cadastro de colaboradores ativos (Involves)' : journeyOriginLabel(origemProva),
    };
  }
  if (resolution?.jornada_aplicada) {
    return {
      ...base, jornada: resolution.jornada_aplicada, jornada_origem: resolution.origem ?? origemProva,
      fallback, referencia_jornada: 'resolucao_da_data',
      motivo: resolution.motivo ?? (resolution.houve_fallback ? null : 'Jornada encontrada no cadastro.'),
      fonte_jornada: resolution.fonte,
    };
  }
  return {
    ...base, jornada: null, jornada_origem: origemProva, fallback, referencia_jornada: null,
    motivo: resolution?.motivo ?? (origemProva && origemProva !== 'INDISPONIVEL'
      ? `Jornada apurada por ${journeyOriginLabel(origemProva)}; horas não registradas na prova.` : 'Jornada não apurada.'),
    fonte_jornada: resolution?.fonte ?? null,
  };
}

/** Ocorrências do grupo com a jornada da data, usando só rotas existentes (detalhes + PDOH diário). */
export async function loadOpportunityTrace(group: OperationalGroup, window: OperationalFilters, signal?: AbortSignal) {
  const detail = await loadGroupDetails(group.grupo_id, window, signal, 200);
  const needsResolution = detail.ocorrencias.items.some((item) => {
    const proof = record(record(item.evidencia)?.comprovacao) ?? {};
    return !hours(record(proof.configuracao_operacional)?.jornada) && !hours(proof.jornada_semanal);
  });
  const byDay = new Map<string, PdohDailyRow['jornada']>();
  if (needsResolution && group.colaborador && window.periodo_inicio && window.periodo_fim) {
    try {
      const pdoh = await v2Request(`${PDOH_SUMMARY_PATH}${queryString({
        marca: window.marca, operacao: window.operacao, colaborador: group.colaborador, periodo: 'personalizado',
        periodo_inicio: window.periodo_inicio, periodo_fim: window.periodo_fim, pagina: 1, tamanho: 200,
      })}`, pdohSummarySchema, signal);
      for (const row of pdoh.detalhes.items)
        if (person(row.colaborador) === person(group.colaborador)) byDay.set(row.data.slice(0, 10), row.jornada);
    } catch {
      // Sem a resolução da data a tela diz "não informada"; nunca inventa jornada.
    }
  }
  return detail.ocorrencias.items
    .map((item) => traceOccurrence(item, byDay.get((item.data_referencia ?? '').slice(0, 10)) ?? null))
    .sort((a, b) => (a.data ?? '').localeCompare(b.data ?? ''));
}
