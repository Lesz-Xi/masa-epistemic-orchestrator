def generate_fixer_prompt(worker_objective: str, error_trace: str, attempted_reasoning: list) -> str:
    return f"""
You are the MASA Orchestrator Epistemic Fixer Agent. 
A Scientific Worker agent has triggered an output guardrail and failed validation.

Your objective is to diagnose the failure and generate a corrected, highly concrete prompt to retry the Worker. 

<CONTEXT>
Original Objective: {worker_objective}
Attempted Reasoning Chain: {attempted_reasoning}
</CONTEXT>

<ERROR_TRACE>
{error_trace}
</ERROR_TRACE>

INSTRUCTIONS:
1. Analyze the Error Trace against the Attempted Reasoning. Identify exactly where the Worker violated the epistemic constraints, hallucinated a format, or failed the JSON schema.
2. Draft a precise, highly directive rewritten prompt for the Worker. 
3. The rewritten prompt MUST explicitly forbid the action that caused the error.

You must output your response STRICTLY in the following JSON format. Do not include markdown formatting or conversational filler outside the JSON.

{{
  "diagnostics": {{
    "failure_point": "Brief explanation of where the logic or schema broke.",
    "correction_strategy": "Brief explanation of how the rewritten prompt fixes it."
  }},
  "rewritten_prompt": "The exact, concrete string to send back to the Worker for its retry attempt."
}}
"""
