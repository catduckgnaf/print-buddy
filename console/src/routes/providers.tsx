import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { ProviderList } from "@/components/install-fields";
import { DEFAULT_SETTINGS, loadSettings, saveSettings, type Settings } from "@/lib/console";

export const Route = createFileRoute("/providers")({ component: ProvidersPage });

function ProvidersPage() {
  const [draft, setDraft] = useState<Settings>(DEFAULT_SETTINGS);

  useEffect(() => setDraft(loadSettings()), []);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Providers</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Connect a site when you want. If you skip it, dropping a link in chat asks for the token then.
          Printables needs no account. A file upload is here for models that are not on a site.
        </p>
      </div>
      <ProviderList
        draft={draft}
        showUpload
        onChange={(partial) => {
          const next = { ...draft, ...partial };
          setDraft(next);
          saveSettings(next);
        }}
      />
    </div>
  );
}
