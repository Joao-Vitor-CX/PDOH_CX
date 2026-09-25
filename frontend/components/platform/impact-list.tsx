import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { formatNumber } from '@/src/lib/pdoh-format';
import { queryString } from '@/src/services/pdoh-api';
import type { ImpactRow } from '@/src/services/findings-service';

const SEVERITY_TONE: Record<string, string> = {
  CRITICA: 'border-red-200 bg-red-50 text-red-800',
  ALTA: 'border-orange-200 bg-orange-50 text-orange-800',
  MEDIA: 'border-amber-200 bg-amber-50 text-amber-900',
  BAIXA: 'border-slate-200 bg-slate-50 text-slate-700',
};
const SEVERITY_LABEL: Record<string, string> = {
  CRITICA: 'Crítica',
  ALTA: 'Alta',
  MEDIA: 'Média',
  BAIXA: 'Baixa',
};

/**
 * Principais impactos operacionais. Só recebe o que o catálogo classifica como
 * OPORTUNIDADE — alertas e telemetria têm abas próprias (fases seguintes).
 */
export function ImpactList({
  items,
  periodo,
  marca,
  limit = 6,
}: {
  items: ImpactRow[];
  periodo: { inicio: string | null; fim: string | null };
  marca: string;
  limit?: number;
}) {
  const visible = items.slice(0, limit);
  const max = Math.max(1, ...visible.map((item) => item.quantidade));
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-bold tracking-tight text-slate-950">
            Principais impactos
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Situações operacionais com maior volume no período consolidado.
          </p>
        </div>
        {items.length > 0 && (
          <Link
            to={`/oportunidades${queryString({ marca, periodo_inicio: periodo.inicio, periodo_fim: periodo.fim })}`}
            className="inline-flex min-h-11 items-center text-sm font-semibold text-blue-700"
          >
            Abrir fila operacional →
          </Link>
        )}
      </div>

      {visible.length === 0 ? (
        <p className="py-8 text-center text-sm text-slate-500">
          Nenhuma oportunidade operacional no período consolidado.
        </p>
      ) : (
        <ul className="mt-4 space-y-4">
          {visible.map((item) => (
            <li key={item.tipo}>
              <Link
                to={`/oportunidades${queryString({ marca, tipo: item.tipo, periodo_inicio: periodo.inicio, periodo_fim: periodo.fim })}`}
                className="block rounded-lg focus-visible:outline-2 focus-visible:outline-blue-600"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-900">
                      {item.titulo}
                    </p>
                    {item.impacto && (
                      <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">
                        {item.impacto}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <Badge
                      variant="outline"
                      className={SEVERITY_TONE[item.severidade] || SEVERITY_TONE.BAIXA}
                    >
                      {SEVERITY_LABEL[item.severidade] || item.severidade}
                    </Badge>
                    <strong className="tabular-nums text-sm text-slate-900">
                      {formatNumber(item.quantidade)}
                    </strong>
                  </div>
                </div>
                <div className="mt-2 h-1.5 rounded-full bg-slate-100" aria-hidden="true">
                  <div
                    className="h-1.5 rounded-full bg-blue-600"
                    style={{ width: `${(item.quantidade / max) * 100}%` }}
                  />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {items.length > visible.length && (
        <p className="mt-4 text-xs text-slate-500">
          Exibindo as {visible.length} maiores de {formatNumber(items.length)} situações.
        </p>
      )}
    </section>
  );
}
