import { LayoutGrid, Users } from 'lucide-react';

export type OperationalView = 'geral' | 'colaborador';

/**
 * Alterna entre o consolidado do período e a abertura por colaborador.
 * O modo escolhido vive na URL: o mesmo link reabre a mesma leitura.
 */
export function ViewToggle({
  value,
  onChange,
  geralLabel = 'Visão geral',
  colaboradorLabel = 'Por colaborador',
}: {
  value: OperationalView;
  onChange: (value: OperationalView) => void;
  geralLabel?: string;
  colaboradorLabel?: string;
}) {
  const options = [
    { id: 'geral' as const, label: geralLabel, Icon: LayoutGrid },
    { id: 'colaborador' as const, label: colaboradorLabel, Icon: Users },
  ];
  return (
    <fieldset className="inline-flex rounded-xl border border-slate-200 bg-white p-1">
      <legend className="sr-only">Modo de leitura</legend>
      {options.map(({ id, label, Icon }) => (
        <button
          key={id}
          type="button"
          aria-pressed={value === id}
          onClick={() => onChange(id)}
          className={`inline-flex min-h-11 items-center gap-2 rounded-lg px-4 text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-blue-600 ${
            value === id
              ? 'bg-blue-700 text-white'
              : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
          }`}
        >
          <Icon className="size-4" aria-hidden="true" />
          {label}
        </button>
      ))}
    </fieldset>
  );
}
