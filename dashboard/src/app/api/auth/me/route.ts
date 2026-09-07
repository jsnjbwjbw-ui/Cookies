import { authConfig, getSession } from "@/lib/session";
import { json } from "@/lib/api";

export async function GET() {
  const user = await getSession();
  const config = authConfig();
  return json({
    authenticated: Boolean(user),
    user: user ?? null,
    config,
  });
}
