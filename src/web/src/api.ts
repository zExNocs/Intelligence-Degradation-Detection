import { QueryClient } from '@tanstack/react-query';
import type { components } from './api.generated';

export type Account = components['schemas']['AccountView'];
export type Session = components['schemas']['SessionView'];
export type AccountInput = components['schemas']['AccountInput'];
export type Group = components['schemas']['GroupView'];
export type GroupInput = components['schemas']['GroupInput'];
export type Target = components['schemas']['Target'];
export type Run = components['schemas']['Run'];
export type RunSummary = components['schemas']['RunSummary'];
export type RunDetail = components['schemas']['RunDetail'];
export type History = components['schemas']['HistoryPage'];
export type Settings = components['schemas']['SettingsView'];
export type Dashboard = components['schemas']['DashboardView'];
export type Challenge = components['schemas']['Challenge'];
export type Kind = components['schemas']['Kind'];
export type Catalog = { version: string; models: { id: string; family: string }[] };
export type SourceAccount = {
  id: number;
  name: string;
  platform: string;
  type: string;
  supported: boolean;
  active: boolean;
};

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
});

/** Keep private request data out of error text and browser persistence. */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(new URL(`api/v1${path}`, document.baseURI), {
    credentials: 'same-origin',
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('idd:unauthorized'));
    const error = await response.json().catch(() => ({ message: `HTTP ${response.status}` }));
    throw new Error(typeof error.message === 'string' ? error.message : `HTTP ${response.status}`);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export function send<T>(path: string, value?: unknown, method = 'POST'): Promise<T> {
  return api<T>(path, { method, body: value === undefined ? undefined : JSON.stringify(value) });
}

export async function refreshViews(): Promise<void> {
  await queryClient.invalidateQueries();
}
