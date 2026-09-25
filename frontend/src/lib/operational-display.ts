// Somente rótulos e cores. Classificação, prioridade e filtros são responsabilidade da API.
// Campos das regras configuráveis que já têm nome de negócio (o motor de regras é quem os nomeia).
const camposDeNegocio: Record<string, string> = {
  horas_nao_registradas: 'Horas não registradas',
  ocio: 'Ócio',
  deslocamento: 'Deslocamento',
  produtividade: 'Produtividade',
};
export function displayLabel(value: string) {
  if (camposDeNegocio[value]) return camposDeNegocio[value];
  // Rótulo que já é texto de negócio ("PDOH Platina") não é reescrito em minúsculas.
  if (/[\s]/u.test(value) && /\p{Lu}/u.test(value)) return value;
  return value
    .replaceAll('_', ' ')
    .toLocaleLowerCase('pt-BR')
    .replace(/^./u, (letter) => letter.toLocaleUpperCase('pt-BR'));
}
export const severityLabels: Record<string, string> = {
  CRITICA: 'Crítica',
  ALTA: 'Alta',
  MEDIA: 'Média',
  BAIXA: 'Baixa',
};
export const severityTones: Record<string, string> = {
  CRITICA: 'border-red-200 bg-red-50 text-red-800',
  ALTA: 'border-orange-200 bg-orange-50 text-orange-800',
  MEDIA: 'border-amber-200 bg-amber-50 text-amber-900',
  BAIXA: 'border-slate-200 bg-slate-50 text-slate-700',
};
// Chaves internas de processamento: nunca chegam à visão do líder.
const evidenciaTecnica = new Set([
  'dataframe',
  'indice_origem',
  'indices',
  'registro_afetado',
  'versao_regra',
  'fingerprint',
  'execution_id',
  'oportunidade_id',
  'achado_id',
  'identidade_origem',
]);
const evidenciaRotulos: Record<string, string> = {
  campo: 'Campo',
  campo_esperado: 'Campo esperado',
  campo_origem: 'Campo de origem',
  campo_inicio: 'Campo inicial',
  campo_fim: 'Campo final',
  valor: 'Valor encontrado',
  valor_encontrado: 'Valor encontrado',
  valor_esperado: 'Valor esperado',
  valor_origem: 'Valor de origem',
  valor_inicio: 'Valor inicial',
  valor_fim: 'Valor final',
  fallback_usado: 'Fallback aplicado',
  fallback_valor: 'Valor do fallback',
  ocorrencias: 'Ocorrências no registro',
  situacao: 'Situação',
  processo: 'Processo',
  origem: 'Origem do dado',
  nome_normalizado: 'Nome normalizado',
  ponto_venda: 'PDV',
  pdv: 'PDV',
  loja: 'Loja',
};
const chavesPdv = ['ponto_venda', 'pdv', 'loja'];

function evidenciaObjeto(evidencia: unknown): Record<string, unknown> {
  if (typeof evidencia === 'string') {
    try {
      evidencia = JSON.parse(evidencia);
    } catch {
      return {};
    }
  }
  return evidencia && typeof evidencia === 'object' && !Array.isArray(evidencia)
    ? (evidencia as Record<string, unknown>)
    : {};
}

function textoDoValor(valor: unknown): string {
  if (valor === null || valor === undefined || valor === '') return 'Não informado';
  if (typeof valor === 'boolean') return valor ? 'Sim' : 'Não';
  if (typeof valor === 'string') return valor;
  if (typeof valor === 'number') return String(valor);
  if (Array.isArray(valor)) {
    return valor.map(textoDoValor).filter((item) => item && item !== 'Não informado').join(', ');
  }
  return ''; // objetos aninhados são estrutura interna, não informação para o líder
}

/** Evidência legível: descarta chaves internas e traduz o que o líder precisa ver. */
export function evidenceEntries(evidencia: unknown) {
  return Object.entries(evidenciaObjeto(evidencia))
    .filter(([chave]) => !evidenciaTecnica.has(chave))
    .map(([chave, valor]) => ({
      chave,
      rotulo: evidenciaRotulos[chave] || displayLabel(chave),
      valor: textoDoValor(valor),
    }))
    .filter((item) => item.valor !== '');
}

/** PDV só aparece quando a evidência realmente o traz. */
export function pdvFromEvidence(evidencia: unknown): string | null {
  const objeto = evidenciaObjeto(evidencia);
  for (const chave of chavesPdv) {
    const valor = objeto[chave];
    if (typeof valor === 'string' && valor.trim()) return valor;
  }
  return null;
}

export const statusLabels: Record<string, string> = {
  ABERTA: 'Aberta',
  EM_ANALISE: 'Em análise',
  REABERTA: 'Reaberta',
  RESOLVIDA: 'Resolvida',
  IGNORADA: 'Ignorada',
};
