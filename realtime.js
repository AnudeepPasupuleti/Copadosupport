/**
 * SSE realtime client with polling fallback for Team Queue.
 */
(function () {
  let es = null;
  let connected = false;
  let reconnectTimer = null;
  let pollOnly = false;

  function setStatus(state) {
    const el = document.getElementById("realtime-status");
    if (!el) return;
    el.hidden = false;
    el.dataset.state = state;
    el.textContent =
      state === "connected"
        ? "Live"
        : state === "reconnecting"
          ? "Reconnecting…"
          : "Polling";
  }

  function invalidate(envelope) {
    const type = envelope && envelope.event_type;
    if (!type) return;
    if (window.TeamApp) {
      if (type.startsWith("case.") || type.startsWith("comment.") || type.startsWith("mention.")) {
        window.TeamApp.onRealtimeEvent?.(envelope);
      }
      if (type === "notification.created" || type.startsWith("mention.") || type === "case.assigned") {
        window.TeamApp.refreshNotifications?.();
      }
      if (type === "client.refetch") {
        window.TeamApp.onRealtimeEvent?.(envelope);
        window.TeamApp.refreshNotifications?.();
      }
    }
  }

  function connect() {
    if (pollOnly || typeof EventSource === "undefined") {
      setStatus("polling");
      return;
    }
    if (es) {
      es.close();
      es = null;
    }
    setStatus("reconnecting");
    es = new EventSource("/api/events/stream", { withCredentials: true });
    es.onopen = () => {
      connected = true;
      setStatus("connected");
    };
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        invalidate(data);
      } catch {
        /* ignore */
      }
    };
    es.onerror = () => {
      connected = false;
      setStatus("reconnecting");
      if (es) {
        es.close();
        es = null;
      }
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    };
  }

  async function boot() {
    try {
      const res = await fetch("/api/queue/meta", { credentials: "same-origin" });
      if (!res.ok) {
        pollOnly = true;
        setStatus("polling");
        return;
      }
      const meta = await res.json();
      if (!meta?.features?.realtime_sse) {
        pollOnly = true;
        setStatus("polling");
        return;
      }
      connect();
    } catch {
      pollOnly = true;
      setStatus("polling");
    }
  }

  window.RealtimeApp = {
    boot,
    isConnected: () => connected,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
