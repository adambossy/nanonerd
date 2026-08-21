import { IdbStore } from "./idbStore";
import { MemoryStore } from "./memoryStore";
import { SyncScheduler, type SchedulerEnv } from "./scheduler";
import type { LocalStore } from "./store";
import { Syncer } from "./syncer";
import { HttpSyncApi } from "./transport";

/**
 * Composition root for the offline layer. Pages and hooks import `offline`
 * and talk to `store` (read/write local state) and `scheduler` (ask for a
 * sync, observe status). Nothing else in the app touches IndexedDB or the
 * sync endpoints.
 */

export interface Offline {
  store: LocalStore;
  syncer: Syncer;
  scheduler: SyncScheduler;
}

export function browserEnv(): SchedulerEnv {
  return {
    isOnline: () => navigator.onLine,
    isVisible: () => document.visibilityState === "visible",
    on(event, handler) {
      if (event === "online") {
        window.addEventListener("online", handler);
        return () => window.removeEventListener("online", handler);
      }
      if (event === "visible") {
        const onChange = () => {
          if (document.visibilityState === "visible") handler();
        };
        document.addEventListener("visibilitychange", onChange);
        return () => document.removeEventListener("visibilitychange", onChange);
      }
      const onHidden = () => {
        if (document.visibilityState === "hidden") handler();
      };
      document.addEventListener("visibilitychange", onHidden);
      window.addEventListener("pagehide", handler);
      return () => {
        document.removeEventListener("visibilitychange", onHidden);
        window.removeEventListener("pagehide", handler);
      };
    },
    setTimeout: (fn, ms) => window.setTimeout(fn, ms),
    clearTimeout: (handle) => window.clearTimeout(handle as number),
  };
}

export function createOffline(): Offline {
  const store: LocalStore =
    typeof indexedDB === "undefined" ? new MemoryStore() : new IdbStore();
  const syncer = new Syncer(store, new HttpSyncApi());
  const scheduler = new SyncScheduler(syncer, browserEnv());
  return { store, syncer, scheduler };
}

export const offline: Offline = createOffline();
offline.scheduler.start();

export { loadArticle, loadArticleList } from "./repository";
export type { SyncStatus } from "./types";
