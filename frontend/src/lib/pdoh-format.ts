const numberFormatter = new Intl.NumberFormat('pt-BR');

export function formatNumber(value: number | null | undefined): string {
  return value == null ? '—' : numberFormatter.format(value);
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const [year, month, day] = value.slice(0, 10).split('-');
  return year && month && day ? `${day}/${month}/${year}` : value;
}

// A API informa data/hora local sem offset; não aplicamos conversão de fuso no navegador.
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  return `${formatDate(value)} ${value.slice(11, 16)}`.trim();
}

export function formatPeriod(start: string | null, end: string | null): string {
  return !start && !end ? 'Não informado' : `${formatDate(start)} – ${formatDate(end)}`;
}
