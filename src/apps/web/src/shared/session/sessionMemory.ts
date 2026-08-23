import {
  createGuestSession,
  getCurrentSession,
  type SessionContext,
} from "../api/publicService";

let guestToken: string | undefined;
let sessionContext: SessionContext | null = null;
let inspected = false;
let inspection: Promise<SessionContext | null> | null = null;

export function currentGuestToken(): string | undefined {
  return guestToken;
}

export function rememberGuestSession(token: string, context: SessionContext) {
  guestToken = token;
  sessionContext = context;
  inspected = true;
}

export function clearSessionMemory() {
  guestToken = undefined;
  sessionContext = null;
  inspected = false;
  inspection = null;
}

export async function inspectCurrentSession(): Promise<SessionContext | null> {
  if (inspected) return sessionContext;
  if (inspection !== null) return inspection;
  inspection = getCurrentSession(guestToken).then(({ data, response }) => {
    inspected = true;
    sessionContext = response.ok && data !== undefined ? data : null;
    return sessionContext;
  }).finally(() => { inspection = null; });
  return inspection;
}

export async function ensureSearchSession(): Promise<SessionContext> {
  const current = await inspectCurrentSession();
  if (current !== null) return current;

  const created = await createGuestSession();
  if (!created.response.ok || created.data === undefined) throw new Error("Guest session unavailable");
  guestToken = created.data.guestToken;
  inspected = false;
  const verified = await inspectCurrentSession();
  if (verified === null) {
    clearSessionMemory();
    throw new Error("Guest session verification failed");
  }
  return verified;
}
