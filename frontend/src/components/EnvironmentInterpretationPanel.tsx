import { BrainCircuit } from 'lucide-react';

import StatusBadge from './StatusBadge';
import type { EnvironmentInterpretation } from '../utils/environmentAnalysis';

export default function EnvironmentInterpretationPanel({ analysis }: { analysis: EnvironmentInterpretation }) {
  return (
    <section className={`panel environment-intelligence-panel tone-${analysis.tone}`}
      aria-labelledby="environment-intelligence-title" data-risk={analysis.risk ?? analysis.availability}>
      <div className="panel-heading">
        <h2 id="environment-intelligence-title"><BrainCircuit size={17} className="text-cyan-400"
          aria-hidden="true" />AI ENVIRONMENT INTERPRETATION</h2>
        <StatusBadge tone={analysis.tone}>{analysis.label}</StatusBadge>
      </div>
      <p className="environment-intelligence-summary">{analysis.title}</p>
      <div className="environment-intelligence-details">
        <div>
          <h3>Observations</h3>
          <ul>{analysis.observations.map(observation => <li key={observation}>{observation}</li>)}</ul>
        </div>
        <div className="environment-intelligence-action">
          <h3>Recommended action</h3>
          <p>{analysis.recommendedAction}</p>
        </div>
      </div>
      <p className="environment-model-note">{analysis.modelNote}<br />
        Risk uses recent retained history; older episode state may be unavailable. Automatic alarms follow the server configuration.
      </p>
    </section>
  );
}
