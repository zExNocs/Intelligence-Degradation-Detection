import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  Menu,
  Stack,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconAlertCircle, IconCheck, IconClock, IconRefresh } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useState, type ReactNode } from 'react';
import { refreshViews } from '../api';
import { useRefresh } from '../state';

export function showError(error: unknown) {
  notifications.show({
    color: 'red',
    title: 'Request failed / 请求失败',
    message: error instanceof Error ? error.message : 'Unexpected error',
  });
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <Group justify="space-between" align="flex-start" mb="xl" gap="md">
      <Stack gap={5}>
        <Text className="eyebrow">{t('Live evidence')}</Text>
        <Group gap="md">
          <Title order={1} size="h2">
            {t(title)}
          </Title>
          {action}
        </Group>
        <Text c="dimmed" size="sm">
          {t(subtitle)}
        </Text>
      </Stack>
      <Group gap="sm">
        <RefreshControls />
      </Group>
    </Group>
  );
}

export function RefreshControls() {
  const { t } = useTranslation();
  const { seconds, setSeconds } = useRefresh();
  const [loading, setLoading] = useState(false);
  return (
    <Group gap={8}>
      <Tooltip label={t('Refresh')}>
        <ActionIcon
          size="lg"
          variant="default"
          aria-label={t('Refresh')}
          loading={loading}
          onClick={async () => {
            setLoading(true);
            try {
              await refreshViews();
            } finally {
              setLoading(false);
            }
          }}
        >
          <IconRefresh size={18} />
        </ActionIcon>
      </Tooltip>
      <Menu position="bottom-end">
        <Menu.Target>
          <Button variant="default" leftSection={<IconClock size={16} />} size="sm">
            {t('Auto refresh')}: {seconds ? `${seconds}s` : t('Off')}
          </Button>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item
            rightSection={seconds > 0 ? <IconCheck size={14} /> : null}
            onClick={() => setSeconds(seconds ? 0 : 15)}
          >
            {t('Enable auto refresh')}
          </Menu.Item>
          <Menu.Divider />
          {[5, 10, 15, 30].map((value) => (
            <Menu.Item
              key={value}
              rightSection={value === seconds ? <IconCheck size={14} /> : null}
              onClick={() => setSeconds(value)}
            >
              {value} {t('seconds')}
            </Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}

export function ErrorNotice({ error }: { error: Error | null }) {
  const { t } = useTranslation();
  return error ? (
    <Alert color="red" mb="md" icon={<IconAlertCircle size={18} />} title={t('Request failed')}>
      {error.message}
    </Alert>
  ) : null;
}

export function CostNotice() {
  const { t } = useTranslation();
  return (
    <Alert variant="light" color="teal" mb="lg" icon={<IconAlertCircle size={17} />}>
      <Text size="sm">
        {t('Model calls consume tokens.')} {t('Refreshing this page does not run a check.')}
      </Text>
    </Alert>
  );
}

export function ResultBadge({
  status,
  verdict,
  score,
}: {
  status: string;
  verdict?: string;
  score?: number | null;
}) {
  const { t } = useTranslation();
  const color =
    status !== 'completed'
      ? ({
          failed: 'red',
          cancelled: 'gray',
          interrupted: 'orange',
          queued: 'gray',
          running: 'blue',
        }[status] ?? 'gray')
      : score != null
        ? score === 1
          ? 'teal'
          : score >= 0.5
            ? 'yellow'
            : 'red'
        : verdict === 'suspected_mismatch' || verdict === 'fail'
          ? 'red'
          : verdict === 'pass' || verdict === 'consistent'
            ? 'teal'
            : 'gray';
  return (
    <Badge color={color} variant="light">
      {t(status === 'completed' && verdict ? verdict : status)}
      {status === 'completed' && score != null
        ? ` · ${(score * 100).toFixed(score === 1 || score === 0 ? 0 : 1)}%`
        : ''}
    </Badge>
  );
}
