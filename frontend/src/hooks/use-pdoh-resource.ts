import { useCallback, useEffect, useState } from 'react';

export function usePdohResource<T>(key: string, loader: (signal: AbortSignal) => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [dataKey, setDataKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [revision, setRevision] = useState(0);
  const retry = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    const run = async () => {
      setRefreshing(true);
      setError(null);
      try {
        const value = await loader(controller.signal);
        if (controller.signal.aborted) return;
        setData(value);
        setDataKey(key);
        setUpdatedAt(new Date());
        setLoading(false);
      } catch (reason: unknown) {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : 'Falha desconhecida na consulta.');
        setErrorKey(key);
        setLoading(false);
      } finally {
        if (!controller.signal.aborted) setRefreshing(false);
      }
    };
    void run();
    return () => controller.abort();
  }, [key, loader, revision]);

  // Um filtro novo não deve exibir dados do filtro anterior como se fossem atuais.
  const currentData = dataKey === key ? data : null;
  const currentError = errorKey === key ? error : null;
  return { data: currentData, error: currentError, loading: currentData === null && currentError === null ? true : loading, refreshing, updatedAt: dataKey === key ? updatedAt : null, retry };
}
