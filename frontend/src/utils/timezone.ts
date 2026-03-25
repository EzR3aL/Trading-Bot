/**
 * Timezone utilities for converting between local and UTC hours.
 * The backend/scheduler always works in UTC. The frontend shows local times.
 */

export function getUserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** Convert a local hour (0-23) to UTC hour, accounting for DST. */
export function localHourToUtc(localHour: number): number {
  const now = new Date();
  now.setHours(localHour, 0, 0, 0);
  return now.getUTCHours();
}

/** Convert a UTC hour (0-23) to the user's local hour. */
export function utcHourToLocal(utcHour: number): number {
  const now = new Date();
  now.setUTCHours(utcHour, 0, 0, 0);
  return now.getHours();
}

/** Format timezone for display, e.g. "Europe/Berlin (UTC+2)" */
export function formatTimezone(): string {
  const tz = getUserTimezone();
  const offset = -(new Date().getTimezoneOffset() / 60);
  const sign = offset >= 0 ? '+' : '';
  return `${tz.replace(/_/g, ' ')} (UTC${sign}${offset})`;
}
