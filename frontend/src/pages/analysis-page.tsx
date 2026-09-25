import { useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ChevronRight, UserRound } from 'lucide-react';
import { SeverityBadge } from '@/components/platform/impact-card';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { CollaboratorImpactCard } from '@/components/platform/impact-card';
import { OperationalFiltersForm } from '@/components/platform/operational-filters';
import { PdohComposition, PdohResult } from '@/components/platform/pdoh-result';
import { PdohHeader } from '@/components/platform/pdoh-header';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatNumber } from '@/src/lib/pdoh-format';
import { PDOH_SUMMARY_PATH, pdohSummarySchema } from '@/src/services/pdoh-indicator';
import {
  filtersFromSearch,
  fixedWindow,
  loadAllGroups,
  resolvePeriod,
  v2Request,
  type OperationalFilters,
} from '@/src/services/operational-api';
import {
  impactosPorColaborador,
  impactosPorRegra,
} from '@/src/services/findings-service';
import { queryString } from '@/src/services/pdoh-api';

async function analysisByKey(key: string, signal: AbortSignal) {
  const selected = filtersFromSearch(new URLSearchParams(key));
  const period = await resolvePeriod(selected, signal);
  const window = fixedWindow(selected, period);
  const [groups, pdoh] = await Promise.all([
    loadAllGroups(window, signal),
    v2Request(`${PDOH_SUMMARY_PATH}${queryString(window)}`, pdohSummarySchema, signal),
  ]);
  return {
    period,
    window,
    pdoh,
    groups,
    impactos: impactosPorRegra(groups.items),
    pessoas: impactosPorColaborador(groups.items),
  };
}
function useAnalysis(key: string) {
  const loader = useCallback((signal: AbortSignal) => analysisByKey(key, signal), [key]);
  return usePdohResource(key, loader);
}

/**
 * Análise individual: responde "o que aconteceu com essa pessoa?".
 * O indicador do colaborador vem da mesma fonte oficial do painel — sem fonte,
 * mostra o estado de indisponibilidade, nunca um número estimado.
 */
export function AnalysisPage() {
  const [search, setSearch] = useSearchParams();
  const filters = filtersFromSearch(search);
  const key = queryString(filters);
  const resource = useAnalysis(key);
  const dados = resource.data;
  const colaborador = filters.colaborador?.trim();
  const apply = (next: OperationalFilters) => setSearch(new URLSearchParams(queryString(next)));

  return (
    <>
      <PdohHeader
        periodoInicio={dados?.period.inicio ?? null}
        periodoFim={dados?.period.fim ?? null}
        updatedAt={resource.updatedAt}
        refreshing={resource.refreshing}
        subtitulo={colaborador ? `Análise de ${colaborador}` : 'Análise PDOH'}
      />
      <div className="mb-5">
        <h2 className="text-2xl font-extrabold tracking-tight text-slate-950">
          {colaborador || 'Análise PDOH'}
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          {colaborador
            ? 'Resultado, composição e causas do período para este colaborador.'
            : 'Visão geral do período. Abra um colaborador para ver o resultado individual.'}
        </p>
      </div>
      <OperationalFiltersForm
        key={key}
        filters={filters}
        period={dados?.period}
        lockedBrand
        detailed
        onApply={apply}
        onReset={() => setSearch({})}
      />

      <ConsultationState {...resource} hasData={!!dados}>
        {dados && (
          <>
            {!colaborador ? (
              <section aria-label="Colaboradores do período">
                <div className="mb-3">
                  <h3 className="text-lg font-bold text-slate-950">
                    Colaboradores com impacto no período
                  </h3>
                  <p className="mt-0.5 text-xs text-slate-500">
                    Selecione uma pessoa para abrir o resultado e as causas individuais.
                  </p>
                </div>
                <div className="space-y-3">
                  {dados.pessoas.map((pessoa) => (
                    <Link
                      key={pessoa.colaborador}
                      to={
                        '/analise' +
                        queryString({ ...dados.window, colaborador: pessoa.colaborador })
                      }
                      className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-300 hover:bg-blue-50/40 focus-visible:outline-2 focus-visible:outline-blue-600"
                    >
                      <UserRound
                        className="size-5 shrink-0 text-slate-400"
                        aria-hidden="true"
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="text-sm font-bold text-slate-950">
                            {pessoa.colaborador}
                          </h4>
                          <SeverityBadge value={pessoa.severidade} />
                        </div>
                        <p className="mt-0.5 truncate text-xs text-slate-500">
                          Principal causa: {pessoa.principal}
                        </p>
                      </div>
                      <dl className="flex shrink-0 gap-6 text-right">
                        <div>
                          <dd className="text-lg font-extrabold tabular-nums text-slate-950">
                            {formatNumber(pessoa.causas)}
                          </dd>
                          <dt className="text-[11px] text-slate-500">
                            {pessoa.causas === 1 ? 'causa' : 'causas'}
                          </dt>
                        </div>
                        <div>
                          <dd className="text-lg font-extrabold tabular-nums text-slate-950">
                            {formatNumber(pessoa.ocorrencias)}
                          </dd>
                          <dt className="text-[11px] text-slate-500">ocorrências</dt>
                        </div>
                      </dl>
                      <ChevronRight
                        className="size-4 shrink-0 text-slate-400"
                        aria-hidden="true"
                      />
                    </Link>
                  ))}
                </div>
                {!dados.pessoas.length && (
                  <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center">
                    <UserRound className="mx-auto mb-3 size-8 text-blue-500" />
                    <h3 className="font-semibold text-slate-800">
                      Nenhum colaborador com impacto neste período
                    </h3>
                    <p className="mx-auto mt-2 max-w-md text-sm text-slate-500">
                      Ajuste o período ou os demais filtros para consultar outra janela.
                    </p>
                  </div>
                )}
              </section>
            ) : (
              <>
                <Link
                  to={'/analise' + queryString({ ...dados.window, colaborador: undefined })}
                  className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-blue-700"
                >
                  <ArrowLeft className="size-4" />
                  Todos os colaboradores
                </Link>
                <section className="grid gap-4 xl:grid-cols-[1fr_2fr]">
                  <PdohResult summary={dados.pdoh} />
                  <PdohComposition summary={dados.pdoh} />
                </section>
                <section className="mt-6">
                  <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
                    <div>
                      <h3 className="text-lg font-bold text-slate-950">
                        Impactadores do colaborador
                      </h3>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {formatNumber(dados.groups.total)} causa(s) no período.
                      </p>
                    </div>
                  </div>
                  <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {dados.groups.items.map((group) => (
                      <CollaboratorImpactCard
                        key={group.grupo_id}
                        group={group}
                        window={dados.window}
                      />
                    ))}
                  </div>
                  {!dados.groups.items.length && (
                    <p className="rounded-2xl border border-slate-200 bg-white p-8 text-sm text-slate-500">
                      Nenhum impactador para este colaborador no período.
                    </p>
                  )}
                </section>
              </>
            )}
          </>
        )}
      </ConsultationState>
    </>
  );
}
