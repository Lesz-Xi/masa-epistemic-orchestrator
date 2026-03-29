## For a scientific discovery engine like MASA, this is unacceptable. If an agent fails an epistemic constraint, you must freeze the environment. When the Fixer Agent provides a rewritten prompt, we need absolute certainty that the subsequent change in the Worker's output was caused by the new prompt, not by random token sampling.

Here is how we architect strict PRNG (Pseudo-Random Number Generator) seed locking and parameter shifting within your orchestration layer.

## 1. The Execution Context Configuration
## Source: context-config.py
We need to define two distinct states for your Worker agents: Exploration State (normal operation) and Fallback State (strict determinism).

You should define these configurations as constants in your orchestration backend.

## 2. Injecting the Seed dynamically (The Causal Lock)
## Source: validate-error.py

When the orchestration loop catches a ValidationError, it triggers the fallback. We don't just use a hardcoded seed like 42 for every task, because different tasks might share the same cached outputs. Instead, we generate a deterministic seed based on the unique task_id.


3. The Orchestration Flow (Putting it together)
When the system is running, the flow looks like this:

Attempt 1: The Worker tries to analyze a paper. It uses temperature: 0.7. It hallucinates a JSON key.

The Catch: Pydantic throws an error. The Orchestrator halts the Worker.

The Fixer: The Orchestrator passes the error to the fixer_agent, which generates a highly specific, corrected prompt.

Attempt 2 (The Lock): The Orchestrator calls execute_with_epistemic_lock(is_retry=True). The temperature drops to 0.0, top_p drops to 0.1, and the seed is locked to the task_id hash.

The Result: The Worker executes the corrected prompt in a completely frozen, deterministic environment. If it succeeds, it proceeds. If it fails again, it eventually hits the 3-strike limit and pushes the trace to your React console.
