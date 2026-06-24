import {
  CopilotRuntime,
  createCopilotRuntimeHandler,
  InMemoryAgentRunner,
  BuiltInAgent,
} from "@copilotkit/runtime/v2";
import { EventType, type BaseEvent } from "@ag-ui/client";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

const agent = new BuiltInAgent({
  type: "custom",
  factory: async function* ({ input, abortSignal }) {
    const forwardedProps = input.forwardedProps as Record<string, unknown> | undefined;
    const state = input.state as Record<string, unknown> | undefined;
    console.log("[route.ts] forwardedProps:", JSON.stringify(forwardedProps));
    console.log("[route.ts] input.state:", JSON.stringify(state));
    console.log("[route.ts] input.messages:", JSON.stringify(input.messages));
    console.log("[route.ts] input.threadId:", input.threadId);
    const threadId = state?.threadId || forwardedProps?.customThreadId || forwardedProps?.threadId || input.threadId;
    const userId = forwardedProps?.userId || (state?.userId as string);

    const body: Record<string, unknown> = {
      messages: input.messages,
      thread_id: threadId,
      agent_id: forwardedProps?.agentId || process.env.NEXT_PUBLIC_DEFAULT_AGENT_ID,
      user_id: userId,
    };

    console.log("[route.ts] Sending to backend:", JSON.stringify(body));
    const response = await fetch(`${BACKEND_URL}/ag-ui/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: abortSignal,
    });

    if (!response.ok || !response.body) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const errBody = await response.json();
        if (errBody.detail) detail = errBody.detail;
      } catch {
        // ignore parse errors
      }
      yield {
        type: EventType.TEXT_MESSAGE_CHUNK,
        role: "assistant",
        messageId: crypto.randomUUID(),
        delta: `[Backend error: ${detail}]`,
      } as BaseEvent;
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const messageId = crypto.randomUUID();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = decoder.decode(value, { stream: true });
      console.log("[route.ts] chunk:", JSON.stringify(text), "len:", text.length);
      if (text) {
        yield {
          type: EventType.TEXT_MESSAGE_CHUNK,
          role: "assistant",
          messageId,
          delta: text,
        } as BaseEvent;
      }
    }
  },
});

const runtime = new CopilotRuntime({
  agents: { default: agent },
  runner: new InMemoryAgentRunner(),
});

const handler = createCopilotRuntimeHandler({
  runtime,
  basePath: "/api/copilotkit",
  mode: "single-route",
});

export const GET = handler;
export const POST = handler;
