/**
 * api_sessions.ts — Lightweight sessions API client for the frontend.
 *
 * All functions route to backend endpoints. Handles errors gracefully with logging.
 */

// ── Configuration ──────────────────────────────────────────────

const API_BASE =
  (typeof window !== "undefined" && (window as any).__Sarasvi_API_URL) ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000/api";

function baseUrl(path: string): string {
  if (!API_BASE) return path;
  return `${API_BASE.replace(/\/$/, "")}${path.startsWith("/") ? path : "/" + path}`;
}

// ── Auth token plumbing ────────────────────────────────────────
// The backend now requires a Bearer JWT on all session/user routes and on the
// WebSocket handshake (?access_token=). We persist it under "authToken", which
// wsClient.ts already reads.

const TOKEN_KEY = "authToken";

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

/** fetch wrapper that injects the Authorization header when a token is present. */
async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getAuthToken();
  const headers = new Headers(init.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { credentials: "include", ...init, headers });
}

// ── Response Types ────────────────────────────────────────────

export interface SessionResponse {
  id: string;
  user_id?: string;
  topic: string;
  status: string;
  started_at?: string;
  ended_at?: string | null;
  duration_ms?: number;
  summary_json?: Record<string, any> | null;
  [key: string]: any;
}

export interface UserResponse {
  id: string;
  email: string;
  name: string;
  learning_profile?: Record<string, any>;
  mastery_scores?: Record<string, number>;
  [key: string]: any;
}

export interface EventsResponse {
  events: any[];
  total: number;
}

export interface TopicsResponse {
  topics: TopicResponse[];
}

export interface TopicResponse {
  name: string;
  description: string;
  icon: string;
}

// ── Session Management ─────────────────────────────────────────

export interface ImageExtractionResponse {
  question_text: string;
  confidence: number;
  contains_math: boolean;
  contains_diagram: boolean;
  diagram_description: string;
  entities: string[];
  relations: string[];
  needs_user_review: boolean;
  verification_errors: string[];
  has_multiple_questions: boolean;
  learning_goal: string;
  math_entities: string[];
  diagram_entities: string[];
}

export async function extractImageText(
  file: File
): Promise<ImageExtractionResponse> {
  const url = baseUrl("/sessions/extract-image");
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await apiFetch(url, {
      method: "POST",
      body: formData,
      credentials: "include",
    });
    if (!res.ok) throw new Error(`Image extraction failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("extractImageText error", e);
    throw e;
  }
}

export async function interruptSession(
  sessionId: string,
  text: string,
  gestureData?: any,
  snapshot?: any,
  viewedPageContext?: { scene_id: string; label: string; page_index: number } | null,
  file?: File | null
): Promise<SessionResponse> {
  const url = baseUrl(`/sessions/${encodeURIComponent(sessionId)}/interrupt`);

  const formData = new FormData();
  formData.append("text", text);

  if (gestureData) {
    formData.append("gesture_data", JSON.stringify(gestureData));
  }

  const mergedSnapshot = snapshot
    ? { ...snapshot, viewed_page_context: viewedPageContext ?? null }
    : viewedPageContext
      ? { viewed_page_context: viewedPageContext }
      : null;

  if (mergedSnapshot) {
    formData.append("snapshot", JSON.stringify(mergedSnapshot));
  }

  if (file) {
    formData.append("file", file);
  }

  try {
    const res = await apiFetch(url, {
      method: "POST",
      body: formData,
      credentials: "include",
    });
    if (!res.ok) throw new Error(`interrupt failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("interruptSession error", e);
    throw e;
  }
}

export async function createSession(
  topic: string,
  opts?: Record<string, any>
): Promise<SessionResponse> {
  const url = baseUrl("/sessions");
  try {
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ topic, ...opts }),
    });
    if (!res.ok) throw new Error(`createSession failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("createSession error", e);
    throw e;
  }
}

export async function getTopics(): Promise<TopicResponse[]> {
  const url = baseUrl("/sessions/topics");
  try {
    const res = await apiFetch(url, { credentials: "include" });
    if (!res.ok) return [];
    const payload = await res.json();
    if (!Array.isArray(payload)) return [];
    return payload
      .map((item: any) => {
        if (typeof item === "string") {
          return { name: item, description: "", icon: "GitBranch" };
        }
        return {
          name: String(item?.name || "Untitled Topic"),
          description: String(item?.description || ""),
          icon: String(item?.icon || "GitBranch"),
        };
      })
      .filter((topic) => topic.name.trim().length > 0);
  } catch (e) {
    console.warn("getTopics error", e);
    return [];
  }
}

export async function getSessionEvents(
  sessionId: string,
  opts?: { from?: number; limit?: number }
): Promise<EventsResponse> {
  const q: string[] = [];
  if (opts?.from !== undefined) q.push(`from=${encodeURIComponent(opts.from)}`);
  if (opts?.limit !== undefined) q.push(`limit=${encodeURIComponent(opts.limit)}`);
  const url = baseUrl(`/sessions/${encodeURIComponent(sessionId)}/events${q.length ? `?${q.join("&")}` : ""}`);
  try {
    const res = await apiFetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(`events fetch failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("getSessionEvents error", e);
    return { events: [], total: 0 };
  }
}

