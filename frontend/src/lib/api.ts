const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json();
}

export async function apiPatch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PATCH ${path} failed: ${res.status}`);
  return res.json();
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`DELETE ${path} failed: ${res.status}`);
  return res.json();
}

export interface MemoryEntry {
  key: string;
  value?: string;
  category?: string;
  updated_at?: string;
  access_count?: number;
}

export async function listMemories(
  agentId: string,
  userId: string,
): Promise<MemoryEntry[]> {
  const params = new URLSearchParams({ agent_id: agentId, user_id: userId, limit: "100" });
  // list_memories endpoint: GET /api/memory?agent_id=...&user_id=...
  const data = await apiGet<Record<string, unknown>[]>(`/api/memory?${params}`);
  return data.map((m) => ({
    key: m.key as string,
    value: (m.value as string) ?? "",
    category: (m.category as string) ?? "",
    updated_at: (m.updated_at as string) ?? undefined,
    access_count: (m.access_count as number) ?? 0,
  }));
}

export async function saveMemory(
  agentId: string,
  userId: string,
  key: string,
  data: Record<string, string>,
): Promise<void> {
  await apiPost("/api/memory", { agent_id: agentId, user_id: userId, key, data });
}

export async function deleteMemory(
  agentId: string,
  userId: string,
  key: string,
): Promise<void> {
  const params = new URLSearchParams({ agent_id: agentId, user_id: userId });
  await apiDelete(`/api/memory/${encodeURIComponent(key)}?${params}`);
}

export interface AgentSummary {
  id: string;
  name: string;
  endpoint_url: string;
  endpoint_type: string;
  description: string;
  created_at: string;
}

export async function listAgents(): Promise<AgentSummary[]> {
  return apiGet<AgentSummary[]>("/api/agents");
}

export async function registerAgent(
  name: string,
  endpointUrl: string,
  endpointType: string,
  description?: string,
): Promise<AgentSummary> {
  return apiPost<AgentSummary>("/api/agents", {
    name,
    endpoint_url: endpointUrl,
    endpoint_type: endpointType || "supervisor",
    description: description || "",
  });
}

export async function autoTitleThread(
  agentId: string,
  threadId: string,
): Promise<{ title: string }> {
  return apiPost<{ title: string }>(
    `/api/sessions/${encodeURIComponent(threadId)}/auto-title?agent_id=${agentId}`,
    {},
  );
}

export async function renameThread(
  agentId: string,
  threadId: string,
  title: string,
): Promise<void> {
  await apiPatch(
    `/api/sessions/${encodeURIComponent(threadId)}/title?agent_id=${agentId}`,
    { title },
  );
}
