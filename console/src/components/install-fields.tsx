import { PrinterPicker } from "@/components/printer-picker";
import { SITES, type Settings } from "@/lib/console";
import { isZmod, usesMoonraker } from "@/lib/printers";

export const fieldClass = "w-full rounded-card border border-line bg-bg px-3 py-2 text-ink";

const PLATFORM = {
  discord: {
    title: "Discord",
    body: "Buttons and slash commands. Turn on the Message Content intent, put the bot token in DISCORD_BOT_TOKEN, and name one print channel. Everyone in that channel can read the print talk. Do not also run Hermes on the same token, or both answer every message.",
  },
  telegram: {
    title: "Telegram",
    body: "A pure bot. Links, files, and buttons work. Ordinary sentences get a short “didn't understand”, even if an OpenAI-compatible key is set. The token stays in TELEGRAM_BOT_TOKEN. Group and channel IDs are negative.",
  },
  matrix: {
    title: "Matrix",
    body: "A pure bot in one unencrypted room. There are no buttons: prompts are a numbered list, and the person types the number. The token stays in MATRIX_ACCESS_TOKEN. The room ID starts with !.",
  },
} as const;

const MODE = {
  standalone: {
    title: "Standalone",
    body: "The default. Print Handy talks to the chat itself. Links, files, colors, slicing, and the start button need no AI key and no Hermes.",
  },
  hermes: {
    title: "Hermes",
    body: "The same commands, running as the Hermes gateway plugin. Use this when Hermes is already how the machine is operated. The cost is a second process, and a shared bot token makes standalone and Hermes both reply.",
  },
} as const;

export function PrinterStep({
  draft,
  onChange,
}: {
  draft: Settings;
  onChange: (partial: Partial<Settings>) => void;
}) {
  const zmod = isZmod(draft.model);
  return (
    <section className="flex flex-col gap-4 rounded-card border border-line bg-surface p-4">
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Printer name</span>
        <input className={fieldClass} value={draft.printerName} onChange={(event) => onChange({ printerName: event.target.value })} />
        <span className="text-muted">The name on the status page. Not the name the bot uses in chat.</span>
      </label>
      <PrinterPicker model={draft.model} onModel={(model) => onChange({ model })} />
      {zmod ? (
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Panel</span>
          <select
            className={fieldClass}
            value={draft.panel}
            onChange={(event) => onChange({ panel: event.target.value as Settings["panel"] })}
          >
            <option value="helix">HelixScreen</option>
            <option value="guppy">GuppyScreen</option>
            <option value="none">No panel</option>
            <option value="stock">Stock Flashforge screen</option>
          </select>
        </label>
      ) : null}
      {zmod ? <DeliveryField draft={draft} onChange={onChange} /> : null}
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Printer URL</span>
        <input
          className={fieldClass}
          value={draft.moonrakerUrl}
          onChange={(event) => onChange({ moonrakerUrl: event.target.value })}
          placeholder={usesMoonraker(draft.model) ? "http://printer.local:7125" : "http://octopi.local"}
        />
        <span className="text-muted">
          The address Print Handy uses to talk to the machine. Klipper (Moonraker) or OctoPi can live on another computer, not on the printer.
        </span>
      </label>
    </section>
  );
}

export function DeliveryField({
  draft,
  onChange,
}: {
  draft: Settings;
  onChange: (partial: Partial<Settings>) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium">Delivery</span>
      <select
        className={fieldClass}
        value={draft.zmodFormat}
        onChange={(event) => onChange({ zmodFormat: event.target.value as Settings["zmodFormat"] })}
      >
        <option value="gcode.3mf">Always 3MF</option>
        <option value="gcode">Always G-code</option>
        <option value="auto">Automatic</option>
      </select>
    </label>
  );
}

