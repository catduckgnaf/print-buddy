import { createFileRoute } from "@tanstack/react-router";
import { normalizeJob, reply } from "@/lib/walkthrough";

export const Route = createFileRoute("/api/v1/chat")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const cookies = request.headers.get("cookie") ?? "";
        const webAuth = cookies.split(";").some((part) => part.trim() === "ph-web-auth=1");
        const signedIn = cookies.split(";").some((part) => part.trim() === "ph-session=1");
        if (webAuth && !signedIn) {
          return Response.json({ error: "Sign in required." }, { status: 401 });
        }
        let body: { input?: unknown; job?: unknown; printerName?: unknown } = {};
        try {
          body = (await request.json()) as typeof body;
        } catch {
          return Response.json({ error: "Send JSON." }, { status: 400 });
        }
        const input = typeof body.input === "string" ? body.input : "";
        const printerName = typeof body.printerName === "string" ? body.printerName : "";
        return Response.json(reply(normalizeJob(body.job), input, printerName));
      },
    },
  },
});
