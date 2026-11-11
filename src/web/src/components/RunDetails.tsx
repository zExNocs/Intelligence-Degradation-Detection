import {
  Accordion,
  Alert,
  Badge,
  Button,
  Code,
  Group,
  Modal,
  ScrollArea,
  Stack,
  Table,
  Tabs,
  Text,
  Textarea,
} from '@mantine/core';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { type RunDetail, refreshViews, send } from '../api';
import { formatTime, useLive, useServerClock } from '../state';
import { ErrorNotice, ResultBadge, showError } from './Common';
import { FingerprintAnalysis } from './FingerprintAnalysis';
import { HtmlPreview } from './HtmlPreview';

export function RunDetails({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const query = useLive<RunDetail>(['run', id], `/runs/${id}`, !!id);
  const { timezone } = useServerClock();
  const [note, setNote] = useState('');
  const run = query.data;
  useEffect(() => setNote(run?.review_note ?? ''), [run?.id, run?.review_note]);
  const active = run?.status === 'running' || run?.status === 'queued';
  async function review(verdict: 'pass' | 'fail' | null) {
    try {
      await send(`/runs/${id}/review`, { verdict, note }, 'PUT');
      await refreshViews();
    } catch (error) {
      showError(error);
    }
  }
  return (
    <Modal
      opened={!!id}
      onClose={onClose}
      title={t('Result details')}
      size="min(1100px, 95vw)"
      centered
    >
      <ErrorNotice error={query.error} />
      {run ? (
        <Stack gap="md">
          <Group justify="space-between">
            <Stack gap={3}>
              <Text fw={600}>
                {run.snapshot.account_name} / {run.snapshot.model}
              </Text>
              <Text c="dimmed" size="xs">
                {run.snapshot.effort} · {run.snapshot.protocol}
              </Text>
            </Stack>
            <ResultBadge
              status={run.status ?? 'queued'}
              verdict={run.review ?? run.judgment?.verdict}
              score={run.judgment?.score}
            />
          </Group>
          <Group gap="lg">
            <Text size="sm">
              {t('Tokens')}: {run.output?.usage?.total_tokens ?? t('Unknown')}
            </Text>
            <Text size="sm">
              {t('Duration')}: {run.output?.elapsed?.toFixed(2) ?? '—'}s
            </Text>
            <Text size="sm">
              {t('Started')}: {formatTime(run.started_at, timezone, i18n.language)}
            </Text>
          </Group>
          {run.error && (
            <Alert color={run.status === 'cancelled' ? 'gray' : 'red'}>{run.error}</Alert>
          )}
          {active && (
            <Button
              color="red"
              variant="light"
              onClick={async () => {
                try {
                  await send(`/runs/${id}/cancel`);
                  await refreshViews();
                } catch (error) {
                  showError(error);
                }
              }}
            >
              {t('Cancel run')}
            </Button>
          )}
          {run.kind === 'modeltrace' && (
            <FingerprintAnalysis
              analysis={run.judgment?.analysis ?? {}}
              verdict={run.judgment?.verdict}
            />
          )}
          <Tabs defaultValue={run.kind === 'pelican' ? 'preview' : 'output'} keepMounted={false}>
            <Tabs.List>
              {run.kind === 'pelican' && <Tabs.Tab value="preview">{t('Preview')}</Tabs.Tab>}
              <Tabs.Tab value="output">
                {t(run.kind === 'pelican' ? 'Raw HTML' : 'Output')}
              </Tabs.Tab>
              <Tabs.Tab value="prompt">{t('Prompt')}</Tabs.Tab>
              <Tabs.Tab value="requirements">{t('Requirements')}</Tabs.Tab>
              <Tabs.Tab value="evidence">{t('Evidence')}</Tabs.Tab>
            </Tabs.List>
            {run.kind === 'pelican' && (
              <Tabs.Panel value="preview" pt="md">
                <Text c="dimmed" size="xs" mb="sm">
                  {t(
                    'HTML runs in an isolated preview with external resources and network access blocked.',
                  )}
                </Text>
                <HtmlPreview html={run.output?.text ?? ''} large />
              </Tabs.Panel>
            )}
            <Tabs.Panel value="output" pt="md">
              <ScrollArea.Autosize mah={500}>
                <Code block className="output-code">
                  {run.output?.text || '—'}
                </Code>
              </ScrollArea.Autosize>
            </Tabs.Panel>
            <Tabs.Panel value="prompt" pt="md">
              {run.kind === 'modeltrace' ? (
                <Accordion>
                  {run.calls.map((call) => (
                    <Accordion.Item key={call.id} value={call.id!}>
                      <Accordion.Control>
                        {call.challenge_id}{' '}
                        <Badge ml="sm" variant="light">
                          {t(call.status ?? 'queued')}
                        </Badge>
                      </Accordion.Control>
                      <Accordion.Panel>
                        <Code block>{call.prompt}</Code>
                        <Text my="sm">
                          {t('Output')} · {call.output?.usage?.total_tokens ?? t('Unknown')}{' '}
                          {t('Tokens')} · {call.output?.elapsed?.toFixed(2)}s
                        </Text>
                        {call.error && <Alert color="red">{call.error}</Alert>}
                        <Code block>{call.output?.text || '—'}</Code>
                      </Accordion.Panel>
                    </Accordion.Item>
                  ))}
                </Accordion>
              ) : (
                <Code block>{run.snapshot.recipe.prompt}</Code>
              )}
            </Tabs.Panel>
            <Tabs.Panel value="requirements" pt="md">
              <Code block>
                {run.kind === 'comparison'
                  ? run.snapshot.recipe.comparison_mode === 'regex'
                    ? run.snapshot.recipe.regex_pattern
                    : run.snapshot.recipe.expected_json
                  : JSON.stringify(
                      {
                        expected_identity: run.snapshot.recipe.expected_identity,
                        challenge_ids: run.snapshot.recipe.challenge_ids,
                        version: run.snapshot.group_revision,
                      },
                      null,
                      2,
                    )}
              </Code>
            </Tabs.Panel>
            <Tabs.Panel value="evidence" pt="md">
              {run.judgment?.differences?.length ? (
                <ScrollArea>
                  <Table striped>
                    <Table.Thead>
                      <Table.Tr>
                        {['Path', 'Reason', 'Expected', 'Actual'].map((label) => (
                          <Table.Th key={label}>{t(label)}</Table.Th>
                        ))}
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {run.judgment.differences.map((difference, index) => (
                        <Table.Tr key={index}>
                          <Table.Td>{difference.path}</Table.Td>
                          <Table.Td>{t(difference.reason)}</Table.Td>
                          <Table.Td>
                            <Code>{JSON.stringify(difference.expected)}</Code>
                          </Table.Td>
                          <Table.Td>
                            <Code>{JSON.stringify(difference.actual)}</Code>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </ScrollArea>
              ) : (
                <Code block>{JSON.stringify(run.judgment?.analysis ?? {}, null, 2)}</Code>
              )}
              <Text size="sm" c="dimmed" mt="sm">
                {t('Bank version')}: {run.snapshot.fingerprint_version ?? '—'}
              </Text>
            </Tabs.Panel>
          </Tabs>
          {run.status === 'completed' && ['pelican', 'other'].includes(run.kind) && (
            <Stack gap="sm">
              <Textarea
                label={t('Review note')}
                placeholder={run.review_note ?? ''}
                value={note}
                onChange={(event) => setNote(event.currentTarget.value)}
              />
              <Group>
                <Button variant="light" onClick={() => review('pass')}>
                  {t('Mark as pass')}
                </Button>
                <Button color="red" variant="light" onClick={() => review('fail')}>
                  {t('Mark as fail')}
                </Button>
                <Button color="gray" variant="subtle" onClick={() => review(null)}>
                  {t('Clear review')}
                </Button>
              </Group>
            </Stack>
          )}
        </Stack>
      ) : (
        <Text c="dimmed">{t('Loading')}…</Text>
      )}
    </Modal>
  );
}
