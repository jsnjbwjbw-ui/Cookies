import { NextResponse } from "next/server";
import { getSession, type SessionUser } from "@/lib/session";
import { logAudit } from "@/lib/audit";

export function json(data: unknown, status = 200) {
  return NextResponse.json(data, { status });
}

export function unauthorized() {
  return NextResponse.json({ error: "يجب تسجيل الدخول عبر ديسكورد أولًا" }, { status: 401 });
}

export function forbidden() {
  return NextResponse.json({ error: "هذه العملية للمشرفين فقط" }, { status: 403 });
}

export async function requireAuth(): Promise<SessionUser | NextResponse> {
  const user = await getSession();
  if (!user) return unauthorized();
  return user;
}

export async function requireAdmin(): Promise<SessionUser | NextResponse> {
  const user = await getSession();
  if (!user) return unauthorized();
  if (!user.isAdmin) return forbidden();
  return user;
}

export function isResponse(v: unknown): v is NextResponse {
  return v instanceof NextResponse;
}

export { logAudit };
