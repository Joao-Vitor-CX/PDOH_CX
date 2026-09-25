import { useCallback } from 'react';
import { ChevronRight } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import {
  ConsultationState,
  StatusBadge,
} from '@/components/platform/consultation-ui';
import { FilterPanel } from '@/components/platform/filter-panel';
import { PageHeader } from '@/components/platform/page-header';
import {
  DateFilters,
  FilterField,
  Pagination,
} from '@/components/platform/query-controls';
import { OpportunityDetail } from '@/components/platform/opportunity-detail';
import { AlertGroups } from '@/components/platform/alert-groups';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatDate, formatNumber } from '@/src/lib/pdoh-format';
import {
  groupPage,
  kindLabel,
  opportunityName,
  recordLabel,
  catalogKind,
} from '@/src/lib/opportunity-presentation';
import {
  opportunityService,
  loadCatalog,
  type OpportunityGroup,
  type OpportunitySummaryData,
} from '@/src/services/opportunity-service';
import { queryString } from '@/src/services/pdoh-api';

export function OpportunitySummary({
  summary,
}: {
  summary: OpportunitySummaryData;
}) {
  return (
    <section
      className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4"
      aria-label="Resumo de oportunidades"
    >
      <div className="col-span-2 rounded-xl border border-blue-200 bg-blue-50 px-5 py-4 xl:col-span-1">
        <p className="text-sm font-semibold text-blue-950">
          Oportunidades operacionais
        </p>
        <p className="mt-1 text-3xl font-extrabold text-blue-950">
          {formatNumber(summary.operational)}
        </p>
        <p className="text-xs text-blue-800">
          Situações para análise / tratativa, conforme catálogo atual
        </p>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white px-5 py-4">
        <p className="text-sm font-semibold">Operacionais em aberto</p>
        <p className="mt-1 text-2xl font-bold">
          {formatNumber(summary.pending)}
        </p>
        <p className="text-xs text-slate-500">Status Aberta no filtro atual</p>
      </div>
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4"><p className="text-sm font-semibold">Alertas de qualidade</p><p className="mt-1 text-2xl font-bold">{formatNumber(summary.alerts)}</p><p className="text-xs text-slate-500">Registros para acompanhamento cadastral</p></div>
      <div className="rounded-xl border border-slate-200 bg-white px-5 py-4">
        <p className="text-sm font-semibold">Telemetria / históricos</p>
        <p className="mt-1 text-2xl font-bold text-slate-600">
          {formatNumber(summary.informative)}
        </p>
        <p className="text-xs text-slate-500">
          Telemetria em uma visão separada
        </p>
      </div>
    </section>
  );
}
function GroupRecords({
  group,
  filters,
  search,
  setSearch,
}: {
  group: OpportunityGroup;
  filters: Record<string, string>;
  search: URLSearchParams;
  setSearch: (search: URLSearchParams) => void;
}) {
  const page = Math.max(1, Math.floor(Number(search.get('pagina')) || 1));
  const by = search.get('agrupar') || 'campo';
  const grouping =
    by === 'processo' || by === 'marca' || by === 'data' ? by : 'campo';
  const query = queryString({
    ...filters,
    regra: group.id,
    tipo: group.rule.tipo_problema,
    pagina: page,
    tamanho: 50,
  });
  const loader = useCallback(
    (signal: AbortSignal) =>
      opportunityService.list(
        {
          ...Object.fromEntries(new URLSearchParams(query)),
          pagina: page,
          tamanho: 50,
        },
        signal,
      ),
    [query, page],
  );
  const resource = usePdohResource(query, loader);
  const subgroups = groupPage(resource.data?.items || [], grouping);
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(search);
    next.delete('oportunidade');
    next.delete('historico');
    next.set(key, value);
    setSearch(next);
  };
  return (
    <section
      className="mt-4 rounded-xl border border-blue-200 bg-white p-4"
      aria-label="Registros do grupo"
    >
      <h2 className="font-bold text-slate-900">
        {opportunityName(group.rule.tipo_problema)}
      </h2>
      <p className="my-2 text-xs text-slate-500">
        {group.rule.marca || 'Regra global'} · {kindLabel(group.kind)}
      </p>
      <label className="my-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
        Organizar esta página por
        <select
          value={grouping}
          onChange={(e) => update('agrupar', e.target.value)}
          className="min-h-11 rounded-lg border bg-white px-3"
        >
          <option value="campo">Campo na evidência</option>
          <option value="processo">Processo / fonte</option>
          <option value="marca">Marca</option>
          <option value="data">Data de referência</option>
        </select>
      </label>
      <ConsultationState {...resource} hasData={!!resource.data}>
        {resource.data && (
          <>
            <p className="mb-3 text-xs text-slate-500">
              {formatNumber(resource.data.total)} registros neste grupo.
              Subgrupos calculados somente sobre os {resource.data.items.length}{' '}
              registros desta página.
            </p>
            {subgroups.map(([label, items]) => (
              <details
                key={label}
                open={subgroups.length === 1}
                className="border-t py-3"
              >
                <summary className="cursor-pointer text-sm font-semibold">
                  {label}{' '}
                  <span className="font-normal text-slate-500">
                    · {items.length} nesta página
                  </span>
                </summary>
                <div className="mt-2 divide-y">
                  {items.map((item) => (
                    <button
                      key={item.oportunidade_id}
                      onClick={() =>
                        update('oportunidade', item.oportunidade_id)
                      }
                      className={`flex min-h-14 w-full items-center justify-between gap-3 rounded-lg p-3 text-left hover:bg-blue-50 ${search.get('oportunidade') === item.oportunidade_id ? 'bg-blue-50 ring-1 ring-blue-200' : ''}`}
                    >
                      <span className="min-w-0">
                        <span className="block text-sm font-medium">
                          {recordLabel(item)}
                        </span>
                        <span className="block text-xs text-slate-500">
                          {formatDate(item.data_referencia)} ·{' '}
                          {item.tabela_origem}
                        </span>
                      </span>
                      <span className="flex items-center gap-2">
                        <StatusBadge value={item.status_oportunidade} />
                        <ChevronRight className="size-4 shrink-0" />
                      </span>
                    </button>
                  ))}
                </div>
              </details>
            ))}
            {!resource.data.items.length && (
              <p className="py-4 text-sm">Nenhum registro nesta página.</p>
            )}
            <Pagination
              page={resource.data.pagina}
              pages={resource.data.paginas}
              onPage={(p) => update('pagina', String(p))}
              label="Registros"
            />
          </>
        )}
      </ConsultationState>
    </section>
  );
}
function useOpportunitySummary(query: string) {
  const loader = useCallback(
    (signal: AbortSignal) => opportunityService.summary(Object.fromEntries(new URLSearchParams(query)), signal),
    [query],
  );
  return usePdohResource(query, loader);
}

