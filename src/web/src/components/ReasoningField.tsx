import { Select } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { api } from '../api';

/** Use the server's model policy and require an explicit fix for incompatible saved values. */
export function ReasoningField({
  protocol,
  model,
  value,
  onChange,
}: {
  protocol: string;
  model: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const options = useQuery({
    queryKey: ['reasoning-options', protocol, model],
    queryFn: () =>
      api<string[]>(`/models/reasoning-options?${new URLSearchParams({ protocol, model })}`),
    staleTime: 300_000,
  });
  const supported = ['default', ...(options.data ?? [])];
  const invalid = !!options.data && !supported.includes(value);
  return (
    <Select
      label={t('Reasoning effort')}
      data={[
        { value: 'default', label: t('Upstream default') },
        ...(options.data ?? []).map((effort) => ({ value: effort, label: effort })),
        ...(!supported.includes(value)
          ? [{ value, label: `${value}${invalid ? ` (${t('Unsupported')})` : ''}`, disabled: true }]
          : []),
      ]}
      value={value}
      onChange={(next) => onChange(next ?? 'default')}
      error={
        options.error?.message ??
        (invalid
          ? t(
              'This model does not support the saved reasoning effort. Select a supported value or upstream default.',
            )
          : undefined)
      }
      allowDeselect={false}
    />
  );
}
