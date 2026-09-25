import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, Bell, BellOff, CheckCheck, ChevronRight, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { useOpportunityNotifications } from '@/src/hooks/use-opportunity-notifications';
import { formatDate, formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import {
  isNewNotification, notificationDetailUrl, notificationMessage, type WeeklyNotification,
} from '@/src/services/opportunity-notifications';

/**
 * Central de Notificações. Um aviso por regra na semana vigente (resumo consolidado);
 * abrir um aviso leva ao detalhamento semanal da Dashboard.
 */
export function OpportunityNotifications({ userId }: { userId: string }) {
  const { data, error, refreshing, seen, markSeen, refresh } = useOpportunityNotifications(userId);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const items = data?.notifications ?? [];
  const unread = data ? items.filter((item) => isNewNotification(item, data.period, seen)) : [];
  const count = unread.length;
  const summary = count === 1 ? 'Há ocorrências novas em 1 regra nesta semana.' : count > 1
    ? `Há ocorrências novas em ${formatNumber(count)} regras nesta semana.` : 'Nenhuma ocorrência nova nesta semana.';
  const label = error ? 'Notificações: não foi possível atualizar' : !data
    ? 'Notificações: carregando ocorrências' : `Notificações: ${summary}`;

  function openDetail(item?: WeeklyNotification) {
    if (!data) return;
    if (item) markSeen([item], data.period);
    setOpen(false);
    void navigate(notificationDetailUrl(data.period, item?.tipo));
  }

  return (
    <Dialog open={open} onOpenChange={(value) => {
      setOpen(value);
      if (value) refresh();
    }}>
      <DialogTrigger render={<Button variant="ghost" size="icon" />} className="relative size-11 rounded-full text-slate-600 hover:bg-blue-50 hover:text-blue-700" aria-label={label}>
        <Bell className="size-5" aria-hidden="true" />
        {error ? <span className="absolute top-0 right-0 grid min-w-5 place-items-center rounded-full bg-amber-600 px-1 text-[10px] font-bold leading-5 text-white" aria-hidden="true">!</span>
          : count > 0 && <span className="absolute top-0 right-0 min-w-5 rounded-full bg-blue-700 px-1 text-center text-[10px] font-bold leading-5 text-white" aria-hidden="true">{count > 99 ? '99+' : count}</span>}
      </DialogTrigger>
      <output className="sr-only">{error ? 'Não foi possível carregar notificações.' : data ? summary : 'Carregando notificações.'}</output>
      <DialogContent className="flex max-h-[88dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-xl">
        <DialogHeader className="shrink-0 border-b border-slate-100 px-5 py-5 pr-12">
          <DialogTitle className="text-lg font-bold text-slate-950">Central de Notificações</DialogTitle>
          <DialogDescription>Resumo semanal das oportunidades comprovadas, uma linha por regra.</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto px-5 py-4" aria-busy={refreshing}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-slate-500">{data ? `Semana ${formatPeriod(data.period.inicio, data.period.fim)}` : 'Consultando ocorrências…'}</p>
            <Button variant="ghost" size="sm" disabled={refreshing} onClick={refresh} aria-label="Atualizar notificações">
              <RefreshCw className={refreshing ? 'animate-spin' : ''} aria-hidden="true" />Atualizar
            </Button>
          </div>
          {error && <div role="alert" className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <p className="font-semibold">Não foi possível carregar notificações.</p>
            {data && <p className="mt-1 text-xs">A lista abaixo é da última consulta bem-sucedida.</p>}
            <Button variant="outline" size="sm" className="mt-2" onClick={refresh} disabled={refreshing}>Tentar novamente</Button>
          </div>}
          {!data && !error && <p className="py-10 text-center text-sm text-slate-500">Carregando notificações…</p>}
          {data && <>
            {!error && <div className={`mb-4 flex items-center gap-3 rounded-xl p-4 ${count ? 'bg-blue-50 text-blue-900' : 'bg-slate-50 text-slate-600'}`}>
              {count ? <Bell className="size-5 shrink-0" aria-hidden="true" /> : <BellOff className="size-5 shrink-0" aria-hidden="true" />}
              <p className="text-sm font-medium">{summary}</p>
            </div>}
            {count > 0 && <Button variant="ghost" size="sm" className="mb-3 text-blue-700" onClick={() => markSeen(items, data.period)}><CheckCheck aria-hidden="true" />Marcar todas como vistas</Button>}
            {items.length > 0 && <ul className="space-y-2">
              {items.map((item) => {
                const isNew = isNewNotification(item, data.period, seen);
                return <li key={item.tipo}>
                  <button type="button" onClick={() => openDetail(item)} aria-label={`Abrir detalhamento semanal: ${item.titulo}`} className={`flex w-full items-start gap-3 rounded-xl border p-4 text-left transition hover:border-blue-300 hover:bg-blue-50 focus-visible:outline-2 focus-visible:outline-blue-600 ${isNew ? 'border-blue-100 bg-blue-50/40' : 'border-slate-200 bg-white'}`}>
                    <span className={`mt-1.5 size-2 shrink-0 rounded-full ${isNew ? 'bg-blue-600' : 'bg-slate-300'}`} aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block break-words text-sm font-semibold text-slate-900">{item.titulo}</span>
                      <span className="mt-1 block break-words text-sm text-slate-700">{notificationMessage(item)}</span>
                      <span className="mt-2 block text-xs text-slate-500">
                        {formatNumber(item.colaboradores)} {item.colaboradores === 1 ? 'colaborador' : 'colaboradores'} · última em {formatDate(item.ultima_ocorrencia)} · {isNew ? 'Nova' : 'Vista'}
                      </span>
                    </span>
                    <ChevronRight className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden="true" />
                  </button>
                </li>;
              })}
            </ul>}
          </>}
        </div>
        <div className="shrink-0 border-t border-slate-100 bg-slate-50 px-5 py-4">
          {data && <Button onClick={() => openDetail()} className="min-h-11 w-full bg-blue-700 text-white hover:bg-blue-800">Abrir monitoramento da semana<ArrowUpRight aria-hidden="true" /></Button>}
          <p className="mt-2 text-center text-[11px] text-slate-500">Leitura salva para você neste navegador. Atualização automática a cada minuto.</p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
