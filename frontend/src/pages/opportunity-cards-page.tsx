import { useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, SearchCheck } from 'lucide-react';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { OperationalFiltersForm } from '@/components/platform/operational-filters';
import { OperationalGroupCard } from '@/components/platform/operational-group-card';
import { Pagination } from '@/components/platform/query-controls';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import {
  filtersFromSearch,
  fixedWindow,
  loadAllGroups,
  loadGroups,
  periodFilters,
  resolvePeriod,
  type OperationalFilters,
} from '@/src/services/operational-api';
import { queryString } from '@/src/services/pdoh-api';

async function queueByKey(key: string, signal: AbortSignal) {
  const params = new URLSearchParams(key);
  const selected = filtersFromSearch(params);
  const period = await resolvePeriod(selected, signal);
  const groups = await loadGroups(
    fixedWindow(selected, period),
    Number(params.get('pagina')),
    12,
    signal,
  );
  return { period, groups };
}
async function ruleOptionsByKey(key: string, signal: AbortSignal) {
  const base = filtersFromSearch(new URLSearchParams(key));
  const groups = await loadAllGroups(base, signal, true);
  return [
    ...new Map(
      groups.items.map((group) => [
        group.tipo_problema,
        { value: group.tipo_problema, label: group.titulo },
      ]),
    ).values(),
  ];
}
function useQueue(key: string) {
  const loader = useCallback(
    (signal: AbortSignal) => queueByKey(key, signal),
    [key],
  );
  return usePdohResource(key, loader);
}
function useRuleOptions(key: string) {
  const loader = useCallback(
    (signal: AbortSignal) => ruleOptionsByKey(key, signal),
    [key],
  );
  return usePdohResource(key, loader);
}

export function OpportunityCardsPage() {
  const [search, setSearch] = useSearchParams();
  const filters = filtersFromSearch(search);
  const page = Math.max(1, Math.floor(Number(search.get('pagina')) || 1));
  const key = queryString({ ...filters, pagina: page });
  const resource = useQueue(key);
  // Opções vindas dos grupos do período, independentemente dos filtros da fila.
  const optionsKey = queryString(periodFilters(filters));
  const options = useRuleOptions(optionsKey);
  const apply = (next: OperationalFilters) =>
    setSearch(new URLSearchParams(queryString(next)));
  return (
    <>
      <Link
        to={'/dashboard' + queryString(periodFilters(filters))}
        className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-blue-700"
      >
        <ArrowLeft className="size-4" />
        Painel PDOH
      </Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-wider text-blue-700">
            Atuação operacional
          </p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight text-slate-950">
            Oportunidades
          </h1>
          <p className="mt-2 text-sm text-slate-500">
            Priorize a análise. Confira o colaborador, o impacto e as
            ocorrências.
          </p>
        </div>
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-right">
          <p className="text-2xl font-bold text-blue-950">
            {formatNumber(resource.data?.groups.total)}
          </p>
          <p className="text-xs text-blue-800">cards no filtro</p>
        </div>
      </div>
      <p className="mb-4 text-sm text-slate-600">
        {filters.marca || 'Todas as marcas'} ·{' '}
        {resource.data
          ? formatPeriod(resource.data.period.inicio, resource.data.period.fim)
          : 'Consultando período…'}
      </p>
      <OperationalFiltersForm
        key={key}
        filters={filters}
        period={resource.data?.period}
        rules={options.data || []}
        detailed
        onApply={apply}
        onReset={() => setSearch({})}
      />
      {options.error && (
        <p className="mb-4 text-sm text-amber-800">
          Não foi possível carregar as opções de regra.{' '}
          <button
            onClick={options.retry}
            className="min-h-11 font-semibold underline"
          >
            Tentar novamente
          </button>
        </p>
      )}
      {filters.regra && (
        <p className="mb-4 text-sm text-blue-800">
          Filtro de regra aplicado pelo link.{' '}
          <button
            onClick={() => {
              const next = new URLSearchParams(search);
              next.delete('regra');
              next.delete('pagina');
              setSearch(next);
            }}
            className="min-h-11 font-semibold underline"
          >
            Remover filtro
          </button>
        </p>
      )}
      <ConsultationState {...resource} hasData={!!resource.data}>
        {resource.data && (
          <>
            <div className="mb-4 flex flex-wrap justify-between gap-2 text-xs text-slate-500">
              <span>Grupos operacionais · ocorrências consolidadas</span>
              <span>Ordem: severidade → ocorrências</span>
            </div>
            <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
              {resource.data.groups.items.map((group) => (
                <OperationalGroupCard key={group.grupo_id} group={group} />
              ))}
            </div>
            {!resource.data.groups.items.length && (
              <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center">
                <SearchCheck className="mx-auto mb-3 size-8 text-blue-500" />
                <h2 className="font-semibold text-slate-800">
                  Nenhuma oportunidade neste filtro
                </h2>
                <p className="mt-2 text-sm text-slate-500">
                  Ajuste a marca, o período ou os demais filtros para consultar
                  outros grupos.
                </p>
              </div>
            )}
            <Pagination
              page={resource.data.groups.pagina}
              pages={resource.data.groups.paginas}
              label="Oportunidades"
              onPage={(value) => {
                const next = new URLSearchParams(search);
                next.set('pagina', String(value));
                setSearch(next);
              }}
            />
            <p className="mt-5 text-xs leading-relaxed text-slate-500">
              As ocorrências pertencem às janelas de processamento selecionadas;
              suas datas podem ultrapassar esse intervalo. Cada card e sua
              prioridade são entregues pela consulta operacional.
            </p>
          </>
        )}
      </ConsultationState>
    </>
  );
}

/** Links antigos ficam explicados, sem consultar dados v1 dentro do novo painel. */
export function PreviousConsultationPage() {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-8">
      <h1 className="text-xl font-bold">Consulta anterior</h1>
      <p className="mt-3 max-w-xl text-sm leading-relaxed text-slate-600">
        Este link pertence à consulta anterior. A nova visão apresenta
        oportunidades consolidadas por colaborador. O acompanhamento detalhado
        de execuções e registros será integrado em uma próxima etapa.
      </p>
      <Link
        to="/oportunidades"
        className="mt-5 inline-flex min-h-11 items-center font-semibold text-blue-700"
      >
        Abrir oportunidades
      </Link>
    </section>
  );
}
