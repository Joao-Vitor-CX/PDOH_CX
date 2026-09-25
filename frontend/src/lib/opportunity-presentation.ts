import type { Opportunity, Rule } from '../services/pdoh-api';

// Vocabulário de apresentação. Os critérios e as tratativas vêm do catálogo da API.
const names: Record<string, string> = {
  PESQUISA_CAMPOS_NULOS: 'Dados obrigatórios incompletos',
  CHECKOUT_AUSENTE: 'Ausência de registro de saída',
  VALOR_SEM_PADRONIZACAO: 'Informação sem padronização',
  REGISTRO_DUPLICADO: 'Duplicidade técnica',
  CAMPO_OBRIGATORIO_VAZIO: 'Campo obrigatório não preenchido',
  INCONSISTENCIA_HORARIO: 'Horários inconsistentes',
  DADO_FORA_DO_PADRAO: 'Informação fora do padrão',
  DATA_FORA_DO_PERIODO: 'Registro fora do período',
  PDV_MESMO_NOME_IDS_DISTINTOS: 'Ponto de venda com identificação divergente',
  VOLUME_OPORTUNIDADES_TRUNCADO: 'Limite de evidências atingido',
  IDENTIFICACAO_AMBIGUA: 'Identificação ambígua',
  DIVERGENCIA_CADASTRAL: 'Divergência cadastral',
  IDENTIFICACAO_COLABORADOR: 'Normalização do nome do colaborador',
  SEM_LIDERES_NO_PERIODO: 'Nenhuma liderança no período',
  PDV_SEM_IDENTIFICADOR: 'Ponto de venda sem identificador',
  COLABORADOR_SEM_CLASSIFICACAO: 'Colaborador sem classificação',
  FALHA_PARAMETRIZACAO: 'Parametrização pendente',
  COLUNA_OBRIGATORIA_AUSENTE: 'Informação obrigatória ausente na fonte',
  DADO_INCOMPLETO: 'Registro incompleto',
  JORNADA_NAO_ENCONTRADA: 'Jornada não parametrizada',
  DATA_HORA_INVALIDA: 'Data ou hora inválida',
};
export function humanize(value: string) {
  return value
    .replaceAll('_', ' ')
    .toLocaleLowerCase('pt-BR')
    .replace(/^./, (letter) => letter.toLocaleUpperCase('pt-BR'));
}
export function opportunityName(code: string) {
  return names[code] || humanize(code);
}
export type OpportunityKind =
  | 'operacional'
  | 'alerta'
  | 'informativo'
  | 'nao_classificado';
export function catalogKind(
  rule: Pick<Rule, 'classificacao'> | null | undefined,
): OpportunityKind {
  if (rule?.classificacao === 'TELEMETRIA') return 'informativo';
  if (rule?.classificacao === 'ALERTA') return 'alerta';
  if (rule?.classificacao === 'OPORTUNIDADE') return 'operacional';
  return 'nao_classificado';
}
export function kindLabel(kind: OpportunityKind) {
  if (kind === 'alerta') return 'Alerta de qualidade';
  return kind === 'operacional'
    ? 'Análise / tratativa'
    : kind === 'informativo'
      ? 'Informativo'
      : 'Classificação indisponível';
}
export function evidenceObject(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') {
    try {
      return evidenceObject(JSON.parse(value));
    } catch {
      return {};
    }
  }
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
export function evidenceText(value: unknown): string {
  if (value === null) return 'Nulo';
  if (value === undefined) return 'Não informado';
  if (typeof value === 'boolean') return value ? 'Sim' : 'Não';
  if (Array.isArray(value)) return value.map(evidenceText).join(', ');
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'bigint')
    return value.toString();
  return JSON.stringify(value) ?? 'Não informado';
}
export function recordLabel(item: Opportunity) {
  const evidence = evidenceObject(item.evidencia);
  const reference = evidence.registro_afetado ?? evidence.indice_origem;
  return (
    item.colaborador ||
    (reference !== undefined && reference !== null
      ? `Registro ${evidenceText(reference)}`
      : `Registro ${item.oportunidade_id.slice(0, 8)}`)
  );
}
export function affectedProcess(item: Opportunity) {
  const evidence = evidenceObject(item.evidencia);
  return evidenceText(evidence.processo ?? item.tabela_origem);
}
// Agrupamento de uma página, sem inferir causas nem multiplicar evidencia.ocorrencias.
export function groupPage(
  items: Opportunity[],
  by: 'campo' | 'processo' | 'marca' | 'data',
) {
  const groups = new Map<string, Opportunity[]>();
  for (const item of items) {
    const evidence = evidenceObject(item.evidencia);
    const key =
      by === 'campo'
        ? evidenceText(evidence.campo_esperado ?? evidence.campo_origem)
        : by === 'processo'
          ? affectedProcess(item)
          : by === 'marca'
            ? item.marca
            : item.data_referencia || 'Não informada';
    groups.set(key, [...(groups.get(key) || []), item]);
  }
  return [...groups.entries()].sort(
    (a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]),
  );
}
