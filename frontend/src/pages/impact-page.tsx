import { useCallback } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Target } from 'lucide-react';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { CollaboratorImpactCard, ImpactCard } from '@/components/platform/impact-card';
import { OperationalFiltersForm } from '@/components/platform/operational-filters';
import { PdohHeader } from '@/components/platform/pdoh-header';
import { Pagination } from '@/components/platform/query-controls';
import { ViewToggle, type OperationalView } from '@/components/platform/view-toggle';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatNumber } from '@/src/lib/pdoh-format';
import { impactosPorRegra } from '@/src/services/findings-service';
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

/**
 * Duas leituras da mesma consulta:
 * - geral: o período consolidado por regra, sem o recorte de regra, para não esconder
 *   as demais causas enquanto uma delas está selecionada;
 * - colaborador: a fila paginada com todos os filtros aplicados.
 */
async function impactByKey(key: string, signal: AbortSignal) {
  const params = new URLSearchParams(key);
  const selected = filtersFromSearch(params);
  const period = await resolvePeriod(selected, signal);
  const window = fixedWindow(selected, period);
  const [consolidado, pagina] = await Promise.all([
    loadAllGroups({ ...window, tipo: undefined, regra: undefined }, signal),
    loadGroups(window, Number(params.get('pagina')), 12, signal),
  ]);
  return {
    period,
    window,
    impactos: impactosPorRegra(consolidado.items),
    totalGeral: consolidado.total,
    groups: pagina,
  };
}
function useImpact(key: string) {
  const loader = useCallback((signal: AbortSignal) => impactByKey(key, signal), [key]);
  return usePdohResource(key, loader);
}

const VISAO_FILTRADA = ['tipo', 'regra', 'colaborador', 'severidade', 'status'] as const;

