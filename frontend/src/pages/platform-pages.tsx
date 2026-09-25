import { useCallback } from 'react';
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
import { OpportunitySummary } from './opportunities-page';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { opportunityName, humanize } from '@/src/lib/opportunity-presentation';
import {
  formatDateTime,
  formatNumber,
  formatPeriod,
} from '@/src/lib/pdoh-format';
import {
  opportunityService,
  mapLimited,
} from '@/src/services/opportunity-service';
import {
  apiRequest,
  executionDetailSchema,
  executionSchema,
  pageSchema,
  queryString,
  stageSchema,
  sourceSchema,
} from '@/src/services/pdoh-api';
import type { z } from 'zod';

async function loadOperationalDashboard(key: string, signal: AbortSignal) {
  const filters = Object.fromEntries(new URLSearchParams(key));
  const [summary, dashboard] = await Promise.all([
    opportunityService.summary(filters, signal),
    opportunityService.dashboard(filters, signal),
  ]);
  return { summary, dashboard };
}
function useOperationalDashboard(key: string) {
  const loader = useCallback(
    (signal: AbortSignal) => loadOperationalDashboard(key, signal),
    [key],
  );
  return usePdohResource(key, loader);
}
export function DashboardPage({ brandId }: { brandId?: string }) {
  const [search, setSearch] = useSearchParams();
  const filters = {
    marca: brandId || search.get('marca') || '',
    periodo_inicio: search.get('periodo_inicio') || '',
    periodo_fim: search.get('periodo_fim') || '',
  };
  const key = queryString(filters);
  const resource = useOperationalDashboard(key);
  const update = (name: string, value: string) => {
    const next = new URLSearchParams(search);
    if (value) next.set(name, value);
    else next.delete(name);
    setSearch(next);
  };
  const active =
    resource.data?.summary.groups.filter(
      (group) => group.kind === 'operacional',
    ) || [];
  const max = Math.max(1, ...active.map((group) => group.total));
  return (
    <>
      <PageHeader
        eyebrow="Visão executiva"
        title="O que precisa de acompanhamento?"
        description="Priorize as situações operacionais e acompanhe o processamento."
      />
      <FilterPanel activeCount={Object.values(filters).filter(Boolean).length}>
        {!brandId && (
          <FilterField
            label="Marca"
            value={filters.marca}
            onChange={(v) => update('marca', v)}
          />
        )}
        <DateFilters
          start={filters.periodo_inicio}
          end={filters.periodo_fim}
          setStart={(v) => update('periodo_inicio', v)}
          setEnd={(v) => update('periodo_fim', v)}
        />
        <button
          className="min-h-11 text-sm text-blue-700"
          onClick={() => setSearch({})}
        >
          Limpar filtros
        </button>
      </FilterPanel>
      <ConsultationState {...resource} hasData={!!resource.data}>
        {resource.data && (
          <>
            <OpportunitySummary summary={resource.data.summary} />
            {resource.data.summary.unclassified > 0 && (
              <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
                {formatNumber(resource.data.summary.unclassified)} registros sem
                classificação reconhecida não entram no indicador operacional.{' '}
                <Link
                  className="font-semibold underline"
                  to={`/oportunidades/registros${key}`}
                >
                  Conferir registros e vínculos
                </Link>
              </p>
            )}
            <div className="grid items-start gap-5 xl:grid-cols-[1.6fr_1fr]">
              <section className="rounded-xl border bg-white p-5">
                <h2 className="font-bold">Principais situações operacionais</h2>
                <p className="mb-4 mt-1 text-xs text-slate-500">
                  Grupos com mais registros no filtro. Abra um grupo para
                  conferir as evidências.
                </p>
                <div className="space-y-5">
                  {active.slice(0, 8).map((group) => (
                    <Link
                      key={group.id}
                      className="block rounded-lg focus-visible:outline-2 focus-visible:outline-blue-600"
                      to={`/oportunidades${queryString({ ...filters, grupo: group.id })}`}
                    >
                      <div className="mb-2 flex items-start justify-between gap-4 text-sm">
                        <span className="font-semibold">
                          {opportunityName(group.rule.tipo_problema)}
                          <span className="block text-xs font-normal text-slate-500">
                            {group.rule.marca || 'Regra global'}
                          </span>
                        </span>
                        <strong>{formatNumber(group.total)}</strong>
                      </div>
                      <div
                        className="h-2 rounded bg-slate-100"
                        aria-hidden="true"
                      >
                        <div
                          className="h-2 rounded bg-blue-600"
                          style={{ width: `${(group.total / max) * 100}%` }}
                        />
                      </div>
                    </Link>
                  ))}
                </div>
                {!active.length && (
                  <p className="py-5 text-sm text-slate-500">
                    Nenhuma situação operacional no filtro.
                  </p>
                )}
                <Link
                  className="mt-5 inline-flex min-h-11 items-center text-sm font-semibold text-blue-700"
                  to={`/oportunidades${key}`}
                >
                  Abrir fila operacional →
                </Link>
              </section>
              <section className="rounded-xl border bg-white p-5">
                <h2 className="font-bold">Acompanhamento do processamento</h2>
                <p className="mt-3 text-3xl font-bold">
                  {formatNumber(resource.data.dashboard.total_execucoes)}{' '}
                  <span className="text-sm font-normal text-slate-500">
                    execuções
                  </span>
                </p>
                <div className="my-4 space-y-2">
                  {resource.data.dashboard.status_execucoes.map((item) => (
                    <div
                      key={item.valor}
                      className="flex justify-between gap-3 text-sm"
                    >
                      <span>{humanize(item.valor)}</span>
                      <strong>{formatNumber(item.quantidade)}</strong>
                    </div>
                  ))}
                </div>
                {resource.data.dashboard.ultimas_execucoes[0] && (
                  <div className="border-t pt-4 text-sm">
                    <p className="font-semibold">Última execução</p>
                    <p>
                      {resource.data.dashboard.ultimas_execucoes[0].marca} ·{' '}
                      {formatDateTime(
                        resource.data.dashboard.ultimas_execucoes[0]
                          .iniciado_em,
                      )}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      {formatPeriod(
                        resource.data.dashboard.ultimas_execucoes[0]
                          .periodo_inicio,
                        resource.data.dashboard.ultimas_execucoes[0]
                          .periodo_fim,
                      )}
                    </p>
                    <p className="mt-2">
                      {formatNumber(
                        resource.data.dashboard.ultimas_execucoes[0]
                          .total_fallbacks,
                      )}{' '}
                      usos de fallback registrados nesta execução
                    </p>
                  </div>
                )}
                <Link
                  to="/processamentos"
                  className="mt-4 inline-flex min-h-11 items-center text-sm font-semibold text-blue-700"
                >
                  Ver execuções →
                </Link>
              </section>
            </div>
            <section className="mt-5 rounded-xl border bg-white p-5">
              <h2 className="font-bold">Atividade por período processado</h2>
              <p className="mt-1 text-xs text-slate-500">
                Execuções por marca e janela. Períodos podem se sobrepor; não
                representa evolução de problemas únicos.
              </p>
              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {resource.data.dashboard.marcas_periodos.items.map((item) => (
                  <Link
                    key={JSON.stringify([
                      item.marca,
                      item.periodo_inicio,
                      item.periodo_fim,
                    ])}
                    to={`/oportunidades${queryString({ marca: item.marca, periodo_inicio: item.periodo_inicio, periodo_fim: item.periodo_fim })}`}
                    className="rounded-lg border border-slate-100 p-3 text-sm hover:bg-blue-50"
                  >
                    <strong>{item.marca}</strong>
                    <p>{formatPeriod(item.periodo_inicio, item.periodo_fim)}</p>
                    <p className="text-xs text-slate-500">
                      {item.quantidade_execucoes} execuções · abrir
                      oportunidades no período
                    </p>
                  </Link>
                ))}
              </div>
              {resource.data.dashboard.marcas_periodos.paginas > 1 && (
                <p className="mt-3 text-xs">
                  Primeiros 200 períodos. Refine marca e datas para consultar os
                  demais.
                </p>
              )}
            </section>
            <p className="mt-4 text-xs text-slate-500">
              Contagens de registros conforme o catálogo atual; repetições entre
              execuções permanecem preservadas. Campos e fontes podem ser
              explorados nos registros de cada página do grupo.
              {resource.data.summary.unclassified > 0 &&
                ` Há ${formatNumber(resource.data.summary.unclassified)} registros sem classificação reconhecida.`}
            </p>
          </>
        )}
      </ConsultationState>
    </>
  );
}
export function ExecutionCard({
  execution,
}: {
  execution: z.infer<typeof executionDetailSchema>;
}) {
  return (
    <article className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-bold">{execution.marca}</h2>
          <p className="mt-1 text-sm">
            {formatPeriod(execution.periodo_inicio, execution.periodo_fim)}
          </p>
        </div>
        <StatusBadge value={execution.status_execucao} />
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Processada em {formatDateTime(execution.iniciado_em)}
      </p>
      <div className="mt-4 flex items-end justify-between gap-3">
        <div>
          <p className="text-xl font-bold">
            {formatNumber(execution.quantidade_oportunidades)}
          </p>
          <p className="text-xs text-slate-500">
            Registros de validação · inclui informativos
          </p>
        </div>
        <Link
          className="inline-flex min-h-11 items-center text-sm font-semibold text-blue-700"
          to={`/processamentos/${encodeURIComponent(execution.execution_id)}`}
        >
          Acompanhar →
        </Link>
      </div>
      <details className="mt-3 text-xs text-slate-500">
        <summary className="cursor-pointer">Identificação da execução</summary>
        <p className="mt-2 break-all font-mono">{execution.execution_id}</p>
      </details>
    </article>
  );
}
export function ProcessingPage() {
  const [search, setSearch] = useSearchParams();
  const page = Math.max(1, Math.floor(Number(search.get('pagina')) || 1));
  const filters = {
    marca: search.get('marca') || '',
    status: search.get('status') || '',
    periodo_inicio: search.get('periodo_inicio') || '',
    periodo_fim: search.get('periodo_fim') || '',
  };
  const query = queryString({ ...filters, pagina: page, tamanho: 12 });
  const loader = useCallback(
    async (signal: AbortSignal) => {
      const list = await apiRequest(
        `/execucoes${query}`,
        pageSchema(executionSchema),
        signal,
      );
      const items = await mapLimited(list.items, (item) =>
        apiRequest(
          `/execucoes/${encodeURIComponent(item.execution_id)}`,
          executionDetailSchema,
          signal,
        ),
      );
      return { ...list, items };
    },
    [query],
  );
  const resource = usePdohResource(query, loader);
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(search);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete('pagina');
    setSearch(next);
  };
  return (
    <>
      <PageHeader
        eyebrow="Processamento"
        title="Execuções"
        description="Acompanhe o resultado de cada processamento e as oportunidades relacionadas."
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
        <label className="text-xs font-semibold text-slate-600">
          Status
          <select
            className="ml-2 min-h-11 rounded-lg border bg-white px-3"
            value={filters.status}
            onChange={(e) => update('status', e.target.value)}
          >
            <option value="">Todos</option>
            {[
              'CONCLUIDA',
              'CONCLUIDA_COM_ALERTAS',
              'CONCLUIDA_SEM_RESULTADO',
              'FALHA_TECNICA',
              'INICIADA',
            ].map((status) => (
              <option key={status} value={status}>
                {humanize(status)}
              </option>
            ))}
          </select>
        </label>
      </FilterPanel>
      <ConsultationState {...resource} hasData={!!resource.data}>
        {resource.data && (
          <>
            <p className="mb-4 text-sm text-slate-500">
              {formatNumber(resource.data.total)} execuções no filtro
            </p>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {resource.data.items.map((execution) => (
                <ExecutionCard
                  key={execution.execution_id}
                  execution={execution}
                />
              ))}
            </div>
            {!resource.data.items.length && <p>Nenhuma execução encontrada.</p>}
            <Pagination
              page={page}
              pages={resource.data.paginas}
              label="Execuções"
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
function ExecutionEvidence({ id }: { id: string }) {
  const loader = useCallback(
    async (signal: AbortSignal) => {
      const [stages, sources] = await Promise.all([
        apiRequest(
          `/execucoes/${encodeURIComponent(id)}/etapas?tamanho=200`,
          pageSchema(stageSchema),
          signal,
        ),
        apiRequest(
          `/execucoes/${encodeURIComponent(id)}/fontes?tamanho=200`,
          pageSchema(sourceSchema),
          signal,
        ),
      ]);
      return { stages, sources };
    },
    [id],
  );
  const resource = usePdohResource(id, loader);
  return (
    <ConsultationState {...resource} hasData={!!resource.data}>
      {resource.data && (
        <div className="grid gap-5 md:grid-cols-2">
          <section>
            <h3 className="mb-3 font-semibold">Etapas registradas</h3>
            {resource.data.stages.items.map((stage) => (
              <div className="border-t py-3 text-sm" key={stage.id}>
                <p>
                  {humanize(stage.etapa)} · {humanize(stage.status_etapa)}
                </p>
                {stage.mensagem && (
                  <p className="mt-1 text-xs text-slate-500">
                    {stage.mensagem}
                  </p>
                )}
              </div>
            ))}
            {resource.data.stages.paginas > 1 && (
              <p>Exibindo primeiras 200 etapas.</p>
            )}
          </section>
          <section>
            <h3 className="mb-3 font-semibold">Fontes consumidas</h3>
            {resource.data.sources.items.map((source) => (
              <p className="break-all border-t py-3 text-sm" key={source.id}>
                {source.tabela_origem} · {formatNumber(source.linhas_recebidas)}{' '}
                linhas
              </p>
            ))}
            {resource.data.sources.paginas > 1 && (
              <p>Exibindo primeiras 200 fontes.</p>
            )}
          </section>
        </div>
      )}
    </ConsultationState>
  );
}
export function ExecutionDetailPage() {
  const { executionId = '' } = useParams();
  const [search, setSearch] = useSearchParams();
  const loader = useCallback(
    (signal: AbortSignal) =>
      apiRequest(
        `/execucoes/${encodeURIComponent(executionId)}`,
        executionDetailSchema,
        signal,
      ),
    [executionId],
  );
  const resource = usePdohResource(executionId, loader);
  return (
    <>
      <PageHeader
        title="Resultado do processamento"
        description="Confira o resultado e abra a fila de oportunidades desta execução."
      />
      <Link
        className="mb-4 inline-block text-sm text-blue-700"
        to="/processamentos"
      >
        Voltar às execuções
      </Link>
      <ConsultationState {...resource} hasData={!!resource.data}>
        {resource.data && (
          <>
            <ExecutionCard execution={resource.data} />
            <section className="my-4 rounded-xl border bg-white p-5">
              <h2 className="font-bold">Oportunidades desta execução</h2>
              <p className="mt-2 text-sm text-slate-600">
                Abra a fila para consultar separadamente as situações
                operacionais e os eventos informativos.
              </p>
              <Link
                className="mt-3 inline-flex min-h-11 items-center font-semibold text-blue-700"
                to={`/oportunidades?execution_id=${encodeURIComponent(executionId)}`}
              >
                Abrir oportunidades →
              </Link>
              <p className="mt-2 text-sm">
                {formatNumber(resource.data.total_fallbacks)} usos de fallback
                registrados no processamento.
              </p>
              {resource.data.erro_resumo && (
                <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">
                  O processamento registrou uma falha técnica. Os dados gerados
                  precisam ser conferidos antes de uso.
                </p>
              )}
            </section>
            <details
              open={search.get('detalhes') === 'sim'}
              onToggle={(event) => {
                const open = event.currentTarget.open;
                if (open !== (search.get('detalhes') === 'sim'))
                  setSearch(open ? { detalhes: 'sim' } : {});
              }}
              className="rounded-xl border bg-white p-5"
            >
              <summary className="cursor-pointer text-sm font-semibold text-blue-700">
                Consultar detalhes do processamento
              </summary>
              {search.get('detalhes') === 'sim' && (
                <div className="mt-4">
                  <ExecutionEvidence id={executionId} />
                  {resource.data.erro_resumo && (
                    <pre className="mt-4 max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-4 text-xs">
                      {resource.data.erro_resumo}
                    </pre>
                  )}
                </div>
              )}
            </details>
          </>
        )}
      </ConsultationState>
    </>
  );
}
