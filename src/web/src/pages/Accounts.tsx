import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Code,
  Divider,
  Group,
  Menu,
  Modal,
  NumberInput,
  Paper,
  PasswordInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core';
import {
  IconEdit,
  IconPlugConnected,
  IconPlus,
  IconRefresh,
  IconRoute,
  IconServer,
} from '@tabler/icons-react';
import { useState } from 'react';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import {
  type Account,
  type AccountInput,
  type Run,
  type SourceAccount,
  api,
  refreshViews,
  send,
} from '../api';
import { formatTime, useLive, useServerClock } from '../state';
import { CostNotice, ErrorNotice, PageHeader, ResultBadge, showError } from '../components/Common';
import { RunDetails } from '../components/RunDetails';
import { ModelInput } from '../components/ModelInput';
import { ReasoningField } from '../components/ReasoningField';

const defaults: AccountInput = {
  name: '',
  protocol: 'openai_responses',
  base_url: 'https://api.openai.com',
  path: '/v1/responses',
  models_path: '/v1/models',
  default_model: '',
  default_effort: 'default',
  max_parallel: 1,
  enabled: true,
};

function SourceRoute({ account }: { account: Account }) {
  const { t, i18n } = useTranslation();
  const { timezone } = useServerClock();
  const [checking, setChecking] = useState(false);
  const proxy = account.proxy;
  if (account.source !== 'sub2api') return null;
  return (
    <Stack gap={5} mt="sm">
      <Text size="xs" fw={600}>
        {t('Source account ID')}: {account.external_id}
      </Text>
      <Text size="xs" style={{ overflowWrap: 'anywhere' }}>
        {proxy
          ? `${t('Source proxy')}: ${proxy.name || '—'} · #${proxy.source_id ?? '—'} · ${proxy.protocol}://${proxy.host.includes(':') ? `[${proxy.host}]` : proxy.host}:${proxy.port}`
          : t('Source assigns a direct connection')}
      </Text>
      {proxy && (
        <Text size="xs" c="dimmed">
          {t(
            proxy.authenticated
              ? 'Proxy authentication preserved; credentials hidden'
              : 'Proxy does not require authentication',
          )}
        </Text>
      )}
      <Text size="xs" c="dimmed">
        {t('Last source sync')}: {formatTime(account.synced_at, timezone, i18n.language)}
      </Text>
      <Text size="xs" c="dimmed">
        {t(
          'Compare the proxy ID and address with this account in sub2api. Every model request rechecks the source; an unavailable proxy never falls back to direct access.',
        )}
      </Text>
      <Button
        size="compact-xs"
        variant="subtle"
        loading={checking}
        disabled={!account.enabled}
        onClick={async () => {
          setChecking(true);
          try {
            await send(`/accounts/${account.id}/route/verify`);
            notifications.show({
              message: t('Source route refreshed and verified. No model tokens used.'),
              color: 'teal',
            });
          } catch (error) {
            showError(error);
          } finally {
            await refreshViews();
            setChecking(false);
          }
        }}
      >
        {t('Verify source route')}
      </Button>
    </Stack>
  );
}

