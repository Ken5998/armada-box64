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
import { callable, definePlugin, toaster, useQuickAccessVisible } from "@decky/api";
import { Fragment, ReactNode, useEffect, useState } from "react";
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
type Catalog = {
  versions: { tag: string; size: number }[];
  plugin: { version: string } | null;
  current: string;
};
type PluginDownload = { path: string; version: string; sha256: string };

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
const getCatalog = callable<[refresh: boolean], Reply<Catalog>>("get_catalog");
const downloadVersion = callable<[tag: string], Reply<string[]>>("download_version");
const removeVersion = callable<[tag: string], Reply<string[]>>("remove_version");
const downloadPlugin = callable<[], Reply<PluginDownload>>("download_plugin");

// Decky's own installer: it asks for confirmation, replaces the plugin and reloads it.
const UPDATE = 2;
function deckyInstall(update: PluginDownload) {
  const backend = (window as unknown as { DeckyBackend: { call(route: string, ...args: unknown[]): Promise<unknown> } })
    .DeckyBackend;
  return backend.call("utilities/install_plugin", `file://${update.path}`, "Armada Box64", update.version,
    update.sha256, UPDATE);
}

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

// What the panel shows and what was picked in it. It lives outside the components, so the
// panel comes back exactly as it was when Steam rebuilds it (for example after closing the
// Quick Access menu) instead of starting empty and scrolled to the top.
const kept: {
  state?: State;
  catalog?: Catalog;
  games: Record<string, GameInfo>;
  picks: Record<string, string | undefined>;
} = { games: {}, picks: {} };

function useKept<T>(read: () => T, write: (value: T) => void): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(read);
  return [value, (next: T) => {
    write(next);
    setValue(next);
  }];
}
const usePick = (key: string) => useKept(() => kept.picks[key], (v) => (kept.picks[key] = v));

// One backend call at a time. Controls stay enabled while it runs: Steam moves the gamepad
// focus (and the scroll position) away from a control that becomes disabled.
let working = false;