export async function getSessions(userId?: string): Promise<{ sessions: SessionResponse[]; total: number }> {
  const url = baseUrl(`/sessions${userId ? `?user_id=${encodeURIComponent(userId)}` : ""}`);
  try {
    const res = await apiFetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(`getSessions failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("getSessions error", e);
    return { sessions: [], total: 0 };
  }
}

export async function teachTopic(sessionId: string, topic: string): Promise<boolean> {
  const url = baseUrl(`/sessions/${encodeURIComponent(sessionId)}/teach?topic=${encodeURIComponent(topic)}`);
  try {
    const res = await apiFetch(url, { method: "POST", credentials: "include" });
    if (!res.ok) throw new Error(`teach failed: ${res.status}`);
    return true;
  } catch (e) {
    console.warn("teachTopic error", e);
    throw e;
  }
}

export async function continueSession(
  sessionId: string,
  snapshot?: any
): Promise<SessionResponse> {
  const url = baseUrl(`/sessions/${encodeURIComponent(sessionId)}/continue`);
  try {
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ snapshot }),
      credentials: "include",
    });
    if (!res.ok) throw new Error(`continue failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("continueSession error", e);
    throw e;
  }
}

export async function adaptSession(
  sessionId: string,
  cognitiveLoad: number,
  confusionLevel: number,
  snapshot?: any
): Promise<SessionResponse> {
  const url = baseUrl(`/sessions/${encodeURIComponent(sessionId)}/adapt`);
  try {
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cognitive_load: cognitiveLoad,
        confusion_level: confusionLevel,
        snapshot: snapshot,
      }),
      credentials: "include",
    });
    if (!res.ok) throw new Error(`adapt failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("adaptSession error", e);
    throw e;
  }
}

// ── User Management ───────────────────────────────────────────

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: UserResponse;
}

/** Register a new account (password required) and persist the returned token. */
export async function registerUser(
  email: string,
  name: string,
  password: string,
  learningProfile?: Record<string, any>
): Promise<UserResponse> {
  const url = baseUrl("/auth/register");
  const res = await apiFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, name, password, learning_profile: learningProfile ?? {} }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `register failed: ${res.status}`);
  }
  const data: AuthResponse = await res.json();
  setAuthToken(data.access_token);
  return data.user;
}

/** Log in with email + password and persist the returned token. */
export async function loginUser(email: string, password: string): Promise<UserResponse> {
  const url = baseUrl("/auth/login");
  const res = await apiFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail || `login failed: ${res.status}`);
  }
  const data: AuthResponse = await res.json();
  setAuthToken(data.access_token);
  return data.user;
}

export function logoutUser(): void {
  setAuthToken(null);
}

export async function getUser(userId: string): Promise<UserResponse> {
  const url = baseUrl(`/users/${encodeURIComponent(userId)}`);
  try {
    const res = await apiFetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(`getUser failed: ${res.status}`);
    return await res.json();
  } catch (e) {
    console.warn("getUser error", e);
    throw e;
  }
}

/** Returns the currently authenticated user, or null if the token is absent/expired. */
export async function getCurrentUser(): Promise<UserResponse | null> {
  if (!getAuthToken()) return null;
  try {
    const res = await apiFetch(baseUrl("/auth/me"));
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}


/**
 * Send a real-time student interaction signal to the backend cognitive tracker.
 *
 * Supported eventTypes:
 *   response_latency    payload: { delay_seconds: number }
 *   quiz_outcome        payload: { is_correct: boolean, difficulty?: number, misconception_trigger?: string }
 *   hesitation_indicator payload: { intensity: number }   (0–1)
 *   draw_pause          payload: { duration_ms: number }
 *   replay_scrub        payload: { delta_ms: number }     (negative = backward)
 *   session_interrupt   payload: {}
 *   concept_mastered    payload: {}
 */
export async function sendInteractionSignal(
  sessionId: string,
  eventType: string,
  payload: Record<string, any> = {},
  concept: string = "general"
): Promise<void> {
  const url = baseUrl(`/sessions/${encodeURIComponent(sessionId)}/interaction`);
  try {
    await apiFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ event_type: eventType, payload, concept }),
    });
  } catch (e) {
    // Fire-and-forget — tracker failures should never block the UI
    console.warn("sendInteractionSignal error", e);
  }
}

export default {
  interruptSession,
  extractImageText,
  createSession,
  registerUser,
  loginUser,
  logoutUser,
  getSessions,
  teachTopic,
  continueSession,
  adaptSession,
  getUser,
  getCurrentUser,
  sendInteractionSignal,
};
