import type { LucideIcon } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatNumber } from '@/src/lib/pdoh-format';
import { cn } from '@/lib/utils';

export type MetricTone = 'pdoh' | 'oportunidade' | 'alerta' | 'telemetria';

const TONES: Record<MetricTone, { ring: string; icon: string; value: string }> = {
  pdoh: { ring: 'ring-blue-200/70', icon: 'bg-blue-50 text-blue-700', value: 'text-slate-950' },
  oportunidade: { ring: 'ring-blue-200/70', icon: 'bg-blue-50 text-blue-700', value: 'text-blue-950' },
  alerta: { ring: 'ring-amber-200/70', icon: 'bg-amber-50 text-amber-700', value: 'text-amber-900' },
  telemetria: { ring: 'ring-slate-200', icon: 'bg-slate-100 text-slate-600', value: 'text-slate-700' },
};

/**
 * Card de indicador. `value` já chega pronto da API; o componente não calcula métrica.
 */
export function MetricCard({
  label,
  value,
  caption,
  detail,
  tone,
  icon: Icon,
  to,
}: {
  label: string;
  value: number | string;
  caption: string;
  detail?: string;
  tone: MetricTone;
  icon: LucideIcon;
  to?: string;
}) {
  const style = TONES[tone];
  const body = (
    <article
      className={cn(
        'flex h-full flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm ring-1 transition',
        style.ring,
        to && 'hover:-translate-y-0.5 hover:shadow-md',
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-extrabold uppercase tracking-[.14em] text-slate-500">
          {label}
        </p>
        <span className={cn('grid size-9 shrink-0 place-items-center rounded-xl', style.icon)}>
          <Icon className="size-4" aria-hidden="true" />
        </span>
      </div>
      <p className={cn('mt-3 text-[2rem] font-extrabold leading-none tracking-[-.04em]', style.value)}>
        {typeof value === 'number' ? formatNumber(value) : value}
      </p>
      <p className="mt-2 text-[13px] font-medium text-slate-600">{caption}</p>
      {detail && <p className="mt-auto pt-3 text-xs text-slate-500">{detail}</p>}
    </article>
  );
  return to?.startsWith('#') ? <a href={to} className="rounded-2xl focus-visible:outline-2 focus-visible:outline-blue-600">{body}</a> : to ? (
    <Link to={to} className="rounded-2xl focus-visible:outline-2 focus-visible:outline-blue-600">
      {body}
    </Link>
  ) : (
    body
  );
}
