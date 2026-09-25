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
import { apiRequest, collaboratorSchema, entitySchema, pageSchema, queryString } from '@/src/services/pdoh-api';

const entityPageSchema = pageSchema(entitySchema);

export function IdentifiersPage() {
  const [search, setSearch] = useSearchParams();
  const marca = search.get('marca') || '';
  const tipo = search.get('tipo_entidade') || '';
  const status = search.get('status') || '';
  const page = Number(search.get('pagina') || '1');
  const query = queryString({ marca, tipo_entidade: tipo, status, pagina: Number.isInteger(page) && page > 0 ? page : 1, tamanho: 50 });
  const loader = useCallback((signal: AbortSignal) => apiRequest(`/entidades${query}`, entityPageSchema, signal), [query]);
  const resource = usePdohResource(query, loader);
  const update = (name: string, value: string, resetPage = true) => { const next = new URLSearchParams(search); if (value) next.set(name, value); else next.delete(name); if (resetPage) next.delete('pagina'); setSearch(next); };
  return <><PageHeader eyebrow="Identificadores únicos" title="Entidades rastreáveis" description="Consulta de identificadores internos, vínculo com execuções e origem preservados no PDOH_CX." />
    <FilterPanel activeCount={[marca, tipo, status].filter(Boolean).length}><Filter className="mb-2 size-4 text-blue-600" /><FilterField label="Marca" value={marca} onChange={(value) => update('marca', value)} /><FilterField label="Tipo de entidade" value={tipo} onChange={(value) => update('tipo_entidade', value)} /><FilterField label="Status" value={status} onChange={(value) => update('status', value)} /></FilterPanel>
    <ConsultationState {...resource} hasData={!!resource.data}>{resource.data && <Card className="overflow-hidden border-slate-200 shadow-sm"><CardHeader className="border-b bg-slate-50/60"><CardTitle className="text-sm">{formatNumber(resource.data.total)} identificadores no filtro</CardTitle></CardHeader><CardContent className="p-0">{resource.data.items.length ? <Table><TableHeader><TableRow><TableHead>ID</TableHead><TableHead>Tipo</TableHead><TableHead>Marca</TableHead><TableHead>Nome normalizado</TableHead><TableHead>Origem</TableHead><TableHead>Observações</TableHead><TableHead>Status</TableHead><TableHead>Detalhe</TableHead></TableRow></TableHeader><TableBody>{resource.data.items.map((item) => <TableRow key={item.identificador_id}><TableCell className="max-w-56 truncate font-mono text-xs" title={item.identificador_id}>{item.identificador_id}</TableCell><TableCell>{item.tipo_entidade}</TableCell><TableCell>{item.marca}</TableCell><TableCell>{item.nome_normalizado || '—'}</TableCell><TableCell>{item.origem_dado}</TableCell><TableCell>{formatNumber(item.quantidade_observacoes)}</TableCell><TableCell><StatusBadge value={item.status} /></TableCell><TableCell><Link to={`/identificadores/entidades/${encodeURIComponent(item.identificador_id)}`} className="text-xs font-semibold text-blue-700 hover:underline">Abrir</Link></TableCell></TableRow>)}</TableBody></Table> : <p className="p-6 text-sm text-slate-500">Nenhum identificador para este filtro.</p>}</CardContent></Card>}</ConsultationState>
    {resource.data && <Pagination page={resource.data.pagina} pages={resource.data.paginas} onPage={(value) => update('pagina', String(value), false)} label="Entidades" />}
  </>;
}

export function EntityDetailPage() {
  const { entityId = '' } = useParams();
  const id = encodeURIComponent(entityId);
  const loader = useCallback((signal: AbortSignal) => apiRequest(`/entidades/${id}`, entitySchema, signal), [id]);
  const resource = usePdohResource(id, loader);
  return <><PageHeader eyebrow="Identidade de entidade" title="Detalhe do identificador" description="ID interno e execuções associadas, sem agregações simuladas." action={<Link to="/identificadores" className="inline-flex items-center gap-2 text-sm font-semibold text-blue-700"><ArrowLeft className="size-4" /> Voltar aos identificadores</Link>} />
    <ConsultationState {...resource} hasData={!!resource.data}>{resource.data && <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle className="break-all font-mono text-base">{resource.data.identificador_id}</CardTitle></CardHeader><CardContent className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-3"><Field label="Tipo" value={resource.data.tipo_entidade} /><Field label="Marca" value={resource.data.marca} /><Field label="Identificador interno" value={resource.data.identificador_interno} /><Field label="Chave de identidade" value={resource.data.chave_identidade} /><Field label="Nome original" value={resource.data.nome_original || '—'} /><Field label="Nome normalizado" value={resource.data.nome_normalizado || '—'} /><Field label="Origem" value={resource.data.origem_dado} /><Field label="Observações" value={formatNumber(resource.data.quantidade_observacoes)} /><Field label="Status" value={resource.data.status} /><Field label="Criado em" value={formatDateTime(resource.data.data_criacao)} /><Field label="Atualizado em" value={formatDateTime(resource.data.data_atualizacao)} /><ExecutionLink label="Primeira execução" id={resource.data.primeira_execucao_id} /><ExecutionLink label="Última execução" id={resource.data.ultima_execucao_id} /></CardContent></Card>}</ConsultationState>
  </>;
}

export function CollaboratorDetailPage() {
  const { collaboratorId = '' } = useParams();
  const id = encodeURIComponent(collaboratorId);
  const loader = useCallback((signal: AbortSignal) => apiRequest(`/colaboradores/${id}`, collaboratorSchema, signal), [id]);
  const resource = usePdohResource(id, loader);
  return <><PageHeader eyebrow="Identidade de colaborador" title="Colaborador rastreável" description="Registro de identidade fornecido pela API; não são exibidos KPIs de produtividade do protótipo." action={<Link to="/oportunidades" className="inline-flex items-center gap-2 text-sm font-semibold text-blue-700"><ArrowLeft className="size-4" /> Voltar às oportunidades</Link>} />
    <ConsultationState {...resource} hasData={!!resource.data}>{resource.data && <Card className="border-slate-200 shadow-sm"><CardHeader><CardTitle className="break-all font-mono text-base">{resource.data.colaborador_id_interno}</CardTitle></CardHeader><CardContent className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-3"><Field label="Marca" value={resource.data.marca} /><Field label="Chave de identidade" value={resource.data.chave_identidade} /><Field label="Usuário referência" value={resource.data.usuario_referencia || '—'} /><Field label="Nome referência" value={resource.data.nome_referencia || '—'} /><Field label="Nome normalizado" value={resource.data.nome_normalizado || '—'} /><Field label="Observações" value={formatNumber(resource.data.quantidade_observacoes)} /><Field label="Primeira observação" value={formatDateTime(resource.data.primeira_observacao_em)} /><Field label="Última observação" value={formatDateTime(resource.data.ultima_observacao_em)} /><ExecutionLink label="Primeira execução" id={resource.data.primeira_execucao_id} /><ExecutionLink label="Última execução" id={resource.data.ultima_execucao_id} /></CardContent></Card>}</ConsultationState>
  </>;
}

function Field({ label, value }: { label: string; value: string }) { return <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><p className="mt-1 break-all font-semibold text-slate-900">{value}</p></div>; }
function ExecutionLink({ label, id }: { label: string; id: string }) { return <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p><Link to={`/processamentos/${encodeURIComponent(id)}`} className="mt-1 block break-all font-mono text-blue-700 hover:underline">{id}</Link></div>; }
