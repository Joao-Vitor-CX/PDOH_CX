import { useCallback, useEffect, useRef, useState } from 'react';
import {
  loadOpportunityNotifications, markNotificationsSeen, notificationStorageKey, parseSeenOpportunities,
  type NotificationSnapshot, type SeenOpportunities, type WeeklyNotification,
} from '../services/opportunity-notifications';
import type { ResolvedPeriod } from '../services/operational-api';
import { OPPORTUNITIES_REFRESHED } from '../services/weekly-monitoring';

export function useOpportunityNotifications(user: string) {
  const storageKey = notificationStorageKey(user);
  const [seen, setSeen] = useState<SeenOpportunities>(() => {
    try { return parseSeenOpportunities(localStorage.getItem(storageKey)); } catch { return {}; }
  });
  const [data, setData] = useState<NotificationSnapshot | null>(null);
  const [error, setError] = useState(false);
  const [refreshing, setRefreshing] = useState(true);
  const refreshRef = useRef<() => void>(() => {});
  const refresh = useCallback(() => refreshRef.current(), []);

  useEffect(() => {
    let active = true;
    let busy = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | undefined;
    const run = async () => {
      if (!active || busy) return;
      clearTimeout(timer);
      if (document.hidden) {
        timer = setTimeout(() => void run(), 60_000);
        return;
      }
      busy = true;
      controller = new AbortController();
      setRefreshing(true);
      try {
        const result = await loadOpportunityNotifications(controller.signal);
        if (active) { setData(result); setError(false); }
      } catch {
        if (active) setError(true); // Erro não vira contagem zero nem apaga a última leitura.
      } finally {
        busy = false;
        if (active) {
          setRefreshing(false);
          timer = setTimeout(() => void run(), 60_000);
        }
      }
    };
    const onVisible = () => { if (!document.hidden) void run(); };
    refreshRef.current = () => void run();
    const onRefreshed = () => void run();
    window.addEventListener('focus', onVisible);
    window.addEventListener(OPPORTUNITIES_REFRESHED, onRefreshed);
    document.addEventListener('visibilitychange', onVisible);
    void run();
    return () => {
      active = false;
      controller?.abort();
      clearTimeout(timer);
      refreshRef.current = () => {};
      window.removeEventListener('focus', onVisible);
      window.removeEventListener(OPPORTUNITIES_REFRESHED, onRefreshed);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);

  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(seen)); } catch { /* Leitura local em memória continua funcionando. */ }
  }, [seen, storageKey]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null) setSeen(parseSeenOpportunities(event.newValue));
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [storageKey]);

  const markSeen = useCallback((items: WeeklyNotification[], period: ResolvedPeriod) => {
    setSeen((current) => markNotificationsSeen(current, items, period));
  }, []);
  return { data, error, refreshing, seen, markSeen, refresh };
}