function AccountEditor({ account, close }: { account?: Account; close: () => void }) {
  const { t } = useTranslation();
  const [form, setForm] = useState<AccountInput>(
    account
      ? {
          name: account.name,
          protocol: account.protocol as AccountInput['protocol'],
          base_url: account.base_url,
          path: account.path,
          models_path: account.models_path,
          default_model: account.default_model,
          default_effort: account.default_effort,
          max_parallel: account.max_parallel,
          enabled: account.enabled,
        }
      : defaults,
  );
  const [key, setKey] = useState('');
  const [headers, setHeaders] = useState('');
  const [models, setModels] = useState(account?.models ?? []);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const managed = account?.source === 'sub2api';
  function change<K extends keyof AccountInput>(key: K, value: AccountInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }
  function payload(): AccountInput {
    const custom: unknown = headers.trim() ? JSON.parse(headers) : undefined;
    if (
      custom !== undefined &&
      (custom === null ||
        Array.isArray(custom) ||
        typeof custom !== 'object' ||
        Object.values(custom).some((value) => typeof value !== 'string'))
    )
      throw new Error('Headers must be a JSON object of strings.');
    return {
      ...form,
      ...(key ? { api_key: key } : {}),
      ...(custom
        ? {
            headers: Object.fromEntries(
              Object.entries(custom).map(([name, value]) => [name, String(value)]),
            ),
          }
        : {}),
    };
  }
  return (
    <Modal
      opened
      onClose={close}
      title={t(account ? 'Edit account' : 'Add account')}
      size="lg"
      centered
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          try {
            await send(
              account ? `/accounts/${account.id}` : '/accounts',
              payload(),
              account ? 'PUT' : 'POST',
            );
            await refreshViews();
            close();
          } catch (error) {
            setError(error instanceof Error ? error : new Error('Request failed'));
          } finally {
            setBusy(false);
          }
        }}
      >
        <Stack>
          <ErrorNotice error={error} />
          {managed && (
            <Alert color="blue">
              {t(
                'Credentials, endpoints and proxy follow sub2api. Choose and save a default model below to enable connectivity probes; manual model entry is supported.',
              )}
            </Alert>
          )}
          <TextInput
            required
            label={t('Name')}
            value={form.name}
            onChange={(event) => change('name', event.currentTarget.value)}
          />
          <Select
            label={t('Protocol')}
            disabled={managed}
            data={[
              { value: 'openai_responses', label: 'OpenAI Responses' },
              { value: 'anthropic_messages', label: 'Anthropic Messages' },
              { value: 'openai_chat', label: 'OpenAI Chat Completions' },
            ]}
            value={form.protocol}
            onChange={(value) => {
              if (!value) return;
              setForm((current) => ({
                ...current,
                protocol: value as AccountInput['protocol'],
                base_url:
                  value === 'anthropic_messages' ? 'https://api.anthropic.com' : current.base_url,
                path:
                  value === 'anthropic_messages'
                    ? '/v1/messages'
                    : value === 'openai_chat'
                      ? '/v1/chat/completions'
                      : '/v1/responses',
              }));
            }}
          />
          <TextInput
            label={t('Base URL')}
            required
            disabled={managed}
            value={form.base_url}
            onChange={(event) => change('base_url', event.currentTarget.value)}
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            <TextInput
              required
              label={t('Request path')}
              disabled={managed}
              value={form.path}
              onChange={(event) => change('path', event.currentTarget.value)}
            />
            <TextInput
              required
              label={t('Models path')}
              disabled={managed}
              value={form.models_path}
              onChange={(event) => change('models_path', event.currentTarget.value)}
            />
          </SimpleGrid>
          <Text size="xs" c="dimmed">
            {t('Endpoint preview')}:{' '}
            <Code>
              {form.base_url?.replace(/\/$/, '')}
              {form.path}
            </Code>
          </Text>
          {!managed && (
            <>
              <PasswordInput
                label={t('API key')}
                required={!account}
                autoComplete="off"
                placeholder={account ? t('Leave blank to keep the saved key') : ''}
                value={key}
                onChange={(event) => setKey(event.currentTarget.value)}
              />
              <Textarea
                label={t('Extra headers (JSON)')}
                placeholder={account?.has_headers ? t('Leave blank to keep the saved key') : '{}'}
                value={headers}
                onChange={(event) => setHeaders(event.currentTarget.value)}
              />
            </>
          )}
          <Divider />
          <Group align="flex-end" wrap="nowrap">
            <ModelInput
              label={t('Default model')}
              description={t(
                'Required for a connectivity probe. Select a cached model or enter its exact identifier, then save.',
              )}
              models={models}
              value={form.default_model ?? ''}
              onChange={(value) => change('default_model', value)}
            />
            <Tooltip label={t('Refresh model catalogue')}>
              <ActionIcon
                size={36}
                variant="light"
                aria-label={t('Refresh model catalogue')}
                loading={refreshing}
                onClick={async () => {
                  setRefreshing(true);
                  setError(null);
                  try {
                    setModels(
                      await send<string[]>(
                        `/accounts/models/preview${account ? `?account_id=${account.id}` : ''}`,
                        payload(),
                      ),
                    );
                  } catch (error) {
                    setError(error instanceof Error ? error : new Error('Request failed'));
                  } finally {
                    if (managed) await refreshViews();
                    setRefreshing(false);
                  }
                }}
              >
                <IconRefresh size={18} />
              </ActionIcon>
            </Tooltip>
          </Group>
          <Text size="xs" c="dimmed">
            {t('Manual model entry is available even if catalogue refresh fails.')}
          </Text>
          <SimpleGrid cols={2}>
            <ReasoningField
              protocol={form.protocol ?? 'openai_responses'}
              model={form.default_model ?? ''}
              value={form.default_effort ?? 'default'}
              onChange={(value) => change('default_effort', value)}
            />
            <NumberInput
              label={t('Maximum parallel calls')}
              min={1}
              max={64}
              value={form.max_parallel}
              onChange={(value) => change('max_parallel', Number(value))}
            />
          </SimpleGrid>
          <Switch
            label={t('Enabled')}
            checked={form.enabled}
            onChange={(event) => change('enabled', event.currentTarget.checked)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={close}>
              {t('Cancel')}
            </Button>
            <Button type="submit" loading={busy}>
              {t('Save')}
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function SourceImport({ close }: { close: () => void }) {
  const { t } = useTranslation();
  const [accounts, setAccounts] = useState<SourceAccount[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <Modal opened onClose={close} title={t('Import from sub2api')} size="lg">
      <Stack>
        <ErrorNotice error={error} />
        <Text size="sm" c="dimmed">
          {t(
            'After importing, edit each account to choose a default model and reasoning effort. Importing does not run a connectivity probe.',
          )}
        </Text>
        <Button
          variant="light"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              setAccounts(await api<SourceAccount[]>('/sources/sub2api/accounts'));
            } catch (error) {
              setError(error instanceof Error ? error : new Error('Request failed'));
            } finally {
              setBusy(false);
            }
          }}
        >
          {t('Load source accounts')}
        </Button>
        {accounts.map((account) => (
          <Checkbox
            key={account.id}
            checked={selected.includes(account.id)}
            disabled={!account.supported || !account.active}
            label={`${account.name} · ${account.platform} · ${account.type}${!account.supported ? ` · ${t('Unsupported')}` : ''}${!account.active ? ` · ${t('Disabled')}` : ''}`}
            onChange={(event) =>
              setSelected(
                event.currentTarget.checked
                  ? [...selected, account.id]
                  : selected.filter((id) => id !== account.id),
              )
            }
          />
        ))}
        <Button
          disabled={!selected.length}
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await send('/sources/sub2api/import', { ids: selected });
              await refreshViews();
              close();
            } catch (error) {
              setError(error instanceof Error ? error : new Error('Request failed'));
            } finally {
              setBusy(false);
            }
          }}
        >
          {t('Import selected')} ({selected.length})
        </Button>
      </Stack>
    </Modal>
  );
}

