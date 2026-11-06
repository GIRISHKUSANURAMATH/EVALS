"""Evaluation categories and the mapping from detected failure types to categories."""

from __future__ import annotations

BUILTIN_CATEGORIES: dict[str, str] = {
    "correctness": "Does the response correctly answer the request?",
    "hallucination": "Does the response contain fabricated or unsupported claims?",
    "relevance": "Is the response relevant to the specific input?",
    "instruction_following": "Does the response follow explicit instructions (format, constraints)?",
    "safety": "Is the response safe, and are refusals appropriate?",
    "formatting": "Is the output well-formed and complete?",
    "tool_usage": "Are tools called correctly and are tool errors handled?",
    "latency": "Does the system respond within acceptable time?",
    "error_handling": "Does the system degrade gracefully when something fails?",
    "edge_cases": "Unusual inputs the system should handle robustly.",
}

FAILURE_TO_CATEGORY: dict[str, str] = {
    "application_error": "error_handling",
    "timeout": "latency",
    "excessive_latency": "latency",
    "empty_response": "error_handling",
    "missing_response": "error_handling",
    "malformed_structured_output": "instruction_following",
    "tool_call_failure": "tool_usage",
    "negative_feedback": "correctness",
    "hallucination_candidate": "hallucination",
    "repetitive_output": "formatting",
    "truncated_output": "formatting",
    "canned_response": "relevance",
    "refusal": "safety",
    "edge_case_input": "edge_cases",
    "repeated_failure": "error_handling",
}

# Priority used to pick the primary failure when a trace has several (lower = more important).
FAILURE_PRIORITY: list[str] = [
    "hallucination_candidate",
    "tool_call_failure",
    "malformed_structured_output",
    "timeout",
    "application_error",
    "empty_response",
    "missing_response",
    "truncated_output",
    "negative_feedback",
    "refusal",
    "repetitive_output",
    "canned_response",
    "excessive_latency",
    "edge_case_input",
    "repeated_failure",
]
