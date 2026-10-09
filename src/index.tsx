import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  Router,
  showModal,
  staticClasses,
  ToggleField,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { Fragment, useEffect, useState } from "react";
import { FaMicrochip } from "react-icons/fa";
import { t } from "./i18n";

type Values = {
  ntsync: boolean;
  wow64: boolean;
  dynacache: boolean;
  log: boolean;
  preset: string;
  safeflags: string;
  box64: string;
};
type BoolKey = "ntsync" | "wow64" | "dynacache" | "log";
type State = {
  runtime: { version: string | null; installed: string[]; bundled: string[]; update: boolean };
  protons: { name: string; path: string; wow64: boolean }[];
  tools: { dir: string; name: string; source: string; source_exists: boolean; outdated: boolean; components: boolean }[];
  settings: { global: Values; games: Record<string, Partial<Values>> };
  recent: string[];
  presets: string[];
  components: string[];
};
type Job = { state: "running" | "done" | "failed"; verbs: string[]; message: string; log: string };
type GameInfo = { prefix: boolean; tool: string | null; components_ok: boolean; installed: string[]; job: Job | null };
type Reply<T> = { ok: true; result: T } | { ok: false; error: string };

const getState = callable<[], Reply<State>>("get_state");
const installRuntime = callable<[], Reply<string>>("install_runtime");
const createTool = callable<[proton: string], Reply<{ dir: string; name: string }>>("create_tool");
const removeTool = callable<[tool: string], Reply<null>>("remove_tool");
const setGlobal = callable<[key: string, value: unknown], Reply<unknown>>("set_global");
const setGame = callable<[game: string, key: string, value: unknown], Reply<unknown>>("set_game");
const resetGame = callable<[game: string], Reply<unknown>>("reset_game");
const cleanPrefix = callable<[game: string], Reply<{ moved: number }>>("clean_prefix");
const getGame = callable<[game: string], Reply<GameInfo>>("get_game");
const installComponents = callable<[game: string, verbs: string[]], Reply<Job>>("install_components");

const SAFEFLAGS = ["preset", "0", "1", "2"];
const BOOLS: { key: BoolKey; label: string; hint: string }[] = [
  { key: "ntsync", label: t.ntsync, hint: t.ntsyncHint },
  { key: "wow64", label: t.wow64, hint: t.wow64Hint },
  { key: "dynacache", label: t.dynacache, hint: t.dynacacheHint },
  { key: "log", label: t.log, hint: t.logHint },
];

function gameName(id: string): string {
  const store = (window as unknown as { appStore?: { GetAppOverviewByAppID(id: number): { display_name?: string } | null } })
    .appStore;
  return store?.GetAppOverviewByAppID(Number(id))?.display_name || id;
}

const safeflagsLabel = (v: string) => (v === "preset" ? t.fromPreset : v);
const presetLabel = (v: string) => t.presetNames[v] ?? v;
const componentLabel = (v: string) => t.componentNames[v] ?? v;