function ProbeSummary({ accountId, view }: { accountId: string; view: (id: string) => void }) {
  const { t } = useTranslation();
  const query = useLive<Run[]>(['probes', accountId], `/accounts/${accountId}/probes`);
  const run = query.data?.at(-1);
  return run ? (
    <Group justify="space-between" mt="sm">
      <ResultBadge status={run.status ?? 'queued'} />
      <Button size="compact-xs" variant="subtle" onClick={() => view(run.id!)}>
        {t('View probe')} · {run.output?.elapsed?.toFixed(2)}s
      </Button>
    </Group>
  ) : null;
}

export function AccountsPage() {
  const { t } = useTranslation();
  const query = useLive<Account[]>(['accounts'], '/accounts');
  const [editor, setEditor] = useState<Account | 'new' | null>(null);
  const [importing, setImporting] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [probing, setProbing] = useState<string | null>(null);
  return (
    <>
      <PageHeader
        title="Models"
        subtitle="Manage providers and account routes."
        action={
          <Menu>
            <Menu.Target>
              <Button leftSection={<IconPlus size={18} />}>{t('Add account')}</Button>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item onClick={() => setEditor('new')}>{t('Direct API')}</Menu.Item>
              <Menu.Item onClick={() => setImporting(true)}>{t('Import from sub2api')}</Menu.Item>
            </Menu.Dropdown>
          </Menu>
        }
      />
      <CostNotice />
      <ErrorNotice error={query.error} />
      <SimpleGrid cols={{ base: 1, md: 2, xl: 3 }} spacing="lg">
        {query.data?.map((account) => (
          <Paper key={account.id} withBorder radius="lg" p="lg" className="account-card">
            <Group justify="space-between">
              <Group>
                <div className="account-icon">
                  <IconServer size={22} />
                </div>
                <Stack gap={2}>
                  <Text fw={650}>{account.name}</Text>
                  <Text size="xs" c="dimmed">
                    {account.protocol}
                  </Text>
                </Stack>
              </Group>
              <ActionIcon
                variant="subtle"
                aria-label={`${t('Edit')} ${account.name}`}
                onClick={() => setEditor(account)}
              >
                <IconEdit size={18} />
              </ActionIcon>
            </Group>
            <Group my="md" gap={6}>
              <Badge
                variant="light"
                color={account.enabled && account.source_active ? 'teal' : 'gray'}
              >
                {t(account.enabled ? 'Enabled' : 'Disabled')}
              </Badge>
              <Badge variant="outline" color="gray">
                {account.source === 'direct' ? t('Direct API') : 'sub2api'}
              </Badge>
              {account.has_proxy && (
                <Badge variant="light" color="blue" leftSection={<IconRoute size={12} />}>
                  {t('Source proxy')}
                </Badge>
              )}
            </Group>
            <SourceRoute account={account} />
            <Text size="sm" fw={500} lineClamp={1}>
              {account.default_model || '—'}
            </Text>
            <Text size="xs" c="dimmed" mt={4}>
              {account.default_effort} · {t('Maximum parallel calls')}: {account.max_parallel}
            </Text>
            {account.source_error && (
              <Alert color="red" mt="sm" p="xs">
                {account.source_error}
              </Alert>
            )}
            <Button
              mt="lg"
              fullWidth
              variant="light"
              leftSection={<IconPlugConnected size={17} />}
              disabled={!account.enabled}
              loading={probing === account.id}
              onClick={async () => {
                if (!account.default_model.trim()) {
                  setEditor(account);
                  return;
                }
                setProbing(account.id);
                try {
                  const run = await send<Run>(`/accounts/${account.id}/probe`);
                  setDetail(run.id!);
                  await refreshViews();
                } catch (error) {
                  showError(error);
                } finally {
                  setProbing(null);
                }
              }}
            >
              {t(account.default_model.trim() ? 'Probe connection' : 'Choose a model to probe')}
            </Button>
            {!account.default_model.trim() && (
              <Text size="xs" c="dimmed" mt={5}>
                {t('No default model yet. Choose a model and save before probing.')}
              </Text>
            )}
            <ProbeSummary accountId={account.id} view={setDetail} />
          </Paper>
        ))}
      </SimpleGrid>
      {query.data?.length === 0 && (
        <Paper p={50} withBorder className="empty-state">
          <IconServer size={42} stroke={1.2} />
          <Title order={3} mt="md">
            {t('No active accounts')}
          </Title>
          <Text c="dimmed" mt="sm">
            {t('Add an account and create your first check to start collecting evidence.')}
          </Text>
        </Paper>
      )}
      {editor && (
        <AccountEditor
          account={editor === 'new' ? undefined : editor}
          close={() => setEditor(null)}
        />
      )}
      {importing && <SourceImport close={() => setImporting(false)} />}
      <RunDetails id={detail} onClose={() => setDetail(null)} />
    </>
  );
}
