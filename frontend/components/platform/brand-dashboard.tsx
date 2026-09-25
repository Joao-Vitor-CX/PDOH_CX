import { ArrowRight, Database, Layers3, Workflow } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { StatusBadge } from '@/components/platform/consultation-ui';
import { CatalogSummary } from '@/components/platform/catalog-summary';
import type { Dashboard, Execution } from '@/src/services/pdoh-api';
import { formatDateTime, formatNumber, formatPeriod } from '@/src/lib/pdoh-format';

function MetricCard({ label, value, detail, icon: Icon }: { label: string; value: string; detail: string; icon: typeof Database }) {
  return <Card className="border-slate-200 shadow-sm"><CardContent className="p-5"><div className="flex items-start justify-between"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-500">{label}</p><p className="mt-3 text-3xl font-black tracking-tight text-slate-950">{value}</p><p className="mt-1 text-xs text-slate-500">{detail}</p></div><div className="rounded-xl bg-blue-50 p-2.5 text-blue-600"><Icon className="size-5" /></div></div></CardContent></Card>;
}

function CountDistribution({ title, counts }: { title: string; counts: Dashboard['status_execucoes'] }) {
  const max = Math.max(1, ...counts.map((count) => count.quantidade));
  return <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle className="text-sm">{title}</CardTitle></CardHeader><CardContent className="space-y-4">
    {counts.length === 0 && <p className="text-sm text-slate-500">Nenhuma ocorrência no período selecionado.</p>}
    {counts.map(({ valor, quantidade }) => <div key={valor} className="space-y-1.5"><div className="flex items-center justify-between gap-2 text-xs"><span className="break-all font-semibold text-slate-700">{valor}</span><span className="font-mono text-slate-600">{formatNumber(quantidade)}</span></div><div className="h-2 rounded-full bg-slate-100" aria-hidden="true"><div className="h-full rounded-full bg-gradient-to-r from-blue-700 to-blue-400" style={{ width: `${Math.max(quantidade > 0 ? 2 : 0, quantidade / max * 100)}%` }} /></div></div>)}
  </CardContent></Card>;
}

export function ExecutionTable({ executions }: { executions: Execution[] }) {
  return <><div className="divide-y md:hidden">{executions.map((execution) => <div key={execution.execution_id} className="space-y-3 p-4 text-sm"><div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="font-bold text-slate-900">{execution.marca}</p><p className="break-all font-mono text-xs text-slate-600">{execution.execution_id}</p></div><StatusBadge value={execution.status_execucao} /></div><div className="grid grid-cols-2 gap-2 text-xs"><div><p className="text-slate-500">Período</p><p>{formatPeriod(execution.periodo_inicio, execution.periodo_fim)}</p></div><div><p className="text-slate-500">Linhas recebidas</p><p>{formatNumber(execution.linhas_recebidas)}</p></div><div className="col-span-2"><p className="text-slate-500">Iniciada em</p><p>{formatDateTime(execution.iniciado_em)}</p></div></div><Link to={`/processamentos/${encodeURIComponent(execution.execution_id)}`} className="inline-flex items-center gap-1 font-semibold text-blue-700 hover:underline">Abrir execução <ArrowRight className="size-3" /></Link></div>)}</div><div className="hidden md:block"><Table><TableHeader><TableRow><TableHead>ID da execução</TableHead><TableHead>Marca</TableHead><TableHead>Período</TableHead><TableHead>Iniciada em</TableHead><TableHead>Linhas recebidas</TableHead><TableHead>Status</TableHead><TableHead>Detalhe</TableHead></TableRow></TableHeader><TableBody>
    {executions.map((execution) => <TableRow key={execution.execution_id}><TableCell className="max-w-52 truncate font-mono text-xs" title={execution.execution_id}>{execution.execution_id}</TableCell><TableCell className="font-semibold">{execution.marca}</TableCell><TableCell>{formatPeriod(execution.periodo_inicio, execution.periodo_fim)}</TableCell><TableCell>{formatDateTime(execution.iniciado_em)}</TableCell><TableCell>{formatNumber(execution.linhas_recebidas)}</TableCell><TableCell><StatusBadge value={execution.status_execucao} /></TableCell><TableCell><Link to={`/processamentos/${encodeURIComponent(execution.execution_id)}`} className="inline-flex items-center gap-1 text-xs font-semibold text-blue-700 hover:underline">Abrir <ArrowRight className="size-3" /></Link></TableCell></TableRow>)}
  </TableBody></Table></div></>;
}