// Windows components of one game: they go into that game's own prefix, installed with
// winetricks through the Box64 tool the game last started with.
function GameComponents({ game, all }: { game: string; all: string[] }) {
  // The state only triggers a new render; the kept copy is per game and survives a rebuild.
  const [, setInfo] = useKept<GameInfo | undefined>(() => kept.games[game], (v) => v && (kept.games[game] = v));
  const [pick, setPick] = usePick(`component:${game}`);
  const current = kept.games[game];

  const load = async () => {
    const reply = await getGame(game);
    if (reply.ok) setInfo(reply.result);
  };

  useEffect(() => {
    load();
  }, [game]);

  // While an install runs, its state is read again every few seconds.
  const running = current?.job?.state === "running";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [running, game]);

  if (!current) return null;
  const available = all.filter((v) => !current.installed.includes(v));
  const choice = pick && available.includes(pick) ? pick : available[0];
  const blocker = !current.prefix ? t.needPrefix : !current.components_ok ? t.needGE : null;
  const job = current.job;

  const start = async () => {
    if (!choice || running) return;
    const reply = await installComponents(game, [choice]);
    if (!reply.ok) toaster.toast({ title: t.error, body: reply.error });
    await load();
  };

  return (
    <PanelSection title={t.componentsFor(gameName(game))}>
      <PanelSectionRow>
        <Field
          description={blocker ?? t.componentsWhere(current.tool ?? "-")}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <Field
          label={t.installedHere}
          description={current.installed.length ? current.installed.map(componentLabel).join(", ") : t.noComponents}
        />
      </PanelSectionRow>
      {!blocker && available.length > 0 && (
        <>
          <PanelSectionRow>
            <DropdownItem
              label={t.addComponent}
              menuLabel={t.addComponent}
              rgOptions={available.map((v) => ({ data: v, label: componentLabel(v) }))}
              selectedOption={choice}
              onChange={(o) => setPick(o.data)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={start}>
              {running ? t.installing(job!.verbs.map(componentLabel).join(", ")) : t.installThis(componentLabel(choice!))}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {job && job.state !== "running" && (
        <PanelSectionRow>
          <Field description={job.state === "done" ? t.installed(job.verbs.map(componentLabel).join(", ")) : `${job.message} (${job.log})`} />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function Content() {
  const [state, setStateNow] = useKept<State | undefined>(() => kept.state, (v) => (kept.state = v));
  const [catalog, setCatalog] = useKept<Catalog | undefined>(() => kept.catalog, (v) => (kept.catalog = v));
  const [busy, setBusy] = useState(working);
  const [restart, setRestart] = usePick("restart");
  const running = Router.MainRunningApp?.appid;
  const [game, setGameId] = usePick("game");
  const [fetch, setFetch] = usePick("download");
  const [drop, setDrop] = usePick("remove");

  // Looks for new Box64 versions and plugin releases; a quiet check when the panel opens.
  const check = async (refresh: boolean) => {
    const reply = await getCatalog(refresh);
    if (reply.ok) setCatalog(reply.result);
    else if (refresh) toaster.toast({ title: t.error, body: reply.error });
    if (reply.ok && refresh && !reply.result.plugin) toaster.toast({ title: t.error, body: t.upToDate });
  };

  const refresh = async () => {
    const reply = await getState();
    if (reply.ok) setStateNow(reply.result);
    else toaster.toast({ title: t.error, body: reply.error });
  };

  // Runs one backend call, reports a failure, then reloads everything from disk.
  const run = async <T,>(call: () => Promise<Reply<T>>): Promise<T | undefined> => {
    if (working) return undefined;
    working = true;
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
      working = false;
      setBusy(false);
    }
  };

  // The panel stays mounted, so it reads the state again each time the menu opens.
  const visible = useQuickAccessVisible();
  useEffect(() => {
    if (visible) refresh();
  }, [visible]);
  useEffect(() => {
    check(false);
  }, []);

  if (!state) return null;
  const { runtime, settings } = state;
  const globals = settings.global;

  const downloadable = (catalog?.versions ?? []).filter((v) => !runtime.installed.includes(v.tag));
  const toFetch = fetch && downloadable.some((v) => v.tag === fetch) ? fetch : downloadable[0]?.tag;
  const toDrop = drop && runtime.installed.includes(drop) ? drop : runtime.installed[runtime.installed.length - 1];
  const updatePlugin = async () => {
    const update = await run(downloadPlugin);
    if (update) await deckyInstall(update);
  };

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
    if (done !== undefined) setRestart("yes");
  };

  const confirmRepair = (id: string) =>
    showModal(
      <ConfirmModal
        strTitle={t.cleanTitle(gameName(id))}
        strDescription={t.cleanBody}
        onOK={async () => {
          const result = await run(() => cleanPrefix(id));
          if (result) toaster.toast({ title: gameName(id), body: t.cleaned(result.moved) });
        }}
      />,
    );

  const box64Section = (
    <PanelSection title={t.box64} key="box64">
      <PanelSectionRow>
        <Field
          label={runtime.version ?? t.notInstalled}
          description={runtime.installed.length ? `${t.versions}: ${runtime.installed.join(", ")}` : t.firstRun}
        />
      </PanelSectionRow>
      {(runtime.update || !runtime.version) && runtime.bundled.length > 0 && (
        <PanelSectionRow>
          <ButtonItem layout="below" description={`${t.bundled}: ${runtime.bundled.join(", ")}`}
            onClick={() => run(installRuntime)}>
            {busy ? t.working : runtime.installed.length ? t.updateBox64 : t.installBox64}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {runtime.installed.length > 0 && downloadable.length > 0 && (
        <>
          <PanelSectionRow>
            <DropdownItem
              label={t.download}
              menuLabel={t.download}
              rgOptions={downloadable.map((v) => ({ data: v.tag, label: `${v.tag} (${Math.ceil(v.size / 1048576)} MB)` }))}
              selectedOption={toFetch}
              onChange={(o) => setFetch(o.data)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => toFetch && run(() => downloadVersion(toFetch))}>
              {busy ? t.working : `${t.downloadButton} ${toFetch}`}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {runtime.installed.length > 1 && (
        <>
          <PanelSectionRow>
            <DropdownItem
              label={t.removeVersion}
              menuLabel={t.removeVersion}
              rgOptions={runtime.installed.map((v) => ({ data: v, label: v }))}
              selectedOption={toDrop}
              onChange={(o) => setDrop(o.data)}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem layout="below" onClick={() => toDrop && run(() => removeVersion(toDrop))}>
              {`${t.removeButton} ${toDrop}`}
            </ButtonItem>
          </PanelSectionRow>
        </>
      )}
      {catalog?.plugin ? (
        <PanelSectionRow>
          <ButtonItem layout="below" description={`${catalog.current} → ${catalog.plugin.version}`} onClick={updatePlugin}>
            {t.updatePlugin}
          </ButtonItem>
        </PanelSectionRow>
      ) : (
        <PanelSectionRow>
          <ButtonItem layout="below" description={catalog ? `Armada Box64 ${catalog.current}` : undefined}
            onClick={() => check(true)}>
            {t.checkUpdates}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );

  const protonSection = (
    <PanelSection title={t.protons} key="protons">
      <PanelSectionRow>
        <Field description={t.protonsHint} />
      </PanelSectionRow>
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
                disabled={!runtime.version}
                onChange={(on) => toggleProton(proton.name, proton.path, on)}
              />
            </PanelSectionRow>
            {tool?.outdated && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  description={t.outdated}
                  disabled={!runtime.version}
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
              onClick={async () => (await run(() => removeTool(tool.dir))) !== undefined && setRestart("yes")}
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
  );

  const defaultsSection = (
    <PanelSection title={t.defaults} key="defaults">
      {BOOLS.map(({ key, label, hint }) => (
        <PanelSectionRow key={key}>
          <ToggleField
            label={label}
            description={hint}
            checked={globals[key]}
            onChange={(value) => run(() => setGlobal(key, value))}
          />
        </PanelSectionRow>
      ))}
      <PanelSectionRow>
        <DropdownItem
          label={t.box64Version}
          menuLabel={t.box64Version}
          rgOptions={versionOptions}
          selectedOption={globals.box64}
          onChange={(o) => run(() => setGlobal("box64", o.data))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label={t.preset}
          menuLabel={t.preset}
          rgOptions={state.presets.map((p) => ({ data: p, label: presetLabel(p) }))}
          selectedOption={globals.preset}
          onChange={(o) => run(() => setGlobal("preset", o.data))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label={t.safeflags}
          menuLabel={t.safeflags}
          rgOptions={SAFEFLAGS.map((v) => ({ data: v, label: safeflagsLabel(v) }))}
          selectedOption={globals.safeflags}
          onChange={(o) => run(() => setGlobal("safeflags", o.data))}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <Field description={t.precedence} />
      </PanelSectionRow>
    </PanelSection>
  );

  const gameSections: ReactNode[] = !selected
    ? [
        <PanelSection title={t.game} key="game">
          <PanelSectionRow>
            <Field description={t.noGames} />
          </PanelSectionRow>
        </PanelSection>,
      ]
    : [
        <PanelSection title={t.game} key="game">
          <PanelSectionRow>
            <DropdownItem
              label={t.pickGame}
              menuLabel={t.pickGame}
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
                menuLabel={label}
                rgOptions={[
                  { data: "default", label: `${t.useDefault} (${globals[key] ? t.on : t.off})` },
                  { data: "on", label: t.on },
                  { data: "off", label: t.off },
                ]}
                selectedOption={overrides[key] === undefined ? "default" : overrides[key] ? "on" : "off"}
                onChange={(o) => run(() => setGame(selected, key, o.data === "default" ? null : o.data === "on"))}
              />
            </PanelSectionRow>
          ))}
          <PanelSectionRow>
            <DropdownItem
              label={t.box64Version}
              menuLabel={t.box64Version}
              rgOptions={[{ data: "inherit", label: `${t.useDefault} (${versionLabel(globals.box64)})` }, ...versionOptions]}
              selectedOption={overrides.box64 ?? "inherit"}
              onChange={(o) => run(() => setGame(selected, "box64", o.data === "inherit" ? null : o.data))}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <DropdownItem
              label={t.preset}
              menuLabel={t.preset}
              rgOptions={[
                { data: "inherit", label: `${t.useDefault} (${presetLabel(globals.preset)})` },
                ...state.presets.map((p) => ({ data: p, label: presetLabel(p) })),
              ]}
              selectedOption={overrides.preset ?? "inherit"}
              onChange={(o) => run(() => setGame(selected, "preset", o.data === "inherit" ? null : o.data))}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <DropdownItem
              label={t.safeflags}
              menuLabel={t.safeflags}
              rgOptions={[
                { data: "inherit", label: `${t.useDefault} (${safeflagsLabel(globals.safeflags)})` },
                ...SAFEFLAGS.map((v) => ({ data: v, label: safeflagsLabel(v) })),
              ]}
              selectedOption={overrides.safeflags ?? "inherit"}
              onChange={(o) => run(() => setGame(selected, "safeflags", o.data === "inherit" ? null : o.data))}
            />
          </PanelSectionRow>
          {Object.keys(overrides).length > 0 && (
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={() => run(() => resetGame(selected))}>
                {t.resetGame}
              </ButtonItem>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <Field description={t.gameHint} />
          </PanelSectionRow>
        </PanelSection>,
        <GameComponents key="components" game={selected} all={state.components} />,
        <PanelSection title={t.repairTitle(gameName(selected))} key="repair">
          <PanelSectionRow>
            <ButtonItem layout="below" description={t.cleanPrefixHint} onClick={() => confirmRepair(selected)}>
              {t.cleanPrefix}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>,
      ];

  // Day to day the game comes first; until Box64 is installed, setting it up does.
  return (
    <>
      {runtime.version
        ? [...gameSections, defaultsSection, protonSection, box64Section]
        : [box64Section, protonSection, ...gameSections, defaultsSection]}
    </>
  );
}

const NAME = "Armada Box64";

type DeckyState = {
  _activePlugin?: { name: string } | null;
  _plugins?: { name: string }[];
  setActivePlugin?(name: string): void;
};

// After an update Decky loads the new plugin but keeps showing the old panel while it stays open
// (decky-loader issue 976). Once the new plugin is registered, open it in place of the old one.
function showNewPanel() {
  const state = (window as unknown as { DeckyPluginLoader?: { deckyState?: DeckyState } }).DeckyPluginLoader
    ?.deckyState;
  const active = state?._activePlugin;
  const loaded = state?._plugins?.find((plugin) => plugin.name === NAME);
  if (active?.name === NAME && loaded && loaded !== active) state?.setActivePlugin?.(NAME);
}

export default definePlugin(() => {
  setTimeout(showNewPanel, 1000);
  return {
    name: NAME,
    titleView: <div className={staticClasses.Title}>{NAME}</div>,
    content: <Content />,
    icon: <FaMicrochip />,
    // Decky unmounts a plugin's panel while a dropdown menu or dialog is open; that lost the
    // choice just made and scrolled back to the top. Kept mounted, the panel stays as it was.
    alwaysRender: true,
  };
});
