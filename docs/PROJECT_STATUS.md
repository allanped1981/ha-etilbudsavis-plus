# Project status

Current integration version: `0.1.16`.

## Included

- Offer search, store lookup, preferred-store and location filters.
- Email one-time-code account setup and selected-list synchronization.
- Native Home Assistant todo entities.
- Dashboard card for offer search, list editing, saved searches, grouping, and
  optional notifications.
- WebSocket commands and an LLM API for search and list operations.
- Mocked contract tests for upstream request and response handling.

## Distribution

The repository is structured as a single Home Assistant custom integration for
HACS. The dashboard card is installed with the integration and served from the
integration directory, so both are upgraded together.

## Known limitations

- eTilbudsavis consumer endpoints are undocumented and may change.
- Contract tests use mocked responses; they do not guarantee that the remote
  service will continue to accept the observed requests.
- Account-session renewal and some upstream response fields are not fully
  established. See [`API_RESEARCH.md`](API_RESEARCH.md).
- A notification target must be selected by each Home Assistant user in their
  own dashboard configuration.
