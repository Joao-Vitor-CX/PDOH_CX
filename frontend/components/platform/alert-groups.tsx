import { useCallback } from 'react';
import { Link } from 'react-router-dom';
import { z } from 'zod';
import { ConsultationState, StatusBadge } from './consultation-ui';
import { FilterField, Pagination } from './query-controls';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { apiRequest, alertGroupSchema, pageSchema, opportunitySchema, queryString } from '@/src/services/pdoh-api';
import { formatNumber, formatDate } from '@/src/lib/pdoh-format';
import { opportunityName, recordLabel } from '@/src/lib/opportunity-presentation';

const alertPage = pageSchema(alertGroupSchema).extend({ total_ocorrencias: z.number().int(), unidade: z.string() });
function useAlerts(query: string) {
  const loader = useCallback((signal: AbortSignal) => apiRequest(`/alertas${query}`, alertPage, signal), [query]);
  return usePdohResource(query, loader);
}
function AlertRecords({ group, query, page, onPage }: { group: string; query: string; page: number; onPage: (page: number) => void }) {
  const path = `/alertas/${encodeURIComponent(group)}/registros${query}`;
  const loader = useCallback((signal: AbortSignal) => apiRequest(path, pageSchema(opportunitySchema), signal), [path]);
  const resource = usePdohResource(path, loader);
  return <ConsultationState {...resource} hasData={!!resource.data}>{resource.data && <>
    <p className="text-sm text-slate-500">{formatNumber(resource.data.total)} registros no grupo, incluindo repetições entre execuções.</p>
    <div className="divide-y rounded-xl border bg-white">{resource.data.items.map(item => <Link key={item.oportunidade_id} className="flex min-h-14 items-center justify-between gap-3 p-4" to={`/oportunidades/${item.oportunidade_id}`}><span className="min-w-0 break-words"><strong>{opportunityName(item.tipo_problema)}</strong><span className="block text-xs text-slate-500">{recordLabel(item)} · {formatDate(item.data_referencia)}</span></span><StatusBadge value={item.status_oportunidade} /></Link>)}</div>
    {!resource.data.items.length && <p>Nenhum registro neste grupo para os filtros atuais.</p>}
    <Pagination page={page} pages={resource.data.paginas} label="Registros do alerta" onPage={onPage} />
  </>}</ConsultationState>;
}
export function AlertGroups({ filters, search, setSearch }: { filters: Record<string, string>; search: URLSearchParams; setSearch: (value: URLSearchParams) => void }) {
  const page = Math.max(1, Math.floor(Number(search.get('pagina')) || 1));
  const field = search.get('campo_alerta') || '';
  const group = search.get('alerta') || '';
  const query = queryString({ ...filters, campo: field, pagina: page, tamanho: 20 });
  const resource = useAlerts(query);
  const update = (key: string, value: string) => { const next = new URLSearchParams(search); if(value)next.set(key,value);else next.delete(key);if(key !== 'pagina')next.delete('pagina');setSearch(next); };
  return <section aria-label="Alertas consolidados" className="space-y-4">
    <div><h2 className="text-lg font-bold">Qualidade cadastral e operacional</h2><p className="mt-1 text-sm text-slate-500">Somente classificação ALERTA. Consolidação completa no filtro, não apenas na página. Cada ocorrência é um registro persistido.</p></div>
    <FilterField label="Campo do alerta" value={field} onChange={value=>{const next=new URLSearchParams(search);if(value)next.set('campo_alerta',value);else next.delete('campo_alerta');next.delete('pagina');next.delete('alerta');setSearch(next);}} />
    {group ? <><button className="min-h-11 font-semibold text-blue-700" onClick={()=>update('alerta','')}>← Voltar aos alertas consolidados</button><AlertRecords group={group} query={query} page={page} onPage={value=>update('pagina',String(value))} /></> : <ConsultationState {...resource} hasData={!!resource.data}>{resource.data && <>
      <p className="text-sm text-slate-600">{formatNumber(resource.data.total_ocorrencias)} ocorrências em {formatNumber(resource.data.total)} referências consolidadas.</p>
      <div className="grid items-start gap-4 lg:grid-cols-2">{resource.data.items.map(item=><article key={item.chave_grupo} className="min-w-0 rounded-xl border bg-white p-4">
        <h3 className="break-words font-bold">{item.colaborador || (item.criterio_agrupamento==='REGISTRO_ORIGEM' ? `Registro ${item.referencia}` : 'Sem colaborador identificado')}</h3>
        <p className="mt-1 text-xs text-slate-500">{item.marca} · {formatDate(item.primeira_data)} a {formatDate(item.ultima_data)}</p>
        {item.criterio_agrupamento==='NOME_FONTE_NAO_CONFIRMADO' && <p className="mt-2 text-xs text-amber-800">Referência por nome e fonte; sem ID confirmado, pode reunir homônimos. Não representa pessoa única.</p>}
        {item.criterio_agrupamento==='REGISTRO_SEM_IDENTIDADE' && <p className="mt-2 text-xs text-amber-800">Sem chave estável para consolidar com outros registros.</p>}
        <p className="my-3 text-sm font-semibold">{formatNumber(item.quantidade_ocorrencias)} ocorrências</p>
        <ul className="space-y-2">{item.campos.map(campo=><li key={JSON.stringify([campo.campo,campo.tipo])} className="flex justify-between gap-3 rounded-lg bg-slate-50 p-3 text-sm"><span className="min-w-0 break-words"><strong>{campo.campo}</strong><span className="block text-xs text-slate-500">{opportunityName(campo.tipo)}</span></span><strong>{formatNumber(campo.quantidade_ocorrencias)}</strong></li>)}</ul>
        <button className="mt-3 min-h-11 text-sm font-semibold text-blue-700" onClick={()=>update('alerta',item.chave_grupo)}>Conferir registros e evidências →</button>
      </article>)}</div>
      {!resource.data.items.length && <p className="rounded-xl border bg-white p-6 text-sm">Nenhum alerta para os filtros informados.</p>}
      <Pagination page={page} pages={resource.data.paginas} label="Alertas consolidados" onPage={value=>update('pagina',String(value))} />
    </>}</ConsultationState>}
    <p className="text-xs text-slate-500">Um registro pode envolver mais de um campo. Os totais por campo não devem ser somados para obter pessoas ou registros únicos. Para volumes acima de 100 mil registros, refine marca, período ou execução.</p>
  </section>;
}
