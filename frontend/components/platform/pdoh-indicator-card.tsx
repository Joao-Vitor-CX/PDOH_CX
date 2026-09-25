import { Gauge, TrendingDown, TrendingUp } from 'lucide-react';
import {
  pdohIndicatorState,
  type PdohSummary,
} from '@/src/services/pdoh-indicator';

const percent = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

/**
 * Indicador principal do painel. Recebe o resumo oficial de GET /api/v2/pdoh/resumo;
 * enquanto a rota não existir recebe `null` e mostra o estado indisponível — sem
 * número, sem símbolo de percentual e sem valor ilustrativo.
 */
export function PdohIndicatorCard({ summary }: { summary: PdohSummary | null }) {
  const state = pdohIndicatorState(summary);
  return (
    <article
      aria-labelledby="pdoh-indicador-titulo"
      className="flex flex-col justify-between rounded-2xl bg-[#0b2349] p-6 text-white shadow-sm"
    >
      <div className="flex items-center justify-between">
        <h2
          id="pdoh-indicador-titulo"
          className="text-sm font-bold uppercase tracking-[.16em] text-blue-100"
        >
          PDOH
        </h2>
        <Gauge className="size-6 text-blue-200" aria-hidden="true" />
      </div>

      {state.status === 'disponivel' ? (
        <div className="my-6">
          <p className="text-5xl font-bold tabular-nums tracking-tight">
            {percent.format(state.percentual)}
            <span className="ml-1 text-2xl font-semibold text-blue-200">%</span>
          </p>
          <p className="mt-3 text-sm text-blue-100">Percentual do período</p>
          {state.variacao !== null && (
            <p className="mt-2 inline-flex items-center gap-1.5 text-sm font-semibold">
              {state.variacao >= 0 ? (
                <TrendingUp className="size-4 text-emerald-300" aria-hidden="true" />
              ) : (
                <TrendingDown className="size-4 text-rose-300" aria-hidden="true" />
              )}
              {state.variacao > 0 ? '+' : ''}
              {percent.format(state.variacao)} p.p. vs. período anterior
            </p>
          )}
        </div>
      ) : (
        <output className="my-6 block">
          <p className="text-xl font-semibold leading-snug text-white">
            {state.message}
          </p>
          <p className="mt-3 text-xs leading-relaxed text-blue-100">
            O indicador aparece aqui quando a fonte oficial do PDOH for
            disponibilizada. Nenhum valor é estimado a partir das oportunidades.
          </p>
        </output>
      )}

      <span className="w-fit rounded-full border border-white/20 px-3 py-1 text-xs font-semibold">
        {state.status === 'disponivel'
          ? 'Fonte oficial'
          : 'Fonte oficial ainda não disponível'}
      </span>
    </article>
  );
}
