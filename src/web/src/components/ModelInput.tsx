import { Autocomplete, defaultOptionsFilter } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

/** Browse the full catalogue on open and filter only while editing the identifier. */
export function ModelInput({
  label,
  description,
  models,
  value,
  onChange,
  required,
}: {
  label: string;
  description?: string;
  models: string[];
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}) {
  const { t } = useTranslation();
  const [searching, setSearching] = useState(false);
  return (
    <Autocomplete
      label={label}
      description={description}
      style={{ flex: 1, minWidth: 0 }}
      data={models}
      value={value}
      required={required}
      placeholder={t('Choose a cached model or enter an identifier')}
      onFocus={() => setSearching(false)}
      onDropdownClose={() => setSearching(false)}
      onChange={(next) => {
        setSearching(true);
        onChange(next);
      }}
      filter={(input) => defaultOptionsFilter({ ...input, search: searching ? input.search : '' })}
    />
  );
}
