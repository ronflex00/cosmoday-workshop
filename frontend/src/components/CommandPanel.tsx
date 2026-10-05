import { useEffect, useRef, useState } from 'react';
import { BellRing, CheckCircle2, LoaderCircle, Power, Square, TriangleAlert } from 'lucide-react';

import { sendCommand } from '../services/api';
import type { Command } from '../types/sentinel';
import { formatTime } from '../utils/format';

export default function CommandPanel({ enabled }: { enabled: boolean }) {
  const [pending, setPending] = useState<'activate' | 'stop' | null>(null);
  const [feedback, setFeedback] = useState<{ success: boolean; message: string; ts: number } | null>(null);
  const request = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      request.current?.abort();
    };
  }, []);

  async function publish(command: Command) {
    if (!enabled || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(command.buzzer ? 'activate' : 'stop');
    setFeedback(null);
    const timeout = window.setTimeout(() => controller.abort(), 5_000);
    try {
      await sendCommand(command, controller.signal);
      if (!mounted.current) return;
      setFeedback({ success: true, message: command.buzzer ? 'Alarm activation command sent.' : 'Alarm stop command sent.', ts: Date.now() });
    } catch (error) {
      if (!mounted.current) return;
      setFeedback({ success: false, message: controller.signal.aborted
        ? 'Publication not confirmed. Check the node before retrying.'
        : error instanceof Error ? error.message : 'Command publication failed.', ts: Date.now() });
    } finally {
      window.clearTimeout(timeout);
      request.current = null;
      if (mounted.current) setPending(null);
    }
  }

  return (
    <section className="panel commands-panel" aria-labelledby="commands-title">
      <div className="panel-heading"><h2 id="commands-title"><Power size={17} className="text-cyan-400" aria-hidden="true" />Node controls</h2>
        <span className="section-meta">LED / BUZZER</span></div>
      <div className="command-buttons">
        <button className="command-button activate" disabled={!enabled || pending !== null} onClick={() => void publish({ buzzer: true, led: 'red' })}>
          {pending === 'activate' ? <LoaderCircle className="animate-spin" size={18} aria-hidden="true" /> : <BellRing size={18} aria-hidden="true" />}
          {pending === 'activate' ? 'SENDING…' : 'ACTIVATE ALARM'}
        </button>
        <button className="command-button stop" disabled={!enabled || pending !== null} onClick={() => void publish({ buzzer: false, led: 'green' })}>
          {pending === 'stop' ? <LoaderCircle className="animate-spin" size={18} aria-hidden="true" /> : <Square size={16} aria-hidden="true" />}
          {pending === 'stop' ? 'SENDING…' : 'STOP ALARM'}
        </button>
      </div>
      {feedback && <div className={`command-feedback tone-${feedback.success ? 'success' : 'danger'}`} role={feedback.success ? 'status' : 'alert'}>
        {feedback.success ? <CheckCircle2 size={16} aria-hidden="true" /> : <TriangleAlert size={16} aria-hidden="true" />}
        <span>{feedback.message}<small>{formatTime(feedback.ts)}</small></span>
      </div>}
      <p className="control-footnote">{!enabled ? 'Controls unavailable · connect the backend and MQTT.'
        : 'Command receipt at the node is not yet reported.'}</p>
    </section>
  );
}
