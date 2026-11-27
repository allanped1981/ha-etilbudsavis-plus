# eTilbudsavis Plus

A Home Assistant custom integration for searching eTilbudsavis offers,
managing selected shopping lists, and exposing integration functions through
Home Assistant's LLM API.

## Features

- Search offers and stores, with preferred-store and location filters.
- Add offers or regular items to selected eTilbudsavis shopping lists.
- Sign in with email one-time-code verification and synchronize selected lists.
- Expose selected lists as native Home Assistant todo entities.
- Use the dashboard card to search offers, manage list items, save searches,
  and group items by store or department.
- Use Home Assistant WebSocket commands and its LLM API for offer search,
  saved searches, and list operations.
- Optionally send a notification when an item is added from the card. Set the
  notification service in your own dashboard configuration; no device or
  notification target is included in the repository.

The integration calls eTilbudsavis consumer endpoints directly from Home
Assistant. These endpoints are undocumented and may change. See
[`docs/API_RESEARCH.md`](docs/API_RESEARCH.md) for the observed request shapes
and known limitations.

## Install and update

For Home Assistant 2026.11 and newer:

1. Open **Settings → Marketplace** and choose **Add from link**.
2. Add `allanped1981/ha-etilbudsavis-plus` as a custom repository.
3. Open **eTilbudsavis Plus** and select **Install**.
4. Complete email verification and choose the shopping lists and stores to
   use.

For older Home Assistant versions with HACS, add the same repository under
**HACS → Custom repositories** as an **Integration**, then download it and
restart Home Assistant.

The Marketplace or HACS checks the public repository for updates. Download an
available update and restart Home Assistant to update the integration and its
dashboard card together. The repository is not required to be listed in the
default catalog.

Add the dashboard resource `/etilbudsavis_plus/etilbudsavis-plus-card.js` as a
**JavaScript module** once, then add the card or adapt the example view in
[`dashboards/etilbudsavis-plus-view.yaml`](dashboards/etilbudsavis-plus-view.yaml).

### Optional mobile notifications

The card can call a Home Assistant notification service after adding an item.
Add the `notification_service` option to the card configuration and set it to
your own service name, for example `mobile_app_your_device`. Leave the option
out to disable notifications. See the dashboard example for the card's
configuration structure.

## MCP / LLM API

Home Assistant registers the integration's tools as the `etilbudsavis_plus`
LLM API. If Home Assistant's built-in MCP Server integration is enabled, the
API is available at `/api/mcp/etilbudsavis_plus`.

## Development checks

```sh
python -m unittest discover -s tests
python -m compileall -q custom_components tests
node --check custom_components/etilbudsavis_plus/www/etilbudsavis-plus-card.js
```

These checks use mocked service responses. They do not confirm that the
undocumented upstream API will continue to accept requests.
