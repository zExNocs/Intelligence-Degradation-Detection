import {
  Button,
  Checkbox,
  Group as ButtonGroup,
  Modal,
  MultiSelect,
  Paper,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  type Account,
  type Catalog,
  type Challenge,
  type Group,
  type GroupInput,
  type Kind,
  type Settings,
  refreshViews,
  send,
} from '../api';
import { formatTime, useLive } from '../state';
import { CostNotice, ErrorNotice } from './Common';
import { ModelFields } from './ModelFields';

const cronOptions = [
  { value: '*/30 * * * *', label: 'Every 30 minutes' },
  { value: '*/15 * * * *', label: 'Every 15 minutes' },
  { value: '*/5 * * * *', label: 'Every 5 minutes' },
  { value: '0 * * * *', label: 'Every hour' },
  { value: '0 9 * * *', label: 'Daily at 09:00' },
];

export function ScheduleField({
  value,
  timezone,
  onChange,
}: {
  value: string;
  timezone: string;
  onChange: (value: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const [mode, setMode] = useState(
    cronOptions.some((option) => option.value === value) ? 'friendly' : 'source',
  );
  const [preview, setPreview] = useState<number[]>([]);
  const [error, setError] = useState<Error | null>(null);
  return (
    <Stack gap="xs">
      <ButtonGroup justify="space-between">
        <Text size="sm" fw={500}>
          {t('Schedule')}
        </Text>
        <SegmentedControl
          size="xs"
          value={mode}
          onChange={setMode}
          data={[
            { value: 'friendly', label: t('Friendly') },
            { value: 'source', label: t('Cron source') },
          ]}
        />
      </ButtonGroup>
      {mode === 'source' ? (
        <TextInput
          aria-label={t('Cron source')}
          value={value}
          onChange={(event) => onChange(event.currentTarget.value)}
        />
      ) : (
        <Select
          aria-label={t('Friendly')}
          value={value}
          data={[
            ...cronOptions.map((option) => ({ ...option, label: t(option.label) })),
            ...(!cronOptions.some((option) => option.value === value)
              ? [{ value, label: `${t('Custom cron')}: ${value}` }]
              : []),
          ]}
          onChange={(selected) => selected && onChange(selected)}
        />
      )}
      <ButtonGroup justify="space-between">
        <Text size="xs" c="dimmed">
          {timezone} · {value}
        </Text>
        <Button
          size="compact-xs"
          variant="subtle"
          onClick={async () => {
            try {
              const result = await send<{ occurrences: number[] }>('/schedules/preview', {
                expression: value,
                timezone,
              });
              setPreview(result.occurrences);
              setError(null);
            } catch (error) {
              setError(error instanceof Error ? error : new Error('Request failed'));
            }
          }}
        >
          {t('Preview schedule')}
        </Button>
      </ButtonGroup>
      <ErrorNotice error={error} />
      {preview.map((item) => (
        <Text key={item} size="xs" c="dimmed">
          {formatTime(item, timezone, i18n.language)}
        </Text>
      ))}
    </Stack>
  );
}

export function GroupEditor({
  kind,
  existing,
  settings,
  close,
}: {
  kind: Kind;
  existing?: Group;
  settings: Settings;
  close: () => void;
}) {
  const { t, i18n } = useTranslation();
  const accounts = useLive<Account[]>(['accounts'], '/accounts');
  const challenges = useLive<Challenge[]>(
    ['challenges'],
    '/fingerprint/challenges',
    kind === 'modeltrace',
  );
  const catalog = useLive<Catalog>(
    ['fingerprint-catalog'],
    '/fingerprint/catalog',
    kind === 'modeltrace',
  );
  const [form, setForm] = useState<GroupInput>(
    existing?.recipe ?? {
      name: '',
      kind,
      prompt: settings.prompts?.[kind] ?? '',
      cron: settings.default_cron ?? '*/30 * * * *',
      enabled: true,
      comparison_mode: 'json',
      expected_json: settings.default_expected_json ?? '{}',
      regex_pattern: '',
      targets: [],
      challenge_ids: ['intuition-294', 'sequential-311', 'immediate-329'],
      parallel: false,
      expected_identity: null,
    },
  );
  const [error, setError] = useState<Error | null>(null);
  const [saving, setSaving] = useState(false);
  function change<K extends keyof GroupInput>(key: K, value: GroupInput[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }
  return (
    <Modal
      opened
      onClose={close}
      title={t(existing ? 'Edit test group' : 'Create test group')}
      size="xl"
      centered
    >
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (!form.targets.length) {
            setError(new Error(t('Please select at least one account.')));
            return;
          }
          setSaving(true);
          try {
            await send(
              existing ? `/groups/${existing.id}` : '/groups',
              form,
              existing ? 'PUT' : 'POST',
            );
            await refreshViews();
            close();
          } catch (error) {
            setError(error instanceof Error ? error : new Error('Request failed'));
          } finally {
            setSaving(false);
          }
        }}
      >
        <Stack gap="md">
          <CostNotice />
          <ErrorNotice error={error} />
          <TextInput
            required
            label={t('Name')}
            value={form.name}
            onChange={(event) => change('name', event.currentTarget.value)}
          />
          <MultiSelect
            label={t('Select accounts')}
            required
            searchable
            data={(accounts.data ?? []).map((account) => ({
              value: account.id,
              label: account.name,
              disabled: !account.enabled,
            }))}
            value={form.targets.map((target) => target.account_id)}
            onChange={(ids) =>
              change(
                'targets',
                ids.map(
                  (id) =>
                    form.targets.find((target) => target.account_id === id) ?? {
                      account_id: id,
                      model:
                        accounts.data?.find((account) => account.id === id)?.last_model ??
                        accounts.data?.find((account) => account.id === id)?.default_model ??
                        '',
                      effort:
                        accounts.data?.find((account) => account.id === id)?.last_effort ??
                        accounts.data?.find((account) => account.id === id)?.default_effort ??
                        'default',
                    },
                ),
              )
            }
          />
          <SimpleGrid cols={{ base: 1, sm: 2 }}>
            {form.targets.map((target, index) => (
              <Paper withBorder p="md" key={target.account_id}>
                <Text fw={600} size="sm" mb="sm">
                  {accounts.data?.find((account) => account.id === target.account_id)?.name}
                </Text>
                <ModelFields
                  account={accounts.data?.find((account) => account.id === target.account_id)}
                  model={target.model}
                  effort={target.effort ?? 'default'}
                  onModel={(model) =>
                    change(
                      'targets',
                      form.targets.map((item, position) =>
                        position === index ? { ...item, model } : item,
                      ),
                    )
                  }
                  onEffort={(effort) =>
                    change(
                      'targets',
                      form.targets.map((item, position) =>
                        position === index ? { ...item, effort } : item,
                      ),
                    )
                  }
                />
              </Paper>
            ))}
          </SimpleGrid>
          {kind !== 'modeltrace' ? (
            <Textarea
              label={t('Prompt')}
              required
              minRows={5}
              autosize
              maxRows={15}
              value={form.prompt ?? ''}
              onChange={(event) => change('prompt', event.currentTarget.value)}
            />
          ) : (
            <>
              <Text fw={500}>{t('Fixed challenges')}</Text>
              <Checkbox.Group
                value={form.challenge_ids}
                onChange={(value) => change('challenge_ids', value)}
              >
                <Stack gap="xs">
                  {challenges.data?.map((challenge) => (
                    <Checkbox
                      key={challenge.id}
                      value={challenge.id}
                      label={i18n.language === 'zh' ? challenge.name : challenge.name_en}
                    />
                  ))}
                </Stack>
              </Checkbox.Group>
              <Switch
                label={t('Run challenges in parallel')}
                description={t('Account and global parallel limits still apply.')}
                checked={form.parallel}
                onChange={(event) => change('parallel', event.currentTarget.checked)}
              />
              <Select
                searchable
                clearable
                label={t('Expected identity (optional)')}
                data={[
                  { group: t('Family'), items: ['gpt', 'claude'] },
                  {
                    group: t('Models'),
                    items: (catalog.data?.models ?? []).map((model) => model.id),
                  },
                ]}
                value={form.expected_identity}
                onChange={(value) => change('expected_identity', value)}
              />
            </>
          )}
          {kind === 'comparison' && (
            <>
              <SegmentedControl
                value={form.comparison_mode}
                onChange={(value) => change('comparison_mode', value as 'json' | 'regex')}
                data={[
                  { value: 'json', label: t('JSON structure') },
                  { value: 'regex', label: t('Regex match') },
                ]}
              />
              {form.comparison_mode === 'regex' ? (
                <Textarea
                  required
                  label={t('Regular expression')}
                  value={form.regex_pattern ?? ''}
                  onChange={(event) => change('regex_pattern', event.currentTarget.value)}
                />
              ) : (
                <Textarea
                  required
                  label={t('Expected JSON')}
                  minRows={4}
                  value={form.expected_json ?? '{}'}
                  onChange={(event) => change('expected_json', event.currentTarget.value)}
                />
              )}
            </>
          )}
          <ScheduleField
            value={form.cron ?? '*/30 * * * *'}
            timezone={settings.timezone ?? 'UTC'}
            onChange={(value) => change('cron', value)}
          />
          <Switch
            label={t('Enabled')}
            checked={form.enabled}
            onChange={(event) => change('enabled', event.currentTarget.checked)}
          />
          <ButtonGroup justify="flex-end">
            <Button variant="default" onClick={close}>
              {t('Cancel')}
            </Button>
            <Button type="submit" loading={saving}>
              {t('Save')}
            </Button>
          </ButtonGroup>
        </Stack>
      </form>
    </Modal>
  );
}
