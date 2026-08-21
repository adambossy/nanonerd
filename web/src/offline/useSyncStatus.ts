import { useEffect, useState } from "react";
import { offline } from "./index";
import type { SyncStatus } from "./types";

/** React adapter over the scheduler's status stream. */
export function useSyncStatus(): SyncStatus {
  const [status, setStatus] = useState<SyncStatus>(() => offline.scheduler.getStatus());
  useEffect(() => offline.scheduler.subscribe(setStatus), []);
  return status;
}
