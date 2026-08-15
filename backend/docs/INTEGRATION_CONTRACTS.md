# Team integration contracts

The backend team owns HTTP routes, request/response schemas, validation, error mapping,
file upload handling, and service orchestration. It does not own database schemas,
vector search algorithms, model selection, or prompt quality.

## LLM team boundary

Implement `app.ports.persona_generator.PersonaGenerator`.

```python
async def generate(request: PersonaCreateRequest) -> dict[str, Any]:
    ...
```

Requirements:

- Return data compatible with `PersonaProfile`.
- Do not choose or return the final `agent_id`; the backend creates it.
- Raise `PersonaGeneratorError` for model, parsing, or connection failures.
- Model names, prompts, retries, and Ollama settings belong inside the adapter.

The same rule applies to `ReviewGenerator` and `ChatGenerator`:

- `app.ports.review_generator.ReviewGenerator`
- `app.ports.chat_generator.ChatGenerator`

The review generator returns claims, feedback, questions, and sources compatible
with `ReviewResult`. The chat generator returns an answer and optional sources
compatible with `ChatResponse`. The backend always supplies final IDs and path IDs.

## DB team boundary

Implement `app.ports.agent_repository.AgentRepository`.

```python
async def save(persona: PersonaProfile) -> None:
    ...

async def get(agent_id: UUID) -> PersonaProfile | None:
    ...
```

Requirements:

- Preserve the API model values supplied by the backend.
- Return `None` when an agent does not exist.
- Database sessions, migrations, SQLite tables, and Chroma collections stay inside
  the repository adapter.

Review persistence implements `app.ports.review_repository.ReviewRepository`.
Chat persistence can be added as a separate repository when the DB team finalizes
message-history requirements; the current HTTP contract does not assume a schema.

## HTTP error contract

All HTTP and validation failures use this public shape:

```json
{
  "error": {
    "code": "http_404",
    "message": "Review not found"
  }
}
```

## Wiring

When team implementations are ready, change only `app/dependencies.py`. Routes and
orchestration services must not import concrete DB or LLM libraries.
