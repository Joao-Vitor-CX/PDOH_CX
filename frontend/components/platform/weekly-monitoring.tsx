import { useCallback, useMemo, useState } from 'react';
import {
  ArrowLeft, CalendarRange, ChevronLeft, ChevronRight, Download, Eye, History, TriangleAlert, Users,
} from 'lucide-react';
import { AlertCard, AlertCategoryRow } from '@/components/platform/alert-card';
import { alertDetails, loadAlertRecords } from '@/src/services/operational-trace';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { OpportunityDetail } from '@/components/platform/opportunity-detail-modal';
import { XlsxButton, useXlsxExport } from '@/components/platform/daily-opportunities';
import { loadOpportunityRecords } from '@/src/services/daily-validation';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatDate, formatDateTime, formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import { displayLabel } from '@/src/lib/operational-display';
import {
  loadAlertGroups, type OperationalGroup, type ResolvedPeriod,
} from '@/src/services/operational-api';
import {
  csvFileName, loadOccurrences, occurrencesCsv, shiftWeek,
  type MonitoringMode, type OccurrenceRow, type WeeklyCard, type WeeklyMonitoring,
} from '@/src/services/weekly-monitoring';

function downloadCsv(name: string, content: string) {
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }));
  const link = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Baixa as ocorrências dos grupos informados, respeitando a janela selecionada. */
function useCsvDownload() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (groups: OperationalGroup[], data: WeeklyMonitoring, tipo?: string) => {
    setError(null);
    setBusy(true);
    try {
      const rows = await loadOccurrences(groups, data.window);
      downloadCsv(csvFileName(data.period, tipo), occurrencesCsv(rows));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível gerar o arquivo.');
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, error };
}

function DownloadButton({ label, onClick, busy, disabled }: {
  label: string; onClick: () => void; busy: boolean; disabled?: boolean;
}) {
  return (
    <Button variant="outline" className="min-h-11" onClick={onClick} disabled={disabled || busy}>
      <Download aria-hidden="true" />
      {busy ? 'Gerando arquivo…' : label}
    </Button>
  );
}

function CardMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <dd className="text-lg font-extrabold tabular-nums text-slate-950">{formatNumber(value)}</dd>
      <dt className="text-[11px] text-slate-500">{label}</dt>
    </div>
  );
}

function MonitoringCard({ card, period, mode, onOpen }: {
  card: WeeklyCard; period: ResolvedPeriod; mode: MonitoringMode; onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`Abrir detalhamento: ${card.titulo}`}
      className="flex min-h-36 flex-col rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-colors hover:border-blue-300 hover:bg-blue-50/30 focus-visible:outline-2 focus-visible:outline-blue-600"
    >
      <span className="break-words text-sm font-bold tracking-tight text-slate-950">{card.tipo}</span>
      <span className="mt-1 text-xs text-slate-500">
        {mode === 'semana' ? 'Semana' : 'Dia'} {formatPeriod(period.inicio, period.fim)}
      </span>
      <dl className="mt-auto grid grid-cols-3 gap-2 pt-4">
        <CardMetric label="Ocorrências" value={card.ocorrencias} />
        <CardMetric label="Colaboradores" value={card.colaboradores} />
        <CardMetric label="Fallback" value={card.fallback} />
      </dl>
    </button>
  );
}

const JORNADA_ROTULO = { sim: 'Sim', fallback: 'Não · jornada padrão 44H', nao: 'Não apurada' } as const;

