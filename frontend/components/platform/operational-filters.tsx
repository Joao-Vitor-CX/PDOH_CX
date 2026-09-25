import { useState, type SyntheticEvent, type ReactNode } from 'react';
import { FilterPanel } from './filter-panel';
import type {
  OperationalFilters,
  PeriodMode,
  ResolvedPeriod,
} from '@/src/services/operational-api';

const inputClass =
  'min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm font-normal text-slate-800 focus-visible:outline-2 focus-visible:outline-blue-600';
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1.5 text-xs font-semibold text-slate-600">
      {label}
      {children}
    </label>
  );
}

export function OperationalFiltersForm({
  filters,
  period,
  rules = [],
  detailed = false,
  pdohValidation = false,
  collaborators = [],
  states = [],
  lockedBrand = false,
  onApply,
  onReset,
}: {
  filters: OperationalFilters;
  period?: ResolvedPeriod;
  rules?: { value: string; label: string }[];
  detailed?: boolean;
  pdohValidation?: boolean;
  collaborators?: string[];
  states?: string[];
  lockedBrand?: boolean;
  onApply: (filters: OperationalFilters) => void;
  onReset: () => void;
}) {
  const [mode, setMode] = useState<PeriodMode>(filters.periodo || 'automatico');
  const submit = (event: SyntheticEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (key: string) => {
      const value = form.get(key);
      return typeof value === 'string' ? value.trim() : '';
    };
    const next: OperationalFilters = { periodo: mode };
    for (const field of [
      'marca',
      'colaborador',
      'estado',
      'tipo',
      'severidade',
      'status',
    ] as const) {
      const value = text(field);
      if (value) next[field] = value;
    }
    if (lockedBrand) next.marca = filters.marca;
    if (mode === 'personalizado') {
      next.periodo_inicio = text('periodo_inicio');
      next.periodo_fim = text('periodo_fim');
    }
    if (mode === 'relativo') {
      const quantidade = Number(text('periodo_quantidade'));
      if (Number.isInteger(quantidade) && quantidade > 0)
        next.periodo_quantidade = quantidade;
      const unidade = text('periodo_unidade');
      if (unidade === 'dias' || unidade === 'semanas' || unidade === 'meses')
        next.periodo_unidade = unidade;
    }
    onApply(next);
  };
  const active = [
    'marca',
    'colaborador',
    'estado',
    'tipo',
    'regra',
    'severidade',
    'status',
  ].filter((key) => filters[key as keyof OperationalFilters]).length;
  return (
    <FilterPanel activeCount={active}>
      <form
        onSubmit={submit}
        className="grid w-full items-end gap-3 sm:grid-cols-2 xl:grid-cols-4"
      >
        {!lockedBrand && (
          <Field label="Marca">
            <input
              className={inputClass}
              name="marca"
              defaultValue={filters.marca}
              placeholder="Todas as marcas"
              maxLength={80}
            />
          </Field>
        )}
        <Field label="Período">
          <select
            name="periodo"
            className={inputClass}
            value={mode}
            onChange={(event) => setMode(event.target.value as PeriodMode)}
          >
            <option value="automatico">Mais recente com dados</option>
            {pdohValidation && <option value="hoje">Hoje</option>}
            {pdohValidation && <option value="ontem">Ontem</option>}
            <option value="semana">Semana anterior · seg–sáb</option>
            {pdohValidation && <option value="ultimos_7_dias">Últimos 7 dias</option>}
            {pdohValidation && <option value="ultimos_30_dias">Últimos 30 dias</option>}
            <option value="mes">Mês anterior</option>
            {pdohValidation && <option value="tres_meses">3 meses anteriores</option>}
            {pdohValidation && <option value="doze_meses">12 meses anteriores</option>}
            <option value="personalizado">{pdohValidation ? 'Intervalo de datas fixo' : 'Personalizado'}</option>
            {pdohValidation && <option value="relativo">Intervalo de datas relativo</option>}
          </select>
        </Field>
        {mode === 'personalizado' && (
          <>
            <Field label="Data inicial">
              <input
                required
                type="date"
                name="periodo_inicio"
                className={inputClass}
                defaultValue={filters.periodo_inicio || period?.inicio}
              />
            </Field>
            <Field label="Data final">
              <input
                required
                type="date"
                name="periodo_fim"
                className={inputClass}
                defaultValue={filters.periodo_fim || period?.fim}
              />
            </Field>
          </>
        )}
        {mode === 'relativo' && pdohValidation && (
          <>
            <Field label="Quantidade">
              <input required min={1} max={3650} type="number" name="periodo_quantidade"
                className={inputClass} defaultValue={filters.periodo_quantidade || 7} />
            </Field>
            <Field label="Unidade">
              <select name="periodo_unidade" className={inputClass}
                defaultValue={filters.periodo_unidade || 'dias'}>
                <option value="dias">Dias</option>
                <option value="semanas">Semanas</option>
                <option value="meses">Meses</option>
              </select>
            </Field>
          </>
        )}
        {pdohValidation && (
          <>
            <Field label="Colaborador">
              <input className={inputClass} name="colaborador" list="pdoh-colaboradores"
                placeholder="Todos os colaboradores" defaultValue={filters.colaborador} maxLength={255} />
              <datalist id="pdoh-colaboradores">
                {collaborators.map((name) => <option key={name} value={name}>{name}</option>)}
              </datalist>
            </Field>
            <Field label="Estado">
              <select className={inputClass} name="estado" defaultValue={filters.estado || ''}>
                <option value="">Todos os estados</option>
                {states.map((state) => <option key={state} value={state}>{state}</option>)}
              </select>
            </Field>
          </>
        )}
        {detailed && (
          <>
            <Field label="Colaborador">
              <input
                className={inputClass}
                name="colaborador"
                placeholder="Buscar por nome"
                defaultValue={filters.colaborador}
                maxLength={255}
              />
            </Field>
            <Field label="Regra">
              <select
                className={inputClass}
                name="tipo"
                defaultValue={filters.tipo || ''}
              >
                <option value="">Todas as regras no período</option>
                {filters.tipo &&
                  !rules.some((rule) => rule.value === filters.tipo) && (
                    <option value={filters.tipo}>
                      Regra selecionada no link
                    </option>
                  )}
                {rules.map((rule) => (
                  <option key={rule.value} value={rule.value}>
                    {rule.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Severidade">
              <select
                className={inputClass}
                name="severidade"
                defaultValue={filters.severidade || ''}
              >
                <option value="">Todas</option>
                <option value="CRITICA">Crítica</option>
                <option value="ALTA">Alta</option>
                <option value="MEDIA">Média</option>
                <option value="BAIXA">Baixa</option>
              </select>
            </Field>
            <Field label="Status">
              <select
                className={inputClass}
                name="status"
                defaultValue={filters.status || ''}
              >
                <option value="">Pendentes de ação</option>
                <option value="ABERTA">Aberta</option>
                <option value="EM_ANALISE">Em análise</option>
                <option value="REABERTA">Reaberta</option>
                <option value="RESOLVIDA">Resolvida</option>
                <option value="IGNORADA">Ignorada</option>
              </select>
            </Field>
          </>
        )}
        <div className="flex gap-2">
          <button
            type="submit"
            className="min-h-11 rounded-lg bg-blue-700 px-4 text-sm font-semibold text-white hover:bg-blue-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          >
            Aplicar filtros
          </button>
          <button
            type="button"
            onClick={onReset}
            className="min-h-11 rounded-lg px-3 text-sm font-semibold text-slate-600 hover:bg-slate-100"
          >
            {pdohValidation ? 'Excluir filtros' : 'Limpar'}
          </button>
        </div>
      </form>
    </FilterPanel>
  );
}
