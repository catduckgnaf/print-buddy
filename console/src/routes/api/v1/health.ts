import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/v1/health")({
  server: {
    handlers: {
      GET: ({ request }) => {
        const webAuth = (request.headers.get("cookie") ?? "")
          .split(";")
          .some((part) => part.trim() === "ph-web-auth=1");
        return Response.json({
          ok: true,
          service: "print-handy",
          auth: webAuth ? "username" : "off",
          routes: ["GET /api/v1/health", "POST /api/v1/chat"],
        });
      },
    },
  },
});
