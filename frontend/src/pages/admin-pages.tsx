import { useCallback, useState, type ReactNode } from 'react';
import {
  BookMarked,
  CalendarClock,
  Database,
  FileClock,
  ListChecks,
  RefreshCw,
  Route,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { PdohHeader } from '@/components/platform/pdoh-header';
import { usePdohResource } from '@/src/hooks/use-pdoh-resource';
import {
  loadOperationGovernance,
  type GovernanceTab,
  type OperationGovernance,
} from '@/src/services/governance-api';

const tabs: Array<{
  id: GovernanceTab;
  label: string;
  icon: typeof BookMarked;
}> = [
  { id: 'regras', label: 'Regras de negócio', icon: BookMarked },
  { id: 'jornada', label: 'Jornada', icon: CalendarClock },
  { id: 'fallback', label: 'Fallback', icon: Route },
  { id: 'fontes', label: 'Fontes', icon: Database },
  { id: 'tratativas', label: 'Tratativas', icon: ListChecks },
  { id: 'historico', label: 'Histórico', icon: FileClock },
];

function Badge({
  children,
  tone = 'slate',
}: {
  children: ReactNode;
  tone?: 'slate' | 'blue' | 'amber' | 'green';
}) {
  const colors = {
    slate: 'bg-slate-100 text-slate-700',
    blue: 'bg-blue-50 text-blue-700',
    amber: 'bg-amber-50 text-amber-800',
    green: 'bg-emerald-50 text-emerald-700',
  };
  return (
    <span
      className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${colors[tone]}`}
    >
      {children}
    </span>
  );
}

function RulesView({ data }: { data: OperationGovernance }) {
  return (
    <div className="space-y-4">
      {data.regras_governanca.map((rule) => (
        <Card key={rule.configuracao_id} className="border-slate-200 shadow-sm">
          <CardHeader className="border-b bg-slate-50/70">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <CardTitle>{rule.nome_regra}</CardTitle>
                <code className="mt-1 block text-xs text-slate-500">
                  {rule.codigo_interno}
                </code>
              </div>
              <div className="flex gap-2">
                <Badge tone="amber">{rule.status}</Badge>
                <Badge>Prioridade {rule.prioridade}</Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 pt-1 md:grid-cols-2">
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-slate-400">
                  Descrição
                </p>
                <p className="mt-1 text-sm text-slate-700">{rule.descricao}</p>
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-wide text-slate-400">
                  Comportamento esperado
                </p>
                <p className="mt-1 text-sm text-slate-700">
                  {rule.comportamento_esperado}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="blue">{rule.categoria}</Badge>
              <Badge tone={rule.geracao_automatica_ativa ? 'green' : 'slate'}>
                Geração automática:{' '}
                {rule.geracao_automatica_ativa ? 'ativa' : 'desativada'}
              </Badge>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">
                  Condições
                </p>
                <ul className="space-y-2">
                  {rule.condicoes.map((item) => (
                    <li
                      key={`${item.ordem}-${item.campo_logico}`}
                      className="rounded-lg border border-slate-200 p-3 text-xs"
                    >
                      <span className="font-semibold text-slate-900">
                        {item.papel_fonte}.{item.campo_logico}
                      </span>{' '}
                      <code className="ml-1 text-blue-700">
                        {item.operador}
                      </code>
                      <p className="mt-1 text-slate-500">{item.descricao}</p>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-400">
                  Exceções e bloqueios
                </p>
                <ul className="space-y-2">
                  {rule.excecoes.map((item) => (
                    <li
                      key={`${item.ordem}-${item.campo_logico}`}
                      className="rounded-lg border border-amber-100 bg-amber-50/40 p-3 text-xs"
                    >
                      <span className="font-semibold text-slate-900">
                        {item.descricao}
                      </span>
                      <p className="mt-1 text-slate-500">
                        {item.papel_fonte}.{item.campo_logico} · {item.operador}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function JourneyView({ data }: { data: OperationGovernance }) {
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader>
        <CardTitle>Ordem configurável de resolução</CardTitle>
        <p className="text-xs text-slate-500">
          Estrutura em validação. As etapas abaixo ainda não substituem o
          comportamento vigente.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Prioridade</TableHead>
              <TableHead>Origem</TableHead>
              <TableHead>Papel</TableHead>
              <TableHead>Fallback</TableHead>
              <TableHead>Uso atual</TableHead>
              <TableHead>Descrição</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.prioridade_jornada.map((step) => (
              <TableRow key={step.prioridade}>
                <TableCell className="font-bold">{step.prioridade}</TableCell>
                <TableCell>
                  <code className="text-xs">{step.origem_codigo}</code>
                </TableCell>
                <TableCell>{step.papel_fonte}</TableCell>
                <TableCell>{step.fallback ? 'Sim' : 'Não'}</TableCell>
                <TableCell>
                  <Badge
                    tone={step.aplicado_no_processamento ? 'green' : 'amber'}
                  >
                    {step.aplicado_no_processamento
                      ? 'Aplicado'
                      : 'Não aplicado'}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-md whitespace-normal text-slate-600">
                  {step.descricao}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function FallbackView({ data }: { data: OperationGovernance }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="border-slate-200 shadow-sm">
        <CardHeader>
          <CardTitle>Fallback vigente</CardTitle>
          <p className="text-xs text-slate-500">
            Configuração já existente, apenas para consulta.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.fallback.length ? (
            data.fallback.map((item) => (
              <div
                key={`${item.regra}-${item.escopo}-${item.chave}`}
                className="rounded-xl border p-4"
              >
                <div className="flex justify-between gap-3">
                  <strong>{item.regra}</strong>
                  <Badge tone="green">{item.status}</Badge>
                </div>
                <p className="mt-2 text-sm text-slate-600">
                  {item.chave}: <strong>{item.valor_fallback}</strong>
                </p>
                <p className="mt-1 text-xs text-slate-400">
                  {item.escopo} · desde {item.vigencia_inicio}
                </p>
              </div>
            ))
          ) : (
            <p className="text-sm text-slate-500">
              Nenhum fallback cadastrado.
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="border-slate-200 shadow-sm">
        <CardHeader>
          <CardTitle>Fallback de jornada proposto</CardTitle>
          <p className="text-xs text-slate-500">
            Nenhuma etapa está conectada ao processador nesta fase.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.prioridade_jornada
            .filter((step) => step.fallback)
            .map((step) => (
              <div
                key={step.prioridade}
                className="flex items-center gap-3 rounded-xl border p-4"
              >
                <span className="grid size-8 place-items-center rounded-full bg-blue-50 font-bold text-blue-700">
                  {step.prioridade}
                </span>
                <div>
                  <strong className="text-sm">{step.origem_codigo}</strong>
                  <p className="text-xs text-slate-500">{step.descricao}</p>
                </div>
              </div>
            ))}
        </CardContent>
      </Card>
    </div>
  );
}

function SourcesView({ data }: { data: OperationGovernance }) {
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader>
        <CardTitle>Mapeamento por papel semântico</CardTitle>
        <p className="text-xs text-slate-500">
          As regras apontam para o papel; o nome físico fica centralizado neste
          cadastro.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Papel</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Prioridade</TableHead>
              <TableHead>Fonte física</TableHead>
              <TableHead>Campos</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.fontes_semanticas.map((source) => (
              <TableRow key={`${source.papel}-${source.prioridade}`}>
                <TableCell className="font-bold">{source.papel}</TableCell>
                <TableCell>{source.tipo}</TableCell>
                <TableCell>{source.prioridade}</TableCell>
                <TableCell>
                  <code className="text-xs">
                    {source.tabela_fisica
                      ? `${source.schema_fisico}.${source.tabela_fisica}`
                      : 'Pendente'}
                  </code>
                </TableCell>
                <TableCell className="max-w-md whitespace-normal text-xs text-slate-500">
                  {Object.entries(source.mapeamento_campos)
                    .map(
                      ([logical, physical]) =>
                        `${logical} → ${String(physical)}`,
                    )
                    .join(' · ') || 'Pendente'}
                </TableCell>
                <TableCell>
                  <Badge tone={source.status === 'MAPEADA' ? 'green' : 'amber'}>
                    {source.status}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function TreatmentsView({ data }: { data: OperationGovernance }) {
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader>
        <CardTitle>Tratativas por resultado</CardTitle>
        <p className="text-xs text-slate-500">
          A intenção futura está cadastrada; a geração de oportunidade permanece
          desativada.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Regra</TableHead>
              <TableHead>Resultado</TableHead>
              <TableHead>Destino</TableHead>
              <TableHead>Ação recomendada</TableHead>
              <TableHead>Gera oportunidade</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.regras_governanca.flatMap((rule) =>
              rule.tratativas.map((treatment) => (
                <TableRow key={`${rule.codigo_interno}-${treatment.resultado}`}>
                  <TableCell>
                    <code className="text-xs">{rule.codigo_interno}</code>
                  </TableCell>
                  <TableCell>
                    <Badge
                      tone={
                        treatment.resultado === 'CONFIRMADO'
                          ? 'green'
                          : treatment.resultado === 'INDISPONIVEL'
                            ? 'amber'
                            : 'slate'
                      }
                    >
                      {treatment.resultado}
                    </Badge>
                  </TableCell>
                  <TableCell>{treatment.destino}</TableCell>
                  <TableCell className="max-w-md whitespace-normal text-slate-600">
                    {treatment.acao_recomendada}
                  </TableCell>
                  <TableCell>
                    <strong className="text-slate-600">
                      {treatment.gera_oportunidade ? 'Sim' : 'Não'}
                    </strong>
                  </TableCell>
                </TableRow>
              )),
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function HistoryView({ data }: { data: OperationGovernance }) {
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader>
        <CardTitle>Histórico de configuração</CardTitle>
        <p className="text-xs text-slate-500">
          Eventos de cadastro e alteração com usuário, data e motivo.
        </p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Data</TableHead>
              <TableHead>Entidade</TableHead>
              <TableHead>Referência</TableHead>
              <TableHead>Ação</TableHead>
              <TableHead>Usuário</TableHead>
              <TableHead>Motivo</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.historico_governanca.map((event) => (
              <TableRow key={event.id}>
                <TableCell className="text-xs">
                  {new Date(event.registrado_em).toLocaleString('pt-BR')}
                </TableCell>
                <TableCell>{event.entidade_tipo}</TableCell>
                <TableCell>
                  <code className="text-xs">
                    {event.codigo_referencia || '—'}
                  </code>
                </TableCell>
                <TableCell>
                  <Badge tone="blue">{event.acao}</Badge>
                </TableCell>
                <TableCell>{event.usuario}</TableCell>
                <TableCell className="max-w-md whitespace-normal text-slate-600">
                  {event.motivo}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function ConfigurationCenter({ initialTab }: { initialTab: GovernanceTab }) {
  const [tab, setTab] = useState<GovernanceTab>(initialTab);
  const loader = useCallback(
    (signal: AbortSignal) => loadOperationGovernance(signal),
    [],
  );
  const resource = usePdohResource('governanca-bracell-exclusiva', loader);
  return (
    <>
      <PdohHeader
        periodoInicio={null}
        periodoFim={null}
        semPeriodo
        updatedAt={resource.updatedAt}
        subtitulo="Configurações da operação"
      />
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-extrabold tracking-tight text-slate-950">
            Governança operacional
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-slate-500">
            Visão técnica de leitura da configuração BRACELL · EXCLUSIVA. Ativar
            regras e ajustar tempo, condição e exceções é feito em Configurações.
          </p>
        </div>
        {resource.data && (
          <div className="flex gap-2">
            <Badge tone="blue">
              {resource.data.regras_governanca.length} regras
            </Badge>
            <Badge>{resource.data.fontes_semanticas.length} fontes</Badge>
          </div>
        )}
      </div>
      <nav
        className="mb-5 flex gap-2 overflow-x-auto pb-1"
        aria-label="Áreas de configuração"
      >
        {tabs.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              aria-current={tab === item.id ? 'page' : undefined}
              className={`flex shrink-0 items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold ${tab === item.id ? 'bg-blue-700 text-white shadow-sm' : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}
            >
              <Icon className="size-4" />
              {item.label}
            </button>
          );
        })}
      </nav>
      {resource.loading && (
        <Card>
          <CardContent className="flex items-center gap-3 py-8 text-sm text-slate-500">
            <RefreshCw className="size-4 animate-spin" />
            Carregando configurações...
          </CardContent>
        </Card>
      )}
      {resource.error && (
        <Card className="border-red-200">
          <CardContent className="py-6 text-sm text-red-700">
            {resource.error}
            <button
              type="button"
              className="ml-3 font-bold underline"
              onClick={resource.retry}
            >
              Tentar novamente
            </button>
          </CardContent>
        </Card>
      )}
      {resource.data && tab === 'regras' && <RulesView data={resource.data} />}
      {resource.data && tab === 'jornada' && (
        <JourneyView data={resource.data} />
      )}
      {resource.data && tab === 'fallback' && (
        <FallbackView data={resource.data} />
      )}
      {resource.data && tab === 'fontes' && (
        <SourcesView data={resource.data} />
      )}
      {resource.data && tab === 'tratativas' && (
        <TreatmentsView data={resource.data} />
      )}
      {resource.data && tab === 'historico' && (
        <HistoryView data={resource.data} />
      )}
    </>
  );
}

export function GovernancePage() {
  return <ConfigurationCenter initialTab="historico" />;
}
