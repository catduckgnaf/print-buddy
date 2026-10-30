import { useEffect, useState } from "react";

const KEY = "print-handy-theme";

function currentTheme(): "dark" | "light" {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    setTheme(currentTheme());
  }, []);

  function choose(next: "dark" | "light") {
    if (next === "light") document.documentElement.dataset.theme = "light";
    else delete document.documentElement.dataset.theme;
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* private mode */
    }
    setTheme(next);
  }

  return (
    <div className="flex rounded-card border border-line p-0.5 text-sm" role="group" aria-label="Color theme">
      <button
        type="button"
        aria-pressed={theme === "dark"}
        className={
          "rounded-card px-3 py-2 " + (theme === "dark" ? "bg-ink text-bg" : "text-muted")
        }
        onClick={() => choose("dark")}
      >
        Dark
      </button>
      <button
        type="button"
        aria-pressed={theme === "light"}
        className={
          "rounded-card px-3 py-2 " + (theme === "light" ? "bg-ink text-bg" : "text-muted")
        }
        onClick={() => choose("light")}
      >
        Light
      </button>
    </div>
  );
}
