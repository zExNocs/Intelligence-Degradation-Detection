import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Button,
  ColorInput,
  Divider,
  Group,
  Loader,
  MantineProvider,
  Menu,
  NavLink,
  Paper,
  PasswordInput,
  Popover,
  SegmentedControl,
  Stack,
  Text,
  Title,
  Tooltip,
  createTheme,
  type MantineColorsTuple,
} from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
import { Notifications } from '@mantine/notifications';
import {
  IconBike,
  IconBrain,
  IconFingerprint,
  IconGitCompare,
  IconLanguage,
  IconLayoutDashboard,
  IconLogout,
  IconPalette,
  IconServer,
  IconSettings,
  IconShieldLock,
  IconTerminal2,
} from '@tabler/icons-react';
import { QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, queryClient, send, type Session } from './api';
import { RefreshProvider } from './state';
import { AccountsPage } from './pages/Accounts';
import { ChecksPage } from './pages/Checks';
import { DashboardPage } from './pages/Dashboard';
import { SettingsPage } from './pages/Settings';
import { ErrorNotice } from './components/Common';

type Page =
  'dashboard' | 'accounts' | 'pelican' | 'comparison' | 'modeltrace' | 'other' | 'settings';
type Mode = 'auto' | 'light' | 'dark';
const navigation = [
  { id: 'dashboard', name: 'Dashboard', icon: IconLayoutDashboard },
  { id: 'accounts', name: 'Models', icon: IconServer },
  { id: 'pelican', name: 'Pelican', icon: IconBike },
  { id: 'comparison', name: 'Comparison', icon: IconGitCompare },
  { id: 'modeltrace', name: 'ModelTrace', icon: IconFingerprint },
  { id: 'other', name: 'Other checks', icon: IconTerminal2 },
] as const;

/** Derive a full accessible component palette from the selected primary color. */
function palette(hex: string): MantineColorsTuple {
  function mix(weight: number) {
    const base = [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16));
    return `#${base
      .map((channel) =>
        Math.round(weight >= 0 ? channel + (255 - channel) * weight : channel * (1 + weight))
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')}`;
  }
  return [
    mix(0.94),
    mix(0.85),
    mix(0.7),
    mix(0.5),
    mix(0.3),
    mix(0.12),
    hex,
    mix(-0.12),
    mix(-0.25),
    mix(-0.4),
  ];
}

