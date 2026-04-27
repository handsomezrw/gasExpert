import type { ChatMessage, ChatSession } from "@/types";

const BASE_URL = "/api";

export async function fetchSessions(): Promise<{ sessions: ChatSession[] }> {
  const res = await fetch(`${BASE_URL}/history/sessions`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function fetchSessionMessages(
  sessionId: string,
): Promise<{ session_id: string; messages: ChatMessage[] }> {
  const res = await fetch(`${BASE_URL}/history/sessions/${sessionId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function healthCheck() {
  const res = await fetch(`${BASE_URL}/health`);
  return res.json();
}
