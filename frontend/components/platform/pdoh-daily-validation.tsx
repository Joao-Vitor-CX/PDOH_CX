import { Fragment, useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, Clock3, ShieldCheck, TriangleAlert } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { DailyOpportunities } from '@/components/platform/daily-opportunities';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import type { PdohSummary, PdohDailyRow, DayStatus } from '@/src/services/pdoh-indicator';
import type { OperationalFilters } from '@/src/services/operational-api';
import { dayStatusLabel, loadOpportunityGroups, summarizeOpportunities } from '@/src/services/daily-validation';
import { formatDate, formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import { queryString } from '@/src/services/pdoh-api';
import { OPPORTUNITIES_REFRESHED } from '@/src/services/weekly-monitoring';

// Origem da jornada. FALLBACK é a jornada padrão (cadastro sem jornada), não o fallback de checkout.
const JOURNEY_ORIGIN: Record<string, string> = {
  INVOLVES: 'Cadastro Involves', RAW: 'RAW operacional', CONFIGURACAO: 'Configuração da operação',
  FALLBACK: 'Jornada padrão 44H',
};
const STATUS_TONE: Record<DayStatus, string> = {
  VALIDO: 'bg-emerald-50 text-emerald-800 border-emerald-200',
  CHECKOUT_ESQUECIDO: 'bg-amber-50 text-amber-900 border-amber-200',
  DESCONSIDERADO: 'bg-slate-100 text-slate-700 border-slate-200',
  SEM_ATIVIDADE_PREVISTA: 'bg-slate-100 text-slate-700 border-slate-200',
};
const value = (text: string | null | undefined) => text || 'Não informado';
const hhmm = (text: string | null | undefined) => text?.slice(0, 5) ?? null;
const yesNo = (flag: boolean | null | undefined) => (flag == null ? 'Não informado' : flag ? 'Sim' : 'Não');

/** Saída do dia: a registrada, ou a considerada pelo fallback quando o checkout foi esquecido. */
function exitTime(row: PdohDailyRow) {
  if (row.validacao?.fallback_aplicado) return `${row.validacao.saida_considerada} (fallback)`;
  if (row.validacao?.status === 'CHECKOUT_ESQUECIDO') return 'Não registrada';
  return hhmm(row.ultimo_checkout) ?? '—';
}

function Block({ title, fields }: { title: string; fields: [string, string][] }) {
  return <section className="rounded-lg border border-slate-200 bg-white p-3">
    <h4 className="text-xs font-bold uppercase tracking-wide text-slate-500">{title}</h4>
    <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2">{fields.map(([label, text]) => <div key={label}>
      <dt className="text-[11px] text-slate-500">{label}</dt><dd className="break-words text-xs text-slate-900">{text}</dd>
    </div>)}</dl>
  </section>;
}

/** Detalhamento do dia em quatro blocos operacionais; nada técnico na tabela principal. */
function DayDetail({ row }: { row: PdohDailyRow }) {
  const v = row.validacao;
  const expected = v?.saida_considerada ? `${hhmm(row.primeiro_checkin) ?? '—'} – ${v.saida_considerada}` : value(hhmm(row.horas_programadas) && `${hhmm(row.horas_programadas)} programadas`);
  return <div className="grid gap-3 bg-slate-50 p-4 md:grid-cols-2">
    <Block title="Informações gerais" fields={[
      ['Estado', value(row.estado)], ['Dia', value(row.nome_do_dia)],
      ['Justificativa', row.justificativa ?? 'Nenhuma'], ['Status da validação', dayStatusLabel(v?.status)],
    ]} />
    <Block title="Jornada aplicada" fields={[
      ['Jornada considerada', value(row.jornada.jornada_aplicada)],
      ['Origem da jornada', value(row.jornada.origem ? JOURNEY_ORIGIN[row.jornada.origem] ?? row.jornada.origem : null)],
      ['Horário esperado', expected], ['Fallback aplicado', yesNo(v?.fallback_aplicado)],
    ]} />
    <Block title="Indicadores do dia" fields={[
      ['Produtividade', value(row.produtividade)], ['Ócio', value(row.ocio)],
      ['Deslocamento', value(row.deslocamento)], ['Horas não registradas', value(row.horas_nao_registradas)],
    ]} />
    <Block title="Resultado da validação" fields={[
      ['Considerado no cálculo', yesNo(v?.considerado)],
      ['Desconsiderado', yesNo(v ? !v.considerado : null)],
      ['Gerou oportunidade', v?.gerou_oportunidade ? 'Sim · Checkout ausente' : v ? 'Não' : 'Não informado'],
      ['Motivo', value(v?.motivo)],
    ]} />
  </div>;
}

