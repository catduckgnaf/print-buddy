import { modelLabel } from "@/lib/printers";

export type Settings = {
  printerName: string;
  model: string;
  platform: "discord" | "telegram" | "matrix";
  mode: "standalone" | "hermes";
  botName: string;
  chatChannel: string;
  allowedUsers: string;
  llmUrl: string;
  llmModel: string;
  llmKeySet: boolean;
  panel: "helix" | "guppy" | "stock" | "none";
  hasCamera: "yes" | "no" | "unsure";
  moonrakerUrl: string;
  spoolmanUrl: string;
  timelapse: "rendered" | "container" | "off";
  camera: "auto" | "moonraker" | "bambu" | "go2rtc" | "none";
  streamUrl: string;
  liveView: boolean;
  voiceChannel: string;
  watchEnabled: boolean;
  sensitivity: number;
  zmodFormat: "auto" | "gcode.3mf" | "gcode";
  logLevel: "info" | "debug" | "warning";
  webuiPort: number;
  webAuth: boolean;
  authUsername: string;
  authPasswordHash: string;
  cliEnabled: boolean;
  setupDone: boolean;
  uploads: Upload[];
  providers: Record<string, boolean>;
};

export type Upload = { id: string; name: string; size: number };

export const SITES = [
  { id: "makerworld", name: "MakerWorld", needsToken: true, note: "Account token. A downloaded profile is resliced for the printer you picked." },
  { id: "printables", name: "Printables", needsToken: false, note: "No account. A link is enough." },
  { id: "thingiverse", name: "Thingiverse", needsToken: true, note: "App token." },
  { id: "myminifactory", name: "MyMiniFactory", needsToken: true, note: "API key." },
  { id: "crealitycloud", name: "Creality Cloud", needsToken: true, note: "Login token." },
  { id: "thangs", name: "Thangs", needsToken: true, note: "Login token." },
  { id: "nexprint", name: "Nexprint", needsToken: true, note: "Login token." },
  { id: "makeronline", name: "MakerOnline", needsToken: false, note: "Lists the files. Downloads are not supported." },
  { id: "cults3d", name: "Cults3D", needsToken: true, note: "Listing details only. Cults never exposes the files." },
] as const;

export const SPOOLS = [
  { name: "PolyLite PLA", material: "PLA", color: "Silk red", swatch: "#b42318", left: 620, total: 1000, slot: "IFS 1" },
  { name: "PolyLite PLA", material: "PLA", color: "Black", swatch: "#1a1814", left: 840, total: 1000, slot: "IFS 2" },
  { name: "Overture PETG", material: "PETG", color: "White", swatch: "#f4f1ea", left: 210, total: 1000, slot: "IFS 3" },
  { name: "Polymaker ASA", material: "ASA", color: "Grey", swatch: "#8a8175", left: 960, total: 1000, slot: "Shelf" },
];

export const DEFAULT_SETTINGS: Settings = {
  printerName: "Shop AD5X",
  model: "flashforge.ad5x",
  platform: "discord",
  mode: "standalone",
  botName: "Print Handy",
  chatChannel: "",
  allowedUsers: "",
  llmUrl: "",
  llmModel: "",
  llmKeySet: false,
  panel: "helix",
  hasCamera: "yes",
  moonrakerUrl: "http://192.168.1.60:7125",
  spoolmanUrl: "http://127.0.0.1:8000",
  timelapse: "container",
  camera: "moonraker",
  streamUrl: "",
  liveView: false,
  voiceChannel: "",
  watchEnabled: true,
  sensitivity: 3,
  zmodFormat: "auto",
  logLevel: "info",
  webuiPort: 8088,
  webAuth: false,
  authUsername: "",
  authPasswordHash: "",
  cliEnabled: false,
  setupDone: false,
  uploads: [],
  providers: {},
};

const STORAGE_KEY = "print-handy-console-settings";

export function loadSettings(): Settings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } as Settings;
    if (!Array.isArray(parsed.uploads)) parsed.uploads = [];
    if (!parsed.providers || typeof parsed.providers !== "object") parsed.providers = {};
    return parsed;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: Settings) {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  syncWebAuthCookie(settings.webAuth);
}

export function syncWebAuthCookie(on: boolean) {
  if (typeof document === "undefined") return;
  document.cookie = on
    ? "ph-web-auth=1; Path=/; SameSite=Lax"
    : "ph-web-auth=; Path=/; Max-Age=0; SameSite=Lax";
}

const SESSION_KEY = "ph-secure-session";

export function hasSecureSession() {
  if (typeof window === "undefined") return false;
  return window.sessionStorage.getItem(SESSION_KEY) === "1";
}

export function setSecureSession(on: boolean) {
  if (typeof window === "undefined") return;
  if (on) window.sessionStorage.setItem(SESSION_KEY, "1");
  else window.sessionStorage.removeItem(SESSION_KEY);
  if (typeof document === "undefined") return;
  document.cookie = on
    ? "ph-session=1; Path=/; SameSite=Lax"
    : "ph-session=; Path=/; Max-Age=0; SameSite=Lax";
}

export async function hashPassword(password: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(password));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function printerTitle(model: string) {
  return modelLabel(model);
}

export type DoctorStatus = "ok" | "warn" | "fail" | "skip";

export type DoctorRow = {
  label: string;
  status: DoctorStatus;
  detail: string;
};

export const DOCTOR: DoctorRow[] = [
  { label: "Settings", status: "ok", detail: "config/local.yaml loaded" },
  { label: "Printer model", status: "ok", detail: "flashforge.ad5x" },
  { label: "ZMod version", status: "ok", detail: "1.7.5-2 (from the printer OS)" },
  { label: "OrcaSlicer", status: "ok", detail: "2.5.0-beta, writable scratch dir" },
  { label: "Moonraker", status: "ok", detail: "idle, screenless (display_off=1)" },
  { label: "Spoolman", status: "ok", detail: "bundled, /api/v1/health ok" },
  { label: "Bot heartbeat", status: "ok", detail: "discord standalone, connected" },
  { label: "Listener", status: "ok", detail: "posting to the print channel" },
  {
    label: "Camera",
    status: "warn",
    detail: "snapshot answers; live voice view has not been checked",
  },
  { label: "Debug mode", status: "skip", detail: "off" },
];

export const PRINTERS = [
  {
    id: "ad5x",
    name: "Shop AD5X",
    model: "flashforge.ad5x",
    connection: "Moonraker",
    channel: "print-shop",
    endpoint: "192.168.1.60:7125",
    state: "printing",
    default: true,
  },
  {
    id: "kobra",
    name: "Kobra 2",
    model: "anycubic.kobra2",
    connection: "Moonraker",
    channel: "print-shop",
    endpoint: "192.168.1.74:7125",
    state: "idle",
    default: false,
  },
];