function Controls({
  mode,
  setMode,
  primary,
  setPrimary,
  background,
  setBackground,
  accent,
  setAccent,
}: {
  mode: Mode;
  setMode: (value: Mode) => void;
  primary: string;
  setPrimary: (value: string) => void;
  background: string;
  setBackground: (value: string) => void;
  accent: string;
  setAccent: (value: string) => void;
}) {
  const { t, i18n } = useTranslation();
  return (
    <Group gap="xs">
      <Menu position="bottom-end">
        <Menu.Target>
          <ActionIcon variant="default" size="lg" aria-label={t('Language')}>
            <IconLanguage size={19} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          {[
            { id: 'en', label: 'English' },
            { id: 'zh', label: '简体中文' },
          ].map((language) => (
            <Menu.Item
              key={language.id}
              onClick={() => {
                void i18n.changeLanguage(language.id);
                localStorage.setItem('idd-language', language.id);
                document.documentElement.lang = language.id;
              }}
            >
              {language.label}
            </Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>
      <Popover position="bottom-end" width={300} shadow="md">
        <Popover.Target>
          <ActionIcon variant="default" size="lg" aria-label={t('Appearance')}>
            <IconPalette size={19} />
          </ActionIcon>
        </Popover.Target>
        <Popover.Dropdown>
          <Stack gap="sm">
            <Text fw={600}>{t('Appearance')}</Text>
            <SegmentedControl
              value={mode}
              onChange={(value) => setMode(value as Mode)}
              data={[
                { value: 'auto', label: t('System') },
                { value: 'light', label: t('Light') },
                { value: 'dark', label: t('Dark') },
              ]}
            />
            <ColorInput
              label={t('Background')}
              value={background}
              onChange={setBackground}
              placeholder="Default"
            />
            <ColorInput label={t('Primary')} value={primary} onChange={setPrimary} />
            <ColorInput label={t('Accent')} value={accent} onChange={setAccent} />
            <Button
              variant="subtle"
              size="xs"
              onClick={() => {
                setMode('auto');
                setPrimary('#0f766e');
                setBackground('');
                setAccent('#d49b48');
              }}
            >
              {t('Reset appearance')}
            </Button>
          </Stack>
        </Popover.Dropdown>
      </Popover>
    </Group>
  );
}

function Login({ signedIn }: { signedIn: (session: Session) => void }) {
  const { t } = useTranslation();
  const [token, setToken] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);
  return (
    <div className="login-screen">
      <div className="login-intro">
        <div className="brand-symbol large">
          <IconBrain size={34} stroke={1.5} />
        </div>
        <Text className="eyebrow" mt="xl">
          INTELLIGENCE DEGRADATION DETECTION
        </Text>
        <Title order={1} mt="md">
          {t('Observe. Compare. Understand.')}
        </Title>
        <Text c="dimmed" mt="md">
          {t('Model evaluation workspace')}
        </Text>
      </div>
      <Paper withBorder p={36} radius="xl" className="login-card">
        <IconShieldLock size={28} stroke={1.5} />
        <Title order={2} mt="md">
          {t('Private workspace')}
        </Title>
        <Text c="dimmed" size="sm" mt="sm" mb="xl">
          {t('Enter the token from your server authentication file.')}
        </Text>
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            setLoading(true);
            try {
              const session = await send<Session>('/auth/session', { token });
              setToken('');
              signedIn(session);
            } catch (error) {
              setError(error instanceof Error ? error : new Error('Request failed'));
            } finally {
              setLoading(false);
            }
          }}
        >
          <Stack>
            <ErrorNotice error={error} />
            <PasswordInput
              required
              label={t('Access token')}
              autoComplete="current-password"
              value={token}
              onChange={(event) => setToken(event.currentTarget.value)}
            />
            <Button type="submit" fullWidth loading={loading}>
              {t('Sign in')}
            </Button>
          </Stack>
        </form>
      </Paper>
    </div>
  );
}

