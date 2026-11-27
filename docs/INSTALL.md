# Installation

## Install with Home Assistant Marketplace

On Home Assistant 2026.11 or newer:

1. Go to **Settings → Marketplace → Add from link**.
2. Add `allanped1981/ha-etilbudsavis-plus` as a custom repository.
3. Open **eTilbudsavis Plus** and select **Install**.
4. Follow the email verification flow and select the shopping lists and stores
   the integration should use.
5. In **Settings → Dashboards → Resources**, add
   `/etilbudsavis_plus/etilbudsavis-plus-card.js` with type **JavaScript
   module** once.
6. Add the card to a dashboard, or adapt
   [`../dashboards/etilbudsavis-plus-view.yaml`](../dashboards/etilbudsavis-plus-view.yaml).

For older Home Assistant versions with HACS, add this repository as a custom
**Integration** repository, download it, restart Home Assistant, then set up
the integration and resource as above.

The card is served from inside the integration directory. Marketplace or HACS
updates the integration and card together. After downloading an update,
restart Home Assistant and reload the dashboard in the browser.

## Optional notifications

To notify a phone or another target after an item is added from the card, add
`notification_service` to that card's configuration and set it to a service
available in your Home Assistant instance. For example:

```yaml
type: custom:etilbudsavis-plus-card
notification_service: mobile_app_your_device
```

The notification option is disabled when omitted. The repository contains no
device-specific service name.

## Account and upstream API

The integration requests an email one-time code and stores the resulting
account session in the Home Assistant config entry. It does not require a
browser session cookie to be copied into the setup.

The consumer API is undocumented and can change without notice. See
[`API_RESEARCH.md`](API_RESEARCH.md) for the observed contract and limitations.

## MCP / LLM API

The integration registers an LLM API named `etilbudsavis_plus`. If Home
Assistant's built-in MCP Server integration is configured, the tools are
available at `/api/mcp/etilbudsavis_plus`.

## Remove

Remove the integration from **Settings → Devices & services**, remove the
dashboard resource, and remove the card from dashboards. This does not delete
shopping lists stored by eTilbudsavis.
