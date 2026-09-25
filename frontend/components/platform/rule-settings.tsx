import { useId, useMemo, useState, type ReactNode } from 'react';
import { ArrowRight, CheckCircle2, Info, Lock, Plus, Search, Settings2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  MOTIVO_MINIMO,
  buildCreatePayload,
  buildRuleEdit,
  calcularPreviaJornada,
  confirmedTreatment,
  creationOutcomeText,
  describeHistoryEvent,
  draftFromRule,
  emptyCreateDraft,
  fieldOptionLabel,
  formatarDuracao,
  operatorLabels,
  operatorsForDraft,
  otherConditions,
  outcomeText,
  papelCampoKey,
  principalCondition,
  scheduleDrafts,
  statusInfo,
  validateCreateDraft,
  validateDraft,
  validSchedules,
  scheduleEditableFields,
  scheduleNotice,
  type CreateDraft,
  type DefaultJourney,
  type RuleDraft,
} from '@/src/lib/rule-settings';
import {
  createRule, updateRule, type AvailableField, type GovernanceCondition, type GovernanceHistoryEvent,
  type GovernanceRule, type RuleCreateResult, type RuleEditResult, type ScheduleEdit,
} from '@/src/services/governance-api';

const TONES = {
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  slate: 'bg-slate-100 text-slate-600 ring-slate-200',
  blue: 'bg-blue-50 text-blue-700 ring-blue-200',
} as const;

const CHECKOUT_CODE = 'CHECKOUT_AUSENTE';
const CHECKOUT_NAME = 'Check-out ausente';
const CHECKOUT_DESCRIPTION = 'Identifica colaboradores que não registraram check-out no sistema dentro da jornada configurada.';
// Configuração operacional (jornada) não expõe o campo "motivo" ao usuário: o motivo é
// registrado automaticamente, do mesmo jeito que a criação já faz no servidor.
const CHECKOUT_MOTIVO_CRIACAO = 'Oportunidade criada pela tela de Configurações.';
const CHECKOUT_MOTIVO_EDICAO = 'Configuração de jornada atualizada pela tela de Configurações.';
const INTERVALO_PADRAO = '01:00';

