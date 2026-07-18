import { cookies } from "next/headers";
import { AppShell } from "@/components/AppShell";
import { SignIn } from "@/components/SignIn";
import { whoami } from "@/lib/backendAuth";

// The workspace is gated on a real Entra session (A2). Checked server-side: an
// unauthenticated visitor sees the sign-in screen, never the workspace.
export const dynamic = "force-dynamic";

export default async function Page() {
  const cookieHeader = cookies()
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const user = await whoami(cookieHeader);

  if (!user) return <SignIn />;
  // Open on the Legal spoke to mirror the design-language blueprint (§5).
  return <AppShell initialSpoke="legal" user={user} />;
}
