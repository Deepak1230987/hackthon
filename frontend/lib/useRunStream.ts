"use client";

import { useEffect, useReducer, useState } from "react";

import { ApiRequestError, fetchRun, runEventsUrl } from "./api";
import { initialRunState, isTerminal, runReducer } from "./runReducer";
import {
  RUN_EVENT_TYPES,
  type ConnectionState,
  type RunEventType,
  type RunStatus,
  type RunView,
} from "./types";

const MAX_SSE_FAILURES = 3;
const POLL_INTERVAL_MS = 3000;
const REFRESH_MS = 1000;
// Events carry ids only, and these arrive in bursts, so the view is read at most
// once a second while they do.
const REFRESH_EVENTS = new Set<string>([
  "claim_verified",
  "verdict",
  "script_ready",
  "sentence_translated",
  "guard_failed",
  "sentence_ready",
]);

// Retrying can't fix a 4xx, except for a timeout or a rate limit.
function isFinalRejection(status: number | undefined): boolean {
  return (
    status !== undefined &&
    status >= 400 &&
    status < 500 &&
    status !== 408 &&
    status !== 429
  );
}

export function useRunStream(runId: string): {
  view: RunView;
  connection: ConnectionState;
  loaded: boolean;
} {
  const [state, dispatch] = useReducer(runReducer, initialRunState);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let stopped = false;
    let source: EventSource | undefined;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let refreshTimer: ReturnType<typeof setTimeout> | undefined;

    // Returns false when there is nothing more to wait for.
    const loadSnapshot = async (): Promise<boolean> => {
      try {
        const run = await fetchRun(runId);
        if (stopped) return false;
        dispatch({ type: "snapshot", run });
        setLoaded(true);
        return !isTerminal(run.status);
      } catch (e) {
        if (stopped) return false;
        if (e instanceof ApiRequestError && isFinalRejection(e.httpStatus)) {
          dispatch({ type: "rejected", error: e.error });
          setLoaded(true);
          return false;
        }
        return true;
      }
    };

    const poll = async () => {
      setConnection("polling");
      const keepGoing = await loadSnapshot();
      if (stopped) return;
      if (keepGoing) pollTimer = setTimeout(poll, POLL_INTERVAL_MS);
      else setConnection("closed");
    };

    const openStream = () => {
      let failures = 0;
      const stream = new EventSource(runEventsUrl(runId));
      source = stream;

      stream.onopen = () => {
        failures = 0;
        setConnection("live");
      };

      stream.onerror = () => {
        failures += 1;
        if (
          stream.readyState === EventSource.CLOSED ||
          failures >= MAX_SSE_FAILURES
        ) {
          stream.close();
          void poll();
        } else {
          setConnection("reconnecting");
        }
      };

      for (const type of RUN_EVENT_TYPES) {
        stream.addEventListener(type, (message) => {
          const seq = Number(message.lastEventId);
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse(message.data);
          } catch {
            return;
          }
          if (!Number.isInteger(seq)) return;
          dispatch({
            type: "event",
            event: { seq, type: type as RunEventType, payload },
          });
          setLoaded(true);
          const ended =
            type === "run_status" && isTerminal(payload.status as RunStatus);
          if (ended) {
            stream.close();
            setConnection("closed");
          }
          // Events don't carry the document, so read it once it has changed.
          if (
            ended ||
            type === "segment_done" ||
            (type === "run_status" && payload.status === "waiting_input") ||
            (type === "node_finished" && payload.node === "acquire")
          ) {
            void loadSnapshot();
          }
          if (REFRESH_EVENTS.has(type) && !refreshTimer) {
            refreshTimer = setTimeout(() => {
              refreshTimer = undefined;
              void loadSnapshot();
            }, REFRESH_MS);
          }
        });
      }
    };

    void loadSnapshot().then((keepGoing) => {
      if (stopped) return;
      if (keepGoing) openStream();
      else setConnection("closed");
    });

    return () => {
      stopped = true;
      source?.close();
      if (pollTimer) clearTimeout(pollTimer);
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [runId]);

  return { view: state.view, connection, loaded };
}
