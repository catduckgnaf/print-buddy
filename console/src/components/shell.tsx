import { Link, Navigate, useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";
import { ThemeToggle } from "@/components/theme-toggle";
import { hasSecureSession, loadSettings, setSecureSession, syncWebAuthCookie } from "@/lib/console";

const LINKS = [
  { to: "/", label: "Status" },
  { to: "/chat", label: "Chat" },
  { to: "/search", label: "Search" },
  { to: "/layers", label: "Layers" },
  { to: "/printers", label: "Printers" },
  { to: "/spools", label: "Spools" },
  { to: "/providers", label: "Providers" },
  { to: "/settings", label: "Settings" },
] as const;

const MOBILE = [
  { to: "/", label: "Status" },
  { to: "/chat", label: "Chat" },
  { to: "/search", label: "Search" },
  { to: "/settings", label: "Settings" },
] as const;

export function Shell({ children }: { children: ReactNode }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const navigate = useNavigate();
  const [webAuth, setWebAuth] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const settings = loadSettings();
    const on = settings.webAuth;
    setWebAuth(on);
    syncWebAuthCookie(on);
    setAuthed(hasSecureSession());
    setReady(true);
  }, [path]);

  useEffect(() => {
    if (!ready || path === "/login" || path === "/setup") return;
    if (webAuth && !authed) return;
    if (!loadSettings().setupDone) navigate({ to: "/setup" });
  }, [path, navigate, webAuth, authed, ready]);

  if (path === "/login") return <>{children}</>;
  if (!ready) return <div className="min-h-screen bg-bg" />;
  if (webAuth && !authed) return <Navigate to="/login" />;

  return (
    <div className="min-h-screen bg-bg text-ink">
      <header className="border-b border-line bg-surface pt-[env(safe-area-inset-top)]">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="grid size-9 place-items-center rounded-card bg-accent text-sm font-semibold text-accent-ink"
            >
              PH
            </span>
            <div>
              <p className="text-sm font-semibold tracking-tight">Print Handy</p>
              <p className="font-mono text-xs text-muted">2.2.0 · sample install</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <nav className="hidden flex-wrap gap-1 md:flex">
              {LINKS.map((link) => {
                const active = path === link.to;
                return (
                  <Link
                    key={link.to}
                    to={link.to}
                    className={
                      "rounded-card px-3 py-2 text-sm font-medium " +
                      (active ? "bg-ink text-bg" : "text-ink hover:bg-bg")
                    }
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>
            {webAuth && authed ? (
              <button
                type="button"
                className="rounded-card border border-line px-3 py-2 text-sm"
                onClick={() => {
                  setSecureSession(false);
                  setAuthed(false);
                  navigate({ to: "/login" });
                }}
              >
                Sign out
              </button>
            ) : null}
            <ThemeToggle />
          </div>
        </div>
      </header>
      <InstallHint />
      <main className="mx-auto max-w-5xl px-4 py-6 pb-24 md:pb-6">{children}</main>
      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">
        <ul className="grid grid-cols-4">
          {MOBILE.map((link) => {
            const active = path === link.to;
            return (
              <li key={link.to}>
                <Link
                  to={link.to}
                  className={
                    "block px-1 py-3 text-center text-xs font-medium " + (active ? "text-accent" : "text-muted")
                  }
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}

function InstallHint() {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      ("standalone" in navigator && Boolean((navigator as { standalone?: boolean }).standalone));
    const narrow = window.matchMedia("(max-width: 767px)").matches;
    setShow(narrow && !standalone && sessionStorage.getItem("ph-install-dismiss") !== "1");
  }, []);
  if (!show) return null;
  return (
    <p className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-2 text-sm text-muted">
      Add Print Handy to your home screen to use it full screen.
      <button
        type="button"
        className="shrink-0 rounded-card border border-line px-2 py-1 text-ink"
        onClick={() => {
          sessionStorage.setItem("ph-install-dismiss", "1");
          setShow(false);
        }}
      >
        Not now
      </button>
    </p>
  );
}