export function OpportunitiesPage() {
  const [search, setSearch] = useSearchParams();
  const filters = {
    marca: search.get('marca') || '',
    periodo_inicio: search.get('periodo_inicio') || '',
    periodo_fim: search.get('periodo_fim') || '',
    status: search.get('status') || '',
    execution_id: search.get('execution_id') || '',
    tipo: search.get('tipo') || '',
  };
  const key = queryString(filters);
  const resource = useOpportunitySummary(key);
  const view =
    search.get('visao') === 'informativo' ? 'informativo' : search.get('visao') === 'alerta' ? 'alerta' : 'operacional';
  const selected = resource.data?.groups.find(
    (group) => group.id === search.get('grupo') && group.kind === view,
  );
  const id = search.get('oportunidade');
  const update = (name: string, value: string) => {
    const next = new URLSearchParams(search);
    if (value) next.set(name, value);
    else next.delete(name);
    for (const field of ['grupo', 'pagina', 'oportunidade', 'historico', 'alerta', 'campo_alerta'])
      next.delete(field);
    setSearch(next);
  };
  const selectGroup = (group: OpportunityGroup) => {
    const next = new URLSearchParams(search);
    next.set('grupo', group.id);
    next.delete('pagina');
    next.delete('oportunidade');
    setSearch(next);
  };
  return (
    <>
      <PageHeader
        eyebrow="Acompanhamento operacional"
        title="Oportunidades"
        description="Entenda o problema, confira a evidência e encontre a orientação de tratativa."
      />
      <FilterPanel activeCount={Object.values(filters).filter(Boolean).length}>
        <FilterField
          label="Marca"
          value={filters.marca}
          onChange={(v) => update('marca', v)}
        />
        <DateFilters
          start={filters.periodo_inicio}
          end={filters.periodo_fim}
          setStart={(v) => update('periodo_inicio', v)}
          setEnd={(v) => update('periodo_fim', v)}
        />
        <FilterField
          label="Status"
          value={filters.status}
          onChange={(v) => update('status', v)}
        />
        <button
          className="min-h-11 px-2 text-sm font-semibold text-blue-700"
          onClick={() => setSearch(new URLSearchParams())}
        >
          Limpar filtros
        </button>
      </FilterPanel>
      <p className="mb-3 text-xs text-slate-500">
        {filters.marca || 'Todas as marcas'} ·{' '}
        {filters.periodo_inicio || 'Início livre'} a{' '}
        {filters.periodo_fim || 'Fim livre'} ·{' '}
        {filters.status || 'Todos os status'}
        {filters.tipo ? ` · ${opportunityName(filters.tipo)}` : ''}
        {filters.execution_id ? ` · Execução ${filters.execution_id}` : ''}
      </p>
      <ConsultationState {...resource} hasData={!!resource.data}>
        {resource.data && (
          <>
            <OpportunitySummary summary={resource.data} />
            {resource.data.unclassified > 0 && (
              <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
                {formatNumber(resource.data.unclassified)} registros sem
                classificação reconhecida no vínculo com o catálogo atual. Eles
                não entram no indicador operacional.{' '}
                <Link
                  className="font-semibold text-blue-800 underline"
                  to={`/oportunidades/registros${key}`}
                >
                  Conferir todos os registros e vínculos
                </Link>
              </div>
            )}
            <div
              className={`grid items-start gap-5 ${id ? 'xl:grid-cols-[1.1fr_1fr]' : ''}`}
            >
              <div className="min-w-0">
                <nav
                  className="mb-3 flex border-b"
                  aria-label="Visão de oportunidades"
                >
                  {[
                    ['operacional', 'Operacionais'],
                    ['alerta', 'Alertas'],
                    ['informativo', 'Telemetria'],
                  ].map(([value, label]) => (
                    <button
                      key={value}
                      onClick={() => update('visao', value)}
                      aria-current={view === value ? 'page' : undefined}
                      className={`min-h-11 border-b-2 px-4 text-sm font-semibold ${view === value ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-500'}`}
                    >
                      {label}
                    </button>
                  ))}
                </nav>
                {view === 'alerta' ? <AlertGroups filters={filters} search={search} setSearch={setSearch} /> : <><section
                  className="overflow-hidden rounded-xl border border-slate-200 bg-white"
                  aria-label="Grupos de oportunidades"
                >
                  <div className="border-b px-4 py-3 text-xs font-semibold text-slate-500">
                    Grupos por regra / tipo · contagens completas no filtro
                  </div>
                  {resource.data.groups
                    .filter(
                      (group) =>
                        group.kind === view &&
                        (!selected || group.id === selected.id),
                    )
                    .map((group) => (
                      <button
                        key={group.id}
                        onClick={() => selectGroup(group)}
                        className={`flex min-h-20 w-full items-center justify-between gap-4 border-b p-4 text-left hover:bg-blue-50 ${selected?.id === group.id ? 'border-l-4 border-l-blue-600 bg-blue-50' : ''}`}
                      >
                        <span className="min-w-0">
                          <span className="block text-sm font-bold text-slate-900">
                            {opportunityName(group.rule.tipo_problema)}
                          </span>
                          <span className="mt-1 block text-xs text-slate-500">
                            {group.rule.marca || 'Global'} ·{' '}
                            {kindLabel(group.kind)}
                          </span>
                        </span>
                        <span className="flex shrink-0 items-center gap-3">
                          <span className="text-right">
                            <strong className="block text-lg">
                              {formatNumber(group.total)}
                            </strong>
                            <span className="text-xs text-slate-500">
                              registros
                            </span>
                          </span>
                          <ChevronRight className="size-4" />
                        </span>
                      </button>
                    ))}
                  {!resource.data.groups.some(
                    (group) => group.kind === view,
                  ) && (
                    <p className="p-6 text-sm text-slate-500">
                      Nenhum grupo nesta visão para os filtros informados.
                    </p>
                  )}
                </section>
                <p className="mt-3 text-xs leading-relaxed text-slate-500">
                  Classificação pelo catálogo atual. A contagem representa
                  registros vinculados, incluindo repetições entre execuções;
                  não representa pessoas ou problemas únicos.
                </p>
                {selected && (
                  <button
                    className="mt-3 min-h-11 text-sm font-semibold text-blue-700"
                    onClick={() => update('grupo', '')}
                  >
                    ← Escolher outro grupo
                  </button>
                )}
                {selected && (
                  <GroupRecords
                    key={selected.id}
                    group={selected}
                    filters={filters}
                    search={search}
                    setSearch={setSearch}
                  />
                )}
                </>}
              </div>
              {id && (
                <div className="order-first min-w-0 xl:order-none">
                  <OpportunityDetail
                    id={id}
                    historyPage={Math.max(
                      1,
                      Number(search.get('historico')) || 1,
                    )}
                    onHistoryPage={(p) => {
                      const next = new URLSearchParams(search);
                      next.set('historico', String(p));
                      setSearch(next);
                    }}
                    onClose={() => {
                      const next = new URLSearchParams(search);
                      next.delete('oportunidade');
                      setSearch(next);
                    }}
                  />
                </div>
              )}
            </div>
          </>
        )}
      </ConsultationState>
    </>
  );
}
export function OpportunityDetailPage() {
  const { opportunityId = '' } = useParams();
  const [search, setSearch] = useSearchParams();
  return (
    <>
      <Link
        to="/oportunidades"
        className="mb-4 inline-flex min-h-11 items-center text-sm font-semibold text-blue-700"
      >
        Voltar às oportunidades
      </Link>
      <div className="max-w-4xl">
        <OpportunityDetail
          id={opportunityId}
          historyPage={Math.max(1, Number(search.get('pagina')) || 1)}
          onHistoryPage={(p) => setSearch({ pagina: String(p) })}
        />
      </div>
    </>
  );
}
export function OpportunityRecordsPage() {
  const [search, setSearch] = useSearchParams();
  const page = Math.max(1, Math.floor(Number(search.get('pagina')) || 1));
  const filters = Object.fromEntries(
    [...search].filter(([key]) =>
      [
        'marca',
        'periodo_inicio',
        'periodo_fim',
        'status',
        'execution_id',
        'tipo',
      ].includes(key),
    ),
  );
  const query = queryString({ ...filters, pagina: page, tamanho: 50 });
  const loader = useCallback(
    async (signal: AbortSignal) => {
      const [list, catalog] = await Promise.all([
        opportunityService.list(
          {
            ...Object.fromEntries(new URLSearchParams(query)),
            pagina: page,
            tamanho: 50,
          },
          signal,
        ),
        loadCatalog(signal),
      ]);
      return { ...list, catalog };
    },
    [query, page],
  );
  const resource = usePdohResource(query, loader);
  return (
    <>
      <PageHeader
        title="Consulta de registros e vínculos"
        description="Consulta completa para conferência. Esta lista inclui registros de todas as classificações."
      />
      <Link to="/oportunidades" className="mb-4 inline-block text-blue-700">
        Voltar à visão operacional
      </Link>
      <ConsultationState {...resource} hasData={!!resource.data}>
        {resource.data && (
          <>
            <div className="divide-y rounded-xl border bg-white">
              {resource.data.items.map((item) => (
                <Link
                  key={item.oportunidade_id}
                  to={`/oportunidades/${item.oportunidade_id}`}
                  className="flex justify-between gap-3 break-words p-4"
                >
                  <span>
                    {opportunityName(item.tipo_problema)}
                    <span className="block break-all text-xs text-slate-500">
                      {item.marca} · {item.oportunidade_id}
                    </span>
                    <span className="block text-xs font-semibold text-slate-600">
                      {kindLabel(
                        catalogKind(
                          resource.data?.catalog.find(
                            (rule) =>
                              rule.regra_id === item.regra_id &&
                              rule.tipo_problema === item.tipo_problema,
                          ),
                        ),
                      )}
                    </span>
                  </span>
                  <ChevronRight className="size-4" />
                </Link>
              ))}
            </div>
            <Pagination
              page={page}
              pages={resource.data.paginas}
              label="Registros"
              onPage={(p) => {
                const next = new URLSearchParams(search);
                next.set('pagina', String(p));
                setSearch(next);
              }}
            />
          </>
        )}
      </ConsultationState>
    </>
  );
}