export function BrandDashboard({ dashboard, brand }: { dashboard: Dashboard; brand?: string }) {
  const last = dashboard.ultimas_execucoes[0];
  const knownBrands = new Set(dashboard.marcas_periodos.items.map((item) => item.marca));
  return <div className="space-y-4">
    <section className="relative overflow-hidden rounded-2xl bg-[linear-gradient(115deg,#07152f,#0b2c63_70%,#164ea1)] p-6 text-white shadow-xl md:p-8">
      <div className="absolute -right-10 -top-24 size-72 rounded-full bg-blue-400/15 blur-2xl" aria-hidden="true" />
      <div className="relative flex flex-wrap items-start justify-between gap-4"><div><p className="text-[10px] font-extrabold uppercase tracking-[.18em] text-blue-300">Inteligência operacional · consulta real</p><h2 className="mt-2 text-2xl font-extrabold tracking-tight md:text-3xl">{brand ? `Marca ${brand}` : 'Visão PDOH_CX'}</h2><p className="mt-2 text-sm text-blue-100/80">Execuções e oportunidades produzidas pelo processamento existente.</p></div><Link to="/processamentos" className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-400">Ver execuções <ArrowRight className="size-4" /></Link></div>
      <div className="relative mt-6 flex flex-wrap gap-x-8 gap-y-2 border-t border-white/15 pt-4 text-xs text-blue-100"><span>Última execução: {last ? formatDateTime(last.iniciado_em) : 'Nenhuma'}</span><span>{last ? `Marca ${last.marca}` : 'Marca —'}</span><span>{last ? formatPeriod(last.periodo_inicio, last.periodo_fim) : 'Período —'}</span><span>{last ? <StatusBadge value={last.status_execucao} /> : 'Status —'}</span></div>
    </section>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Execuções" value={formatNumber(dashboard.total_execucoes)} detail="No filtro atual" icon={Workflow} />
      <MetricCard label="Oportunidades" value={formatNumber(dashboard.quantidade_oportunidades)} detail="Encontradas pelas validações" icon={Database} />
      <MetricCard label="Status distintos" value={formatNumber(dashboard.status_execucoes.length)} detail="Status reais de execução" icon={Layers3} />
      <MetricCard label="Marcas no retorno" value={formatNumber(knownBrands.size)} detail={dashboard.marcas_periodos.paginas > 1 ? 'Página atual de marcas/períodos' : 'Marcas com execuções'} icon={Layers3} />
    </div>
    <CatalogSummary brand={brand} />
    <div className="grid gap-4 xl:grid-cols-3"><CountDistribution title="Execuções por status" counts={dashboard.status_execucoes} /><CountDistribution title="Oportunidades por status" counts={dashboard.status_oportunidades} /><CountDistribution title="Inconsistências por tipo" counts={dashboard.distribuicao_por_tipo} /></div>
    <Card className="overflow-hidden border-slate-200 shadow-sm"><CardHeader className="border-b bg-slate-50/60"><CardTitle className="text-sm">Últimas execuções</CardTitle><p className="text-xs text-slate-500">IDs, datas e contagens preservados da API</p></CardHeader><CardContent className="p-0">{dashboard.ultimas_execucoes.length ? <ExecutionTable executions={dashboard.ultimas_execucoes} /> : <p className="p-6 text-sm text-slate-500">Nenhuma execução encontrada.</p>}</CardContent></Card>
  </div>;
}
