import { useId, useState, type ReactNode } from 'react';
import { ChevronDown, Filter } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

export function FilterPanel({ children, activeCount = 0 }: { children: ReactNode; activeCount?: number }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <Card className="mb-4 border-slate-200 shadow-sm"><CardContent className="p-4">
    <button type="button" className="flex w-full items-center justify-between gap-2 text-sm font-semibold text-blue-700 md:hidden" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}><span className="flex items-center gap-2"><Filter className="size-4" />Filtros {activeCount ? `· ${activeCount} ativos` : ''}</span><ChevronDown className={`size-4 transition-transform ${open ? 'rotate-180' : ''}`} /></button>
    <div id={id} className={`${open ? 'flex' : 'hidden'} flex-wrap items-end gap-3 pt-4 md:flex md:pt-0`}>{children}</div>
  </CardContent></Card>;
}
