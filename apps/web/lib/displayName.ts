/** Extract a user-friendly display name from Principal data.
 *
 * Priority order:
 * 1. display_name from user record (email/name from IdP claims)
 * 2. Email-format idp_subject (dev-login): show local part before @
 * 3. Entra format (entra:{tenant}:{object-id}): show last 8 chars of object-id
 * 4. Fallback: first 8 chars of user_id
 */
export function getDisplayName(userId: string, idpSubject: string, displayName?: string): string {
  // Prefer stored display name from IdP claims
  if (displayName) {
    return displayName;
  }

  // Email format (dev-login or future email-based IdP)
  if (idpSubject.includes("@")) {
    return idpSubject.split("@")[0];
  }

  // Entra format: entra:{tenant}:{object-id} -> show last 8 of object-id
  if (idpSubject.startsWith("entra:")) {
    const parts = idpSubject.split(":");
    if (parts.length === 3) {
      const objectId = parts[2];
      return objectId.slice(-8);
    }
  }

  // Fallback: first 8 of user_id
  return userId.slice(0, 8);
}
