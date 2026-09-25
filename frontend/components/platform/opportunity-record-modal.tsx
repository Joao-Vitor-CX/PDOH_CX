import { useCallback } from 'react';
import { CalendarDays, Clock3, Database, History, UserRound } from 'lucide-react';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { displayLabel } from '@/src/lib/operational-display';
import { formatDate, formatDateTime } from '@/src/lib/pdoh-format';
import { dayStatusLabel, loadHistory, type OpportunityRecord } from '@/src/services/daily-validation';

function Campo({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold text-slate-500">{rotulo}</dt>
      <dd className="mt-0.5 break-words text-sm text-slate-900">{valor}</dd>
    </div>
  );
}

function HistoryList({ id }: { id: string }) {
  const loader = useCallback((signal: AbortSignal) => loadHistory(id, signal), [id]);
  const resource = usePdohResource(`historico|${id}`, loader);
  return (
    <ConsultationState {...resource} hasData={!!resource.data}>
      {resource.data && (resource.data.length ? (
        <ol className="mt-3 space-y-2">
          {resource.data.map((item) => (
            <li key={item.id} className="rounded-lg border border-slate-200 p-3 text-xs text-slate-700">
              <p className="font-semibold text-slate-900">
                {displayLabel(item.acao)} · {item.status_anterior ? `${displayLabel(item.status_anterior)} → ` : ''}{displayLabel(item.status_novo)}
              </p>
              <p className="mt-1">{formatDateTime(item.registrado_em)} · execução {item.execution_id}{item.responsavel ? ` · ${item.responsavel}` : ''}</p>
              {item.observacao && <p className="mt-1 text-slate-600">{item.observacao}</p>}
            </li>
          ))}
        </ol>
      ) : <p className="mt-3 text-sm text-slate-500">Nenhuma tratativa registrada.</p>)}
    </ConsultationState>
  );
}

/** Detalhe de UMA ocorrência: os mesmos campos da tabela e do XLSX, mais evidências e histórico. */
export function OpportunityRecordDetail({ record }: { record: OpportunityRecord }) {
  return (
    <div className="space-y-5">
      <header className="space-y-2 text-sm text-slate-700">
        <p className="flex items-start gap-2"><UserRound className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <span className="break-words font-medium">{record.colaborador}</span></p>
        <p className="flex items-center gap-2"><CalendarDays className="size-4 shrink-0" aria-hidden="true" />
          {formatDate(record.data)}{record.status_dia && ` · dia ${dayStatusLabel(record.status_dia).toLocaleLowerCase('pt-BR')}`}</p>
      </header>

      <section className="rounded-xl bg-slate-50 p-4">
        <h3 className="text-sm font-bold text-slate-900">Motivo</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate-700">{record.motivo}</p>
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
          <Campo rotulo="Regra" valor={record.regra} />
          <Campo rotulo="Cenário" valor={record.cenario} />
          <Campo rotulo="Status" valor={displayLabel(record.status)} />
          <Campo rotulo="Jornada" valor={record.jornada ?? 'Não informada'} />
          <Campo rotulo="Origem" valor={record.origem_jornada ?? 'Não informada'} />
          <Campo rotulo="Fallback" valor={record.fallback} />
          <Campo rotulo="Check-in" valor={record.checkin ?? 'Não informado'} />
          <Campo rotulo="Checkout" valor={record.checkout ?? 'Não informado'} />
          <Campo rotulo="Saída considerada" valor={record.saida_considerada ?? '—'} />
        </dl>
      </section>

      <section>
        <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <Database className="size-4" aria-hidden="true" />Evidências
        </h3>
        <p className="mt-2 text-sm text-slate-700">{record.evidencia ?? 'Não informada'}</p>
        {record.evidencias.length > 0 && (
          <ul className="mt-3 space-y-2">
            {record.evidencias.map((linha, indice) => (
              <li key={`${linha.verificacao}-${indice}`} className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 text-sm">
                <span aria-hidden="true" className={`mt-1 size-2 shrink-0 rounded-full ${
                  linha.atendido === true ? 'bg-emerald-500' : linha.atendido === false ? 'bg-slate-400' : 'bg-amber-500'}`} />
                <div className="min-w-0">
                  <p className="font-medium text-slate-800">{linha.verificacao}
                    <span className="ml-2 text-xs font-normal text-slate-500">
                      {linha.atendido === true ? 'atendido' : linha.atendido === false ? 'não atendido' : 'não verificável'}
                    </span>
                  </p>
                  {(linha.fonte || linha.campo || linha.valor) && (
                    <p className="mt-1 text-xs text-slate-500">
                      {[linha.fonte, linha.campo, linha.valor].filter(Boolean).join(' · ')}
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
          <Clock3 className="size-3" aria-hidden="true" />
          Identificada em {formatDateTime(record.identificada_em)} · execução {record.execucao}
          {record.repeticoes > 1 && ` · gravada em ${record.repeticoes} execuções`} · ID {record.id}
        </p>
      </section>

      <section>
        <h3 className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <History className="size-4" aria-hidden="true" />Histórico
        </h3>
        <HistoryList id={record.id} />
      </section>
    </div>
  );
}
