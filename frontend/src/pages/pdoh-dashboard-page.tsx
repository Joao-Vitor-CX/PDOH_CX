import { useCallback, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowUpRight, RefreshCw, Target } from 'lucide-react';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { ImpactCard } from '@/components/platform/impact-card';
import { OperationalFiltersForm } from '@/components/platform/operational-filters';
import { PdohComposition, PdohResult } from '@/components/platform/pdoh-result';
import { PdohHeader } from '@/components/platform/pdoh-header';
import { PdohTrend } from '@/components/platform/pdoh-trend';
import { PdohDailyValidation } from '@/components/platform/pdoh-daily-validation';
import { WeeklyMonitoringSection } from '@/components/platform/weekly-monitoring';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { useWeeklyMonitoring } from '@/src/hooks/use-weekly-monitoring';
import { formatPeriod } from '@/src/lib/pdoh-format';
import { loadPdohOverview } from '@/src/services/findings-service';
import {
  filtersFromSearch,
  fixedWindow,
  type OperationalFilters,
} from '@/src/services/operational-api';
import { queryString } from '@/src/services/pdoh-api';
import {
  OPPORTUNITIES_REFRESHED, weekContaining, type MonitoringMode,
} from '@/src/services/weekly-monitoring';

function overviewByKey(key: string, signal: AbortSignal) {
  return loadPdohOverview(filtersFromSearch(new URLSearchParams(key)), signal);
}
function useOverview(key: string) {
  const loader = useCallback((signal: AbortSignal) => overviewByKey(key, signal), [key]);
  return usePdohResource(key, loader);
}

/** Seção secundária que não respondeu: o resultado do PDOH acima continua válido. */
function SectionUnavailable({ what, onRetry }: { what: string; onRetry: () => void }) {
  return (
    <p className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
      {what} indisponíveis no momento. O resultado do PDOH acima não depende desta seção.{' '}
      <button type="button" className="font-bold underline" onClick={onRetry}>
        Tentar novamente
      </button>
    </p>
  );
}

/**
 * Painel PDOH. A leitura é sempre resultado → indicadores → causas → cadastro.
 * Nenhum número é calculado aqui: tudo vem consolidado das APIs v2.
 */