export function Pill({ tone = 'slate', children }: { tone?: keyof typeof TONES; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold ring-1 ring-inset ${TONES[tone]}`}>{children}</span>;
}

export const formatDateTime = (value: string) =>
  new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value));

function Label({ htmlFor, children }: { htmlFor?: string; children: ReactNode }) {
  return <label htmlFor={htmlFor} className="mb-1.5 block text-xs font-bold uppercase tracking-wide text-slate-500">{children}</label>;
}

function FieldError({ id, message }: { id: string; message?: string }) {
  return message ? <p id={id} role="alert" className="mt-1 text-xs font-medium text-red-700">{message}</p> : null;
}

/** Escolha entre duas opções (Sim/Não, Ativa/Inativa) com o estado sempre visível. */
function Segmented({ name, label, value, onChange, options, disabled }: {
  name: string; label: string; value: boolean; onChange: (value: boolean) => void; disabled?: boolean;
  options: [string, string];
}) {
  return (
    <fieldset className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5">
      <legend className="sr-only">{label}</legend>
      {([true, false] as const).map((option) => (
        <label
          key={String(option)}
          className={`min-w-16 cursor-pointer rounded-md px-3 py-1.5 text-center text-sm font-semibold transition has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-50 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-blue-500 ${value === option
            ? option ? 'bg-emerald-600 text-white shadow-sm' : 'bg-slate-700 text-white shadow-sm'
            : 'text-slate-600 hover:bg-white'}`}
        >
          <input type="radio" name={name} className="sr-only" checked={value === option} disabled={disabled} onChange={() => onChange(option)} />
          {option ? options[0] : options[1]}
        </label>
      ))}
    </fieldset>
  );
}

// ---------------------------------------------------------------------------- tabela
export function CheckoutRuleTable({ rule, configuring, onConfigure }: {
  rule: GovernanceRule | null; configuring: boolean; onConfigure: () => void;
}) {
  const status = rule ? statusInfo(rule) : null;
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader className="border-b">
        <CardTitle>Oportunidade configurável</CardTitle>
        <p className="mt-1 text-sm text-slate-500">Defina as jornadas e os horários esperados para identificar a ausência de check-out.</p>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nome</TableHead>
              <TableHead>Código</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Prioridade</TableHead>
              <TableHead>Marca</TableHead>
              <TableHead className="w-24 text-center">Ação</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow data-state={configuring ? 'selected' : undefined} className={configuring ? 'bg-blue-50/70' : ''}>
              <TableCell className="font-semibold text-slate-900">{CHECKOUT_NAME}</TableCell>
              <TableCell><code className="text-xs text-slate-500">{CHECKOUT_CODE}</code></TableCell>
              <TableCell>
                {status
                  ? <span title={status.detail}><Pill tone={status.tone}>{status.label}</Pill></span>
                  : <Pill>Não configurada</Pill>}
              </TableCell>
              <TableCell>{rule?.prioridade ?? 1}</TableCell>
              <TableCell>BRACELL</TableCell>
              <TableCell className="text-center">
                <Button type="button" variant="ghost" size="icon-sm" onClick={onConfigure}
                  aria-label="Configurar Check-out ausente" aria-pressed={configuring} title="Configurar oportunidade">
                  <Settings2 className="size-4" aria-hidden="true" />
                </Button>
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export function RulesTable({ rules, selected, creating, onSelect, onCreate }: {
  rules: GovernanceRule[]; selected: string | null; creating: boolean;
  onSelect: (code: string) => void; onCreate: () => void;
}) {
  const [query, setQuery] = useState('');
  const visible = useMemo(() => {
    const term = query.trim().toLowerCase();
    return term ? rules.filter((rule) => `${rule.nome_regra} ${rule.codigo_interno}`.toLowerCase().includes(term)) : rules;
  }, [rules, query]);
  const active = rules.filter((rule) => rule.ativa).length;
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>Regras de oportunidade</CardTitle>
            <p className="mt-1 text-sm text-slate-500">Cadastre e gerencie as oportunidades que o sistema deve procurar.</p>
            {rules.length > 0 && (
              <p className="mt-1.5 text-xs text-slate-500">
                {rules.length} cadastrada{rules.length === 1 ? '' : 's'} · <strong className="text-slate-700">{active} ativa{active === 1 ? '' : 's'}</strong>. Sem regra ativa, nenhuma oportunidade é criada.
              </p>
            )}
          </div>
          <Button type="button" onClick={onCreate} aria-pressed={creating}>
            <Plus className="size-4" aria-hidden="true" />
            Nova oportunidade
          </Button>
        </div>
        {rules.length > 0 && (
          <div className="relative mt-3 w-full sm:w-64">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-slate-400" aria-hidden="true" />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar oportunidade..." aria-label="Buscar oportunidade" className="pl-8" />
          </div>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {rules.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <p className="text-sm font-medium text-slate-700">Apenas oportunidades configuradas são exibidas.</p>
            <p className="mt-1 text-sm text-slate-500">
              Para adicionar uma nova oportunidade, clique em{' '}
              <button type="button" onClick={onCreate} className="font-semibold text-blue-700 hover:underline">Nova oportunidade</button>.
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nome da oportunidade</TableHead>
                <TableHead>Código</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Prioridade</TableHead>
                <TableHead>Marca</TableHead>
                <TableHead>Última alteração</TableHead>
                <TableHead>Ações</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((rule) => {
                const status = statusInfo(rule);
                const isSelected = !creating && selected === rule.codigo_interno;
                return (
                  <TableRow
                    key={rule.codigo_interno}
                    data-state={isSelected ? 'selected' : undefined}
                    onClick={() => onSelect(rule.codigo_interno)}
                    className={`cursor-pointer ${isSelected ? 'bg-blue-50/70' : ''}`}
                  >
                    <TableCell className="font-semibold text-slate-900">
                      <button type="button" onClick={(event) => { event.stopPropagation(); onSelect(rule.codigo_interno); }}
                        aria-pressed={isSelected} className="text-left hover:underline focus-visible:underline">
                        {rule.nome_regra}
                      </button>
                    </TableCell>
                    <TableCell><code className="text-xs text-slate-500">{rule.codigo_interno}</code></TableCell>
                    <TableCell><span title={status.detail}><Pill tone={status.tone}>{status.label}</Pill></span></TableCell>
                    <TableCell>{rule.prioridade}</TableCell>
                    <TableCell>BRACELL</TableCell>
                    <TableCell className="text-xs text-slate-500">{formatDateTime(rule.atualizado_em)}</TableCell>
                    <TableCell>
                      <button type="button" onClick={(event) => { event.stopPropagation(); onSelect(rule.codigo_interno); }}
                        className="text-sm font-semibold text-blue-700 hover:underline">
                        Editar
                      </button>
                    </TableCell>
                  </TableRow>
                );
              })}
              {!visible.length && (
                <TableRow><TableCell colSpan={7} className="py-8 text-center text-sm text-slate-500">Nenhuma oportunidade encontrada.</TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------- como funciona
const STEPS = [
  ['Configuração', 'A regra diz o que o sistema deve procurar.'],
  ['Regra ativa', 'Só regras ativas entram na análise. Sem regra, nada é criado.'],
  ['Motor valida', 'O motor compara os dados da fonte com a condição e as exceções.'],
  ['Oportunidade criada', 'Critérios atendidos: a oportunidade nasce com a regra aplicada registrada.'],
] as const;

export function HowItWorks() {
  return (
    <Card className="border-slate-200 shadow-sm">
      <CardHeader><CardTitle className="flex items-center gap-2"><Info className="size-4 text-blue-700" aria-hidden="true" />Como funciona?</CardTitle></CardHeader>
      <CardContent>
        <ol className="grid gap-3 md:grid-cols-4">
          {STEPS.map(([title, text], index) => (
            <li key={title} className="relative rounded-xl border border-slate-200 bg-slate-50/60 p-3">
              <span className="mb-2 grid size-6 place-items-center rounded-full bg-blue-700 text-xs font-bold text-white">{index + 1}</span>
              <p className="text-sm font-bold text-slate-900">{title}</p>
              <p className="mt-1 text-xs text-slate-600">{text}</p>
              {index < STEPS.length - 1 && <ArrowRight className="absolute top-1/2 -right-2.5 hidden size-4 -translate-y-1/2 text-slate-300 md:block" aria-hidden="true" />}
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-slate-500">Mudanças valem para os próximos processamentos. Oportunidades já criadas permanecem no histórico.</p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------- edição
/** Prévia visual (Saída - Entrada - Intervalo). Não é o cálculo oficial do PDOH. */
function CalculoPrevia({ entrada, saida, intervalo }: { entrada: string | null; saida: string | null; intervalo: string }) {
  const previa = calcularPreviaJornada(entrada, saida, intervalo);
  if (!previa) return null;
  return (
    <div className="mt-3 rounded-lg border border-blue-100 bg-blue-50/60 p-3 text-xs text-blue-950">
      <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Prévia do cálculo</p>
      <div className="mt-1.5 grid grid-cols-3 gap-2">
        <div><span className="block text-slate-500">Entrada</span><strong className="text-slate-800">{entrada}</strong></div>
        <div><span className="block text-slate-500">Saída</span><strong className="text-slate-800">{saida}</strong></div>
        <div><span className="block text-slate-500">Intervalo</span><strong className="text-slate-800">{intervalo || 'não informado'}</strong></div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <div><span className="block text-slate-500">Tempo bruto</span><strong className="text-slate-900">{formatarDuracao(previa.brutoMin)}</strong></div>
        <div><span className="block text-slate-500">Tempo líquido</span><strong className="text-slate-900">{formatarDuracao(previa.liquidoMin)}</strong></div>
      </div>
      <p className="mt-2 text-[11px] text-blue-900/70">Saída − Entrada − Intervalo = Tempo líquido. Apenas uma prévia: não altera o cálculo oficial do PDOH nem substitui a jornada oficial.</p>
    </div>
  );
}

function ScheduleFields({ items, onChange, padrao = null }: {
  items: ScheduleEdit[]; available: GovernanceRule['jornadas']; onChange: (items: ScheduleEdit[]) => void;
  padrao?: DefaultJourney | null;
}) {
  const fieldId = useId();
  const [selectedIndex, setSelectedIndex] = useState(0);
  const selected = Math.min(selectedIndex, Math.max(0, items.length - 1));
  function adicionarJornada() {
    onChange([...items, { jornada: 0, nome_jornada: '', origem_configuracao: 'MANUAL',
      intervalo: INTERVALO_PADRAO, ativo: true, hora_entrada_padrao: null, hora_saida_padrao: null }]);
    setSelectedIndex(items.length);
  }
  return <fieldset className="space-y-3">
    <legend className="mb-1 text-sm font-bold text-slate-800">Horários esperados por jornada</legend>
    <p className="text-xs text-slate-500">As jornadas da operação vêm do cadastro: nome e carga semanal são fixos, mas você configura entrada, saída, intervalo e se a jornada está ativa. Você também pode adicionar jornadas manuais. Isso define o horário esperado da oportunidade CHECKOUT_AUSENTE; não cria regras nem altera os registros reais do Involves.</p>
    {items.length > 0 && <label htmlFor={`${fieldId}-selecao`} className="block text-sm font-semibold text-slate-800">
      Jornada
      <NativeSelect id={`${fieldId}-selecao`} value={String(selected)} onChange={(event) => setSelectedIndex(Number(event.target.value))}>
        {items.map((item, index) => <NativeSelectOption key={item.id ?? index} value={String(index)}>
          {item.nome_jornada || (item.jornada ? `Jornada ${item.jornada}H` : 'Nova jornada manual')}{item.origem_configuracao === 'MANUAL' ? ' · Manual' : ' · Operação'}
          {!item.hora_entrada_padrao || !item.hora_saida_padrao ? ' · sem horário' : item.ativo ? ' · ativa' : ''}
        </NativeSelectOption>)}
      </NativeSelect>
    </label>}
    {items.map((item, index) => {
      if (index !== selected) return null;
      const manual = item.origem_configuracao === 'MANUAL';
      const editaveis = new Set<string>(scheduleEditableFields(item));
      const pode = (campo: string) => editaveis.has(campo);
      const change = (patch: Partial<ScheduleEdit>) => onChange(items.map((s, i) => i === index ? { ...s, ...patch } : s));
      const intervalo = item.intervalo ?? '';
      const aviso = scheduleNotice(item, padrao);
      const duplicate = items.some((s, i) => i !== index && s.jornada === item.jornada && item.jornada > 0);
      return <div key={item.id ?? index} className="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Checkbox checked={item.ativo} disabled={!pode('ativo')} onCheckedChange={(v) => change({ ativo: v === true })} />
            {item.nome_jornada || (manual ? 'Nova jornada' : `Jornada ${item.jornada}h`)} · {item.ativo ? 'ativa' : 'inativa'}
          </label>
          <span className={manual ? 'text-xs text-blue-700' : 'text-xs text-slate-500'}>{manual ? 'Origem: Manual · editável' : 'Origem: Operação · horários configuráveis'}</span>
          {manual && !item.id && <Button type="button" variant="ghost" size="sm" onClick={() => onChange(items.filter((_, i) => i !== index))}>Remover</Button>}
        </div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-slate-600" htmlFor={`${fieldId}-${index}-nome`}>Nome da jornada{!pode('nome_jornada') && ' (do cadastro)'}<Input id={`${fieldId}-${index}-nome`} required={manual} maxLength={120} readOnly={!pode('nome_jornada')} value={item.nome_jornada ?? `Jornada ${item.jornada}h`} onChange={(e) => change({ nome_jornada: e.target.value })} /></label>
          <label className="text-xs text-slate-600" htmlFor={`${fieldId}-${index}-carga`}>Carga semanal (horas){!pode('jornada') && ' (do cadastro)'}<Input id={`${fieldId}-${index}-carga`} type="number" min="0.01" max="168" step="0.01" required={manual} readOnly={!pode('jornada')} value={item.jornada || ''} onChange={(e) => change({ jornada: Number(e.target.value) })} /></label>
        </div>
        {duplicate && <p role="alert" className="mt-2 text-xs text-red-700">Já existe uma jornada com esta carga semanal.</p>}
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <label htmlFor={`${fieldId}-${index}-entrada`} className="text-xs text-slate-600">Entrada padrão<Input id={`${fieldId}-${index}-entrada`} type="time" required={manual || item.ativo} readOnly={!pode('hora_entrada_padrao')} value={item.hora_entrada_padrao ?? ''} onChange={(e) => change({ hora_entrada_padrao: e.target.value || null })} className="mt-1 bg-white" /></label>
          <label htmlFor={`${fieldId}-${index}-saida`} className="text-xs text-slate-600">Saída padrão<Input id={`${fieldId}-${index}-saida`} type="time" required={manual || item.ativo} readOnly={!pode('hora_saida_padrao')} value={item.hora_saida_padrao ?? ''} onChange={(e) => change({ hora_saida_padrao: e.target.value || null })} className="mt-1 bg-white" /></label>
          <label htmlFor={`${fieldId}-${index}-intervalo`} className="text-xs text-slate-600">Intervalo{!manual && ' (opcional)'}<Input id={`${fieldId}-${index}-intervalo`} type="time" required={manual} readOnly={!pode('intervalo')} value={intervalo} onChange={(e) => change({ intervalo: e.target.value || null })} className="mt-1 bg-white" /></label>
        </div>
        {aviso && <div role={aviso.tom === 'atencao' ? 'alert' : 'status'} className={`mt-2 rounded-lg border p-2 text-xs ${aviso.tom === 'atencao' ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-slate-200 bg-white text-slate-600'}`}>
          <p className="font-semibold">{aviso.texto}</p>
          <p className="mt-0.5">{aviso.acao}</p>
          {aviso.fallback && <p className="mt-1 text-[11px] opacity-80">{aviso.fallback}</p>}
        </div>}
        {item.hora_entrada_padrao && item.hora_saida_padrao && <CalculoPrevia entrada={item.hora_entrada_padrao} saida={item.hora_saida_padrao} intervalo={intervalo} />}
      </div>;
    })}
    <p className="text-xs text-slate-500">Saída anterior à entrada representa término no dia seguinte. Nome, carga semanal, entrada, saída e intervalo são obrigatórios para jornadas manuais; jornada ativa sempre exige entrada e saída.</p>
    <Button type="button" variant="outline" size="sm" onClick={adicionarJornada}>
      <Plus className="size-3.5" aria-hidden="true" />Adicionar jornada
    </Button>
  </fieldset>;
}

