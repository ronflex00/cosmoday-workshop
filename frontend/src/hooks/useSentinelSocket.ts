import { useEffect, useState } from 'react';

import { fetchState, WS_URL } from '../services/api';
import { isStateMessage } from '../types/sentinel';
import type { SentinelState } from '../types/sentinel';

export function useSentinelSocket() {
  const [state, setState] = useState<SentinelState | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receivedAt, setReceivedAt] = useState<string | null>(null);

  useEffect(() => {
    setConnected(false);
    let stopped = false;
    let socket: WebSocket | null = null;
    let controller: AbortController | null = null;
    let retryTimer: number | undefined;
    let connectionTimer: number | undefined;
    let attempts = 0;

    function retry() {
      if (stopped || retryTimer !== undefined) return;
      const delay = Math.min(1_000 * 2 ** Math.min(attempts, 4), 10_000);
      attempts += 1;
      retryTimer = window.setTimeout(() => {
        retryTimer = undefined;
        void connect();
      }, delay);
    }

    async function connect() {
      if (stopped) return;
      const request = new AbortController();
      controller = request;
      const requestTimeout = window.setTimeout(() => request.abort(), 5_000);
      try {
        // Every connection starts with REST; the WS initial snapshot then closes the gap.
        const initial = await fetchState(request.signal);
        if (stopped) return;
        setState(initial);
        setReceivedAt(new Date().toISOString());
        setError(null);
      } catch {
        if (!stopped) {
          setError('Le backend est inaccessible ou sa réponse est invalide. Nouvelle tentative automatique…');
          retry();
        }
        return;
      } finally {
        window.clearTimeout(requestTimeout);
        if (controller === request) controller = null;
      }
      if (stopped) return;

      let current: WebSocket;
      try {
        current = new WebSocket(WS_URL);
      } catch {
        setError('La connexion en temps réel est indisponible. Nouvelle tentative automatique…');
        retry();
        return;
      }
      socket = current;
      connectionTimer = window.setTimeout(() => {
        if (current.readyState === WebSocket.CONNECTING) current.close();
      }, 5_000);

      current.onopen = () => {
        if (stopped || socket !== current) return;
        window.clearTimeout(connectionTimer);
        attempts = 0;
        setConnected(true);
        setError(null);
      };

      current.onmessage = (event) => {
        if (stopped || socket !== current) return;
        try {
          const message: unknown = JSON.parse(event.data);
          if (!isStateMessage(message)) throw new Error('Invalid state message');
          setState(message.data);
          setReceivedAt(new Date().toISOString());
          setError(null);
        } catch {
          console.warn('[WS] Message invalide ignoré');
          setError('Une mise à jour incorrecte a été ignorée. Les dernières données valides sont conservées.');
        }
      };

      current.onerror = () => {
        if (stopped || socket !== current) return;
        setConnected(false);
        setError('La connexion en temps réel est interrompue. Reconnexion automatique…');
        current.close();
      };

      current.onclose = () => {
        if (stopped || socket !== current) return;
        window.clearTimeout(connectionTimer);
        socket = null;
        setConnected(false);
        setError('La connexion en temps réel est interrompue. Reconnexion automatique…');
        retry();
      };
    }

    void connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      window.clearTimeout(connectionTimer);
      controller?.abort();
      if (socket) {
        socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
        socket.close();
      }
    };
  }, []);

  return { state, connected, error, receivedAt };
}
