const BASE_URL = "/api";

export async function fetchSessions() {
  const res = await fetch(`${BASE_URL}/history/sessions`);
  return res.json();
}

export async function fetchSessionMessages(sessionId: string) {
  const res = await fetch(`${BASE_URL}/history/sessions/${sessionId}`);
  return res.json();
}

export async function healthCheck() {
  const res = await fetch(`${BASE_URL}/health`);
  return res.json();
}
