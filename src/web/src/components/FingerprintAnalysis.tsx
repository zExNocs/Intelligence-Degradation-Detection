import { Alert, Badge, Group, Progress, Stack, Table, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';

type Candidate = { model: string; probability: number };

function isCandidate(value: unknown): value is Candidate {
  return (
    typeof value === 'object' &&
    value !== null &&
    'model' in value &&
    typeof value.model === 'string' &&
    'probability' in value &&
    typeof value.probability === 'number'
  );
}

/** Present closed-set probabilities without suggesting an identity guarantee. */
export function FingerprintAnalysis({
  analysis,
  verdict,
}: {
  analysis: Record<string, unknown>;
  verdict?: string;
}) {
  const { t } = useTranslation();
  const candidates = Array.isArray(analysis.results) ? analysis.results.filter(isCandidate) : [];
  return (
    <Stack gap="sm">
      <Alert color={verdict === 'incomplete' ? 'orange' : 'blue'}>
        {t(
          verdict === 'incomplete'
            ? 'Incomplete challenges: attribution is reference only.'
            : 'Attribution is relative to the loaded candidate bank, not proof of model identity. Unlisted models may resemble listed candidates.',
        )}
      </Alert>
      <Group>
        <Badge variant="light">
          {String(analysis.prediction_name ?? analysis.prediction ?? t('Unknown'))}
        </Badge>
        <Text size="sm">
          {t('Valid outputs')}: {String(analysis.used_outputs ?? 0)}
        </Text>
      </Group>
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('Candidate model')}</Table.Th>
            <Table.Th>{t('Probability within bank')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {candidates.map((candidate) => (
            <Table.Tr key={candidate.model}>
              <Table.Td>{candidate.model}</Table.Td>
              <Table.Td>
                <Group wrap="nowrap">
                  <Progress value={candidate.probability * 100} style={{ flex: 1, minWidth: 60 }} />
                  <Text size="xs" w={55}>
                    {(candidate.probability * 100).toFixed(2)}%
                  </Text>
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
