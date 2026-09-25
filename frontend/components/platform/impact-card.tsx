import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowUpRight, ChevronRight, UserRound } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { OpportunityDetail } from '@/components/platform/opportunity-detail-modal';
import { formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import { severityLabels, severityTones, statusLabels, displayLabel } from '@/src/lib/operational-display';
import type {
  OperationalFilters,
  OperationalGroup,
  OperationalValidation,
} from '@/src/services/operational-api';
import type { ImpactoPorRegra } from '@/src/services/findings-service';

/** Selo da comprovação. `indisponivel` fica âmbar: ausência de prova, não aprovação. */
const TOM_VALIDACAO: Record<string, string> = {
  confirmado: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  nao_aplicavel: 'border-slate-200 bg-slate-50 text-slate-600',
  indisponivel: 'border-amber-200 bg-amber-50 text-amber-900',
};

export function ValidationBadge({ validacao }: { validacao?: OperationalValidation }) {
  if (!validacao) return null;
  return (
    <span
      title={validacao.motivo || undefined}
      className={`inline-flex shrink-0 items-center rounded-md border px-2.5 py-1 text-xs font-semibold ${TOM_VALIDACAO[validacao.resultado] || TOM_VALIDACAO.indisponivel}`}
    >
      {validacao.rotulo}
    </span>
  );
}

export function SeverityBadge({ value }: { value: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-md border px-2.5 py-1 text-xs font-semibold ${severityTones[value] || 'border-slate-200 bg-slate-50 text-slate-700'}`}
    >
      {severityLabels[value] || value}
    </span>
  );
}

/**
 * Impactador do PDOH consolidado por regra: a causa, quem ela atinge e o que fazer.
 * Os números vêm somados dos grupos já consolidados pela API.
 */
export function ImpactCard({ impacto, to }: { impacto: ImpactoPorRegra; to: string }) {
  return (
    <Link
      to={to}
      className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-300 hover:bg-blue-50/40 focus-visible:outline-2 focus-visible:outline-blue-600"
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-bold text-slate-950">{impacto.titulo}</h3>
          <SeverityBadge value={impacto.severidade} />
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Impacta {impacto.impacto || 'a operação'}
        </p>
        {impacto.acao_recomendada && (
          <p className="mt-2 line-clamp-1 text-xs text-slate-600">
            <span className="font-semibold text-slate-700">Ação:</span> {impacto.acao_recomendada}
          </p>
        )}
      </div>
      <dl className="flex shrink-0 gap-6 text-right">
        <div>
          <dd className="text-xl font-extrabold tabular-nums text-slate-950">
            {formatNumber(impacto.colaboradores)}
          </dd>
          <dt className="text-[11px] text-slate-500">
            {impacto.colaboradores === 1 ? 'colaborador' : 'colaboradores'}
          </dt>
        </div>
        <div>
          <dd className="text-xl font-extrabold tabular-nums text-slate-950">
            {formatNumber(impacto.ocorrencias)}
          </dd>
          <dt className="text-[11px] text-slate-500">ocorrências</dt>
        </div>
      </dl>
      <ChevronRight className="size-4 shrink-0 text-slate-400" aria-hidden="true" />
    </Link>
  );
}

/**
 * Impactador de um colaborador. Abre o detalhe apenas quando solicitado, para não
 * consultar a API de todos os cards da lista.
 */
export function CollaboratorImpactCard({
  group,
  window,
}: {
  group: OperationalGroup;
  window: OperationalFilters;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <article className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="border-b border-slate-100 p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-blue-700">
              {group.marca}
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <ValidationBadge validacao={group.validacao} />
              <SeverityBadge value={group.severidade} />
            </div>
          </div>
          <h3 className="text-base font-bold leading-snug text-slate-950">{group.titulo}</h3>
          <p className="mt-3 flex items-start gap-2 text-sm text-slate-600">
            <UserRound className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <span className="break-words">
              {group.colaborador || 'Colaborador não informado'}
            </span>
          </p>
        </div>
        <div className="flex flex-1 flex-col p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p>
              <strong className="text-3xl font-bold tabular-nums tracking-tight text-slate-950">
                {formatNumber(group.quantidade)}
              </strong>
              <span className="ml-2 text-xs text-slate-500">ocorrências</span>
            </p>
            <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">
              {statusLabels[group.status_operacional] || displayLabel(group.status_operacional)}
            </span>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            {formatPeriod(group.primeira_ocorrencia, group.ultima_ocorrencia)}
            {group.campo ? ` · ${displayLabel(group.campo)}` : ''}
          </p>
          <dl className="mt-4 space-y-3 text-sm">
            <div>
              <dt className="text-xs font-semibold text-slate-500">Impacto</dt>
              <dd className="mt-1 leading-relaxed text-slate-700">
                {group.impacto || 'Não informado'}
              </dd>
            </div>
            {group.evidencia?.fonte && (
              <div>
                <dt className="text-xs font-semibold text-slate-500">Origem da evidência</dt>
                <dd className="mt-1 leading-relaxed text-slate-700">
                  {displayLabel(group.evidencia.fonte)}
                  {group.evidencia.campo ? ` · ${displayLabel(group.evidencia.campo)}` : ''}
                </dd>
              </div>
            )}
            <div className="rounded-lg bg-slate-50 p-3">
              <dt className="text-xs font-semibold text-slate-500">Ação recomendada</dt>
              <dd className="mt-1 leading-relaxed text-slate-700">
                {group.acao_recomendada || 'Orientação ainda não cadastrada para esta regra.'}
              </dd>
            </div>
          </dl>
          <DialogTrigger
            render={
              <button
                type="button"
                aria-label={`Abrir análise: ${group.titulo}, ${group.colaborador || 'colaborador não informado'}`}
              />
            }
            className="mt-4 flex min-h-11 items-center justify-between rounded-lg border border-slate-200 px-3 text-sm font-semibold text-blue-700 hover:border-blue-300 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600"
          >
            Abrir análise
            <ArrowUpRight className="size-4" aria-hidden="true" />
          </DialogTrigger>
        </div>
      </article>
      <DialogContent className="max-h-[85dvh] overflow-y-auto p-6 sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="pr-7 text-xl font-bold leading-snug">
            {group.titulo}
          </DialogTitle>
          <DialogDescription>
            {group.colaborador || 'Colaborador não informado'} · {group.marca}
          </DialogDescription>
        </DialogHeader>
        {open && <OpportunityDetail group={group} window={window} />}
      </DialogContent>
    </Dialog>
  );
}
