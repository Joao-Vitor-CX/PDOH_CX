import { useCallback, useState } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatDate } from '@/src/lib/pdoh-format';
import {
  GRANULARIDADES,
  PDOH_TREND_PATH,
  pdohTrendSchema,
  type Granularidade,
} from '@/src/services/pdoh-indicator';
import { v2Request, type OperationalFilters } from '@/src/services/operational-api';
import { queryString } from '@/src/services/pdoh-api';

const eixo = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });

function trendByKey(key: string, signal: AbortSignal) {
  return v2Request(`${PDOH_TREND_PATH}?${key}`, pdohTrendSchema, signal);
}

/**
 * Evolução do PDOH, direto de GET /api/v2/pdoh/evolucao.
 *
 * A API agrupa por dia, semana (seg–sáb) ou mês; o navegador apenas escolhe a janela e
 * desenha. Sem série oficial não há curva — um gráfico decorativo com dados estimados
 * seria pior que nenhum gráfico.
 */
export function PdohTrend({ window }: { window: OperationalFilters }) {
  const [granularidade, setGranularidade] = useState<Granularidade>('dia');
  const key = queryString({ ...window, granularidade }).slice(1);
  const loader = useCallback((signal: AbortSignal) => trendByKey(key, signal), [key]);
  const resource = usePdohResource(key, loader);
  const dados = resource.data;
  const serie = (dados?.pontos || []).map((ponto) => ({
    percentual: ponto.pdoh,
    rotulo:
      granularidade === 'mes'
        ? formatDate(ponto.periodo).slice(3)
        : formatDate(ponto.periodo).slice(0, 5),
  }));

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-bold tracking-tight text-slate-950">
            Evolução do PDOH
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Tendência do resultado ao longo do período.
          </p>
        </div>
        <fieldset className="inline-flex rounded-lg border border-slate-200 p-0.5">
          <legend className="sr-only">Agrupamento da série</legend>
          {GRANULARIDADES.map((opcao) => (
            <button
              key={opcao.valor}
              type="button"
              aria-pressed={granularidade === opcao.valor}
              onClick={() => setGranularidade(opcao.valor)}
              className={`min-h-11 rounded-md px-3 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-blue-600 ${
                granularidade === opcao.valor
                  ? 'bg-blue-700 text-white'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
              }`}
            >
              {opcao.rotulo}
            </button>
          ))}
        </fieldset>
      </div>

      <ConsultationState {...resource} hasData={!!dados}>
        {serie.length > 1 ? (
          <div className="mt-4 h-60 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={serie} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
                <defs>
                  <linearGradient id="pdoh-area" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#1d6fe8" stopOpacity={0.28} />
                    <stop offset="100%" stopColor="#1d6fe8" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#e9eef4" vertical={false} />
                <XAxis
                  dataKey="rotulo"
                  tick={{ fill: '#64748b', fontSize: 12 }}
                  axisLine={{ stroke: '#e9eef4' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: '#64748b', fontSize: 12 }}
                  axisLine={false}
                  tickLine={false}
                  width={54}
                  tickFormatter={(valor: number) => `${eixo.format(valor)}%`}
                />
                <Tooltip
                  formatter={(valor) => [`${eixo.format(Number(valor))}%`, 'PDOH']}
                  contentStyle={{ borderRadius: 12, border: '1px solid #dde5ee', fontSize: 13 }}
                />
                <Area
                  type="monotone"
                  dataKey="percentual"
                  stroke="#1d6fe8"
                  strokeWidth={2.5}
                  fill="url(#pdoh-area)"
                  dot={{ r: 3, fill: '#1d6fe8' }}
                  activeDot={{ r: 5 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <output className="mt-4 block rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center">
            <p className="text-sm font-semibold text-slate-500">
              {serie.length === 1
                ? 'Um único ponto no período: a curva precisa de ao menos dois'
                : dados && !dados.disponivel
                  ? 'Sem registros no período selecionado'
                  : 'Série histórica do PDOH ainda não publicada'}
            </p>
            <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-slate-500">
              {dados?.motivo ||
                'O gráfico é desenhado assim que a API entregar a série oficial. Nenhuma curva é estimada a partir dos impactadores.'}
            </p>
          </output>
        )}
      </ConsultationState>
    </section>
  );
}