export function ChatStep({
  draft,
  onChange,
}: {
  draft: Settings;
  onChange: (partial: Partial<Settings>) => void;
}) {
  const platform = PLATFORM[draft.platform];
  const mode = MODE[draft.mode];
  return (
    <section className="flex flex-col gap-4 rounded-card border border-line bg-surface p-4">
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Name in chat</span>
        <input className={fieldClass} value={draft.botName} onChange={(event) => onChange({ botName: event.target.value })} />
        <span className="text-muted">
          What it calls itself in replies and help. This is not the name in the Discord developer portal. A shop bot can be named Print Bitch.
        </span>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Where it talks</span>
        <select
          className={fieldClass}
          value={draft.platform}
          onChange={(event) => onChange({ platform: event.target.value as Settings["platform"] })}
        >
          <option value="discord">Discord</option>
          <option value="matrix">Matrix</option>
          <option value="telegram">Telegram</option>
        </select>
        <span className="text-muted">{platform.body}</span>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">{draft.platform === "matrix" ? "Room ID" : "Channel or chat ID"}</span>
        <input
          className={fieldClass}
          value={draft.chatChannel}
          onChange={(event) => onChange({ chatChannel: event.target.value })}
          placeholder={draft.platform === "matrix" ? "!room:server" : "The one print channel"}
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Who may print</span>
        <input
          className={fieldClass}
          value={draft.allowedUsers}
          onChange={(event) => onChange({ allowedUsers: event.target.value })}
          placeholder="User IDs, or leave empty to allow the whole channel"
        />
        <span className="text-muted">Empty on Discord means everyone in the print channel. A deny list still wins.</span>
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">How it runs</span>
        <select
          className={fieldClass}
          value={draft.mode}
          onChange={(event) => onChange({ mode: event.target.value as Settings["mode"] })}
        >
          <option value="hermes">Hermes</option>
          <option value="standalone">Standalone</option>
        </select>
        <span className="text-muted">{mode.body}</span>
      </label>
      <div className="flex flex-col gap-3 border-t border-line pt-4">
        <div>
          <p className="text-sm font-medium">OpenAI-compatible key</p>
          <p className="mt-1 text-sm text-muted">
            Optional. Standalone already handles links and buttons without it. A key lets Discord answer ordinary sentences,
            and it feeds the roast and /print-design. Telegram and Matrix never use it for chat. The real install reads the key
            from LLM_API_KEY. This page only remembers that you set one.
          </p>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Chat URL</span>
          <input
            className={fieldClass}
            value={draft.llmUrl}
            onChange={(event) => onChange({ llmUrl: event.target.value })}
            placeholder="https://api.openai.com/v1/chat/completions"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">Model</span>
          <input
            className={fieldClass}
            value={draft.llmModel}
            onChange={(event) => onChange({ llmModel: event.target.value })}
            placeholder="Required when the URL is set"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium">API key</span>
          <input
            className={fieldClass}
            type="password"
            autoComplete="off"
            placeholder={draft.llmKeySet ? "A key is set. Type to replace it." : "Leave empty to skip"}
            onChange={(event) => onChange({ llmKeySet: event.target.value.trim().length > 0 })}
          />
        </label>
      </div>
    </section>
  );
}

export function CameraStep({
  draft,
  onChange,
  framed = true,
}: {
  draft: Settings;
  onChange: (partial: Partial<Settings>) => void;
  framed?: boolean;
}) {
  const body = (
    <>
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">Camera</span>
        <select
          className={fieldClass}
          value={draft.hasCamera}
          onChange={(event) => {
            const hasCamera = event.target.value as Settings["hasCamera"];
            onChange(hasCamera === "no" ? { hasCamera, timelapse: "off", watchEnabled: false } : { hasCamera });
          }}
        >
          <option value="no">No camera</option>
          <option value="unsure">Not sure yet</option>
          <option value="yes">This printer has a camera</option>
        </select>
        {draft.hasCamera === "no" ? (
          <span className="text-muted">No snapshot, no watch, and no timelapse. You can add a camera later.</span>
        ) : null}
      </label>
      {draft.hasCamera !== "no" ? (
        <>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Where the picture comes from</span>
            <select
              className={fieldClass}
              value={draft.camera}
              onChange={(event) => onChange({ camera: event.target.value as Settings["camera"] })}
            >
              <option value="bambu">Bambu camera</option>
              <option value="auto">Follow the printer</option>
              <option value="moonraker">Moonraker webcam</option>
              <option value="none">No snapshot URL</option>
              <option value="go2rtc">RTSP stream</option>
            </select>
          </label>
          {draft.camera === "go2rtc" ? (
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">RTSP URL</span>
              <input
                className={fieldClass}
                value={draft.streamUrl}
                onChange={(event) => onChange({ streamUrl: event.target.value })}
                placeholder="rtsp://camera.local:554/stream"
              />
              <span className="text-muted">Print Handy hands this address to go2rtc and reads the camera from there.</span>
            </label>
          ) : null}
          {draft.platform === "discord" ? (
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Live view in Discord</span>
              <select
                className={fieldClass}
                value={draft.liveView ? "activity" : "off"}
                onChange={(event) => onChange({ liveView: event.target.value === "activity" })}
              >
                <option value="activity">Activity in a voice channel</option>
                <option value="off">Off</option>
              </select>
              <span className="text-muted">
                The bot posts stills in the print channel. It cannot send video. The Activity plays this same go2rtc stream inside one voice channel.
              </span>
            </label>
          ) : (
            <p className="text-sm text-muted">Live view is Discord only. This chat gets stills, not a stream.</p>
          )}
          {draft.platform === "discord" && draft.liveView ? (
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Voice channel ID</span>
              <input
                className={fieldClass}
                value={draft.voiceChannel}
                onChange={(event) => onChange({ voiceChannel: event.target.value })}
                placeholder="The one private voice channel"
              />
            </label>
          ) : null}
          <label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              className="size-5 accent-accent"
              checked={draft.watchEnabled}
              onChange={(event) => onChange({ watchEnabled: event.target.checked })}
            />
            <span>
              <span className="font-medium">Watch the print</span>
              <span className="mt-1 block text-muted">
                Posts a picture when it thinks it sees spaghetti, a detached part, an empty bed, or a stall, and offers a pause.
                It never stops the printer itself.
              </span>
            </span>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Timelapse</span>
            <select
              className={fieldClass}
              value={draft.timelapse}
              onChange={(event) => onChange({ timelapse: event.target.value as Settings["timelapse"] })}
            >
              <option value="off">Off</option>
              <option value="container">Print Handy records it</option>
              <option value="rendered">The printer records it</option>
            </select>
            <span className="text-muted">
              {draft.timelapse === "rendered"
                ? "The printer makes the video, for example with moonraker-timelapse. Print Handy attaches that file when the print finishes."
                : draft.timelapse === "container"
                  ? "Print Handy takes frames from the camera and makes the video. This is not the printer's own timelapse."
                  : "No video is kept."}
            </span>
          </label>
        </>
      ) : null}
    </>
  );
  return framed ? <section className="flex flex-col gap-4 rounded-card border border-line bg-surface p-4">{body}</section> : <div className="flex flex-col gap-4">{body}</div>;
}

