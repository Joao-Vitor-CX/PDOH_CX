import { useCallback } from 'react';
import { ArrowLeft, Filter } from 'lucide-react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ConsultationState, StatusBadge } from '@/components/platform/consultation-ui';
import { FilterPanel } from '@/components/platform/filter-panel';
import { PageHeader } from '@/components/platform/page-header';
import { FilterField, Pagination } from '@/components/platform/query-controls';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatDateTime, formatNumber } from '@/src/lib/pdoh-format';
import { apiRequest, mappingHistorySchema, mappingSchema, pageSchema, queryString, ruleSchema } from '@/src/services/pdoh-api';

const rulesPageSchema = pageSchema(ruleSchema);
const mappingsPageSchema = pageSchema(mappingSchema);

export function ParametersPage() {
  const [search, setSearch] = useSearchParams();
  const tab = search.get('aba') === 'de-para' ? 'de-para' : 'regras';
  const switchTab = (value: string) => setSearch({ aba: value });
  return <><PageHeader eyebrow="Parametrizações PDOH_CX" title="Regras e De/Para" description="Configurações existentes no banco, consultadas pela API. Esta interface não permite alterações." />
    <div className="mb-4 flex gap-2" role="tablist" aria-label="Tipos de parametrização"><button type="button" role="tab" aria-selected={tab === 'regras'} onClick={() => switchTab('regras')} className={`rounded-lg px-4 py-2 text-sm font-semibold ${tab === 'regras' ? 'bg-blue-700 text-white' : 'border border-slate-300 bg-white text-slate-700'}`}>Regras</button><button type="button" role="tab" aria-selected={tab === 'de-para'} onClick={() => switchTab('de-para')} className={`rounded-lg px-4 py-2 text-sm font-semibold ${tab === 'de-para' ? 'bg-blue-700 text-white' : 'border border-slate-300 bg-white text-slate-700'}`}>De/Para</button></div>
    {tab === 'regras' ? <RulesList search={search} setSearch={setSearch} /> : <MappingsList search={search} setSearch={setSearch} />}
  </>;
}

type SearchSetter = ReturnType<typeof useSearchParams>[1];
function updateQuery(search: URLSearchParams, setSearch: SearchSetter, name: string, value: string, resetPage = true) {
  const next = new URLSearchParams(search);
  if (value) next.set(name, value); else next.delete(name);
  if (resetPage) next.delete('pagina');
  setSearch(next);
}