// Windows components of one game: what is installed, and one more to install with winetricks.
function GameComponents({ game, all }: { game: string; all: string[] }) {
  const [info, setInfo] = useState<GameInfo | null>(null);
  const [pick, setPick] = useState<string | undefined>();

  const load = async () => {
    const reply = await getGame(game);
    if (reply.ok) setInfo(reply.result);
  };

  useEffect(() => {
    setInfo(null);
    load();
  }, [game]);

  // While an install runs, its state is read again every few seconds.
  const running = info?.job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [running, game]);

  if (!info) return null;
  const available = all.filter((v) => !info.installed.includes(v));
  const choice = pick && available.includes(pick) ? pick : available[0];
  const blocker = !info.prefix ? t.needPrefix : !info.components_ok ? t.needGE : null;
  const job = info.job;

  const start = async () => {
    if (!choice) return;
    const reply = await installComponents(game, [choice]);
    if (!reply.ok) toaster.toast({ title: t.error, body: reply.error });
    await load();
  };

  return (
    <>
      <PanelSectionRow>
        <Field
          label={t.components}
          description={info.installed.length ? info.installed.map(componentLabel).join(", ") : t.noComponents}
        />
      </PanelSectionRow>
      {blocker ? (
        <PanelSectionRow>
          <Field description={blocker} />
        </PanelSectionRow>
      ) : (
        <>
          <PanelSectionRow>
            <DropdownItem
              label={t.addComponent}
              rgOptions={available.map((v) => ({ data: v, label: componentLabel(v) }))}
              selectedOption={choice}
              disabled={running || !available.length}
              onChange={(o) => setPick(o.data)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" description={info.tool ? `${t.withTool} ${info.tool}` : undefined}
              disabled={running || !choice} onClick={start}>
              {running ? t.installing(job!.verbs.map(componentLabel).join(", ")) : t.install}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {job && job.state !== "running" && (
        <PanelSectionRow>
          <Field description={job.state === "done" ? t.installed(job.verbs.map(componentLabel).join(", ")) : `${job.message} (${job.log})`} />
        </PanelSectionRow>
      )}
    </>
  );
}

function Content() {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [restart, setRestart] = useState(false);
  const running = Router.MainRunningApp?.appid;
  const [game, setGameId] = useState<string | undefined>(running ? String(running) : undefined);

  const refresh = async () => {
    const reply = await getState();
    if (reply.ok) setState(reply.result);
    else toaster.toast({ title: t.error, body: reply.error });
  };

  // Runs one backend call, reports a failure, then reloads everything from disk.
  const run = async <T,>(call: () => Promise<Reply<T>>): Promise<T | undefined> => {
    setBusy(true);
    try {
      const reply = await call();
      if (!reply.ok) {
        toaster.toast({ title: t.error, body: reply.error });
        return undefined;
      }
      return reply.result;
    } finally {
      await refresh();
      setBusy(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  if (!state) return null;
  const { runtime, settings } = state;
  const globals = settings.global;

  const versionLabel = (v: string) => (v === "latest" ? `${t.newest} (${runtime.installed[0] ?? "-"})` : v);
  const versionOptions = ["latest", ...runtime.installed].map((v) => ({ data: v, label: versionLabel(v) }));

  const games = [
    ...new Set([...(running ? [String(running)] : []), ...state.recent, ...Object.keys(settings.games)]),
  ];
  const selected = game && games.includes(game) ? game : games[0];
  const overrides = (selected && settings.games[selected]) || {};

  const toggleProton = async (name: string, path: string, on: boolean) => {
    const existing = state.tools.find((tool) => tool.source === path);
    const done = on
      ? await run(() => createTool(name))
      : existing && (await run(() => removeTool(existing.dir)));
    if (done !== undefined) setRestart(true);
  };

  const confirmClean = (id: string) =>
    showModal(
      <ConfirmModal
        strTitle={t.cleanTitle}
        strDescription={t.cleanBody}
        onOK={async () => {
          const result = await run(() => cleanPrefix(id));
          if (result) toaster.toast({ title: gameName(id), body: t.cleaned(result.moved) });
        }}
      />,
    );

  return (
    <>
      <PanelSection title={t.box64}>
        <PanelSectionRow>
          <Field
            label={runtime.version ?? t.notInstalled}
            description={runtime.installed.length ? `${t.versions}: ${runtime.installed.join(", ")}` : undefined}
          />
        </PanelSectionRow>
        {(runtime.update || !runtime.version) && runtime.bundled.length > 0 && (
          <PanelSectionRow>
            <ButtonItem layout="below" description={`${t.bundled}: ${runtime.bundled.join(", ")}`} disabled={busy}
              onClick={() => run(installRuntime)}>
              {runtime.installed.length ? t.updateBox64 : t.installBox64}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title={t.protons}>
        {state.protons.length === 0 && (
          <PanelSectionRow>
            <Field description={t.noProtons} />
          </PanelSectionRow>
        )}
        {state.protons.map((proton) => {
          const tool = state.tools.find((x) => x.source === proton.path);
          return (
            <Fragment key={proton.path}>
              <PanelSectionRow>
                <ToggleField
                  label={proton.name}
                  description={tool ? `${t.toolOn} "${tool.name}"` : proton.wow64 ? undefined : t.noWow64}
                  checked={!!tool}
                  disabled={busy || !runtime.version}
                  onChange={(on) => toggleProton(proton.name, proton.path, on)}
                />
              </PanelSectionRow>
              {tool?.outdated && (
                <PanelSectionRow>
                  <ButtonItem
                    layout="below"
                    description={t.outdated}
                    disabled={busy || !runtime.version}
                    onClick={() => run(() => createTool(proton.name))}
                  >
                    {t.updateTool}
                  </ButtonItem>
                </PanelSectionRow>
              )}
            </Fragment>
          );
        })}
        {state.tools
          .filter((tool) => !tool.source_exists)
          .map((tool) => (
            <PanelSectionRow key={tool.dir}>
              <ButtonItem
                label={tool.name}
                description={t.orphan}
                disabled={busy}
                onClick={async () => (await run(() => removeTool(tool.dir))) !== undefined && setRestart(true)}
              >
                {t.remove}
              </ButtonItem>
            </PanelSectionRow>
          ))}
        {restart && (
          <PanelSectionRow>
            <ButtonItem layout="below" description={t.restartHint} onClick={() => SteamClient.User.StartRestart(false)}>
              {t.restartSteam}
            </ButtonItem>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title={t.defaults}>
        {BOOLS.map(({ key, label, hint }) => (
          <PanelSectionRow key={key}>
            <ToggleField
              label={label}
              description={hint}
              checked={globals[key]}
              disabled={busy}
              onChange={(value) => run(() => setGlobal(key, value))}
            />
          </PanelSectionRow>
        ))}
        <PanelSectionRow>
          <DropdownItem
            label={t.box64Version}
            rgOptions={versionOptions}
            selectedOption={globals.box64}
            disabled={busy}
            onChange={(o) => run(() => setGlobal("box64", o.data))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label={t.preset}
            rgOptions={state.presets.map((p) => ({ data: p, label: presetLabel(p) }))}
            selectedOption={globals.preset}
            disabled={busy}
            onChange={(o) => run(() => setGlobal("preset", o.data))}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <DropdownItem
            label={t.safeflags}
            rgOptions={SAFEFLAGS.map((v) => ({ data: v, label: safeflagsLabel(v) }))}
            selectedOption={globals.safeflags}
            disabled={busy}
            onChange={(o) => run(() => setGlobal("safeflags", o.data))}
          />
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title={t.game}>
        {!selected ? (
          <PanelSectionRow>
            <Field description={t.noGames} />
          </PanelSectionRow>
        ) : (
          <>
            <PanelSectionRow>
              <DropdownItem
                label={t.pickGame}
                rgOptions={games.map((id) => ({
                  data: id,
                  label: id === String(running) ? `${gameName(id)} (${t.running})` : gameName(id),
                }))}
                selectedOption={selected}
                onChange={(o) => setGameId(o.data)}
              />
            </PanelSectionRow>
            {BOOLS.map(({ key, label }) => (
              <PanelSectionRow key={key}>
                <DropdownItem
                  label={label}
                  rgOptions={[
                    { data: "default", label: `${t.useDefault} (${globals[key] ? t.on : t.off})` },
                    { data: "on", label: t.on },
                    { data: "off", label: t.off },
                  ]}
                  selectedOption={overrides[key] === undefined ? "default" : overrides[key] ? "on" : "off"}
                  disabled={busy}
                  onChange={(o) => run(() => setGame(selected, key, o.data === "default" ? null : o.data === "on"))}
                />
              </PanelSectionRow>
            ))}
            <PanelSectionRow>
              <DropdownItem
                label={t.box64Version}
                rgOptions={[{ data: "inherit", label: `${t.useDefault} (${versionLabel(globals.box64)})` }, ...versionOptions]}
                selectedOption={overrides.box64 ?? "inherit"}
                disabled={busy}
                onChange={(o) => run(() => setGame(selected, "box64", o.data === "inherit" ? null : o.data))}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <DropdownItem
                label={t.preset}
                rgOptions={[
                  { data: "inherit", label: `${t.useDefault} (${presetLabel(globals.preset)})` },
                  ...state.presets.map((p) => ({ data: p, label: presetLabel(p) })),
                ]}
                selectedOption={overrides.preset ?? "inherit"}
                disabled={busy}
                onChange={(o) => run(() => setGame(selected, "preset", o.data === "inherit" ? null : o.data))}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <DropdownItem
                label={t.safeflags}
                rgOptions={[
                  { data: "inherit", label: `${t.useDefault} (${safeflagsLabel(globals.safeflags)})` },
                  ...SAFEFLAGS.map((v) => ({ data: v, label: safeflagsLabel(v) })),
                ]}
                selectedOption={overrides.safeflags ?? "inherit"}
                disabled={busy}
                onChange={(o) => run(() => setGame(selected, "safeflags", o.data === "inherit" ? null : o.data))}
              />
            </PanelSectionRow>
            {Object.keys(overrides).length > 0 && (
              <PanelSectionRow>
                <ButtonItem layout="below" disabled={busy} onClick={() => run(() => resetGame(selected))}>
                  {t.resetGame}
                </ButtonItem>
              </PanelSectionRow>
            )}
            <GameComponents game={selected} all={state.components} />
            <PanelSectionRow>
              <ButtonItem layout="below" description={t.cleanPrefixHint} disabled={busy} onClick={() => confirmClean(selected)}>
                {t.cleanPrefix}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
        <PanelSectionRow>
          <Field description={t.precedence} />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "Armada Box64",
  titleView: <div className={staticClasses.Title}>Armada Box64</div>,
  content: <Content />,
  icon: <FaMicrochip />,
}));
