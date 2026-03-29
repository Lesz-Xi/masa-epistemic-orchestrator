# ---------------------------------------------------------
# MASA Orchestrator: Execution State Configurations
# ---------------------------------------------------------

EXPLORATION_CONFIG = {
    "temperature": 0.7,      # Allows for creative hypothesis generation
    "top_p": 0.9,            # Standard nucleus sampling
    "top_k": 40,             # Standard token pool
    "response_format": {"type": "json_object"}
}

FALLBACK_CONFIG = {
    "temperature": 0.0,      # Eliminates all creative variance; enforces greedy decoding
    "top_p": 0.1,            # Severely restricts the token probability distribution
    "top_k": 1,              # Only consider the absolute most likely next token
    "response_format": {"type": "json_object"}
    # The 'seed' is injected dynamically based on the task ID
}