function RulesList({ search, setSearch }: { search: URLSearchParams; setSearch: SearchSetter }) {
  const marca = search.get('marca') || '';
  const tipo = search.get('tipo') || '';
  const status = search.get('status') || '';
  const page = Number(search.get('pagina') || '1');
  const query = queryString({ marca, tipo, status, pagina: Number.isInteger(page) && page > 0 ? page : 1, tamanho: 50 });
  const loader = useCallback((signal: AbortSignal) => apiRequest(`/regras${query}`, rulesPageSchema, signal), [query]);
  const resource = usePdohResource(query, loader);
  return <><FilterPanel activeCount={[marca, tipo, status].filter(Boolean).length}><Filter className="mb-2 size-4 text-blue-600" /><FilterField label="Marca" value={marca} onChange={(value) => updateQuery(search, setSearch, 'marca', value)} /><FilterField label="Tipo" value={tipo} onChange={(value) => updateQuery(search, setSearch, 'tipo', value)} /><FilterField label="Status" value={status} onChange={(value) => updateQuery(search, setSearch, 'status', value)} /></FilterPanel>
    <ConsultationState {...resource} hasData={!!resource.data}>
      {resource.data && <Card className="overflow-hidden border-slate-200 shadow-sm"><CardHeader className="border-b bg-slate-50/60"><CardTitle className="text-sm">Regras cadastradas · {formatNumber(resource.data.total)}</CardTitle><p className="text-xs text-slate-500">O contrato não possui campo “nome”; o cenário cadastrado identifica a regra.</p></CardHeader><CardContent className="p-0">{resource.data.items.length ? <Table><TableHeader><TableRow><TableHead>ID</TableHead><TableHead>Cenário</TableHead><TableHead>Tipo</TableHead><TableHead>Marca</TableHead><TableHead>Prioridade</TableHead><TableHead>Status</TableHead><TableHead>Configuração</TableHead></TableRow></TableHeader><TableBody>{resource.data.items.map((rule) => <TableRow key={rule.regra_id}><TableCell className="max-w-48 truncate font-mono text-xs" title={rule.regra_id}>{rule.regra_id}</TableCell><TableCell className="max-w-64 whitespace-normal font-semibold">{rule.descricao_cenario}</TableCell><TableCell className="max-w-48 whitespace-normal">{rule.tipo_problema}</TableCell><TableCell>{rule.marca || 'Global'}</TableCell><TableCell>{rule.prioridade}</TableCell><TableCell><StatusBadge value={rule.status_regra} /></TableCell><TableCell><details className="min-w-64 text-xs"><summary className="cursor-pointer font-semibold text-blue-700">Ver configuração</summary><dl className="mt-2 space-y-2 whitespace-normal rounded-lg bg-slate-50 p-3"><div><dt className="font-bold">Identificação</dt><dd>{rule.regra_identificacao}</dd></div><div><dt className="font-bold">Tratamento esperado</dt><dd>{rule.tratamento_esperado}</dd></div><div><dt className="font-bold">Ação de aplicação</dt><dd>{rule.acao_aplicacao}</dd></div><div><dt className="font-bold">Permite processamento</dt><dd>{rule.permite_processamento ? 'Sim' : 'Não'}</dd></div><div><dt className="font-bold">Necessita aprovação</dt><dd>{rule.necessita_aprovacao ? 'Sim' : 'Não'}</dd></div></dl></details></TableCell></TableRow>)}</TableBody></Table> : <p className="p-6 text-sm text-slate-500">Nenhuma regra no filtro informado.</p>}</CardContent></Card>}
    </ConsultationState>
    {resource.data && <Pagination page={resource.data.pagina} pages={resource.data.paginas} onPage={(value) => updateQuery(search, setSearch, 'pagina', String(value), false)} label="Regras" />}
  </>;
}

function MappingsList({ search, setSearch }: { search: URLSearchParams; setSearch: SearchSetter }) {
  const marca = search.get('marca') || '';
  const processo = search.get('processo') || '';
  const campo = search.get('campo_origem') || '';
  const status = search.get('status') || '';
  const page = Number(search.get('pagina') || '1');
  const query = queryString({ marca, processo, campo_origem: campo, status, pagina: Number.isInteger(page) && page > 0 ? page : 1, tamanho: 50 });
  const loader = useCallback((signal: AbortSignal) => apiRequest(`/de-para${query}`, mappingsPageSchema, signal), [query]);
  const resource = usePdohResource(query, loader);
  return <><FilterPanel activeCount={[marca, processo, campo, status].filter(Boolean).length}><Filter className="mb-2 size-4 text-blue-600" /><FilterField label="Marca" value={marca} onChange={(value) => updateQuery(search, setSearch, 'marca', value)} /><FilterField label="Processo" value={processo} onChange={(value) => updateQuery(search, setSearch, 'processo', value)} /><FilterField label="Campo de origem" value={campo} onChange={(value) => updateQuery(search, setSearch, 'campo_origem', value)} /><FilterField label="Status" value={status} onChange={(value) => updateQuery(search, setSearch, 'status', value)} /></FilterPanel>
    <ConsultationState {...resource} hasData={!!resource.data}>
      {resource.data && <Card className="overflow-hidden border-slate-200 shadow-sm"><CardHeader className="border-b bg-slate-50/60"><CardTitle className="text-sm">De/Para cadastrados · {formatNumber(resource.data.total)}</CardTitle></CardHeader><CardContent className="p-0">{resource.data.items.length ? <Table><TableHeader><TableRow><TableHead>ID</TableHead><TableHead>Marca</TableHead><TableHead>Processo</TableHead><TableHead>Campo origem</TableHead><TableHead>Valor origem</TableHead><TableHead>Valor padronizado</TableHead><TableHead>Status</TableHead><TableHead>Histórico</TableHead></TableRow></TableHeader><TableBody>{resource.data.items.map((mapping) => <TableRow key={mapping.de_para_id}><TableCell className="max-w-48 truncate font-mono text-xs" title={mapping.de_para_id}>{mapping.de_para_id}</TableCell><TableCell>{mapping.marca || 'Global'}</TableCell><TableCell>{mapping.processo}</TableCell><TableCell>{mapping.campo_origem}</TableCell><TableCell className="max-w-52 truncate" title={mapping.valor_origem}>{mapping.valor_origem}</TableCell><TableCell className="max-w-52 truncate font-semibold" title={mapping.valor_padronizado}>{mapping.valor_padronizado}</TableCell><TableCell><StatusBadge value={mapping.status} /></TableCell><TableCell><Link className="text-xs font-semibold text-blue-700 hover:underline" to={`/parametrizacoes/de-para/${encodeURIComponent(mapping.de_para_id)}`}>Ver histórico</Link></TableCell></TableRow>)}</TableBody></Table> : <p className="p-6 text-sm text-slate-500">Nenhum De/Para no filtro informado.</p>}</CardContent></Card>}
    </ConsultationState>
    {resource.data && <Pagination page={resource.data.pagina} pages={resource.data.paginas} onPage={(value) => updateQuery(search, setSearch, 'pagina', String(value), false)} label="De/Para" />}
  </>;
}

