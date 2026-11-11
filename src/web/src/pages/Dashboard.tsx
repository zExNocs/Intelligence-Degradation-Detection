import { Badge, Group, Paper, SimpleGrid, Stack, Text, Title, UnstyledButton } from '@mantine/core';
import {
  IconActivity,
  IconArrowUpRight,
  IconCheck,
  IconClock,
  IconCoins,
  IconServer,
} from '@tabler/icons-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { type Dashboard } from '../api';
import { useLive } from '../state';
import { ErrorNotice, PageHeader, ResultBadge } from '../components/Common';
import { RunDetails } from '../components/RunDetails';

export function DashboardPage() {
  const { t } = useTranslation();
  const query = useLive<Dashboard>(['dashboard'], '/dashboard');
  const [details, setDetails] = useState<string | null>(null);
  const value = query.data;
  const metrics = [
    { label: 'Accounts', value: value?.account_count ?? '—', icon: IconServer },
    { label: 'Checks', value: value?.check_count ?? '—', icon: IconActivity },
    { label: 'Runs · 24h', value: value?.runs_24h ?? '—', icon: IconActivity },
    { label: 'Tokens · 24h', value: value?.total_tokens.toLocaleString() ?? '—', icon: IconCoins },
    {
      label: 'Success rate',
      value: value?.success_rate == null ? '—' : `${(value.success_rate * 100).toFixed(1)}%`,
      icon: IconCheck,
    },
    {
      label: 'Average duration',
      value: value?.average_seconds == null ? '—' : `${value.average_seconds.toFixed(1)}s`,
      icon: IconClock,
    },
  ];
  const labels: Record<string, string> = {
    quality: 'Answer mismatch',
    identity: 'Identity divergence',
    manual: 'Human review',
    operational: 'Operational issues',
  };
  return (
    <>
      <PageHeader title="Dashboard" subtitle="A clear view of your models." />
      <ErrorNotice error={query.error} />
      <SimpleGrid cols={{ base: 2, md: 3, xl: 6 }} spacing="md">
        {metrics.map((metric) => (
          <Paper key={metric.label} withBorder p="lg" radius="lg" className="metric-card">
            <Group justify="space-between" mb="xl">
              <Text size="xs" c="dimmed" fw={500}>
                {t(metric.label)}
              </Text>
              <metric.icon size={17} stroke={1.6} />
            </Group>
            <Text className="metric-value">{metric.value}</Text>
          </Paper>
        ))}
      </SimpleGrid>
      {!!value?.unknown_usage_count && (
        <Text c="dimmed" size="xs" mt="sm">
          {t('Unknown usage')}: {value.unknown_usage_count}
        </Text>
      )}
      <Group mt={36} mb="lg" justify="space-between">
        <Title order={3}>{t('Latest findings')}</Title>
        <Badge color="gray" variant="light">
          24h
        </Badge>
      </Group>
      <SimpleGrid cols={{ base: 1, lg: 2 }} spacing="lg">
        {Object.entries(labels).map(([key, label]) => (
          <Paper withBorder p="lg" radius="lg" key={key}>
            <Group justify="space-between" mb="md">
              <Text fw={600}>{t(label)}</Text>
              <Badge variant="light" color={value?.alerts[key]?.length ? 'orange' : 'gray'}>
                {value?.alerts[key]?.length ?? 0}
              </Badge>
            </Group>
            <Stack gap="sm">
              {value?.alerts[key]?.map((run) => (
                <UnstyledButton
                  className="finding-row"
                  key={run.id}
                  onClick={() => setDetails(run.id)}
                >
                  <Group justify="space-between" wrap="nowrap">
                    <Stack gap={3}>
                      <Text size="sm" fw={550}>
                        {run.account_name}
                      </Text>
                      <Text size="xs" c="dimmed">
                        {run.model}
                      </Text>
                      <ResultBadge
                        status={run.status}
                        verdict={run.review ?? run.verdict}
                        score={run.score}
                      />
                    </Stack>
                    <IconArrowUpRight size={18} />
                  </Group>
                </UnstyledButton>
              ))}
              {!value?.alerts[key]?.length && (
                <Text c="dimmed" size="sm" py="lg">
                  {t('No findings yet')}
                </Text>
              )}
            </Stack>
          </Paper>
        ))}
      </SimpleGrid>
      <RunDetails id={details} onClose={() => setDetails(null)} />
    </>
  );
}