export function PdohDashboardPage() {
  const [search, setSearch] = useSearchParams();
  const filters = filtersFromSearch(search);
  const key = queryString(filters);
  const resource = useOverview(key);
  const data = resource.data;
  const apply = (next: OperationalFilters) =>
    setSearch(new URLSearchParams(queryString({ ...next, pagina: undefined, tamanho: 50 })));
  const changePage = (pagina: number) =>
    setSearch(new URLSearchParams(queryString({ ...filters, pagina, tamanho: 50 })));
  const janela = data ? queryString(fixedWindow({}, data.period)) : queryString(filters);

  // Monitoramento: semana (padrão) ou o período do painel. Estado na URL para o sino abrir direto.
  const mode: MonitoringMode = search.get('monitor') === 'dia' ? 'dia' : 'semana';
  const weekParam = search.get('semana');
  const detail = search.get('detalhe');
  const week = weekContaining(weekParam && /^\d{4}-\d{2}-\d{2}$/.test(weekParam) ? weekParam
    : data?.period.fim ?? new Date().toISOString().slice(0, 10));
  const dayParam = search.get('dia');
  const day = dayParam && /^\d{4}-\d{2}-\d{2}$/.test(dayParam) ? dayParam : week.fim;
  const monitoringStart = mode === 'semana' ? week.inicio : day;
  const monitoringEnd = mode === 'semana' ? week.fim : day;
  const monitoringPeriod = data && monitoringStart && monitoringEnd
    ? { inicio: monitoringStart, fim: monitoringEnd } : null;
  const monitoring = useWeeklyMonitoring(monitoringPeriod?.inicio ?? null, monitoringPeriod?.fim ?? null);
  const updateMonitor = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(search);
    for (const [name, value] of Object.entries(changes)) {
      if (value === null) next.delete(name);
      else next.set(name, value);
    }
    setSearch(next, { replace: true });
  };

  const [confirming, setConfirming] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [refreshComplete, setRefreshComplete] = useState(false);
  const [reprocessError, setReprocessError] = useState<string | null>(null);
  // Relê a janela selecionada: a esteira já gravou e deduplicou; aqui se atualiza e se confere.
  async function reprocess() {
    setReprocessing(true);
    setReprocessError(null);
    setRefreshComplete(false);
    try {
      await monitoring.reload();
      resource.retry();
      window.dispatchEvent(new Event(OPPORTUNITIES_REFRESHED));
      setRefreshComplete(true);
    } catch (reason) {
      setReprocessError(reason instanceof Error ? reason.message : 'Não foi possível atualizar as oportunidades.');
    } finally {
      setReprocessing(false);
      setConfirming(false);
    }
  }

  return (
    <>
      <PdohHeader
        periodoInicio={data?.period.inicio ?? null}
        periodoFim={data?.period.fim ?? null}
        updatedAt={resource.updatedAt}
        refreshing={resource.refreshing}
        automatico={data?.pdoh.periodo_automatico}
      />
      <div className="mb-4 flex flex-wrap items-center justify-end gap-3">
        <span className="text-xs text-slate-500">Reprocessamento aguardando integração do backend.</span>
        <Button variant="outline" className="min-h-11" disabled
          title="A API ainda não oferece endpoint de reprocessamento da esteira">
          Reprocessar oportunidades
        </Button>
        <Button
          className="min-h-11 bg-blue-700 text-white hover:bg-blue-800"
          disabled={!monitoring.data || reprocessing}
          onClick={() => setConfirming(true)}
        >
          <RefreshCw className={reprocessing ? 'animate-spin' : ''} aria-hidden="true" />
          {reprocessing ? 'Atualizando…' : 'Atualizar dados'}
        </Button>
      </div>
      <AlertDialog open={confirming} onOpenChange={(open) => { if (!reprocessing) setConfirming(open); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Atualizar leitura das oportunidades?</AlertDialogTitle>
            <AlertDialogDescription>
              {monitoringPeriod && `Janela ${formatPeriod(monitoringPeriod.inicio, monitoringPeriod.fim)}. `}
              As oportunidades já geradas pela esteira serão lidas novamente para atualizar cards,
              detalhamento e Central de Notificações. A execução da esteira depende de um endpoint
              de reprocessamento do backend, ainda indisponível neste contrato.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={reprocessing}>Cancelar</AlertDialogCancel>
            <AlertDialogAction disabled={reprocessing} onClick={() => void reprocess()}>
              {reprocessing ? 'Atualizando…' : 'Atualizar leitura'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {reprocessError && (
        <p role="alert" className="mb-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          {reprocessError}
        </p>
      )}
      {refreshComplete && (
        <output aria-label="Leitura atualizada" className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-950">
          Oportunidades e Central consultadas novamente. A execução da esteira depende do backend.
          <button type="button" className="ml-auto font-semibold underline" onClick={() => setRefreshComplete(false)}>Fechar</button>
        </output>
      )}
      <OperationalFiltersForm
        key={key}
        filters={filters}
        period={data?.period}
        lockedBrand
        pdohValidation
        collaborators={data?.pdoh.filtros_disponiveis.colaboradores}
        states={data?.pdoh.filtros_disponiveis.estados}
        onApply={apply}
        onReset={() => setSearch({})}
      />

      <ConsultationState {...resource} hasData={!!data}>
        {data && (
          <>
            {/* 1. Resultado e sua composição */}
            <section
              className="grid gap-4 xl:grid-cols-[0.8fr_3.2fr]"
              aria-label="Resultado da operação"
            >
              <PdohResult summary={data.pdoh} />
              <PdohComposition summary={data.pdoh} />
            </section>

            {/* 2. Tendência do resultado — série oficial de /pdoh/evolucao */}
            <div className="mt-6">
              <PdohTrend window={fixedWindow(filters, data.period)} />
            </div>

            {/* 3. Monitoramento operacional: oportunidades seguidas de alertas cadastrais. */}
            <WeeklyMonitoringSection
              mode={mode}
              week={week}
              data={monitoring.data}
              error={monitoring.error}
              loading={monitoring.loading}
              refreshing={monitoring.refreshing}
              updatedAt={monitoring.updatedAt}
              onRetry={monitoring.retry}
              day={day}
              onMode={(value) => updateMonitor({ monitor: value === 'dia' ? 'dia' : null, detalhe: null })}
              onDay={(value) => updateMonitor({ monitor: 'dia', dia: value, detalhe: null })}
              onWeek={(value) => updateMonitor({ monitor: null, semana: value.inicio, detalhe: null })}
              detail={detail}
              onDetail={(tipo) => updateMonitor({ detalhe: tipo })}
            />

            <PdohDailyValidation summary={data.pdoh} onPage={changePage} window={fixedWindow(filters, data.period)} />

            {/* Análise complementar preservada após o monitoramento. */}
            <div className="mt-6">
              <section>
                <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                  <div>
                    <h2 className="flex items-center gap-2 text-lg font-bold text-slate-950">
                      <Target className="size-5 text-blue-700" aria-hidden="true" />
                      Principais impactadores do PDOH
                    </h2>
                    <p className="mt-0.5 text-xs text-slate-500">
                      Causas que exigem ação para melhorar o indicador.
                    </p>
                  </div>
                  <Link
                    to={'/impactadores' + janela}
                    className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-blue-700"
                  >
                    Ver todos
                    <ArrowUpRight className="size-4" aria-hidden="true" />
                  </Link>
                </div>
                {!data.impactos && <SectionUnavailable what="Impactadores" onRetry={resource.retry} />}
                <div className="space-y-3">
                  {(data.impactos ?? []).slice(0, 5).map((impacto) => (
                    <ImpactCard
                      key={impacto.tipo}
                      impacto={impacto}
                      to={'/impactadores' + queryString({ ...fixedWindow({}, data.period), tipo: impacto.tipo })}
                    />
                  ))}
                </div>
                {data.impactos && !data.impactos.length && (
                  <p className="rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500">
                    Nenhum impactador do PDOH neste período.
                  </p>
                )}
              </section>
            </div>

            <p className="mt-6 text-xs leading-relaxed text-slate-500">
              O período seleciona as janelas de processamento consolidadas. As datas das
              ocorrências são preservadas e podem se estender além dessa janela.
            </p>
          </>
        )}
      </ConsultationState>
    </>
  );
}