export function MappingHistoryPage() {
  const { mappingId = '' } = useParams();
  const [search, setSearch] = useSearchParams();
  const page = Number(search.get('pagina') || '1');
  const safePage = Number.isInteger(page) && page > 0 ? page : 1;
  const id = encodeURIComponent(mappingId);
  const loader = useCallback((signal: AbortSignal) => apiRequest(`/de-para/${id}/historico${queryString({ pagina: safePage, tamanho: 50 })}`, pageSchema(mappingHistorySchema), signal), [id, safePage]);
  const resource = usePdohResource(`${id}:${safePage}`, loader);
  return <><PageHeader eyebrow="Auditoria de parametrização" title="Histórico do De/Para" description={`ID preservado: ${mappingId}`} action={<Link to="/parametrizacoes?aba=de-para" className="inline-flex items-center gap-2 text-sm font-semibold text-blue-700"><ArrowLeft className="size-4" /> Voltar ao De/Para</Link>} />
    <ConsultationState {...resource} hasData={!!resource.data}>
      {resource.data && <Card className="overflow-hidden border-slate-200 shadow-sm"><CardHeader><CardTitle className="text-sm">{formatNumber(resource.data.total)} eventos de histórico</CardTitle></CardHeader><CardContent className="p-0">{resource.data.items.length ? <Table><TableHeader><TableRow><TableHead>Data</TableHead><TableHead>Ação</TableHead><TableHead>Valor anterior</TableHead><TableHead>Valor novo</TableHead><TableHead>Status anterior</TableHead><TableHead>Status novo</TableHead><TableHead>Responsável</TableHead><TableHead>Observação</TableHead></TableRow></TableHeader><TableBody>{resource.data.items.map((event) => <TableRow key={event.id}><TableCell>{formatDateTime(event.registrado_em)}</TableCell><TableCell>{event.acao}</TableCell><TableCell>{event.valor_padronizado_anterior || '—'}</TableCell><TableCell>{event.valor_padronizado_novo || '—'}</TableCell><TableCell>{event.status_anterior || '—'}</TableCell><TableCell>{event.status_novo || '—'}</TableCell><TableCell>{event.responsavel || '—'}</TableCell><TableCell className="max-w-64 truncate" title={event.observacao || undefined}>{event.observacao || '—'}</TableCell></TableRow>)}</TableBody></Table> : <p className="p-6 text-sm text-slate-500">Nenhum histórico registrado.</p>}</CardContent></Card>}
    </ConsultationState>
    {resource.data && <Pagination page={resource.data.pagina} pages={resource.data.paginas} onPage={(value) => setSearch({ pagina: String(value) })} label="Histórico" />}
  </>;
}
