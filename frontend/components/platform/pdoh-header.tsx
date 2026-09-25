import { CalendarRange, Clock3 } from 'lucide-react';
import { OPERACAO } from '@/src/lib/operacao';
import { formatPeriod } from '@/src/lib/pdoh-format';

/**
 * Cabeçalho compacto: identifica a operação e a janela consultada, sem ocupar a tela.
 * O período vem resolvido da API — o navegador não calcula datas.
 */
export function PdohHeader({
  periodoInicio,
  periodoFim,
  updatedAt,
  refreshing = false,
  subtitulo,
  automatico = false,
  semPeriodo = false,
}: {
  periodoInicio: string | null;
  periodoFim: string | null;
  updatedAt: Date | null;
  refreshing?: boolean;
  subtitulo?: string;
  /** A API escolheu o período: a semana mais recente com dados oficiais. */
  automatico?: boolean;
  /** Páginas de configuração não têm período: o bloco some em vez de ficar em "Consultando…". */
  semPeriodo?: boolean;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-4">
      <div className="flex min-w-0 items-center gap-4">
        {/* oxlint-disable-next-line nextjs/no-img-element -- app Vite: não existe next/image */}
        <img
          src={OPERACAO.logo}
          alt={OPERACAO.nome}
          width={132}
          height={36}
          className="h-9 w-auto shrink-0 object-contain"
        />
        <div className="min-w-0 border-l border-slate-200 pl-4">
          <h1 className="text-lg font-extrabold tracking-tight text-slate-950">
            {OPERACAO.titulo}
          </h1>
          <p className="text-xs text-slate-500">{subtitulo || OPERACAO.descricao}</p>
        </div>
      </div>
      <dl className="flex flex-wrap items-center gap-x-8 gap-y-2">
        {!semPeriodo && (
          <div>
            <dt className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              <CalendarRange className="size-3.5" aria-hidden="true" />
              Período analisado
            </dt>
            <dd className="mt-0.5 text-sm font-semibold text-slate-900">
              {periodoInicio ? formatPeriod(periodoInicio, periodoFim) : 'Consultando…'}
              <span className="ml-2 text-xs font-normal text-slate-500">
                {automatico ? 'Período mais recente com dados' : 'Semana fechada · seg–sáb'}
              </span>
            </dd>
          </div>
        )}
        <div>
          <dt className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <Clock3 className="size-3.5" aria-hidden="true" />
            Última atualização
          </dt>
          <dd className="mt-0.5 text-sm font-semibold text-slate-900">
            {updatedAt
              ? new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(updatedAt)
              : 'Aguardando dados'}
            {refreshing && updatedAt ? (
              <span className="ml-2 text-xs font-normal text-blue-700">atualizando…</span>
            ) : null}
          </dd>
        </div>
      </dl>
    </header>
  );
}
