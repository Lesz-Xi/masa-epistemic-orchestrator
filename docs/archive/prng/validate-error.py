import hashlib
import logging

def generate_deterministic_seed(task_id: str) -> int:
    """
    Creates a consistent integer seed based on the task ID.
    If Task A fails today, it will use the exact same seed as if it failed tomorrow.
    """
    hash_obj = hashlib.sha256(task_id.encode('utf-8'))
    # Convert the first 8 hex characters to an integer (fits within most API limits)
    return int(hash_obj.hexdigest()[:8], 16)

def execute_with_epistemic_lock(task: ScientificTask, current_prompt: str, is_retry: bool):
    """
    Executes the Worker agent, applying strict deterministic locks if in a retry state.
    """
    if not is_retry:
        logging.info(f"Executing node {task.task_id} in EXPLORATION state.")
        api_params = EXPLORATION_CONFIG.copy()
    else:
        logging.warning(f"Executing node {task.task_id} in FALLBACK state. PRNG locked.")
        api_params = FALLBACK_CONFIG.copy()
        # Inject the deterministic seed
        api_params["seed"] = generate_deterministic_seed(task.task_id)

    # Execute the API call to the Worker LLM
    raw_response = llm_client.generate(
        prompt=current_prompt,
        **api_params
    )
    
    return raw_response
