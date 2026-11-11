import { ActionIcon, Group, Stack, Text, Tooltip } from '@mantine/core';
import { IconRefresh } from '@tabler/icons-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { type Account, refreshViews, send } from '../api';
import { showError } from './Common';
import { ModelInput } from './ModelInput';
import { ReasoningField } from './ReasoningField';

export function ModelFields({
  account,
  model,
  effort,
  onModel,
  onEffort,
}: {
  account?: Account;
  model: string;
  effort: string;
  onModel: (value: string) => void;
  onEffort: (value: string) => void;
}) {
  const { t } = useTranslation();
  const [refreshing, setRefreshing] = useState(false);
  return (
    <Stack gap={8}>
      <Group align="flex-end" wrap="nowrap">
        <ModelInput
          label={t('Model')}
          models={account?.models ?? []}
          value={model}
          onChange={onModel}
          required
        />
        <Tooltip label={t('Refresh model catalogue')}>
          <ActionIcon
            size={36}
            variant="light"
            aria-label={t('Refresh model catalogue')}
            loading={refreshing}
            disabled={!account}
            onClick={async () => {
              if (!account) return;
              setRefreshing(true);
              try {
                await send(`/accounts/${account.id}/models/refresh`);
                await refreshViews();
              } catch (error) {
                showError(error);
                await refreshViews();
              } finally {
                setRefreshing(false);
              }
            }}
          >
            <IconRefresh size={17} />
          </ActionIcon>
        </Tooltip>
      </Group>
      <ReasoningField
        protocol={account?.protocol ?? 'openai_responses'}
        model={model}
        value={effort}
        onChange={onEffort}
      />
      {account?.models_error && (
        <Text size="xs" c="red">
          {account.models_error}
        </Text>
      )}
      <Text size="xs" c="dimmed">
        {account?.models_at
          ? `${t('Cached')}: ${new Date(account.models_at * 1000).toLocaleString()}`
          : t('No catalogue cached')}
      </Text>
    </Stack>
  );
}
