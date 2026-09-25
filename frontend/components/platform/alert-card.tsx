import type { ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { formatDateTime, formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import { displayLabel } from '@/src/lib/operational-display';
import type { AlertGroup, AlertCategory } from '@/src/services/operational-api';
import { alertSubject, originLabel, type AlertDetail } from '@/src/services/operational-trace';

/** Categoria de alerta cadastral: quantos problemas e quantas pessoas ela atinge. Abre o detalhe no próprio painel. */
export function AlertCategoryRow({ categoria, expanded, onToggle }: {
  categoria: AlertCategory; expanded: boolean; onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      className="flex w-full items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 text-left transition hover:border-amber-300 hover:bg-amber-50/40 focus-visible:outline-2 focus-visible:outline-blue-600"
    >
      <div className="min-w-0 flex-1">
        <h3 className="truncate text-sm font-bold text-slate-950">{categoria.titulo}</h3>
        <p className="mt-0.5 text-xs text-slate-500">
          {categoria.colaboradores_afetados
            ? `${formatNumber(categoria.colaboradores_afetados)} ${categoria.colaboradores_afetados === 1 ? 'colaborador' : 'colaboradores'}`
            : 'Pendência em valor ou registro de cadastro (o registro não identifica colaborador)'}{' '}
          · qualidade cadastral
        </p>
      </div>
      <div className="shrink-0 text-right">
        <p className="text-lg font-extrabold tabular-nums text-slate-950">
          {formatNumber(categoria.grupos)}
        </p>
        <p className="text-[11px] text-slate-500">
          {categoria.grupos === 1 ? 'pendência' : 'pendências'}
        </p>
      </div>
      <ChevronDown className={`size-4 shrink-0 text-slate-400 transition ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" />
    </button>
  );
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold text-slate-500">{label}</dt>
      <dd className="mt-0.5 break-words text-slate-900">{children}</dd>
    </div>
  );
}

/** Linha de pendência distinta, com o que a origem registrou. */
function DetailRow({ detalhe }: { detalhe: AlertDetail }) {
  return (
    <li className="rounded-lg border border-slate-200 p-3 text-xs">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
        {detalhe.colaborador && <Item label="Colaborador">{detalhe.colaborador}</Item>}
        {detalhe.identificadores.length > 0 && (
          <Item label={detalhe.identificadores.length > 1 ? 'Identificadores encontrados' : 'Identificador'}>
            <span className="font-mono">{detalhe.identificadores.join(' · ')}</span>
          </Item>
        )}
        {detalhe.campo && <Item label="Campo divergente">{displayLabel(detalhe.campo)}</Item>}
        {detalhe.valor_encontrado && <Item label="Valor encontrado">{detalhe.valor_encontrado}</Item>}
        {detalhe.valor_esperado && <Item label="Valor esperado">{detalhe.valor_esperado}</Item>}
        {detalhe.complementos.map((extra) => <Item key={extra.rotulo} label={extra.rotulo}>{extra.valor}</Item>)}
        <Item label="Identificado em">{formatDateTime(detalhe.identificado_em)}</Item>
      </dl>
    </li>
  );
}

/**
 * Pendência cadastral: quem (ou qual valor), onde, o que foi encontrado, por que e o que fazer.
 * `detalhes` vem dos registros individuais do alerta (`GET /api/v2/alertas`), sem recálculo.
 */
export function AlertCard({ alerta, detalhes }: { alerta: AlertGroup; detalhes?: AlertDetail[] | null }) {
  const problema = detalhes?.[0]?.problema;
  const identificacao = detalhes?.length
    ? detalhes.map((d) => d.identificado_em).sort().at(-1) ?? null : null;
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-950">{alerta.titulo}</h3>
        <span className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-900">
          {formatNumber(alerta.quantidade_alertas)}{' '}
          {alerta.quantidade_alertas === 1 ? 'pendência' : 'pendências'}
        </span>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <Item label="Colaborador">{alertSubject(alerta)}</Item>
        <Item label="Campo">{alerta.campo ? displayLabel(alerta.campo) : 'Não se aplica'}</Item>
        <Item label="Origem da informação">{originLabel(alerta.origem) ?? 'Não informada'}</Item>
        <Item label="Período">
          {alerta.primeira_ocorrencia || alerta.ultima_ocorrencia
            ? formatPeriod(alerta.primeira_ocorrencia, alerta.ultima_ocorrencia)
            : identificacao ? `Sem data de ocorrência na origem · identificado em ${formatDateTime(identificacao)}` : 'Não informado'}
        </Item>
      </dl>
      {problema && (
        <div className="mt-4 rounded-lg border border-amber-100 bg-amber-50/60 p-3">
          <p className="text-xs font-semibold text-amber-900">Problema</p>
          <p className="mt-1 text-sm leading-relaxed text-amber-950">{problema}</p>
        </div>
      )}
      {detalhes === undefined ? null : detalhes === null ? (
        <p className="mt-3 text-xs text-slate-500">Registros individuais indisponíveis no momento.</p>
      ) : detalhes.length > 0 && (
        <details className="mt-3" open={detalhes.length <= 4}>
          <summary className="cursor-pointer text-xs font-semibold text-blue-700">
            {detalhes.length === 1 ? 'Registro da pendência' : `${formatNumber(detalhes.length)} registros distintos`}
          </summary>
          <ul className="mt-2 max-h-80 space-y-2 overflow-y-auto">
            {detalhes.map((detalhe, indice) => <DetailRow key={`${detalhe.valor_encontrado}-${detalhe.colaborador}-${indice}`} detalhe={detalhe} />)}
          </ul>
        </details>
      )}
      <div className="mt-4 rounded-lg bg-slate-50 p-3">
        <p className="text-xs font-semibold text-slate-500">Tratativa</p>
        <p className="mt-1 text-sm leading-relaxed text-slate-700">
          {alerta.acao_recomendada || alerta.impacto || 'Tratativa ainda não cadastrada para esta regra.'}
        </p>
      </div>
    </article>
  );
}
