    You are given a single email thread between brokers, customers, and an insurance/claims operations team.
    The content has already been redacted to remove personal identifiers.

    Your job is to **triage this one thread** into a structured JSON object following the `ThreadTriageResult` schema
    and the system rules you have been given. Do not include any explanation or prose; output **only** the JSON object.

    Thread metadata:
    - Number of messages in thread: {message_count}

    Thread content (most recent last):

    {thread_content}

    Now, produce a single JSON object that:
    - Conforms exactly to the `ThreadTriageResult` schema.
    - Uses one of the allowed values for `classification` and `priority`.
    - Includes clear, imperative `required_actions` where any follow-up is needed.
    - Includes `key_entities` only when supported by the text (unknown values must be set to "unknown" or omitted).
    - Includes short `evidence_snippets` quoting the most relevant lines supporting your decisions.
    - Sets `confidence` between 0 and 1.

    Remember: output **only** the JSON object, with no surrounding markdown or commentary.
