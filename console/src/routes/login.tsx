import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";
import { hashPassword, hasSecureSession, loadSettings, setSecureSession } from "@/lib/console";

export const Route = createFileRoute("/login")({ component: LoginPage });

function LoginPage() {
  const navigate = useNavigate();
  const [webAuth, setWebAuth] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    const settings = loadSettings();
    setWebAuth(settings.webAuth);
    if (settings.webAuth && hasSecureSession()) navigate({ to: "/" });
  }, [navigate]);

  if (webAuth === null) return <div className="min-h-screen bg-bg" />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setPending(true);
    const settings = loadSettings();
    const hash = await hashPassword(password);
    setPending(false);
    if (username.trim() !== settings.authUsername || hash !== settings.authPasswordHash) {
      setError("That username or password is wrong.");
      return;
    }
    setSecureSession(true);
    navigate({ to: "/" });
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-6 px-4 py-10">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-muted">Print Handy</p>
        <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      </div>
      {webAuth ? (
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Username</span>
            <input
              className="w-full rounded-card border border-line bg-surface px-3 py-2 text-ink"
              autoComplete="username"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Password</span>
            <input
              className="w-full rounded-card border border-line bg-surface px-3 py-2 text-ink"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error ? <p className="text-sm text-bad">{error}</p> : null}
          <button
            type="submit"
            disabled={pending}
            className="rounded-card bg-accent px-4 py-2 text-sm font-medium text-accent-ink disabled:opacity-50"
          >
            {pending ? "Working…" : "Sign in"}
          </button>
        </form>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted">Secure Auth is off.</p>
          <Link to="/" className="text-sm font-medium text-accent">
            Open the console
          </Link>
        </div>
      )}
    </div>
  );
}
