import {
  Accordion,
  ActionIcon,
  Alert,
  Badge,
  Button,
  Code,
  Group as ButtonGroup,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from '@mantine/core';
import { useElementSize, useIntersection } from '@mantine/hooks';
import { useQuery } from '@tanstack/react-query';
import {
  IconBrandGithub,
  IconChevronLeft,
  IconChevronRight,
  IconEdit,
  IconFingerprint,
  IconPlayerPlay,
  IconPlayerStop,
  IconPlus,
  IconTrash,
} from '@tabler/icons-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  type Account,
  type Catalog,
  type Challenge,
  type Group,
  type History,
  type Kind,
  type RunDetail,
  type RunSummary,
  type Settings,
  api,
  refreshViews,
  send,
} from '../api';
import { formatTime, useLive, useServerClock } from '../state';
import { CostNotice, ErrorNotice, PageHeader, ResultBadge, showError } from '../components/Common';
import { GroupEditor } from '../components/GroupEditor';
import { HtmlPreview } from '../components/HtmlPreview';
import { RunDetails } from '../components/RunDetails';

const pageNames: Record<Kind, string> = {
  pelican: 'Pelican',
  comparison: 'Comparison',
  modeltrace: 'ModelTrace',
  other: 'Other checks',
};

function ResultCell({
  run,
  kind,
  view,
}: {
  run?: RunSummary;
  kind: Kind;
  view: (id: string) => void;
}) {
  const { t } = useTranslation();
  const { ref, entry } = useIntersection<HTMLButtonElement>({ threshold: 0.05 });
  const detail = useQuery({
    queryKey: ['thumbnail', run?.id],
    queryFn: () => api<RunDetail>(`/runs/${run?.id}`),
    enabled: !!run && kind === 'pelican' && run.status === 'completed' && !!entry?.isIntersecting,
    staleTime: Infinity,
  });
  const tone = !run
    ? 'empty'
    : run.status === 'queued' || run.status === 'running'
      ? 'pending'
      : run.status !== 'completed'
        ? 'exception'
        : run.score != null
          ? run.score === 1
            ? 'good'
            : run.score >= 0.5
              ? 'partial'
              : 'bad'
          : run.review === 'fail' || run.verdict === 'suspected_mismatch'
            ? 'bad'
            : run.review === 'pass' || run.verdict === 'consistent'
              ? 'good'
              : 'neutral';
  return (
    <button
      ref={ref}
      type="button"
      disabled={!run}
      className={`result-cell ${tone} ${kind === 'pelican' ? 'visual-cell' : ''}`}
      onClick={() => run && view(run.id)}
      aria-label={run ? `${t('Result details')} ${run.model} ${run.id}` : t('No result')}
    >
      {run ? (
        <>
          {kind === 'pelican' && detail.data?.output?.text && (
            <HtmlPreview html={detail.data.output.text} />
          )}
          <ResultBadge status={run.status} verdict={run.review ?? run.verdict} score={run.score} />
          {kind !== 'pelican' && kind !== 'comparison' && (
            <Text size="xs" c="dimmed" lineClamp={3} mt="sm">
              {run.preview || '—'}
            </Text>
          )}
          <div className="result-meta">
            <span>
              {run.total_tokens ?? t('Unknown')} {t('Tokens')}
            </span>
            <span>{run.elapsed?.toFixed(1)}s</span>
          </div>
        </>
      ) : (
        <Text size="xs" c="dimmed">
          {t('No result')}
        </Text>
      )}
    </button>
  );
}

