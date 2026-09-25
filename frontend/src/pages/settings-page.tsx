import { useCallback, useMemo, useState } from 'react';
import { FileClock, ListChecks, RefreshCw } from 'lucide-react';
import { CheckoutConfigurator, CheckoutRuleTable, HowItWorks, RuleEditor, formatDateTime } from '@/components/platform/rule-settings';
import { PdohHeader } from '@/components/platform/pdoh-header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useAuth } from '@/src/auth/auth-provider';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import {
  actorName,
  describeHistoryEvent,
  entityLabel,
  operatorLabels,
} from '@/src/lib/rule-settings';
import {
  loadOperationGovernance,
  type GovernanceRule,
  type OperationGovernance,
  type RuleCreateResult,
  type RuleEditResult,
} from '@/src/services/governance-api';

type SettingsTab = 'regras' | 'historico';

const tabs: Array<{ id: SettingsTab; label: string; icon: typeof ListChecks }> = [
  { id: 'regras', label: 'Regras de oportunidade', icon: ListChecks },
  { id: 'historico', label: 'Histórico', icon: FileClock },
];

function HistoryTab({ data }: { data: OperationGovernance }) {
  const labels = useMemo(() => operatorLabels(data.regras_governanca), [data.regras_governanca]);
  const names = useMemo(() => Object.fromEntries(data.regras_governanca.map((rule) => [rule.codigo_interno, rule.nome_regra])), [data.regras_governanca]);
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader>
        <CardTitle>Histórico de alterações</CardTitle>
        <p className="text-xs text-slate-500">Quem mudou o quê, quando e por quê. As 100 alterações mais recentes.</p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader><TableRow><TableHead>Data</TableHead><TableHead>Regra</TableHead><TableHead>O que mudou</TableHead><TableHead>Por</TableHead><TableHead>Motivo</TableHead></TableRow></TableHeader>
          <TableBody>
            {data.historico_governanca.map((event) => {
              const { title, details } = describeHistoryEvent(event, labels);
              return (
                <TableRow key={event.id}>
                  <TableCell className="text-xs whitespace-nowrap">{formatDateTime(event.registrado_em)}</TableCell>
                  <TableCell>
                    <span className="font-semibold text-slate-900">{names[event.codigo_referencia ?? ''] ?? entityLabel(event.entidade_tipo)}</span>
                    {event.codigo_referencia && <code className="block text-[11px] text-slate-400">{event.codigo_referencia}</code>}
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    <span className="text-sm font-medium text-slate-800">{title}</span>
                    {details.map((line) => <span key={line} className="block text-xs text-slate-600">{line}</span>)}
                  </TableCell>
                  <TableCell>{event.usuario}</TableCell>
                  <TableCell className="max-w-xs whitespace-normal text-slate-600">{event.motivo}</TableCell>
                </TableRow>
              );
            })}
            {!data.historico_governanca.length && <TableRow><TableCell colSpan={5} className="py-6 text-center text-slate-500">Nenhuma alteração registrada.</TableCell></TableRow>}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<SettingsTab>('regras');
  const [selected, setSelected] = useState<string | null>(null);
  const [configuringCheckout, setConfiguringCheckout] = useState(false);
  // O que o servidor devolveu ao salvar/criar aparece na hora; a releitura confirma em seguida.
  const [saved, setSaved] = useState<Record<string, GovernanceRule>>({});
  const loader = useCallback((signal: AbortSignal) => loadOperationGovernance(signal), []);
  const resource = usePdohResource('configuracoes-bracell-exclusiva', loader);
  const actor = actorName(user?.name, user?.email);

  const rules = useMemo(() => {
    const base = resource.data?.regras_governanca ?? [];
    const overridden = base.map((rule) => {
      const override = saved[rule.codigo_interno];
      return override && override.atualizado_em >= rule.atualizado_em ? override : rule;
    });
    const conhecidos = new Set(overridden.map((rule) => rule.codigo_interno));
    // Oportunidade recém-criada: ainda não veio na última leitura, mas o servidor já confirmou.
    const novas = Object.values(saved).filter((rule) => !conhecidos.has(rule.codigo_interno));
    return [...overridden, ...novas].sort((a, b) => a.prioridade - b.prioridade);
  }, [resource.data, saved]);
  const checkout = rules.find((rule) => rule.codigo_interno === 'CHECKOUT_AUSENTE') ?? null;
  const current = selected === 'CHECKOUT_AUSENTE' ? checkout : null;
  const currentHistory = useMemo(
    () => (resource.data?.historico_governanca ?? []).filter((event) => event.codigo_referencia === current?.codigo_interno),
    [resource.data, current],
  );
  const data = resource.data ? { ...resource.data, regras_governanca: rules } : null;

  function handleSaved(result: RuleEditResult) {
    setSaved((state) => ({ ...state, [result.regra.codigo_interno]: result.regra }));
    resource.retry();
  }

  function handleCreated(result: RuleCreateResult) {
    setSaved((state) => ({ ...state, [result.regra.codigo_interno]: result.regra }));
    setConfiguringCheckout(true);
    setSelected(result.regra.codigo_interno);
    resource.retry();
  }

  function configureCheckout() {
    setConfiguringCheckout(true);
    setSelected('CHECKOUT_AUSENTE');
  }

  function closeCheckout() {
    setConfiguringCheckout(false);
    setSelected(null);
  }

  return (
    <>
      <PdohHeader periodoInicio={null} periodoFim={null} semPeriodo updatedAt={resource.updatedAt} subtitulo="Configurações da operação" />
      <div className="mb-5">
        <h2 className="text-2xl font-extrabold tracking-tight text-slate-950">Configurações</h2>
        <p className="mt-1 max-w-3xl text-sm text-slate-500">Configure os horários esperados da oportunidade operacional de check-out ausente.</p>
        <p className="mt-1 max-w-3xl text-xs text-slate-400">
          A configuração define o horário esperado por jornada; o monitoramento real continua vindo da operação.
        </p>
      </div>
      <nav className="mb-5 flex gap-2 overflow-x-auto pb-1" aria-label="Áreas de configuração">
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <button key={item.id} type="button" onClick={() => setTab(item.id)} aria-current={tab === item.id ? 'page' : undefined}
              className={`flex shrink-0 items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold ${tab === item.id ? 'bg-blue-700 text-white shadow-sm' : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}>
              <Icon className="size-4" aria-hidden="true" />{item.label}
            </button>
          );
        })}
      </nav>

      {resource.loading && (
        <Card><CardContent className="flex items-center gap-3 py-8 text-sm text-slate-500"><RefreshCw className="size-4 animate-spin" />Carregando configurações...</CardContent></Card>
      )}
      {resource.error && (
        <Card className="border-red-200"><CardContent className="py-6 text-sm text-red-700">{resource.error}
          <button type="button" className="ml-3 font-bold underline" onClick={resource.retry}>Tentar novamente</button></CardContent></Card>
      )}
      {data && tab === 'regras' && (
        <div className="space-y-5">
          <CheckoutRuleTable rule={checkout} configuring={configuringCheckout} onConfigure={configureCheckout} />
          {configuringCheckout && (current ? (
            <RuleEditor key={current.codigo_interno} rule={current} actor={actor} history={currentHistory} onSaved={handleSaved} onClose={closeCheckout} />
          ) : (
            <CheckoutConfigurator journeys={data.jornadas_disponiveis} actor={actor} onCreated={handleCreated} onClose={closeCheckout} />
          ))}
          <HowItWorks />
        </div>
      )}
      {data && tab === 'historico' && <HistoryTab data={data} />}
    </>
  );
}