export function ProviderList({
  draft,
  onChange,
  showUpload = false,
}: {
  draft: Settings;
  onChange: (partial: Partial<Settings>) => void;
  showUpload?: boolean;
}) {
  function toggle(id: string) {
    onChange({ providers: { ...draft.providers, [id]: !draft.providers[id] } });
  }

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-card border border-line bg-surface p-4">
        <ul className="flex flex-col gap-3">
          {SITES.map((site) => {
            const on = Boolean(draft.providers[site.id]);
            return (
              <li key={site.id} className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-3 last:border-0 last:pb-0">
                <div>
                  <p className="font-medium">{site.name}</p>
                  <p className="text-sm text-muted">{site.note}</p>
                </div>
                <button
                  type="button"
                  className={"rounded-card px-3 py-2 text-sm font-medium " + (on ? "bg-ok-bg text-ok" : "border border-line bg-bg")}
                  onClick={() => toggle(site.id)}
                >
                  {on ? "Connected" : site.needsToken ? "Connect" : "Enable"}
                </button>
              </li>
            );
          })}
        </ul>
      </section>
      {showUpload ? (
        <section className="rounded-card border border-dashed border-line bg-surface p-4">
          <h2 className="font-semibold">Or send a file</h2>
          <p className="mt-1 text-sm text-muted">
            An STL or 3MF, when there is no link. It is sliced for the printer you picked. This is not part of first boot.
          </p>
          <label className="mt-3 block cursor-pointer rounded-card border border-line bg-bg px-4 py-6 text-center text-sm">
            Choose files
            <input
              className="sr-only"
              type="file"
              multiple
              accept=".stl,.3mf,.gcode,.bgcode"
              onChange={(event) => {
                const list = event.target.files;
                if (!list?.length) return;
                const added = Array.from(list).map((file) => ({
                  id: `${file.name}-${file.size}-${file.lastModified}`,
                  name: file.name,
                  size: file.size,
                }));
                const seen = new Set(draft.uploads.map((file) => file.id));
                onChange({ uploads: [...draft.uploads, ...added.filter((file) => !seen.has(file.id))] });
                event.target.value = "";
              }}
            />
          </label>
          {draft.uploads.length ? (
            <ul className="mt-3 flex flex-col gap-1 text-sm">
              {draft.uploads.map((file) => (
                <li key={file.id} className="flex justify-between gap-3 font-mono">
                  <span className="truncate">{file.name}</span>
                  <span className="text-muted">{Math.max(1, Math.round(file.size / 1024))} KB</span>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
