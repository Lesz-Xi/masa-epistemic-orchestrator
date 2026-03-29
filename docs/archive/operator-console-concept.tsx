import React from 'react';
import { AlertTriangle, Clock, Activity, DollarSign, Terminal, GitBranch } from 'lucide-react';

// Expected Payload Structure from the Streamable HTTP Transport
interface TracePayload {
  taskId: string;
  workerObjective: string;
  errorType:
    | 'PydanticValidationError'
    | 'EpistemicBoundaryViolation'
    | 'LogicFailure'
    | 'JSONParseError'
    | 'ClientError';
  errorMessage: string;
  metrics: {
    ttft: number; // Time To First Token (ms)
    tps: number;  // Tokens Per Second
    cost: number; // USD
  };
  attemptedReasoning: string[];
}

export const DelegationFailureTrace = ({ payload }: { payload: TracePayload }) => {
  return (
    <div className="w-full max-w-4xl mx-auto bg-neutral-900 border border-red-900/50 rounded-lg shadow-2xl overflow-hidden font-mono text-sm text-neutral-300">
      
      {/* HEADER: Hard Termination Alert */}
      <div className="bg-red-950/30 border-b border-red-900/50 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <AlertTriangle className="text-red-500 w-5 h-5" />
          <h2 className="text-red-50 font-semibold tracking-wide uppercase">
            Delegation Terminated: {payload.errorType}
          </h2>
        </div>
        <span className="text-neutral-500 text-xs tracking-widest">ID: {payload.taskId}</span>
      </div>

      <div className="p-6 space-y-8">
        {/* METRICS ROW: LLMOps Tracing */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-neutral-800/50 p-4 rounded border border-neutral-800 flex items-center space-x-4">
            <Clock className="text-amber-500 w-4 h-4" />
            <div>
              <p className="text-neutral-500 text-xs uppercase">TTFT (Latency)</p>
              <p className="text-neutral-100 font-medium">{payload.metrics.ttft} ms</p>
            </div>
          </div>
          <div className="bg-neutral-800/50 p-4 rounded border border-neutral-800 flex items-center space-x-4">
            <Activity className="text-blue-500 w-4 h-4" />
            <div>
              <p className="text-neutral-500 text-xs uppercase">Generation Speed</p>
              <p className="text-neutral-100 font-medium">{payload.metrics.tps} TPS</p>
            </div>
          </div>
          <div className="bg-neutral-800/50 p-4 rounded border border-neutral-800 flex items-center space-x-4">
            <DollarSign className="text-green-500 w-4 h-4" />
            <div>
              <p className="text-neutral-500 text-xs uppercase">Node Token Cost</p>
              <p className="text-neutral-100 font-medium">${payload.metrics.cost.toFixed(4)}</p>
            </div>
          </div>
        </div>

        {/* TRACE: What went wrong */}
        <div className="space-y-4">
          <div>
            <h3 className="flex items-center text-neutral-400 uppercase text-xs font-semibold mb-2">
              <Terminal className="w-4 h-4 mr-2" /> Original Worker Objective
            </h3>
            <p className="bg-neutral-950 p-3 rounded border border-neutral-800 text-neutral-300">
              {payload.workerObjective}
            </p>
          </div>

          <div>
            <h3 className="flex items-center text-red-400 uppercase text-xs font-semibold mb-2">
              <GitBranch className="w-4 h-4 mr-2" /> Schema / Logic Exception
            </h3>
            <pre className="bg-red-950/20 p-4 rounded border border-red-900/30 text-red-200 overflow-x-auto whitespace-pre-wrap">
              {payload.errorMessage}
            </pre>
          </div>

          <div>
            <h3 className="text-neutral-400 uppercase text-xs font-semibold mb-2">
              Attempted Reasoning Chain (Pre-Failure)
            </h3>
            <div className="bg-neutral-950 border border-neutral-800 rounded p-4 space-y-2">
              {payload.attemptedReasoning.map((step, index) => (
                <div key={index} className="flex space-x-3">
                  <span className="text-neutral-600">[{index + 1}]</span>
                  <span className="text-neutral-400">{step}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* FOOTER: Operator Actions */}
      <div className="bg-neutral-950 border-t border-neutral-800 px-6 py-4 flex justify-end space-x-4">
        <button className="px-4 py-2 rounded text-neutral-400 hover:text-white transition-colors text-xs uppercase font-semibold">
          Override & Approve
        </button>
        <button className="px-4 py-2 bg-neutral-100 text-neutral-900 rounded hover:bg-white transition-colors text-xs uppercase font-semibold">
          Trigger Manual Fixer Agent
        </button>
      </div>
    </div>
  );
};
