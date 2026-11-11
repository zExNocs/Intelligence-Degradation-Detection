import {
  Button,
  Divider,
  Group,
  NumberInput,
  Paper,
  PasswordInput,
  SimpleGrid,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { type Kind, type Settings, refreshViews, send } from '../api';
import { useLive } from '../state';
import { ErrorNotice, PageHeader, showError } from '../components/Common';
import { ScheduleField } from '../components/GroupEditor';

export function SettingsPage() {
  const { t } = useTranslation();
  const query = useLive<Settings>(['settings'], '/settings');
  const [form, setForm] = useState<Settings | null>(null);
  const [key, setKey] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (query.data && !dirty) setForm(query.data);
  }, [query.data, dirty]);
  function change<K extends keyof Settings>(name: K, value: Settings[K]) {
    setDirty(true);
    setForm((current) => (current ? { ...current, [name]: value } : current));
  }
  const fields = [
    ['retention_days', 'Retention days', 1, 3650],
    ['retention_count', 'Results per check', 1, 10000],
    ['account_check_limit', 'Checks per account', 1, 100],
    ['global_parallel', 'Global parallel calls', 1, 128],
    ['call_timeout', 'Call timeout (seconds)', 10, 3600],
    ['max_output_tokens', 'Maximum output tokens', 256, 262144],
  ] as const;
  return (
    <>
      <PageHeader title="Settings" subtitle="Defaults apply to newly created groups." />
      <ErrorNotice error={query.error} />
      {form && (
        <Stack gap="lg">
          <Paper withBorder p="xl" radius="lg">
            <Title order={3} mb="lg">
              {t('Global defaults')}
            </Title>
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
              <TextInput
                label={t('Timezone')}
                value={form.timezone}
                placeholder="UTC / Asia/Shanghai"
                onChange={(event) => change('timezone', event.currentTarget.value)}
              />
              {fields.map(([name, label, min, max]) => (
                <NumberInput
                  key={name}
                  label={t(label)}
                  min={min}
                  max={max}
                  value={form[name]}
                  onChange={(value) => change(name, Number(value))}
                />
              ))}
            </SimpleGrid>
            <Divider my="lg" />
            <ScheduleField
              value={form.default_cron ?? '*/30 * * * *'}
              timezone={form.timezone ?? 'UTC'}
              onChange={(value) => change('default_cron', value)}
            />
          </Paper>
          <Paper withBorder p="xl" radius="lg">
            <Title order={3} mb="lg">
              {t('Source connection')}
            </Title>
            <Stack>
              <TextInput
                label={t('Source URL')}
                description={t(
                  'Enter the sub2api service root reachable from this app. Include any reverse-proxy prefix; omit /api/v1 and the model API /v1 suffix.',
                )}
                placeholder="https://example.invalid/sub2api"
                value={form.sub2api_url ?? ''}
                onChange={(event) => change('sub2api_url', event.currentTarget.value)}
              />
              <PasswordInput
                label={t('Administrator key')}
                description={t(
                  'Use a dedicated sub2api administrator API key with account credential and proxy export access. accounts.read alone is insufficient; current scoped keys require Full access for export. This grants broader privileges than this app uses. Leave blank to keep the saved key.',
                )}
                autoComplete="off"
                placeholder={form.has_sub2api_key ? t('Leave blank to keep the saved key') : ''}
                value={key}
                onChange={(event) => setKey(event.currentTarget.value)}
              />
              <Group align="flex-end">
                <NumberInput
                  label={t('Sync interval (seconds)')}
                  description={t(
                    'Default: 60 seconds. Refreshes credentials and proxies for imported accounts; new accounts are imported manually. Routes are also checked before each model request.',
                  )}
                  value={form.sync_seconds}
                  min={10}
                  max={86400}
                  onChange={(value) => change('sync_seconds', Number(value))}
                />
                <Button
                  variant="light"
                  onClick={async () => {
                    try {
                      const result = await send<{ updated: number; failed: number }>(
                        '/sources/sub2api/sync',
                      );
                      notifications.show({
                        message: `${result.updated} / ${result.updated + result.failed}`,
                        color: result.failed ? 'orange' : 'teal',
                      });
                      await refreshViews();
                    } catch (error) {
                      showError(error);
                    }
                  }}
                >
                  {t('Sync now')}
                </Button>
              </Group>
              <Text size="sm" c="dimmed">
                {t(
                  'Save settings before loading accounts or syncing. Sync now uses the saved connection. Discovery and synchronization do not consume model tokens.',
                )}
              </Text>
            </Stack>
          </Paper>
          <Paper withBorder p="xl" radius="lg">
            <Title order={3} mb="lg">
              {t('Default prompts')}
            </Title>
            <Stack>
              {(['pelican', 'comparison', 'other'] as Kind[]).map((kind) => (
                <Textarea
                  key={kind}
                  label={t(
                    kind === 'pelican'
                      ? 'Pelican'
                      : kind === 'comparison'
                        ? 'Comparison'
                        : 'Other checks',
                  )}
                  minRows={3}
                  autosize
                  maxRows={10}
                  value={form.prompts?.[kind] ?? ''}
                  onChange={(event) =>
                    change('prompts', { ...form.prompts, [kind]: event.currentTarget.value })
                  }
                />
              ))}
              <Textarea
                label={t('Expected JSON')}
                minRows={3}
                value={form.default_expected_json ?? '{}'}
                onChange={(event) => change('default_expected_json', event.currentTarget.value)}
              />
            </Stack>
          </Paper>
          <Group justify="flex-end">
            <Button
              loading={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const { has_sub2api_key, ...payload } = form;
                  await send(
                    '/settings',
                    { ...payload, ...(key ? { sub2api_key: key } : {}) },
                    'PUT',
                  );
                  setDirty(false);
                  setKey('');
                  await refreshViews();
                  notifications.show({ message: t('Saved'), color: 'teal' });
                } catch (error) {
                  showError(error);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {t('Save settings')}
            </Button>
          </Group>
          <Paper withBorder p="xl" radius="lg">
            <Title order={3}>{t('Rotate access token')}</Title>
            <Text c="dimmed" size="sm" my="md">
              {t('Rotating the token signs out every existing session.')}
            </Text>
            <Group align="flex-end">
              <PasswordInput
                style={{ flex: 1 }}
                label={t('New token (at least 24 characters)')}
                value={token}
                onChange={(event) => setToken(event.currentTarget.value)}
              />
              <Button
                color="orange"
                disabled={token.length < 24}
                onClick={async () => {
                  try {
                    await send('/auth/token', { token }, 'PUT');
                    setToken('');
                    window.dispatchEvent(new Event('idd:unauthorized'));
                  } catch (error) {
                    showError(error);
                  }
                }}
              >
                {t('Save')}
              </Button>
            </Group>
          </Paper>
        </Stack>
      )}
    </>
  );
}