export default function App() {
  const { t } = useTranslation();
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [version, setVersion] = useState('');
  const [page, setPage] = useState<Page>('dashboard');
  const [opened, { toggle, close }] = useDisclosure();
  const [mode, setMode] = useState<Mode>(() => {
    const value = localStorage.getItem('idd-mode');
    return value === 'light' || value === 'dark' ? value : 'auto';
  });
  const [primary, setPrimary] = useState(localStorage.getItem('idd-primary') ?? '#0f766e');
  const [background, setBackground] = useState(localStorage.getItem('idd-background') ?? '');
  const [accent, setAccent] = useState(localStorage.getItem('idd-accent') ?? '#d49b48');
  const prefersDark = useMediaQuery('(prefers-color-scheme: dark)');
  const color = /^#[0-9a-f]{6}$/i.test(primary) ? primary : '#0f766e';
  useEffect(() => {
    const unauthorized = () => {
      setAuthenticated(false);
      queryClient.clear();
    };
    window.addEventListener('idd:unauthorized', unauthorized);
    void api<Session>('/auth/session')
      .then((session) => {
        setVersion(session.version);
        setAuthenticated(true);
      })
      .catch(() => setAuthenticated(false));
    return () => window.removeEventListener('idd:unauthorized', unauthorized);
  }, []);
  useEffect(() => {
    for (const [key, value] of Object.entries({ mode, primary, background, accent }))
      localStorage.setItem(`idd-${key}`, value);
    document.documentElement.style.setProperty(
      '--app-bg',
      /^#[0-9a-f]{6}$/i.test(background) ? background : '',
    );
    document.documentElement.style.setProperty(
      '--accent-color',
      /^#[0-9a-f]{6}$/i.test(accent) ? accent : '#d49b48',
    );
  }, [mode, primary, background, accent]);
  const controls = (
    <Controls
      {...{ mode, setMode, primary, setPrimary, background, setBackground, accent, setAccent }}
    />
  );
  return (
    <MantineProvider
      theme={createTheme({
        primaryColor: 'brand',
        colors: { brand: palette(color) },
        defaultRadius: 'md',
        fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif',
        headings: { fontWeight: '650' },
      })}
      forceColorScheme={mode === 'auto' ? (prefersDark ? 'dark' : 'light') : mode}
    >
      <Notifications position="top-right" />
      <QueryClientProvider client={queryClient}>
        <RefreshProvider>
          {authenticated == null ? (
            <div className="initial-loading">
              <Loader />
            </div>
          ) : !authenticated ? (
            <>
              <div className="login-controls">{controls}</div>
              <Login
                signedIn={(session) => {
                  setVersion(session.version);
                  setAuthenticated(true);
                }}
              />
            </>
          ) : (
            <AppShell
              header={{ height: 74 }}
              navbar={{ width: 246, breakpoint: 'sm', collapsed: { mobile: !opened } }}
              padding={{ base: 'md', md: 'xl' }}
            >
              <AppShell.Header>
                <Group h="100%" px="xl" justify="space-between">
                  <Group>
                    <Burger
                      aria-label="Toggle navigation"
                      opened={opened}
                      onClick={toggle}
                      hiddenFrom="sm"
                      size="sm"
                    />
                    <div className="brand-symbol">
                      <IconBrain size={23} stroke={1.6} />
                    </div>
                    <Stack gap={0}>
                      <Text fw={700} size="sm">
                        IDD
                      </Text>
                      <Text c="dimmed" size="xs" visibleFrom="sm">
                        {t('Model evaluation workspace')}
                      </Text>
                    </Stack>
                  </Group>
                  {controls}
                </Group>
              </AppShell.Header>
              <AppShell.Navbar p="md">
                <Text className="eyebrow" px="sm" mt="sm" mb="md">
                  {t('Workspace')}
                </Text>
                <Stack gap={5}>
                  {navigation.map((item) => (
                    <NavLink
                      key={item.id}
                      label={t(item.name)}
                      active={page === item.id}
                      leftSection={<item.icon size={19} stroke={1.6} />}
                      onClick={() => {
                        setPage(item.id);
                        close();
                      }}
                      className="nav-item"
                    />
                  ))}
                </Stack>
                <div className="sidebar-bottom">
                  <Paper p="md" className="workspace-note">
                    <Group gap={7}>
                      <span className="status-dot" />
                      <Text size="xs" fw={600}>
                        {t('Private workspace')}
                      </Text>
                    </Group>
                    <Text size="xs" c="dimmed" mt={6}>
                      {version ? `v${version}` : ''}
                    </Text>
                  </Paper>
                  <Divider my="md" />
                  <NavLink
                    label={t('Settings')}
                    leftSection={<IconSettings size={19} />}
                    active={page === 'settings'}
                    onClick={() => {
                      setPage('settings');
                      close();
                    }}
                    className="nav-item"
                  />
                  <NavLink
                    label={t('Sign out')}
                    leftSection={<IconLogout size={19} />}
                    onClick={async () => {
                      await send('/auth/session', undefined, 'DELETE');
                      setAuthenticated(false);
                      queryClient.clear();
                    }}
                    className="nav-item"
                  />
                </div>
              </AppShell.Navbar>
              <AppShell.Main>
                <div className="page-content">
                  {page === 'dashboard' ? (
                    <DashboardPage />
                  ) : page === 'accounts' ? (
                    <AccountsPage />
                  ) : page === 'settings' ? (
                    <SettingsPage />
                  ) : (
                    <ChecksPage key={page} kind={page} />
                  )}
                </div>
              </AppShell.Main>
            </AppShell>
          )}
        </RefreshProvider>
      </QueryClientProvider>
    </MantineProvider>
  );
}
