import { useCallback, useEffect, useRef, useState } from 'react';
import { loadWeeklyMonitoring, type WeeklyMonitoring } from '../services/weekly-monitoring';

/**
 * Leitura do monitoramento de uma janela. `reload` devolve a nova leitura para quem precisa
 * compará-la com a anterior (reprocessamento), sem uma segunda consulta.
 */
export function useWeeklyMonitoring(inicio: string | null, fim: string | null) {
  const key = inicio && fim ? `${inicio}|${fim}` : null;
  const [state, setState] = useState<{ key: string; data: WeeklyMonitoring | null; error: string | null } | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [revision, setRevision] = useState(0);
  const controller = useRef<AbortController | null>(null);

  const fetchWindow = useCallback(async (start: string, end: string) => {
    controller.current?.abort();
    const current = new AbortController();
    controller.current = current;
    setRefreshing(true);
    try {
      const data = await loadWeeklyMonitoring({ inicio: start, fim: end }, current.signal);
      setState({ key: `${start}|${end}`, data, error: null });
      setUpdatedAt(new Date());
      return data;
    } catch (reason) {
      if (!current.signal.aborted) setState({ key: `${start}|${end}`, data: null,
        error: reason instanceof Error ? reason.message : 'Falha desconhecida na consulta.' });
      throw reason;
    } finally {
      if (!current.signal.aborted) setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!inicio || !fim) return;
    const run = async () => {
      try { await fetchWindow(inicio, fim); } catch { /* Estado de erro já registrado. */ }
    };
    void run();
    return () => controller.current?.abort();
  }, [inicio, fim, revision, fetchWindow]);

  const reload = useCallback(
    () => (inicio && fim ? fetchWindow(inicio, fim) : Promise.resolve(null)),
    [inicio, fim, fetchWindow],
  );
  const retry = useCallback(() => setRevision((value) => value + 1), []);

  const current = state && state.key === key ? state : null;
  return {
    data: current?.data ?? null,
    error: current?.error ?? null,
    loading: !current,
    refreshing,
    updatedAt: current ? updatedAt : null,
    retry,
    reload,
  };
}