export function RuleEditor({ rule, actor, history, onSaved, onClose }: {
  rule: GovernanceRule; actor: string; history: GovernanceHistoryEvent[];
  onSaved: (result: RuleEditResult) => void; onClose: () => void;
}) {
  const base = useMemo(() => draftFromRule(rule), [rule]);
  const [edits, setEdits] = useState<Partial<RuleDraft>>({});
  const [exceptionEdits, setExceptionEdits] = useState<Record<number, boolean>>({});
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const draft: RuleDraft = { ...base, ...edits, excecoes: { ...base.excecoes, ...exceptionEdits } };
  const change = (patch: Partial<RuleDraft>) => { setEdits((current) => ({ ...current, ...patch })); setNotice(null); };
  const body = buildRuleEdit(rule, draft);
  const errors = validateDraft(rule, draft);
  const operational = rule.modelo_configuracao === 'JORNADA';
  // Configuração operacional (jornada) não pede motivo ao usuário: fica registrado automaticamente.
  const reasonOk = operational || reason.trim().length >= MOTIVO_MINIMO;
  const canSave = Boolean(body) && Object.keys(errors).length === 0 && reasonOk && !saving;
  const main = principalCondition(rule);
  const others = otherConditions(rule);
  const treatment = confirmedTreatment(rule);
  const needsValue = draft.operador !== 'IS NULL' && draft.operador !== 'IS NOT NULL';
  const labels = useMemo(() => operatorLabels([rule]), [rule]);

  async function save() {
    if (!body || !canSave) return;
    setSaving(true);
    setError(null);
    try {
      const motivo = operational ? CHECKOUT_MOTIVO_EDICAO : reason.trim();
      const result = await updateRule(rule.codigo_interno, { ...body, usuario: actor, motivo });
      setEdits({});
      setExceptionEdits({});
      setReason('');
      setNotice(result.alterado ? 'Regra atualizada. Vale para os próximos processamentos.' : 'Nada mudou: a regra já estava assim.');
      onSaved(result);
    } catch (reasonError) {
      setError(reasonError instanceof Error ? reasonError.message : 'Não foi possível salvar a alteração.');
    } finally {
      setSaving(false);
    }
  }

  function cancel() {
    setEdits({});
    setExceptionEdits({});
    setReason('');
    setError(null);
    setNotice(null);
  }

  const id = (name: string) => `regra-${rule.codigo_interno}-${name}`;
  const status = statusInfo(rule);

  const headerInner = (
    <div className="min-w-0">
      <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">{operational ? 'Oportunidade operacional' : 'Editar oportunidade'}</p>
      {operational
        ? <DialogTitle className="mt-0.5 truncate text-xl font-bold text-slate-950">Configurar oportunidade</DialogTitle>
        : <CardTitle className="mt-0.5 truncate">{rule.nome_regra}</CardTitle>}
      {!operational && <div className="mt-1 flex items-center gap-2">
          <code className="text-xs text-slate-500">{rule.codigo_interno}</code>
          <Pill tone={status.tone}>{status.label}</Pill>
        </div>}
    </div>
  );

  const configuracaoTab = operational ? (
    <>
      <div className="grid grid-cols-2 gap-4">
        <div className="col-span-2">
          <Label>Nome da oportunidade</Label>
          <p className="rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm font-semibold text-slate-900">{CHECKOUT_NAME}</p>
        </div>
        <div className="col-span-2">
          <Label>Descrição</Label>
          <p className="rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700">{CHECKOUT_DESCRIPTION}</p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 p-4">
        <p className="mb-3 text-sm font-bold text-slate-900">Configuração de jornada</p>
        <ScheduleFields items={draft.jornadas ?? []} available={rule.jornadas} padrao={rule.jornada_padrao} onChange={(jornadas) => change({ jornadas })} />
        <FieldError id={id('jornadas-erro')} message={errors.jornadas} />
      </div>
    </>
  ) : (
    <>
      <div>
        <Label htmlFor={id('nome')}>Nome da oportunidade</Label>
        <Input id={id('nome')} value={draft.nome} onChange={(event) => change({ nome: event.target.value })} aria-invalid={Boolean(errors.nome)} aria-describedby={id('nome-erro')} />
        <FieldError id={id('nome-erro')} message={errors.nome} />
      </div>
      <div>
        <Label htmlFor={id('descricao')}>Descrição</Label>
        <Textarea id={id('descricao')} value={draft.descricao} onChange={(event) => change({ descricao: event.target.value })} aria-invalid={Boolean(errors.descricao)} className="min-h-20" />
        <FieldError id={id('descricao-erro')} message={errors.descricao} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label>Gerar oportunidade</Label>
          <Segmented name={id('gerar')} label="Gerar oportunidade" value={draft.gerar} onChange={(gerar) => change({ gerar })} options={['Sim', 'Não']} disabled={!treatment} />
        </div>
        <div>
          <Label htmlFor={id('tempo')}>Tempo mínimo</Label>
          <div className="flex items-center gap-2">
            <Input id={id('tempo')} inputMode="numeric" value={draft.tempo} onChange={(event) => change({ tempo: event.target.value })} aria-invalid={Boolean(errors.tempo)} aria-describedby={id('tempo-erro')} className="w-20" />
            <span className="text-sm text-slate-500">minutos</span>
          </div>
          <FieldError id={id('tempo-erro')} message={errors.tempo} />
        </div>
        <div>
          <Label>Marca</Label>
          <p className="flex items-center gap-1.5 rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700"><Lock className="size-3 text-slate-400" aria-hidden="true" />BRACELL</p>
        </div>
        <div>
          <Label>Operação</Label>
          <p className="flex items-center gap-1.5 rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700"><Lock className="size-3 text-slate-400" aria-hidden="true" />EXCLUSIVA</p>
        </div>
      </div>

      <div>
        <Label>Status</Label>
        <Segmented name={id('status')} label="Status da regra" value={draft.ativa} onChange={(ativa) => change({ ativa })} options={['Ativa', 'Inativa']} />
      </div>

      {rule.fonte && (
        <div className="rounded-lg border border-slate-200 bg-slate-50/70 p-3 text-xs text-slate-600">
          <p className="font-bold uppercase tracking-wide text-slate-500">Fonte dos dados</p>
          <p className="mt-1"><strong className="text-slate-800">{rule.fonte.rotulo}</strong>{rule.fonte.tabela ? <> · <code>{rule.fonte.tabela}</code></> : ' · fonte não mapeada'}</p>
          {rule.fonte.campo_rotulo && <p className="mt-0.5">Campo analisado: {rule.fonte.campo_rotulo}</p>}
        </div>
      )}

      <fieldset>
        <legend className="mb-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">Condição</legend>
        {main ? (
          <div className="grid grid-cols-[1fr_1fr_0.8fr] items-start gap-2">
            <div>
              <p className="text-[11px] font-semibold text-slate-400">Campo</p>
              <p className="mt-1 rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-800">{main.campo_rotulo ?? main.campo_logico}</p>
            </div>
            <div>
              <label htmlFor={id('operador')} className="text-[11px] font-semibold text-slate-400">Regra</label>
              <NativeSelect id={id('operador')} className="mt-1 w-full" value={draft.operador} disabled={!main.editavel} onChange={(event) => change({ operador: event.target.value })}>
                {main.operadores.map((option) => <NativeSelectOption key={option.codigo} value={option.codigo}>{option.rotulo}</NativeSelectOption>)}
              </NativeSelect>
            </div>
            <div>
              <label htmlFor={id('valor')} className="text-[11px] font-semibold text-slate-400">Valor</label>
              <Input id={id('valor')} className="mt-1" value={needsValue ? draft.valor : ''} disabled={!main.editavel || !needsValue} onChange={(event) => change({ valor: event.target.value })} aria-invalid={Boolean(errors.valor)} aria-describedby={id('valor-erro')} />
            </div>
          </div>
        ) : <p className="text-sm text-slate-500">Regra sem condição cadastrada.</p>}
        <FieldError id={id('valor-erro')} message={errors.valor} />
        {main && !main.editavel && <p className="mt-1.5 text-xs text-slate-500">Esta condição é avaliada pelo detector da regra e não pode ser editada aqui.</p>}
        {others.length > 0 && (
          <ul className="mt-2 space-y-1 text-xs text-slate-600">
            {others.map((item) => <li key={`${item.ordem}-${item.campo_logico}`} className="rounded-md bg-slate-50 px-2 py-1">e também: {item.texto ?? item.descricao}</li>)}
          </ul>
        )}
      </fieldset>

      <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-3 text-sm text-blue-950">
        <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Resultado</p>
        <p className="mt-1">{outcomeText(rule, draft)}</p>
        {treatment && <p className="mt-1.5 text-xs text-blue-900/80">Ação recomendada: {treatment.acao_recomendada}</p>}
      </div>
    </>
  );

  const historicoTab = (
    history.length ? (
      <ul className="space-y-3">
        {history.map((event) => {
          const { title, details } = describeHistoryEvent(event, labels);
          return (
            <li key={event.id} className="rounded-lg border border-slate-200 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <strong className="text-slate-900">{title}</strong>
                <span className="text-xs text-slate-400">{formatDateTime(event.registrado_em)}</span>
              </div>
              {details.map((line) => <p key={line} className="mt-1 text-xs text-slate-600">{line}</p>)}
              <p className="mt-1.5 text-xs text-slate-500">{event.usuario} · {event.motivo}</p>
            </li>
          );
        })}
      </ul>
    ) : <p className="text-sm text-slate-500">Nenhuma alteração registrada para esta oportunidade.</p>
  );

  const bodyInner = (
    <div className="space-y-5">
      {operational ? (
        // Configuração operacional (jornada): sem exceções nem motivo visíveis, só o necessário.
        <Tabs defaultValue="configuracao">
          <TabsList className="w-full">
            <TabsTrigger value="configuracao" className="flex-1">Configuração</TabsTrigger>
            <TabsTrigger value="historico" className="flex-1">Histórico</TabsTrigger>
          </TabsList>
          <TabsContent value="configuracao" className="mt-4 space-y-5">{configuracaoTab}</TabsContent>
          <TabsContent value="historico" className="mt-4">{historicoTab}</TabsContent>
        </Tabs>
      ) : (
        <Tabs defaultValue="configuracao">
          <TabsList className="w-full">
            <TabsTrigger value="configuracao" className="flex-1">Configuração</TabsTrigger>
            <TabsTrigger value="excecoes" className="flex-1">Exceções</TabsTrigger>
            <TabsTrigger value="historico" className="flex-1">Histórico</TabsTrigger>
          </TabsList>

          <TabsContent value="configuracao" className="mt-4 space-y-5">
            {configuracaoTab}
          </TabsContent>

          <TabsContent value="excecoes" className="mt-4">
            <fieldset>
              <legend className="mb-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">Exceções <span className="font-normal normal-case">· opcional</span></legend>
              {rule.excecoes.length ? (
                <ul className="space-y-2">
                  {rule.excecoes.map((item) => (
                    <li key={item.ordem} className="flex items-start gap-2.5">
                      <Checkbox id={id(`excecao-${item.ordem}`)} checked={draft.excecoes[item.ordem] ?? false}
                        onCheckedChange={(checked) => { setExceptionEdits((current) => ({ ...current, [item.ordem]: checked === true })); setNotice(null); }} className="mt-0.5" />
                      <label htmlFor={id(`excecao-${item.ordem}`)} className="cursor-pointer text-sm text-slate-800">
                        {item.descricao}
                        {item.texto && <span className="block text-xs text-slate-500">{item.texto}</span>}
                      </label>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-sm text-slate-500">Nenhuma exceção cadastrada.</p>}
            </fieldset>
          </TabsContent>

          <TabsContent value="historico" className="mt-4">{historicoTab}</TabsContent>
        </Tabs>
      )}

      {!operational && (
        <div>
          <Label htmlFor={id('motivo')}>Motivo da alteração</Label>
          <Textarea id={id('motivo')} value={reason} onChange={(event) => { setReason(event.target.value); setNotice(null); }} placeholder="Por que esta mudança? Fica registrado no histórico." className="min-h-16" />
          <p className="mt-1 text-xs text-slate-500">Alterado por <strong>{actor}</strong>. Obrigatório (mínimo {MOTIVO_MINIMO} caracteres).</p>
        </div>
      )}

      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-800">{error}</p>}
      {notice && <output className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm font-medium text-emerald-800"><CheckCircle2 className="size-4 shrink-0" aria-hidden="true" />{notice}</output>}
    </div>
  );

  const footerInner = (
    <>
      <Button type="button" variant="outline" onClick={cancel} disabled={saving || (!body && !reason && !error && !notice)}>Cancelar</Button>
      <Button type="button" onClick={() => void save()} disabled={!canSave}>{saving ? 'Salvando…' : operational ? 'Salvar configuração' : 'Salvar alterações'}</Button>
    </>
  );

  // CHECKOUT_AUSENTE sempre usa modal central expandido; o formulário técnico lateral não participa
  // deste fluxo operacional.
  if (operational) {
    return (
      <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
        <DialogContent className="flex max-h-[88vh] w-full flex-col overflow-hidden sm:max-w-3xl" aria-label="Configurar oportunidade Check-out ausente">
          <div className="-mx-4 -mt-4 shrink-0 border-b bg-white px-4 pt-4 pb-3">{headerInner}</div>
          <div className="min-h-0 flex-1 overflow-y-auto px-0.5">{bodyInner}</div>
          <div className="-mx-4 -mb-4 flex shrink-0 items-center justify-end gap-2 border-t bg-white px-4 pt-3 pb-4">
            {footerInner}
            {body && !reasonOk && <p className="mr-auto text-xs text-amber-700">Informe o motivo para salvar.</p>}
          </div>
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <Card className="border-blue-200 shadow-md lg:sticky lg:top-4" aria-label={`Editar oportunidade ${rule.nome_regra}`}>
      <CardHeader className="border-b">
        <div className="flex items-start justify-between gap-3">
          {headerInner}
          <Button type="button" variant="ghost" size="icon-sm" onClick={onClose} aria-label="Fechar edição"><X /></Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {bodyInner}
        <div className="flex items-center justify-end gap-2 border-t pt-4">{footerInner}</div>
        {body && !reasonOk && <p className="-mt-2 text-right text-xs text-amber-700">Informe o motivo para salvar.</p>}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------- configuração inicial fixa de CHECKOUT_AUSENTE
export function CheckoutConfigurator({ journeys, actor, onCreated, onClose }: {
  journeys: GovernanceRule['jornadas']; actor: string;
  onCreated: (result: RuleCreateResult) => void; onClose: () => void;
}) {
  const idPrefix = useId();
  const [schedules, setSchedules] = useState<ScheduleEdit[]>(() => scheduleDrafts(journeys));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasActiveSchedule = schedules.some((item) => item.ativo);
  const scheduleOk = hasActiveSchedule && validSchedules(schedules);
  const canSave = scheduleOk && !saving;

  async function save() {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      onCreated(await createRule({
        usuario: actor,
        motivo: CHECKOUT_MOTIVO_CRIACAO,
        nome_regra: CHECKOUT_NAME,
        descricao: CHECKOUT_DESCRIPTION,
        tipo_oportunidade: CHECKOUT_CODE,
        jornadas: schedules,
        papel_fonte: 'checkout',
        campo_logico: 'hora_saida',
        operador: 'IS NULL',
        valor: null,
        excecoes: [],
        status: 'ATIVA',
        gerar_oportunidade: true,
      }));
    } catch (reasonError) {
      setError(reasonError instanceof Error ? reasonError.message : 'Não foi possível salvar a configuração.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="flex max-h-[88vh] w-full flex-col overflow-hidden sm:max-w-3xl" aria-label="Configurar oportunidade Check-out ausente">
        <div className="-mx-4 -mt-4 shrink-0 border-b bg-white px-4 pt-4 pb-3">
          <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Oportunidade operacional</p>
          <DialogTitle className="mt-0.5 text-xl font-bold text-slate-950">Configurar oportunidade</DialogTitle>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-0.5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label>Nome</Label>
              <p className="rounded-lg border bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-900">{CHECKOUT_NAME}</p>
            </div>
            <div className="sm:col-span-2">
              <Label>Descrição</Label>
              <p className="rounded-lg border bg-slate-50 px-3 py-2 text-sm text-slate-700">{CHECKOUT_DESCRIPTION}</p>
            </div>
          </div>

          <section className="rounded-xl border border-slate-200 p-4" aria-labelledby={`${idPrefix}-journey-title`}>
            <h3 id={`${idPrefix}-journey-title`} className="mb-3 text-base font-bold text-slate-900">Configuração de jornada</h3>
            <ScheduleFields items={schedules} available={journeys} onChange={(items) => { setSchedules(items); setError(null); }} />
            {!hasActiveSchedule && <p role="alert" className="mt-2 text-xs font-medium text-red-700">Selecione ao menos uma jornada.</p>}
            {hasActiveSchedule && !validSchedules(schedules) && <p role="alert" className="mt-2 text-xs font-medium text-red-700">Verifique nome, carga semanal única (até 168h, com duas casas decimais), entrada, saída e intervalo. Entrada e saída devem ser diferentes.</p>}
          </section>

          {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-800">{error}</p>}
        </div>

        <div className="-mx-4 -mb-4 flex shrink-0 items-center justify-end gap-2 border-t bg-white px-4 pt-3 pb-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>Cancelar</Button>
          <Button type="button" onClick={() => void save()} disabled={!canSave}>{saving ? 'Salvando…' : 'Salvar configuração'}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------- criação livre legada (sem acesso nesta etapa)
export function RuleCreator({ fields, templates, actor, onCreated, onClose, journeys = [] }: {
  journeys?: GovernanceRule['jornadas'];
  fields: AvailableField[]; templates: GovernanceCondition[]; actor: string;
  onCreated: (result: RuleCreateResult) => void; onClose: () => void;
}) {
  const [draft, setDraft] = useState<CreateDraft>(() => emptyCreateDraft(fields, templates));
  const [reason, setReason] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [operational, setOperational] = useState(false);
  const [schedules, setSchedules] = useState<ScheduleEdit[]>(() => scheduleDrafts(journeys));

  const change = (patch: Partial<CreateDraft>) => { setDraft((current) => ({ ...current, ...patch })); setError(null); };
  const operadores = operatorsForDraft(draft, fields);
  const errors = validateCreateDraft(draft, fields);
  const needsValue = draft.operador !== 'IS NULL' && draft.operador !== 'IS NOT NULL';
  const payload = operational ? {
    usuario: actor, motivo: reason.trim(), nome_regra: draft.nome.trim(), descricao: draft.descricao.trim(),
    tipo_oportunidade: 'CHECKOUT_AUSENTE' as const, jornadas: schedules,
    papel_fonte: 'checkout', campo_logico: 'hora_saida', operador: 'IS NULL', valor: null,
    excecoes: Object.entries(draft.excecoes).filter(([, v]) => v).map(([key]) => Number(key)),
    status: draft.ativa ? 'ATIVA' as const : 'INATIVA' as const, gerar_oportunidade: draft.gerar,
  } : buildCreatePayload(draft, fields, actor, reason.trim());
  const reasonOk = reason.trim().length >= MOTIVO_MINIMO;
  const canSave = Boolean(payload) && reasonOk && !saving && (!operational || (draft.nome.trim().length >= 3 && draft.descricao.trim().length >= 3 && validSchedules(schedules)));

  function changeField(papelCampo: string) {
    const proximo = fields.find((field) => papelCampoKey(field.papel_fonte, field.campo_logico) === papelCampo);
    change({ papelCampo, operador: proximo?.operadores[0]?.codigo ?? '', valor: '' });
  }

  async function save() {
    if (!payload || !canSave) return;
    setSaving(true);
    setError(null);
    try {
      onCreated(await createRule(payload));
    } catch (reasonError) {
      setError(reasonError instanceof Error ? reasonError.message : 'Não foi possível criar a oportunidade.');
    } finally {
      setSaving(false);
    }
  }

  const id = (name: string) => `nova-oportunidade-${name}`;

  const headerInner = (
    <div>
      <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Nova oportunidade</p>
      {operational
        ? <DialogTitle className="mt-0.5 text-lg font-bold text-slate-950">Criar oportunidade</DialogTitle>
        : <CardTitle className="mt-0.5">Criar oportunidade</CardTitle>}
    </div>
  );

  const bodyInner = (
    <div className="space-y-5">
      <div>
        <Label htmlFor="nova-tipo">Tipo de oportunidade</Label>
        <NativeSelect id="nova-tipo" value={operational ? 'CHECKOUT_AUSENTE' : 'CONDICAO'} onChange={(e) => { const selected = e.target.value === 'CHECKOUT_AUSENTE'; setOperational(selected); if (selected) change({ nome: 'Check-out ausente', descricao: 'Ausência de checkout após o horário esperado da jornada.' }); }}>
          <NativeSelectOption value="CONDICAO">Condição sobre um campo</NativeSelectOption>
          <NativeSelectOption value="CHECKOUT_AUSENTE">Check-out ausente · jornada</NativeSelectOption>
        </NativeSelect>
      </div>
      {operational ? (
        <div className="grid grid-cols-2 gap-4">
          <div className="col-span-2">
            <Label>Nome</Label>
            <p className="rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-800">{draft.nome}</p>
          </div>
          <div className="col-span-2">
            <Label>Descrição</Label>
            <p className="rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700">{draft.descricao}</p>
          </div>
        </div>
      ) : (
        <>
          <div>
            <Label htmlFor={id('nome')}>Nome</Label>
            <Input id={id('nome')} value={draft.nome} onChange={(event) => change({ nome: event.target.value })} aria-invalid={Boolean(errors.nome)} aria-describedby={id('nome-erro')} placeholder="Ex.: Ócio acima do limite" />
            <FieldError id={id('nome-erro')} message={errors.nome} />
          </div>
          <div>
            <Label htmlFor={id('descricao')}>Descrição</Label>
            <Textarea id={id('descricao')} value={draft.descricao} onChange={(event) => change({ descricao: event.target.value })} aria-invalid={Boolean(errors.descricao)} className="min-h-20" placeholder="O que esta oportunidade identifica na operação." />
            <FieldError id={id('descricao-erro')} message={errors.descricao} />
          </div>
        </>
      )}

      {operational ? (
        <div className="rounded-xl border border-slate-200 p-4">
          <p className="mb-3 text-sm font-bold text-slate-900">Configuração de jornada</p>
          <div className="mb-4 grid grid-cols-2 gap-4">
            <div>
              <Label>Marca</Label>
              <p className="flex items-center gap-1.5 rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700"><Lock className="size-3 text-slate-400" aria-hidden="true" />BRACELL</p>
            </div>
            <div>
              <Label>Operação</Label>
              <p className="flex items-center gap-1.5 rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700"><Lock className="size-3 text-slate-400" aria-hidden="true" />EXCLUSIVA</p>
            </div>
          </div>
          <ScheduleFields items={schedules} available={journeys} onChange={setSchedules} />
          {!validSchedules(schedules) && <p role="alert" className="mt-2 text-xs text-red-700">Verifique nome, carga semanal única (até 168h, com duas casas decimais), entrada, saída e intervalo. Entrada e saída devem ser diferentes.</p>}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Marca</Label>
            <p className="flex items-center gap-1.5 rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700"><Lock className="size-3 text-slate-400" aria-hidden="true" />BRACELL</p>
          </div>
          <div>
            <Label>Operação</Label>
            <p className="flex items-center gap-1.5 rounded-lg border bg-slate-50 px-2.5 py-1.5 text-sm text-slate-700"><Lock className="size-3 text-slate-400" aria-hidden="true" />EXCLUSIVA</p>
          </div>
        </div>
      )}

      {!operational && (
        <fieldset>
          <legend className="mb-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">Condição</legend>
          {fields.length ? (
            <div className="space-y-2">
              <div>
                <label htmlFor={id('campo')} className="text-[11px] font-semibold text-slate-400">Campo analisado</label>
                <NativeSelect id={id('campo')} className="mt-1 w-full" value={draft.papelCampo} onChange={(event) => changeField(event.target.value)}>
                  {fields.map((field) => {
                    const chave = papelCampoKey(field.papel_fonte, field.campo_logico);
                    return <NativeSelectOption key={chave} value={chave}>{fieldOptionLabel(field)}</NativeSelectOption>;
                  })}
                </NativeSelect>
              </div>
              <div className="grid grid-cols-[1fr_0.8fr] gap-2">
                <div>
                  <label htmlFor={id('operador')} className="text-[11px] font-semibold text-slate-400">Regra</label>
                  <NativeSelect id={id('operador')} className="mt-1 w-full" value={draft.operador} onChange={(event) => change({ operador: event.target.value, valor: '' })}>
                    {operadores.map((option) => <NativeSelectOption key={option.codigo} value={option.codigo}>{option.rotulo}</NativeSelectOption>)}
                  </NativeSelect>
                </div>
                <div>
                  <label htmlFor={id('valor')} className="text-[11px] font-semibold text-slate-400">Valor</label>
                  <Input id={id('valor')} className="mt-1" value={needsValue ? draft.valor : ''} disabled={!needsValue} onChange={(event) => change({ valor: event.target.value })} aria-invalid={Boolean(errors.valor)} aria-describedby={id('valor-erro')} />
                </div>
              </div>
              <FieldError id={id('valor-erro')} message={errors.valor} />
            </div>
          ) : <p className="text-sm text-slate-500">Nenhum campo com fonte mapeada disponível.</p>}
        </fieldset>
      )}

      <fieldset>
        <legend className="mb-1.5 text-xs font-bold uppercase tracking-wide text-slate-500">Não gerar quando</legend>
        {templates.length ? (
          <ul className="space-y-2">
            {templates.map((item) => (
              <li key={item.ordem} className="flex items-start gap-2.5">
                <Checkbox id={id(`excecao-${item.ordem}`)} checked={draft.excecoes[item.ordem] ?? false}
                  onCheckedChange={(checked) => change({ excecoes: { ...draft.excecoes, [item.ordem]: checked === true } })} className="mt-0.5" />
                <label htmlFor={id(`excecao-${item.ordem}`)} className="cursor-pointer text-sm text-slate-800">{item.descricao}</label>
              </li>
            ))}
          </ul>
        ) : <p className="text-sm text-slate-500">Nenhum modelo de exceção disponível ainda.</p>}
      </fieldset>

      <div>
        <Label>Status</Label>
        <Segmented name={id('status')} label="Status da oportunidade" value={draft.ativa} onChange={(ativa) => change({ ativa })} options={['Ativa', 'Inativa']} />
      </div>

      <div className="rounded-lg border border-blue-100 bg-blue-50/60 p-3 text-sm text-blue-950">
        <p className="text-[11px] font-bold uppercase tracking-wide text-blue-700">Resultado</p>
        <p className="mt-1">{operational ? 'Jornadas ativas definem os horários esperados. O monitoramento Involves comprova a entrada e a ausência de checkout após a saída esperada. Sem configuração ativa, não gera oportunidade.' : creationOutcomeText(draft, fields)}</p>
      </div>

      <div>
        <Label htmlFor={id('motivo')}>Motivo</Label>
        <Textarea id={id('motivo')} value={reason} onChange={(event) => { setReason(event.target.value); setError(null); }} placeholder="Por que esta oportunidade está sendo criada? Fica registrado no histórico." className="min-h-16" />
        <p className="mt-1 text-xs text-slate-500">Criado por <strong>{actor}</strong>. Obrigatório (mínimo {MOTIVO_MINIMO} caracteres).</p>
      </div>

      {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-800">{error}</p>}
    </div>
  );

  const footerInner = (
    <>
      <Button type="button" variant="outline" onClick={onClose} disabled={saving}>Cancelar</Button>
      <Button type="button" onClick={() => void save()} disabled={!canSave}>{saving ? 'Criando…' : 'Salvar alterações'}</Button>
    </>
  );

  // Ver RuleEditor: a mesma configuração de jornada, aqui na criação, também pede o modal maior.
  if (operational) {
    return (
      <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
        <DialogContent className="flex max-h-[85vh] w-full flex-col overflow-hidden sm:max-w-2xl" aria-label="Criar oportunidade">
          <div className="-mx-4 -mt-4 shrink-0 border-b bg-white px-4 pt-4 pb-3">{headerInner}</div>
          <div className="min-h-0 flex-1 overflow-y-auto px-0.5">{bodyInner}</div>
          <div className="-mx-4 -mb-4 flex shrink-0 items-center justify-end gap-2 border-t bg-white px-4 pt-3 pb-4">
            {footerInner}
            {payload && !reasonOk && <p className="mr-auto text-xs text-amber-700">Informe o motivo para salvar.</p>}
          </div>
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <Card className="border-blue-200 shadow-md lg:sticky lg:top-4" aria-label="Criar oportunidade">
      <CardHeader className="border-b">
        <div className="flex items-start justify-between gap-3">
          {headerInner}
          <Button type="button" variant="ghost" size="icon-sm" onClick={onClose} aria-label="Fechar criação"><X /></Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {bodyInner}
        <div className="flex items-center justify-end gap-2 border-t pt-4">{footerInner}</div>
        {payload && !reasonOk && <p className="-mt-2 text-right text-xs text-amber-700">Informe o motivo para salvar.</p>}
      </CardContent>
    </Card>
  );
}