function OccurrenceTable({ rows, onOpen }: { rows: OccurrenceRow[]; onOpen: (grupoId: string) => void }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[60rem] text-left text-xs">
        <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
          <tr>
            {['Colaborador', 'Data', 'Regra aplicada', 'Oportunidade', 'Jornada encontrada', 'Fallback',
              'Horário esperado', 'Evidências', 'Status', 'Histórico', ''].map((name) => (
              <th key={name} scope="col" className="px-3 py-2 font-semibold">{name}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.oportunidade_id} className="align-top">
              <td className="px-3 py-2 font-medium text-slate-900">{row.colaborador}</td>
              <td className="px-3 py-2 whitespace-nowrap">{formatDate(row.data)}</td>
              <td className="px-3 py-2">{row.regra}</td>
              <td className="px-3 py-2 font-mono text-[11px] text-slate-500" title={row.oportunidade_id}>{row.oportunidade_id.slice(0, 8)}</td>
              <td className="px-3 py-2">
                {JORNADA_ROTULO[row.jornada_encontrada]}
                <span className="block text-[11px] text-slate-500">{row.jornada_aplicada ?? 'Jornada não informada'} · {displayLabel(row.jornada_origem)}</span>
              </td>
              <td className="px-3 py-2">
                {row.fallback ? 'Sim' : 'Não'}
                {row.motivo_fallback && <span className="block text-[11px] text-slate-500">{row.motivo_fallback}</span>}
              </td>
              <td className="px-3 py-2 whitespace-nowrap">{row.horario_esperado ?? '—'}</td>
              <td className="px-3 py-2 break-words">{row.evidencia ?? 'Não informada'}</td>
              <td className="px-3 py-2">
                {displayLabel(row.status)}
                <span className="block text-[11px] text-slate-500">{displayLabel(row.validacao)}</span>
              </td>
              <td className="px-3 py-2 text-[11px] text-slate-600">
                <span className="flex items-center gap-1"><History className="size-3" aria-hidden="true" />{formatDateTime(row.identificada_em)}</span>
                <span className="block text-slate-500">{row.execucao}</span>
                {row.repeticoes > 1 && <span className="block text-slate-500">gravada em {formatNumber(row.repeticoes)} execuções</span>}
              </td>
              <td className="px-3 py-2">
                <Button variant="ghost" size="sm" onClick={() => onOpen(row.grupo_id)} aria-label={`Ver comprovação de ${row.colaborador}`}>
                  <Eye aria-hidden="true" />Comprovação
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Detalhamento de uma regra na janela selecionada: somente as ocorrências dessa janela. */
function WeeklyDetail({ data, card, mode, onClose }: {
  data: WeeklyMonitoring; card: WeeklyCard | null; mode: MonitoringMode; onClose: () => void;
}) {
  const [selected, setSelected] = useState<OperationalGroup | null>(null);
  const groups = useMemo(
    () => (card ? data.groups.filter((group) => group.tipo_problema === card.tipo) : []),
    [card, data.groups],
  );
  const key = card ? `${card.tipo}|${data.period.inicio}|${data.period.fim}|${groups.map((g) => g.grupo_id).join(',')}` : '';
  const loader = useCallback((signal: AbortSignal) => loadOccurrences(groups, data.window, signal),
    [groups, data.window]);
  const resource = usePdohResource(key, loader);
  const csv = useCsvDownload();

  return (
    <Dialog open={!!card} onOpenChange={(open) => { if (!open) { setSelected(null); onClose(); } }}>
      <DialogContent className="flex max-h-[90dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-6xl">
        <DialogHeader className="shrink-0 border-b border-slate-100 px-5 py-5 pr-12">
          <DialogTitle className="text-lg font-bold text-slate-950">{card?.titulo ?? ''}</DialogTitle>
          <DialogDescription>
            {mode === 'semana' ? 'Semana' : 'Dia'} {formatPeriod(data.period.inicio, data.period.fim)} ·{' '}
            {formatNumber(card?.ocorrencias)} ocorrências · {formatNumber(card?.colaboradores)} colaboradores ·{' '}
            {formatNumber(card?.fallback)} com fallback
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          {selected ? (
            <>
              <Button variant="ghost" size="sm" className="mb-4" onClick={() => setSelected(null)}>
                <ArrowLeft aria-hidden="true" />Voltar ao detalhamento
              </Button>
              <OpportunityDetail group={selected} window={data.window} />
            </>
          ) : (
            <ConsultationState {...resource} hasData={!!resource.data}>
              {resource.data && (resource.data.length
                ? <OccurrenceTable rows={resource.data} onOpen={(id) => setSelected(groups.find((g) => g.grupo_id === id) ?? null)} />
                : <p className="rounded-xl border border-slate-200 p-8 text-center text-sm text-slate-500">Nenhuma ocorrência nesta janela.</p>)}
            </ConsultationState>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-slate-50 px-5 py-3">
          <p className="text-xs text-slate-500">{csv.error ?? 'O arquivo traz uma linha por ocorrência da janela selecionada.'}</p>
          {card && <DownloadButton label="Baixar CSV desta regra" busy={csv.busy}
            onClick={() => void csv.run(groups, data, card.tipo)} disabled={!groups.length} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function AlertCategoryDetail({ tipo, data }: { tipo: string; data: WeeklyMonitoring }) {
  const key = `${tipo}|${data.period.inicio}|${data.period.fim}`;
  // Grupos (resumo) + registros individuais da categoria, para explicar cada pendência.
  const loader = useCallback(async (signal: AbortSignal) => {
    const [groups, records] = await Promise.allSettled([
      loadAlertGroups({ ...data.window, tipo }, 1, 12, signal),
      loadAlertRecords(tipo, data.window, signal),
    ]);
    if (groups.status === 'rejected') throw groups.reason;
    return { ...groups.value, records: records.status === 'fulfilled' ? records.value : null };
  }, [tipo, data.window]);
  const resource = usePdohResource(key, loader);
  return (
    <ConsultationState {...resource} hasData={!!resource.data}>
      {resource.data && (
        <div className="mt-2 mb-3 space-y-3">
          <div className="grid gap-3 md:grid-cols-2">
            {resource.data.items.map((alerta) => (
              <AlertCard key={alerta.grupo_id} alerta={alerta}
                detalhes={resource.data?.records ? alertDetails(alerta, resource.data.records) : null} />
            ))}
          </div>
          {resource.data.total > resource.data.items.length && (
            <p className="text-xs text-slate-500">
              Exibindo {formatNumber(resource.data.items.length)} de {formatNumber(resource.data.total)} pendências desta categoria.
            </p>
          )}
        </div>
      )}
    </ConsultationState>
  );
}

/** Alertas cadastrais: apenas monitoramento. Não criam oportunidade, não disparam o sino, não alteram regra. */
function AlertMonitor({ data }: { data: WeeklyMonitoring }) {
  const [open, setOpen] = useState<string | null>(null);
  const alerts = data.alerts;
  return (
    <section className="mt-4 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5" aria-label="Alertas cadastrais">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="flex items-center gap-2 text-base font-bold text-slate-950">
            <TriangleAlert className="size-5 text-amber-600" aria-hidden="true" />
            Alertas cadastrais
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            Apenas monitoramento: não geram oportunidade, não disparam o sino e não alteram regras.
          </p>
        </div>
        {alerts && (
          <p className="text-xs text-slate-500">
            {formatNumber(alerts.grupos)} pendências · {formatNumber(alerts.colaboradores_afetados)} colaboradores
          </p>
        )}
      </div>
      {!alerts && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          Alertas cadastrais indisponíveis no momento. Os cards de oportunidades acima não dependem desta seção.
        </p>
      )}
      <div className="space-y-2">
        {(alerts?.por_regra ?? []).map((categoria) => (
          <div key={categoria.tipo_problema}>
            <AlertCategoryRow categoria={categoria} expanded={open === categoria.tipo_problema}
              onToggle={() => setOpen(open === categoria.tipo_problema ? null : categoria.tipo_problema)} />
            {open === categoria.tipo_problema && <AlertCategoryDetail tipo={categoria.tipo_problema} data={data} />}
          </div>
        ))}
      </div>
      {alerts && !alerts.por_regra.length && (
        <p className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
          Nenhuma pendência cadastral nesta janela.
        </p>
      )}
    </section>
  );
}

/**
 * Monitoramento semanal de oportunidades. Cards pequenos por tipo, detalhamento da janela,
 * download e alertas cadastrais — tudo lido das APIs v2 existentes, sem regra de negócio aqui.
 */
export function WeeklyMonitoringSection({
  mode, week, day, data, error, loading, refreshing, updatedAt, onRetry, onMode, onWeek, onDay, detail, onDetail,
}: {
  mode: MonitoringMode;
  week: ResolvedPeriod;
  day: string;
  data: WeeklyMonitoring | null;
  error: string | null;
  loading: boolean;
  refreshing: boolean;
  updatedAt: Date | null;
  onRetry: () => void;
  onMode: (mode: MonitoringMode) => void;
  onWeek: (week: ResolvedPeriod) => void;
  onDay: (day: string) => void;
  detail: string | null;
  onDetail: (tipo: string | null) => void;
}) {
  const csv = useCsvDownload();
  const xlsx = useXlsxExport();
  const [showAllCards, setShowAllCards] = useState(false);
  const card = data?.cards.find((item) => item.tipo === detail) ?? null;
  return (
    <>
    <section className="mt-6 rounded-2xl border border-slate-200 bg-slate-50/60 p-4 sm:p-5" aria-label="Monitoramento de oportunidades">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-bold text-slate-950">
            <CalendarRange className="size-5 text-blue-700" aria-hidden="true" />
            Monitoramento de oportunidades
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">Ocorrências consolidadas por tipo.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div aria-label="Recorte do monitoramento" className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
            {(['semana', 'dia'] as const).map((value) => (
              <button key={value} type="button" aria-pressed={mode === value} onClick={() => onMode(value)}
                className={`min-h-10 rounded-md px-3 text-sm font-semibold ${mode === value ? 'bg-blue-700 text-white' : 'text-slate-600 hover:bg-slate-100'}`}>
                {value === 'semana' ? 'Semana' : 'Dia'}
              </button>
            ))}
          </div>
          {mode === 'semana' && (
            <div className="inline-flex items-center rounded-lg border border-slate-200 bg-white">
              <Button variant="ghost" size="icon" className="size-10" aria-label="Semana anterior" onClick={() => onWeek(shiftWeek(week, -1))}>
                <ChevronLeft aria-hidden="true" />
              </Button>
              <span className="min-w-36 px-1 text-center text-sm font-semibold text-slate-800">
                {formatDate(week.inicio).slice(0, 5)} a {formatDate(week.fim)}
              </span>
              <Button variant="ghost" size="icon" className="size-10" aria-label="Próxima semana" onClick={() => onWeek(shiftWeek(week, 1))}>
                <ChevronRight aria-hidden="true" />
              </Button>
            </div>
          )}
          {mode === 'dia' && (
            <label className="flex items-center gap-2 text-sm font-semibold text-slate-700">
              Data
              <input type="date" value={day} onChange={(event) => onDay(event.target.value)}
                className="min-h-10 rounded-lg border border-slate-200 bg-white px-2 text-slate-900" />
            </label>
          )}
          <DownloadButton label="Baixar CSV" busy={csv.busy}
            disabled={!data?.groups.length} onClick={() => data && void csv.run(data.groups, data)} />
          <XlsxButton busy={xlsx.busy} disabled={!data?.groups.length}
            onClick={() => data && void xlsx.run(data.period, () => loadOpportunityRecords(data.groups, data.window))} />
        </div>
      </div>
      {(csv.error || xlsx.error) && <p role="alert" className="mb-3 text-sm text-amber-800">{csv.error ?? xlsx.error}</p>}
      <ConsultationState error={error} loading={loading} refreshing={refreshing} updatedAt={updatedAt} retry={onRetry} hasData={!!data}>
        {data && (
          <>
            {data.cards.length ? (
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {data.cards.slice(0, showAllCards ? undefined : 3).map((item) => (
                  <MonitoringCard key={item.tipo} card={item} period={data.period} mode={mode} onOpen={() => onDetail(item.tipo)} />
                ))}
              </div>
            ) : (
              <p className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">
                <Users className="size-4" aria-hidden="true" />
                Nenhuma oportunidade registrada neste {mode === 'semana' ? 'período semanal' : 'dia'}.
              </p>
            )}
            {data.cards.length > 3 && (
              <Button variant="ghost" className="mt-3 text-blue-700" onClick={() => setShowAllCards((value) => !value)}>
                {showAllCards ? 'Mostrar menos' : `Ver todos os ${data.cards.length} tipos`}
              </Button>
            )}
          </>
        )}
      </ConsultationState>
    </section>
    {data && <AlertMonitor key={`${data.period.inicio}|${data.period.fim}`} data={data} />}
    {data && <WeeklyDetail data={data} card={card} mode={mode} onClose={() => onDetail(null)} />}
    </>
  );
}
