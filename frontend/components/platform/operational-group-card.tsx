import { ArrowUpRight, CalendarDays, UserRound } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import {
  displayLabel,
  severityLabels,
  severityTones,
  statusLabels,
} from '@/src/lib/operational-display';
import type { OperationalGroup } from '@/src/services/operational-api';

export function SeverityBadge({ value }: { value: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-md border px-2.5 py-1 text-xs font-semibold ${severityTones[value] || 'border-slate-200 bg-slate-50 text-slate-700'}`}
    >
      {severityLabels[value] || value}
    </span>
  );
}

export function OperationalGroupCard({ group }: { group: OperationalGroup }) {
  return (
    <Dialog>
      <article className="flex min-w-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 p-5">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-bold uppercase tracking-wider text-blue-700">
              {group.marca}
            </span>
            <SeverityBadge value={group.severidade} />
          </div>
          <h2 className="text-base font-bold leading-snug text-slate-950">
            {group.titulo || displayLabel(group.tipo_problema)}
          </h2>
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
              {statusLabels[group.status_operacional] ||
                displayLabel(group.status_operacional)}
            </span>
          </div>
          <p className="mt-3 flex items-start gap-2 text-xs leading-relaxed text-slate-500">
            <CalendarDays className="size-4 shrink-0" aria-hidden="true" />
            <span>
              Período das ocorrências
              <br />
              <span className="font-medium text-slate-700">
                {formatPeriod(
                  group.primeira_ocorrencia,
                  group.ultima_ocorrencia,
                )}
              </span>
            </span>
          </p>
          <dl className="mt-4 space-y-3 text-sm">
            <div>
              <dt className="text-xs font-semibold text-slate-500">
                Impacto informado
              </dt>
              <dd className="mt-1 leading-relaxed text-slate-700">
                {group.impacto || 'Não informado'}
              </dd>
            </div>
            <div className="rounded-lg bg-slate-50 p-3">
              <dt className="text-xs font-semibold text-slate-500">
                Ação recomendada
              </dt>
              <dd className="mt-1 leading-relaxed text-slate-700">
                {group.acao_recomendada ||
                  'Orientação ainda não disponibilizada.'}
              </dd>
            </div>
          </dl>
          <DialogTrigger
            render={
              <button
                type="button"
                aria-label={`Abrir resumo: ${group.titulo}, ${group.colaborador || 'colaborador não informado'}`}
              />
            }
            className="mt-4 flex min-h-11 items-center justify-between rounded-lg border border-slate-200 px-3 text-sm font-semibold text-blue-700 hover:border-blue-300 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600"
            aria-label={`Abrir resumo: ${group.titulo}, ${group.colaborador || 'colaborador não informado'}`}
          >
            Ver resumo
            <ArrowUpRight className="size-4" aria-hidden="true" />
          </DialogTrigger>
        </div>
      </article>
      <DialogContent className="max-h-[85dvh] overflow-y-auto p-6 sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="pr-7 text-xl font-bold leading-snug">
            {group.titulo}
          </DialogTitle>
          <DialogDescription>
            {group.colaborador || 'Colaborador não informado'} · {group.marca}
          </DialogDescription>
        </DialogHeader>
        <div className="flex items-center gap-3">
          <SeverityBadge value={group.severidade} />
          <span className="text-sm text-slate-600">
            {statusLabels[group.status_operacional] ||
              displayLabel(group.status_operacional)}
          </span>
        </div>
        <dl className="grid grid-cols-2 gap-4 rounded-xl bg-slate-50 p-4 text-sm">
          <div>
            <dt className="text-slate-500">Ocorrências</dt>
            <dd className="mt-1 text-2xl font-bold">
              {formatNumber(group.quantidade)}
            </dd>
          </div>
          <div>
            <dt className="text-slate-500">Responsável</dt>
            <dd className="mt-1 font-medium">
              {group.responsavel || 'Não atribuído'}
            </dd>
          </div>
          <div className="col-span-2">
            <dt className="text-slate-500">Período das ocorrências</dt>
            <dd className="mt-1 font-medium">
              {formatPeriod(group.primeira_ocorrencia, group.ultima_ocorrencia)}
            </dd>
          </div>
        </dl>
        <p className="text-sm leading-relaxed text-slate-600">
          {group.impacto || 'Impacto não informado.'}
        </p>
        <p className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-900">
          As evidências e o detalhamento das ocorrências serão disponibilizados
          na próxima etapa.
        </p>
      </DialogContent>
    </Dialog>
  );
}
