import { Fragment, useCallback, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ConsultationState } from '@/components/platform/consultation-ui';
import { OpportunityRecordDetail } from '@/components/platform/opportunity-record-modal';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import type { OperationalFilters, OperationalGroup } from '@/src/services/operational-api';
import { queryString } from '@/src/services/pdoh-api';
import { displayLabel } from '@/src/lib/operational-display';
import { formatNumber, formatPeriod } from '@/src/lib/pdoh-format';
import {
  OPPORTUNITY_COLUMNS, groupFallback, loadHistories, loadOpportunityRecords, workbookBlob, workbookSheets, xlsxFileName,
  type OpportunityRecord,
} from '@/src/services/daily-validation';
import type { ValidationSummary } from '@/src/services/pdoh-indicator';

function downloadBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/**
 * Exporta a semana em XLSX (Resumo, Oportunidades, Evidências, Histórico) a partir das MESMAS
 * linhas do detalhamento; ocorrências e histórico só são lidos no momento da exportação.
 */
export function useXlsxExport() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (periodo: { inicio: string; fim: string }, source: () => Promise<{
    records: OpportunityRecord[]; validacao: ValidationSummary | null;
  }>) => {
    setError(null);
    setBusy(true);
    try {
      const { records, validacao } = await source();
      const historicos = await loadHistories(records.map((record) => record.id));
      downloadBlob(xlsxFileName(periodo), await workbookBlob(workbookSheets({ periodo, validacao, records, historicos })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Não foi possível gerar o arquivo.');
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, error };
}

export function XlsxButton({ onClick, busy, disabled }: { onClick: () => void; busy: boolean; disabled?: boolean }) {
  return (
    <Button variant="outline" className="min-h-11" onClick={onClick} disabled={disabled || busy}>
      <Download aria-hidden="true" />
      {busy ? 'Gerando arquivo…' : 'Baixar XLSX'}
    </Button>
  );
}

/** Ocorrências de UM grupo, lidas só quando o grupo é aberto. */
function GroupOccurrences({ group, window, onOpen }: {
  group: OperationalGroup; window: OperationalFilters; onOpen: (record: OpportunityRecord) => void;
}) {
  const scoped = useMemo(() => ({ ...window, colaborador: group.colaborador ?? window.colaborador }), [group.colaborador, window]);
  const loader = useCallback((signal: AbortSignal) => loadOpportunityRecords([group], scoped, signal), [group, scoped]);
  const resource = usePdohResource(`ocorrencias|${group.grupo_id}|${queryString(scoped)}`, loader);
  return <ConsultationState {...resource} hasData={!!resource.data}>
    {resource.data && <div className="overflow-x-auto">
      <Table className="min-w-[1400px] bg-white text-xs">
        <TableHeader><TableRow>
          {OPPORTUNITY_COLUMNS.map(([label]) => <TableHead key={label}>{label}</TableHead>)}
          <TableHead>Detalhamento</TableHead>
        </TableRow></TableHeader>
        <TableBody>{resource.data.records.map((record) => <TableRow key={record.id} className="align-top">
          {OPPORTUNITY_COLUMNS.map(([label, get]) => label === 'ID'
            ? <TableCell key={label} className="font-mono text-[11px] text-slate-500" title={record.id}>{record.id.slice(0, 8)}</TableCell>
            : <TableCell key={label} className={label === 'Colaborador' ? 'font-semibold' : 'max-w-72 whitespace-normal'}>{get(record)}</TableCell>)}
          <TableCell><Button variant="ghost" size="sm" onClick={() => onOpen(record)}>Detalhar</Button></TableCell>
        </TableRow>)}</TableBody>
      </Table>
    </div>}
  </ConsultationState>;
}

/** Agrupamentos da janela (já carregados pelo card); detalhe por grupo e por ocorrência sob demanda. */
export function DailyOpportunities({ window: windowProp, groups }: { window: OperationalFilters; groups: OperationalGroup[] }) {
  // O pai recria o objeto da janela a cada render; só o CONTEÚDO da janela pode disparar nova carga.
  const windowKey = queryString(windowProp);
  const window = useMemo(() => Object.fromEntries(new URLSearchParams(windowKey)) as OperationalFilters, [windowKey]);
  const [open, setOpen] = useState<string | null>(null);
  const [selected, setSelected] = useState<OpportunityRecord | null>(null);
  const exporter = useXlsxExport();
  const total = groups.reduce((sum, group) => sum + group.quantidade, 0);
  const periodo = { inicio: window.periodo_inicio ?? '', fim: window.periodo_fim ?? '' };
  return <>
    <div className="flex flex-wrap items-center justify-between gap-3 p-4">
      <p className="text-sm text-slate-600">{formatNumber(total)} ocorrências em {formatNumber(groups.length)} agrupamentos · {formatPeriod(window.periodo_inicio ?? null, window.periodo_fim ?? null)}</p>
      <XlsxButton busy={exporter.busy} disabled={!total}
        onClick={() => void exporter.run(periodo, () => loadOpportunityRecords(groups, window))} />
    </div>
    {exporter.error && <p role="alert" className="px-4 pb-3 text-sm text-red-700">{exporter.error}</p>}
    {groups.length ? <Table className="min-w-[760px] text-xs">
      <TableHeader><TableRow>
        {['', 'Colaborador', 'Tipo da oportunidade', 'Ocorrências', 'Fallback aplicado', 'Período', 'Status'].map((label) => <TableHead key={label || 'abrir'}>{label}</TableHead>)}
      </TableRow></TableHeader>
      <TableBody>{groups.map((group) => {
        const expanded = open === group.grupo_id;
        return <Fragment key={group.grupo_id}>
          <TableRow className="cursor-pointer" onClick={() => setOpen(expanded ? null : group.grupo_id)}>
            <TableCell className="w-8">
              <button type="button" aria-expanded={expanded} aria-label={`${expanded ? 'Recolher' : 'Abrir'} ocorrências de ${group.colaborador ?? 'colaborador'}`}
                onClick={(event) => { event.stopPropagation(); setOpen(expanded ? null : group.grupo_id); }} className="rounded p-1 text-blue-700">
                {expanded ? <ChevronDown className="size-4" aria-hidden="true" /> : <ChevronRight className="size-4" aria-hidden="true" />}
              </button>
            </TableCell>
            <TableCell className="font-semibold">{group.colaborador ?? 'Não informado'}</TableCell>
            <TableCell>{group.titulo}<span className="block text-slate-500">{group.tipo_problema}</span></TableCell>
            <TableCell>{formatNumber(group.quantidade)}</TableCell>
            <TableCell>{formatNumber(groupFallback(group))}</TableCell>
            <TableCell>{formatPeriod(group.primeira_ocorrencia, group.ultima_ocorrencia)}</TableCell>
            <TableCell>{displayLabel(group.status_operacional)}</TableCell>
          </TableRow>
          {/* max-w-0: a tabela larga das ocorrências rola dentro da célula e não estica os grupos. */}
          {expanded && <TableRow className="hover:bg-transparent"><TableCell colSpan={7} className="max-w-0 bg-slate-50 p-3">
            <GroupOccurrences group={group} window={window} onOpen={setSelected} />
          </TableCell></TableRow>}
        </Fragment>;
      })}</TableBody>
    </Table> : <p className="p-6 text-sm text-slate-500">Nenhuma oportunidade (checkout ausente com fallback) no período. Horas não registradas impactam só o PDOH.</p>}
    <Dialog open={!!selected} onOpenChange={(value) => { if (!value) setSelected(null); }}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader><DialogTitle>{selected ? `${selected.regra} · ${selected.titulo}` : 'Oportunidade'}</DialogTitle>
          <DialogDescription>Motivo, jornada, evidências e histórico da ocorrência.</DialogDescription></DialogHeader>
        {selected && <OpportunityRecordDetail record={selected} />}
      </DialogContent>
    </Dialog>
  </>;
}
