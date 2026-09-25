import type { ReactNode } from 'react';
import { displayLabel as humanize } from '@/src/lib/operational-display';
import { RefreshCcw } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export function StatusBadge({ value }: { value: string }) {
  const tone =
    value === 'CONCLUIDA'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : value === 'CONCLUIDA_COM_ALERTAS' || value === 'CONCLUIDA_SEM_RESULTADO'
        ? 'border-amber-200 bg-amber-50 text-amber-800'
        : value === 'FALHA_TECNICA'
          ? 'border-red-200 bg-red-50 text-red-800'
          : 'border-blue-200 bg-blue-50 text-blue-800';
  const labels: Record<string, string> = {
    CONCLUIDA: 'Concluída',
    CONCLUIDA_COM_ALERTAS: 'Concluída com alertas',
    CONCLUIDA_SEM_RESULTADO: 'Concluída sem resultado',
    FALHA_TECNICA: 'Falha técnica',
  };
  return (
    <Badge
      title={value}
      variant="outline"
      className={`whitespace-normal ${tone}`}
    >
      {labels[value] || humanize(value)}
    </Badge>
  );
}

export function ConsultationState({
  loading,
  refreshing,
  error,
  hasData,
  updatedAt,
  retry,
  children,
  emptyMessage,
}: {
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  hasData: boolean;
  updatedAt: Date | null;
  retry: () => void;
  children: ReactNode;
  emptyMessage?: string;
}) {
  return (
    <div className="space-y-4">
      <div
        className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500"
        aria-live="polite"
      >
        <span>
          {updatedAt
            ? `Consulta atualizada em ${new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(updatedAt)} · horário local do navegador`
            : 'Aguardando resposta da API de consulta'}
        </span>
        <Button
          variant="outline"
          size="sm"
          onClick={retry}
          disabled={refreshing}
          aria-label="Atualizar consulta"
        >
          <RefreshCcw
            className={`size-3.5 ${refreshing ? 'animate-spin' : ''}`}
          />{' '}
          Atualizar
        </Button>
      </div>
      {error && (
        <Alert variant="destructive">
          <AlertTitle>
            {hasData
              ? 'Não foi possível atualizar; exibindo última resposta válida'
              : 'Não foi possível carregar os dados'}
          </AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {loading && !hasData ? (
        <output className="block rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500">
          Carregando dados reais do PDOH_CX…
        </output>
      ) : hasData ? (
        children
      ) : error ? null : (
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500">
          {emptyMessage || 'Nenhum dado disponível para os filtros informados.'}
        </div>
      )}
    </div>
  );
}
