import { useState } from 'react';
import { Button } from '@/components/ui/button';

export function FilterField({
  label,
  value,
  type = 'text',
  onChange,
}: {
  label: string;
  value: string;
  type?: 'text' | 'date';
  onChange: (value: string) => void;
}) {
  return (
    <DraftFilterField
      key={`${label}:${value}`}
      label={label}
      value={value}
      type={type}
      onChange={onChange}
    />
  );
}

function DraftFilterField({
  label,
  value,
  type,
  onChange,
}: {
  label: string;
  value: string;
  type: 'text' | 'date';
  onChange: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const apply = () => {
    if (type === 'text' && draft !== value) onChange(draft.trim());
  };
  return (
    <label className="flex min-w-0 flex-col gap-1 text-xs font-semibold text-slate-600">
      {label}
      <input
        className="h-11 rounded-lg border border-slate-300 bg-white px-3 text-sm font-normal text-slate-800 focus:border-blue-500 focus:outline-none"
        type={type}
        value={draft}
        onChange={(event) => {
          setDraft(event.target.value);
          if (type === 'date') onChange(event.target.value);
        }}
        onBlur={apply}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur();
        }}
      />
    </label>
  );
}

export function DateFilters({
  start,
  end,
  setStart,
  setEnd,
}: {
  start: string;
  end: string;
  setStart: (value: string) => void;
  setEnd: (value: string) => void;
}) {
  return (
    <>
      <FilterField
        label="Período inicial"
        type="date"
        value={start}
        onChange={setStart}
      />
      <FilterField
        label="Período final"
        type="date"
        value={end}
        onChange={setEnd}
      />
    </>
  );
}

export function Pagination({
  page,
  pages,
  onPage,
  label,
}: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
  label: string;
}) {
  if (pages <= 1) return null;
  return (
    <nav
      aria-label={`Paginação de ${label}`}
      className="mt-4 flex items-center justify-end gap-3 text-xs text-slate-600"
    >
      <span>
        {label}: página {page} de {pages}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPage(page - 1)}
      >
        Anterior
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= pages}
        onClick={() => onPage(page + 1)}
      >
        Próxima
      </Button>
    </nav>
  );
}
