import { Gauge, TrendingDown, TrendingUp } from 'lucide-react';
import { Link } from 'react-router-dom';
import { formatDate } from '@/src/lib/pdoh-format';
import {
  composicaoPdoh,
  pdohIndicatorState,
  rotuloIndicadorVazio,
  INDICADOR_UNAVAILABLE_MESSAGE,
  ROTULO_SEM_FONTE,
  ROTULO_SEM_PERIODO,
  type Indicador,
  type PdohSummary,
} from '@/src/services/pdoh-indicator';

const percentual = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 2,
});

function Variacao({ valor, invertido = false }: { valor: number; invertido?: boolean }) {
  // Em ócio e deslocamento, cair é bom: a cor segue o efeito, não o sinal.
  const positivo = invertido ? valor <= 0 : valor >= 0;
  const Icone = valor >= 0 ? TrendingUp : TrendingDown;
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs font-semibold ${positivo ? 'text-emerald-700' : 'text-rose-700'}`}
    >
      <Icone className="size-3.5" aria-hidden="true" />
      {valor > 0 ? '+' : ''}
      {percentual.format(valor)} p.p. vs. semana anterior
    </span>
  );
}

/** Resultado da operação. Sem fonte oficial, não exibe número algum. */
export function PdohResult({ summary }: { summary: PdohSummary | null }) {
  const state = pdohIndicatorState(summary);
  return (
    <article
      aria-labelledby="pdoh-resultado"
      className="flex flex-col justify-between rounded-2xl bg-[linear-gradient(135deg,#0a1e43_0%,#0b2349_55%,#123064_100%)] p-6 text-white"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2
            id="pdoh-resultado"
            className="text-[11px] font-bold uppercase tracking-[.18em] text-blue-200"
          >
            PDOH da semana
          </h2>
          <p className="mt-1 text-sm text-blue-100/80">Resultado da operação no período</p>
        </div>
        <Gauge className="size-6 shrink-0 text-blue-200" aria-hidden="true" />
      </div>

      {state.status === 'disponivel' ? (
        <div className="my-6">
          <p className="text-[3.25rem] font-extrabold leading-none tracking-tight tabular-nums">
            {percentual.format(state.percentual)}
            <span className="ml-1 text-2xl font-bold text-blue-200">%</span>
          </p>
          {state.variacao !== null && (
            <p className="mt-3">
              <span className="rounded-full bg-white/10 px-2.5 py-1">
                <Variacao valor={state.variacao} />
              </span>
            </p>
          )}
        </div>
      ) : (
        <output className="my-6 block">
          <p className="text-xl font-semibold leading-snug">
            {state.motivo === 'sem_periodo'
              ? ROTULO_SEM_PERIODO
              : state.motivo === 'sem_fonte'
                ? ROTULO_SEM_FONTE
                : state.message}
          </p>
          <p className="mt-3 text-xs leading-relaxed text-blue-100/80">
            {state.motivo === 'sem_periodo' && state.disponivel
              ? `A fonte oficial tem dados de ${formatDate(state.disponivel.de)} a ${formatDate(state.disponivel.ate)}. Nenhum valor é estimado para períodos sem registro.`
              : state.motivo === 'sem_periodo'
                ? state.message
                : 'Nenhum valor é estimado a partir dos impactadores.'}
          </p>
          {state.motivo === 'sem_periodo' && state.disponivel && (
            <Link
              to={`?periodo=personalizado&periodo_inicio=${state.disponivel.de}&periodo_fim=${state.disponivel.ate}`}
              className="mt-4 inline-flex min-h-11 items-center rounded-lg bg-white/10 px-4 text-sm font-semibold text-white hover:bg-white/20 focus-visible:outline-2 focus-visible:outline-white"
            >
              Ver dados disponíveis
            </Link>
          )}
        </output>
      )}

      <span className="w-fit rounded-full border border-white/25 px-3 py-1 text-xs font-semibold">
        {state.status === 'disponivel'
          ? 'Fonte oficial'
          : state.motivo === 'sem_periodo'
            ? 'Período sem dados'
            : state.motivo === 'sem_fonte'
              ? 'Fonte indisponível'
              : 'Aguardando fonte oficial'}
      </span>
    </article>
  );
}

/** KPI da composição do PDOH. Indicador nulo significa sem fonte — nunca zero. */
export function OperationalCard({
  rotulo,
  descricao,
  indicador,
  invertido = false,
  vazio = INDICADOR_UNAVAILABLE_MESSAGE,
}: {
  rotulo: string;
  descricao: string;
  indicador: Indicador | null;
  invertido?: boolean;
  /** Texto do cartão sem valor: reflete o motivo real (sem período, sem fonte...). */
  vazio?: string;
}) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5">
      <h3 className="text-[11px] font-bold uppercase tracking-[.12em] text-slate-500">
        {rotulo}
      </h3>
      {indicador ? (
        <>
          <p className="mt-3 text-[2rem] font-extrabold leading-none tracking-tight tabular-nums text-slate-950">
            {percentual.format(indicador.valor)}
            <span className="ml-0.5 text-base font-bold text-slate-400">
              {indicador.unidade}
            </span>
          </p>
          {indicador.variacao_periodo_anterior !== null && (
            <p className="mt-2">
              <Variacao valor={indicador.variacao_periodo_anterior} invertido={invertido} />
            </p>
          )}
        </>
      ) : (
        <p className="mt-3 text-sm font-semibold text-slate-400">{vazio}</p>
      )}
      <p className="mt-2 text-xs text-slate-500">{descricao}</p>
    </article>
  );
}

/** Composição do PDOH na ordem de leitura do líder. */
export function PdohComposition({ summary }: { summary: PdohSummary | null }) {
  const vazio = rotuloIndicadorVazio(pdohIndicatorState(summary));
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      {composicaoPdoh(summary).map((item) => (
        <OperationalCard
          key={item.chave}
          rotulo={item.rotulo}
          descricao={item.descricao}
          indicador={item.indicador}
          invertido={item.chave !== 'produtividade'}
          vazio={vazio}
        />
      ))}
      <OperationalCard
        rotulo="Efetividade"
        descricao="Indicador oficial composto pelo processamento PDOH"
        indicador={summary?.efetividade ?? null}
        vazio={vazio}
      />
    </div>
  );
}