function GroupMatrix({
  group,
  accounts,
  edit,
  view,
}: {
  group: Group;
  accounts: Account[];
  edit: () => void;
  view: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  const { ref, width } = useElementSize();
  const limit = Math.max(
    1,
    Math.min(8, Math.floor((width - 240) / (group.recipe.kind === 'pelican' ? 248 : 174))),
  );
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const { now, timezone } = useServerClock();
  useEffect(() => setOffset(0), [limit, group.id]);
  const history = useLive<History>(
    ['history', group.id, offset, limit],
    `/groups/${group.id}/history?offset=${offset}&limit=${limit}`,
  );
  const columns = history.data?.batches.length ? history.data.batches : ['empty'];
  const countdown =
    group.next_run_at && now ? Math.max(0, Math.ceil(group.next_run_at - now)) : null;
  async function action(path: string, key: string) {
    setBusy(key);
    try {
      await send(path);
      await refreshViews();
    } catch (error) {
      showError(error);
    } finally {
      setBusy(null);
    }
  }
  return (
    <Paper withBorder p="lg" radius="lg" className="matrix-panel" ref={ref}>
      <ButtonGroup justify="space-between" mb="lg" align="flex-start">
        <Stack gap={4}>
          <ButtonGroup gap="sm">
            <Title order={3} size="h4">
              {group.recipe.name}
            </Title>
            <Badge color={group.recipe.enabled ? 'teal' : 'gray'} variant="dot">
              {group.recipe.enabled ? group.recipe.cron : t('Paused')}
            </Badge>
          </ButtonGroup>
          <Text c="dimmed" size="xs">
            {group.targets.length} {t('Checks')} · {timezone}
          </Text>
        </Stack>
        <ButtonGroup gap="xs">
          <Button
            variant="light"
            size="xs"
            leftSection={<IconPlayerPlay size={14} />}
            loading={busy === 'group'}
            onClick={() => action(`/groups/${group.id}/run`, 'group')}
          >
            {t('Run group')}
          </Button>
          <Tooltip label={t('Edit')}>
            <ActionIcon
              variant="subtle"
              aria-label={`${t('Edit')} ${group.recipe.name}`}
              onClick={edit}
            >
              <IconEdit size={17} />
            </ActionIcon>
          </Tooltip>
          <Tooltip label={t('Delete')}>
            <ActionIcon
              variant="subtle"
              color="red"
              aria-label={`${t('Delete')} ${group.recipe.name}`}
              onClick={async () => {
                if (
                  !window.confirm(
                    t('Remove this idle group and its checks? Historical records remain retained.'),
                  )
                )
                  return;
                try {
                  await send(`/groups/${group.id}`, undefined, 'DELETE');
                  await refreshViews();
                } catch (error) {
                  showError(error);
                }
              }}
            >
              <IconTrash size={17} />
            </ActionIcon>
          </Tooltip>
        </ButtonGroup>
      </ButtonGroup>
      <ErrorNotice error={history.error} />
      <div className="matrix-scroll">
        <Table className="history-matrix" verticalSpacing="md">
          <Table.Thead>
            <Table.Tr>
              <Table.Th className="model-column">{t('Model')}</Table.Th>
              {columns.map((batch) => (
                <Table.Th key={batch}>
                  {formatTime(
                    history.data?.runs.find((run) => run.batch_id === batch)?.created_at,
                    timezone,
                    i18n.language,
                  )}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {group.targets.map((target) => {
              const account = accounts.find((account) => account.id === target.account_id);
              const active = group.active_runs?.[target.id!];
              return (
                <Table.Tr key={target.id}>
                  <Table.Td className="model-column">
                    <Text fw={600} size="sm">
                      {account?.name ?? target.account_id}
                    </Text>
                    <Text size="xs" className="model-id">
                      {target.model}
                    </Text>
                    <Text size="xs" c="dimmed" mt={3}>
                      {target.effort}
                    </Text>
                    <Text size="xs" c="dimmed" mt="sm">
                      {t('Next run')}:{' '}
                      {group.recipe.enabled
                        ? countdown == null
                          ? '—'
                          : `${Math.floor(countdown / 60)}m ${countdown % 60}s`
                        : t('Paused')}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {formatTime(group.next_run_at, timezone, i18n.language)}
                    </Text>
                    <ButtonGroup gap={6} mt="sm">
                      <Tooltip label={t('Run now')}>
                        <ActionIcon
                          variant="light"
                          aria-label={`${t('Run now')} ${account?.name}`}
                          disabled={!!active}
                          loading={busy === target.id}
                          onClick={() => action(`/targets/${target.id}/run`, target.id!)}
                        >
                          <IconPlayerPlay size={16} />
                        </ActionIcon>
                      </Tooltip>
                      {active && (
                        <Tooltip label={t('Cancel run')}>
                          <ActionIcon
                            color="red"
                            variant="light"
                            aria-label={`${t('Cancel run')} ${account?.name}`}
                            onClick={() => action(`/runs/${active}/cancel`, active)}
                          >
                            <IconPlayerStop size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </ButtonGroup>
                  </Table.Td>
                  {columns.map((batch) => (
                    <Table.Td key={batch}>
                      <ResultCell
                        run={history.data?.runs.find(
                          (run) => run.target_id === target.id && run.batch_id === batch,
                        )}
                        kind={group.recipe.kind}
                        view={view}
                      />
                    </Table.Td>
                  ))}
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </div>
      <ButtonGroup justify="flex-end" mt="md">
        <Button
          size="xs"
          variant="default"
          disabled={offset === 0}
          leftSection={<IconChevronLeft size={14} />}
          onClick={() => setOffset(Math.max(0, offset - limit))}
        >
          {t('Newer')}
        </Button>
        <Button
          size="xs"
          variant="default"
          disabled={!history.data?.has_more}
          rightSection={<IconChevronRight size={14} />}
          onClick={() => setOffset(offset + limit)}
        >
          {t('More history')}
        </Button>
      </ButtonGroup>
    </Paper>
  );
}

function FingerprintInfo({ close }: { close: () => void }) {
  const { t, i18n } = useTranslation();
  const challenges = useLive<Challenge[]>(['challenges'], '/fingerprint/challenges');
  const catalog = useLive<Catalog>(['fingerprint-catalog'], '/fingerprint/catalog');
  return (
    <Modal opened onClose={close} title={t('View prompts and fingerprint bank')} size="xl">
      <Stack>
        <Alert color="blue">
          {t(
            'Attribution is relative to the loaded candidate bank, not proof of model identity. Unlisted models may resemble listed candidates.',
          )}
        </Alert>
        <Text size="sm">
          75% nuisance-projected Hellinger + 25% ordered-block sequence fingerprint
        </Text>
        <ButtonGroup gap={6}>
          {catalog.data?.models.map((model) => (
            <Badge key={model.id} variant="light">
              {model.id}
            </Badge>
          ))}
        </ButtonGroup>
        <Text size="xs" c="dimmed">
          {t('Bank version')}: {catalog.data?.version}
        </Text>
        <Accordion>
          {challenges.data?.map((challenge) => (
            <Accordion.Item key={challenge.id} value={challenge.id}>
              <Accordion.Control>
                {i18n.language === 'zh' ? challenge.name : challenge.name_en}
              </Accordion.Control>
              <Accordion.Panel>
                <Code block>{challenge.prompt}</Code>
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      </Stack>
    </Modal>
  );
}

export function ChecksPage({ kind }: { kind: Kind }) {
  const { t } = useTranslation();
  const groups = useLive<Group[]>(['groups'], '/groups');
  const accounts = useLive<Account[]>(['accounts'], '/accounts');
  const settings = useLive<Settings>(['settings'], '/settings');
  const [editor, setEditor] = useState<Group | 'new' | null>(null);
  const [details, setDetails] = useState<string | null>(null);
  const [fingerprintInfo, setFingerprintInfo] = useState(false);
  const visible = groups.data?.filter((group) => group.recipe.kind === kind) ?? [];
  return (
    <>
      <PageHeader
        title={pageNames[kind]}
        subtitle="Observe. Compare. Understand."
        action={
          <Button
            leftSection={<IconPlus size={17} />}
            disabled={!settings.data}
            onClick={() => setEditor('new')}
          >
            {t('Create test group')}
          </Button>
        }
      />
      <CostNotice />
      {kind === 'modeltrace' && (
        <ButtonGroup mb="lg">
          <Button
            variant="light"
            leftSection={<IconFingerprint size={18} />}
            onClick={() => setFingerprintInfo(true)}
          >
            {t('View prompts and fingerprint bank')}
          </Button>
          <Button
            component="a"
            href="https://github.com/xqy2006/ModelTrace"
            target="_blank"
            rel="noopener noreferrer"
            variant="default"
            leftSection={<IconBrandGithub size={18} />}
          >
            {t('ModelTrace on GitHub')}
          </Button>
        </ButtonGroup>
      )}
      <ErrorNotice error={groups.error} />
      <Stack gap="xl">
        {visible.map((group) => (
          <GroupMatrix
            key={group.id}
            group={group}
            accounts={accounts.data ?? []}
            edit={() => setEditor(group)}
            view={setDetails}
          />
        ))}
      </Stack>
      {!visible.length && !groups.isLoading && (
        <Paper withBorder p={50} className="empty-state">
          <IconPlus size={40} stroke={1.2} />
          <Title order={3} mt="md">
            {t('No checks yet')}
          </Title>
          <Text c="dimmed" mt="sm">
            {t('Create a group to compare accounts using the same prompt and schedule.')}
          </Text>
        </Paper>
      )}
      {editor && settings.data && (
        <GroupEditor
          kind={kind}
          existing={editor === 'new' ? undefined : editor}
          settings={settings.data}
          close={() => setEditor(null)}
        />
      )}
      <RunDetails id={details} onClose={() => setDetails(null)} />
      {fingerprintInfo && <FingerprintInfo close={() => setFingerprintInfo(false)} />}
    </>
  );
}
