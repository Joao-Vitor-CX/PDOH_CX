import { useCallback } from 'react';
import { Database, ScrollText } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent } from '@/components/ui/card';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import { formatNumber } from '@/src/lib/pdoh-format';
import { apiRequest, mappingSchema, pageSchema, queryString, ruleSchema } from '@/src/services/pdoh-api';

export function CatalogSummary({ brand }: { brand?: string }) {
  const key = brand || 'global';
  const loader = useCallback(async (signal: AbortSignal) => {
    const marca = brand || undefined;
    const [rules, activeRules, mappings] = await Promise.all([
      apiRequest(`/regras${queryString({ marca, tamanho: 1 })}`, pageSchema(ruleSchema), signal),
      apiRequest(`/regras${queryString({ marca, status: 'ATIVA', tamanho: 1 })}`, pageSchema(ruleSchema), signal),
      apiRequest(`/de-para${queryString({ marca, tamanho: 1 })}`, pageSchema(mappingSchema), signal),
    ]);
    return { rules: rules.total, activeRules: activeRules.total, mappings: mappings.total };
  }, [brand]);
  const resource = usePdohResource(key, loader);
  return <section className="space-y-3" aria-label="Parametrizações cadastradas"><div><h3 className="text-sm font-bold text-slate-900">Parametrizações existentes</h3><p className="text-xs text-slate-500">Contagens obtidas dos catálogos da API; com marca selecionada, incluem registros globais.</p></div>
    {resource.error && <Alert variant="destructive"><AlertTitle>Falha na consulta das parametrizações</AlertTitle><AlertDescription>{resource.error}</AlertDescription></Alert>}
    <div className="grid gap-3 sm:grid-cols-3"><SummaryCard icon={ScrollText} label="Regras cadastradas" value={resource.data ? formatNumber(resource.data.rules) : '—'} loading={resource.loading} /><SummaryCard icon={ScrollText} label="Regras ativas" value={resource.data ? formatNumber(resource.data.activeRules) : '—'} loading={resource.loading} /><SummaryCard icon={Database} label="De/Para cadastrados" value={resource.data ? formatNumber(resource.data.mappings) : '—'} loading={resource.loading} /></div>
  </section>;
}

function SummaryCard({ icon: Icon, label, value, loading }: { icon: typeof Database; label: string; value: string; loading: boolean }) {
  return <Card className="border-slate-200 shadow-sm"><CardContent className="flex items-center justify-between p-4"><div><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-2xl font-bold text-slate-950">{loading ? 'Carregando…' : value}</p></div><Icon className="size-5 text-blue-600" /></CardContent></Card>;
}
