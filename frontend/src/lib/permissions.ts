import type { ActionName, ResourceName, UserProfile } from "../types";

/** Mirror of the backend bitmask check: `(mask & bit) === bit`. */
export function hasAction(
  profile: Pick<UserProfile, "permissions" | "action_bits"> | null,
  resource: ResourceName,
  action: ActionName,
): boolean {
  if (!profile) return false;
  const bit = profile.action_bits[action];
  if (!bit) return false;
  return ((profile.permissions[resource] ?? 0) & bit) === bit;
}