/** Causas que impactaram o PDOH: o consolidado do período e a abertura por colaborador. */
export function ImpactPage() {
  const [search, setSearch] = useSearchParams();
  const filters = filtersFromSearch(search);
  const page = Math.max(1, Math.floor(Number(search.get('pagina')) || 1));
  const key = queryString({ ...filters, pagina: page });
  const resource = useImpact(key);
  const dados = resource.data;

  const escolhida = search.get('visao');
  const filtrado = VISAO_FILTRADA.some((campo) => filters[campo]);
  // Sem escolha explícita, um filtro aplicado já pede a leitura por colaborador.
  const visao: OperationalView =
    escolhida === 'geral' || escolhida === 'colaborador'
      ? escolhida
      : filtrado
        ? 'colaborador'
        : 'geral';

  const trocarVisao = (proxima: OperationalView) => {
    const next = new URLSearchParams(search);
    next.set('visao', proxima);
    next.delete('pagina');
    setSearch(next);
  };
  const apply = (next: OperationalFilters) => {
    // Um novo recorte de regra ou de pessoa refaz a escolha da visão.
    const manter =
      escolhida && next.tipo === filters.tipo && next.colaborador === filters.colaborador;
    setSearch(
      new URLSearchParams(queryString({ ...next, visao: manter ? escolhida : undefined })),
    );
  };
  const janelaAtual = dados ? dados.window : filters;

  return (
    <>
      <PdohHeader
        periodoInicio={dados?.period.inicio ?? null}
        periodoFim={dados?.period.fim ?? null}
        updatedAt={resource.updatedAt}
        refreshing={resource.refreshing}
        subtitulo="Impactadores do PDOH"
      />
      <Link
        to={'/dashboard' + queryString(periodFilters(filters))}
        className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-blue-700"
      >
        <ArrowLeft className="size-4" />
        Voltar ao painel
      </Link>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-2xl font-extrabold tracking-tight text-slate-950">
            Impactadores do PDOH
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Causas que influenciaram o resultado, com o colaborador e a ação necessária.
          </p>
        </div>
        <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-right">
          <p className="text-2xl font-bold text-blue-950">
            {formatNumber(visao === 'geral' ? dados?.impactos.length : dados?.groups.total)}
          </p>
          <p className="text-xs text-blue-800">
            {visao === 'geral' ? 'causas no período' : 'impactadores no filtro'}
          </p>
        </div>
      </div>
      <OperationalFiltersForm
        key={key}
        filters={filters}
        period={dados?.period}
        lockedBrand
        rules={(dados?.impactos || []).map((impacto) => ({
          value: impacto.tipo,
          label: impacto.titulo,
        }))}
        detailed
        onApply={apply}
        onReset={() => setSearch({})}
      />
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <ViewToggle value={visao} onChange={trocarVisao} />
        <p className="text-xs text-slate-500">
          {visao === 'geral'
            ? 'Consolidado por causa em todo o período filtrado.'
            : 'Ocorrências consolidadas por colaborador · ordem: severidade → ocorrências'}
        </p>
      </div>
      {filters.tipo && (
        <p className="mb-4 text-sm text-blue-800">
          Recorte por regra aplicado. A visão geral continua mostrando todas as causas do
          período.{' '}
          <button
            onClick={() => {
              const next = new URLSearchParams(search);
              next.delete('tipo');
              next.delete('regra');
              next.delete('pagina');
              setSearch(next);
            }}
            className="min-h-11 font-semibold underline"
          >
            Remover recorte
          </button>
        </p>
      )}
      <ConsultationState {...resource} hasData={!!dados}>
        {dados && visao === 'geral' && (
          <>
            <div className="space-y-3">
              {dados.impactos.map((impacto) => (
                <ImpactCard
                  key={impacto.tipo}
                  impacto={impacto}
                  to={
                    '/impactadores' +
                    queryString({
                      ...fixedWindow({}, dados.period),
                      colaborador: filters.colaborador,
                      severidade: filters.severidade,
                      status: filters.status,
                      tipo: impacto.tipo,
                      visao: 'colaborador',
                    })
                  }
                />
              ))}
            </div>
            {!dados.impactos.length && <VazioImpacto />}
            <p className="mt-5 text-xs leading-relaxed text-slate-500">
              {formatNumber(dados.totalGeral)} impactadores por colaborador distribuídos em{' '}
              {formatNumber(dados.impactos.length)} causas. Abra uma causa para ver quem
              precisa de tratativa.
            </p>
          </>
        )}
        {dados && visao === 'colaborador' && (
          <>
            <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
              {dados.groups.items.map((group) => (
                <CollaboratorImpactCard
                  key={group.grupo_id}
                  group={group}
                  window={janelaAtual}
                />
              ))}
            </div>
            {!dados.groups.items.length && <VazioImpacto />}
            <Pagination
              page={dados.groups.pagina}
              pages={dados.groups.paginas}
              label="Impactadores"
              onPage={(value) => {
                const next = new URLSearchParams(search);
                next.set('pagina', String(value));
                setSearch(next);
              }}
            />
            <p className="mt-5 text-xs leading-relaxed text-slate-500">
              As ocorrências pertencem às janelas de processamento selecionadas; suas datas
              podem ultrapassar esse intervalo. Cada card e sua prioridade são entregues
              pela consulta operacional.
            </p>
          </>
        )}
      </ConsultationState>
    </>
  );
}

function VazioImpacto() {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-10 text-center">
      <Target className="mx-auto mb-3 size-8 text-blue-500" />
      <h3 className="font-semibold text-slate-800">Nenhum impactador neste filtro</h3>
      <p className="mt-2 text-sm text-slate-500">
        Ajuste o período ou os demais filtros para consultar outras causas.
      </p>
    </div>
  );
}

/** Links antigos ficam explicados, sem consultar dados v1 dentro do novo painel. */
export function PreviousConsultationPage() {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-8">
      <h1 className="text-xl font-bold">Consulta anterior</h1>
      <p className="mt-3 max-w-xl text-sm leading-relaxed text-slate-600">
        Este link pertence à consulta anterior. A nova visão apresenta os impactadores do
        PDOH consolidados por colaborador. O acompanhamento detalhado de execuções e
        registros será integrado em uma próxima etapa.
      </p>
      <Link
        to="/impactadores"
        className="mt-5 inline-flex min-h-11 items-center font-semibold text-blue-700"
      >
        Abrir impactadores
      </Link>
    </section>
  );
}
