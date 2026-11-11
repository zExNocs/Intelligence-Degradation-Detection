import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from './api';

const RefreshContext = createContext({ seconds: 15, setSeconds: (_value: number) => {} });

export function RefreshProvider({ children }: { children: ReactNode }) {
  const [seconds, set] = useState(() => {
    const stored = Number(localStorage.getItem('idd-refresh') ?? '15');
    return [0, 5, 10, 15, 30].includes(stored) ? stored : 15;
  });
  const value = useMemo(
    () => ({
      seconds,
      setSeconds: (next: number) => {
        set(next);
        localStorage.setItem('idd-refresh', String(next));
      },
    }),
    [seconds],
  );
  return <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>;
}

export const useRefresh = () => useContext(RefreshContext);

export function useLive<T>(key: readonly unknown[], path: string, enabled = true) {
  const { seconds } = useRefresh();
  return useQuery<T>({
    queryKey: key,
    queryFn: () => api<T>(path),
    enabled,
    refetchInterval: seconds ? seconds * 1000 : false,
    refetchIntervalInBackground: false,
  });
}

/** Anchor countdowns to server time rather than trusting the browser clock. */
export function useServerClock() {
  const clock = useLive<{ now: number; timezone: string }>(['clock'], '/clock');
  const [anchor, setAnchor] = useState({ server: 0, monotonic: performance.now() });
  const [now, setNow] = useState(0);
  useEffect(() => {
    if (clock.data) setAnchor({ server: clock.data.now, monotonic: performance.now() });
  }, [clock.data, clock.dataUpdatedAt]);
  useEffect(() => {
    const update = () => setNow(anchor.server + (performance.now() - anchor.monotonic) / 1000);
    update();
    const timer = window.setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [anchor]);
  return { now, timezone: clock.data?.timezone ?? 'UTC' };
}

export function formatTime(value: number | null | undefined, timezone: string, language: string) {
  return value
    ? new Intl.DateTimeFormat(language === 'zh' ? 'zh-CN' : 'en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        timeZone: timezone,
      }).format(value * 1000)
    : '—';
}
