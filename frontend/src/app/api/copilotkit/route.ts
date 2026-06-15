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
    const response = await fetch(`${BACKEND_URL}/ag-ui/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: input.messages,
        threadId: input.threadId,
        agentId: input.forwardedProps?.agentId,
      }),
      signal: abortSignal,
    });

    if (!response.ok || !response.body) {
      yield {
        type: EventType.TEXT_MESSAGE_CHUNK,
        role: "assistant",
        messageId: crypto.randomUUID(),
        delta: `[Backend error: ${response.status} ${response.statusText}]`,
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

export const POST = async (req: Request) => {
  const handler = createCopilotRuntimeHandler({
    runtime,
  });
  return handler(req);
};
