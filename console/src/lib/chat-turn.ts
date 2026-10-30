import { createServerFn } from "@tanstack/react-start";
import { authMiddleware } from "@/lib/auth/middleware";
import { normalizeJob, reply, type Job, type TurnResult } from "@/lib/walkthrough";

type ChatInput = { input: string; job: Job; printerName: string };

export const chatTurn = createServerFn({ method: "POST" })
  .middleware([authMiddleware])
  .validator((data: ChatInput) => data)
  .handler(async ({ data }): Promise<TurnResult> => {
    return reply(normalizeJob(data.job), data.input, data.printerName);
  });
