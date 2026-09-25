import type { ReactNode } from 'react';

export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description: string; action?: ReactNode }) {
  return <div className="mb-5 flex flex-col justify-between gap-3 md:flex-row md:items-end">
    <div>{eyebrow && <p className="mb-1 text-[10px] font-extrabold uppercase tracking-[0.18em] text-blue-600">{eyebrow}</p>}<h1 className="text-2xl font-extrabold tracking-[-.035em] text-slate-950 md:text-[1.75rem]">{title}</h1><p className="mt-1 max-w-3xl text-[13px] text-slate-500">{description}</p></div>
    {action}
  </div>;
}
