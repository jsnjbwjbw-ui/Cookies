import crypto from "node:crypto";
import { cookies } from "next/headers";

/**
 * جلسة موقّعة HMAC-SHA256 في كوكي httpOnly — خفيفة وبلا تبعيات.
 * في وضع الإنتاج اضبط SESSION_SECRET، وإلا يُستخدم سر تطوير.
 */

export interface SessionUser {
  id: string;
  username: string;
  globalName?: string;
  avatar?: string;
  isAdmin: boolean;
  demo?: boolean;
}

export interface SessionPayload {
  user: SessionUser;
  iat: number;
  exp: number;
}

const COOKIE_NAME = "ct_session";
const MAX_AGE = 60 * 60 * 24 * 7; // أسبوع

function secret(): string {
  return process.env.SESSION_SECRET || "cookies-tracker-dev-secret-change-me";
}

function b64url(buf: Buffer): string {
  return buf.toString("base64url");
}

function sign(data: string): string {
  return crypto.createHmac("sha256", secret()).update(data).digest("base64url");
}

export function createToken(user: SessionUser): string {
  const payload: SessionPayload = {
    user,
    iat: Date.now(),
    exp: Date.now() + MAX_AGE * 1000,
  };
  const body = b64url(Buffer.from(JSON.stringify(payload), "utf8"));
  return `${body}.${sign(body)}`;
}

export function verifyToken(token: string | undefined | null): SessionPayload | null {
  if (!token) return null;
  const [body, sig] = token.split(".");
  if (!body || !sig) return null;
  const expected = sign(body);
  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  try {
    const payload = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as SessionPayload;
    if (!payload.exp || payload.exp < Date.now()) return null;
    return payload;
  } catch {
    return null;
  }
}

export async function getSession(): Promise<SessionUser | null> {
  const store = await cookies();
  const payload = verifyToken(store.get(COOKIE_NAME)?.value);
  return payload?.user ?? null;
}

export async function setSessionCookie(user: SessionUser): Promise<void> {
  const store = await cookies();
  store.set(COOKIE_NAME, createToken(user), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: MAX_AGE,
  });
}

export async function clearSessionCookie(): Promise<void> {
  const store = await cookies();
  store.set(COOKIE_NAME, "", { httpOnly: true, path: "/", maxAge: 0 });
}

export function authConfig() {
  return {
    oauthEnabled: Boolean(process.env.DISCORD_CLIENT_ID && process.env.DISCORD_CLIENT_SECRET),
    mode: process.env.MONGODB_URI ? ("mongo" as const) : ("demo" as const),
    guildId: process.env.DISCORD_GUILD_ID || null,
    botLinked: Boolean(process.env.DISCORD_BOT_TOKEN),
  };
}