function Metric({ label, value: number }: { label: string; value: number | null | undefined }) {
  return <div><dt className="text-[11px] text-slate-500">{label}</dt><dd className="text-base font-bold text-slate-900">{number == null ? '—' : formatNumber(number)}</dd></div>;
}

export function PdohDailyValidation({ summary, onPage, window }: {
  summary: PdohSummary; onPage: (page: number) => void; window: OperationalFilters;
}) {
  const [view, setView] = useState<'general' | 'opportunities' | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const details = summary.detalhes;
  const validation = summary.validacao;
  const periodo = formatPeriod(summary.periodo.inicio, summary.periodo.fim);
  const opportunityWindow: OperationalFilters = {
    marca: window.marca, operacao: window.operacao, colaborador: window.colaborador,
    periodo: 'personalizado', periodo_inicio: summary.periodo.inicio, periodo_fim: summary.periodo.fim,
  };
  // Carga inicial leve: só os grupos (1 consulta paginada). Ocorrências, evidências e histórico
  // são lidos quando o usuário abre o detalhamento.
  const groupsKey = queryString(opportunityWindow);
  const groupsLoader = useCallback((signal: AbortSignal) => loadOpportunityGroups(
    Object.fromEntries(new URLSearchParams(groupsKey)), signal,
  ), [groupsKey]);
  const groups = usePdohResource(`grupos|${groupsKey}`, groupsLoader);
  const retryGroups = groups.retry;
  useEffect(() => {
    globalThis.window.addEventListener(OPPORTUNITIES_REFRESHED, retryGroups);
    return () => globalThis.window.removeEventListener(OPPORTUNITIES_REFRESHED, retryGroups);
  }, [retryGroups]);
  const opportunities = groups.data ? summarizeOpportunities(groups.data) : null;

  const cards = [
    {
      id: 'general' as const, title: 'Horário geral', Icon: Clock3,
      description: `Dias do período ${periodo}: considerados, justificados e com fallback.`,
      metrics: validation ? <>
        <Metric label="Considerados no cálculo" value={validation.considerados} />
        <Metric label="Desconsiderados (justificados)" value={validation.desconsiderados} />
        <Metric label="Fallback aplicado" value={validation.fallback_aplicado} />
        <Metric label="Sem atividade prevista" value={validation.sem_atividade_prevista} />
      </> : <p className="col-span-full text-xs text-slate-500">Status da validação indisponível para o período.</p>,
    },
    {
      id: 'opportunities' as const, title: 'Oportunidades', Icon: TriangleAlert,
      description: `Tipo: ${opportunities?.tipos.map((tipo) => tipo.titulo).join(' · ') || 'Checkout ausente'} · período ${periodo}`,
      metrics: groups.error ? <p className="col-span-full text-xs text-red-700">{groups.error}</p> : <>
        <Metric label="Ocorrências" value={opportunities?.total} />
        <Metric label="Colaboradores" value={opportunities?.colaboradores} />
        <Metric label="Fallback aplicado" value={opportunities?.fallback} />
        <Metric label="Pendências" value={opportunities?.pendencias} />
      </>,
    },
  ];

  return <Card className="mt-6 overflow-hidden border-slate-200 shadow-sm">
    <CardHeader className="border-b border-slate-200 bg-slate-50/70">
      <CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="size-5 text-blue-700" aria-hidden="true" />Validação diária do PDOH</CardTitle>
      <p className="text-xs text-slate-500">Oportunidade = check-in sem checkout, com fallback aplicado. Dias justificados (atestado, feriado, férias, FTJ) e sem atividade prevista ficam fora da análise; o cálculo do PDOH não muda.</p>
    </CardHeader>
    <CardContent className="p-0">
      <div className="grid gap-3 p-4 sm:grid-cols-2">
        {cards.map(({ id, title, description, Icon, metrics }) => <button key={id} type="button"
          aria-expanded={view === id} aria-controls={`daily-${id}`} onClick={() => setView(view === id ? null : id)}
          className={`rounded-xl border p-4 text-left focus-visible:outline-2 focus-visible:outline-blue-600 ${view === id ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white hover:border-blue-300'}`}>
          <span className="flex items-center gap-2 font-bold text-slate-900"><Icon className="size-5 text-blue-700" aria-hidden="true" />{title}</span>
          <span className="mt-1 block text-xs text-slate-500">{description}</span>
          <dl className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">{metrics}</dl>
        </button>)}
      </div>
      {view === 'general' && <section id="daily-general" aria-label="Horário geral">
        {details.items.length ? <Table className="min-w-[760px] text-xs">
          <TableHeader><TableRow>{['', 'Colaborador', 'Data', 'Jornada aplicada', 'Entrada', 'Saída', 'Status'].map((label) => <TableHead key={label || 'abrir'}>{label}</TableHead>)}</TableRow></TableHeader>
          <TableBody>{details.items.map((row) => {
            const key = `${row.colaborador}-${row.data}`;
            const expanded = open === key;
            return <Fragment key={key}>
              <TableRow className="cursor-pointer" onClick={() => setOpen(expanded ? null : key)}>
                <TableCell className="w-8">
                  <button type="button" aria-expanded={expanded} aria-label={`${expanded ? 'Recolher' : 'Expandir'} detalhamento de ${row.colaborador} em ${formatDate(row.data)}`}
                    onClick={(event) => { event.stopPropagation(); setOpen(expanded ? null : key); }} className="rounded p-1 text-blue-700">
                    {expanded ? <ChevronDown className="size-4" aria-hidden="true" /> : <ChevronRight className="size-4" aria-hidden="true" />}
                  </button>
                </TableCell>
                <TableCell className="font-semibold">{row.colaborador}</TableCell><TableCell>{formatDate(row.data)}</TableCell>
                <TableCell>{value(row.jornada.jornada_aplicada)}</TableCell>
                <TableCell>{hhmm(row.primeiro_checkin) ?? '—'}</TableCell><TableCell>{exitTime(row)}</TableCell>
                <TableCell>{row.validacao
                  ? <span className={`inline-block rounded-full border px-2 py-0.5 font-semibold ${STATUS_TONE[row.validacao.status]}`}>{dayStatusLabel(row.validacao.status)}</span>
                  : 'Não informado'}</TableCell>
              </TableRow>
              {expanded && <TableRow className="hover:bg-transparent"><TableCell colSpan={7} className="whitespace-normal p-0"><DayDetail row={row} /></TableCell></TableRow>}
            </Fragment>;
          })}</TableBody>
        </Table> : <p className="p-6 text-sm text-slate-500">Nenhum registro diário corresponde aos filtros selecionados.</p>}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 text-xs text-slate-600">
          <span>{formatNumber(details.total)} registros · página {details.pagina} de {Math.max(details.paginas, 1)}</span>
          <div className="flex gap-2">
            <button type="button" disabled={details.pagina <= 1} onClick={() => onPage(details.pagina - 1)} className="min-h-9 rounded-md border px-3 font-semibold disabled:opacity-40">Anterior</button>
            <button type="button" disabled={details.pagina >= details.paginas} onClick={() => onPage(details.pagina + 1)} className="min-h-9 rounded-md border px-3 font-semibold disabled:opacity-40">Próxima</button>
          </div>
        </div>
      </section>}
      {view === 'opportunities' && <section id="daily-opportunities" aria-label="Oportunidades da validação diária">
        {window.estado && <p className="px-4 text-xs text-amber-800">O filtro de estado aplica-se ao horário geral. A API de oportunidades oferece período e colaborador.</p>}
        {groups.data ? <DailyOpportunities key={groupsKey} window={opportunityWindow} groups={groups.data} />
          : <p className="p-6 text-sm text-slate-500">{groups.error ?? 'Carregando oportunidades…'}</p>}
      </section>}
    </CardContent>
  </Card>;
}
