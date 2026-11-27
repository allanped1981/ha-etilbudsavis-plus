# API research and capability status

Research completed 2026-11-24. The offer search response observed during
research omitted image URLs. A request to `/v2/offers/{offerId}` returned the
offer's `images.thumb`, `images.view`, and `images.zoom` URLs. The integration
uses the detail endpoint to enrich results when needed.

## Observed offer search

Community source code calls `https://api.etilbudsavis.dk/v2/offers/search` with
`query`, `country_id`, `limit`, `offset`, and `api_av`; optional parameters
include `dealer_ids` and geographic fields `r_lat`, `r_lng`, `r_radius`, and
`r_locale`. The implementation in this repository uses those observed fields
and reports upstream failures without inventing missing offer data.

Expected result fields observed in community code include `id`, `heading`,
`description`, `pricing.price`, `pricing.currency`, `branding`, `dealer`,
`quantity`, `run_from`, and `run_till`. Exact field availability may vary.
The offer detail endpoint returns `images.thumb`, `images.view`, and
`images.zoom`; the `thumb` is a cropped offer image matching the one shown on
eTilbudsavis. The integration now uses it as an image fallback. Lookups are
best-effort and limited to the first 30 image-less results, with at most four
requests in flight. A detail lookup failure leaves the offer visible with its
placeholder.

## Account-based lists

The current README for `CagosDk/hacs-etilbudsavis` describes email one-time-code
login, selecting lists, and synchronization of list items. It also describes
its API use as internal and unsupported. Read-only inspection of its current
`api.py` shows a client key in the source and the OTP/list request shapes. The
repository has no explicit source-code license, so this project does not copy
its implementation. It includes only the observed public client-key value,
which is not an account credential.

The client key and endpoint acceptance may change. A previous assumption that
the key can be acquired from a supported developer portal has not been
verified. The config flow asks only for email and the one-time code. Do not
extract or reuse a private session token from a browser. Contract tests do not
verify that the server still accepts these requests. Session refresh behavior
and offer-reference preservation remain unknown. Avoid tests that modify a
real shopping list; use a dedicated test list instead.

## Offer-linked list writes

The account read endpoint returns offer-backed items with `businessPublicId`
and an `offer` object containing `publicId`, `name`, `description`, numeric
`price`, `currencyCode`, `validFrom`, `validUntil`, and `image`. Offer-linked
write requests include `publicOfferId` and `businessPublicId` inside
`item.offer`, while retaining the top-level `businessPublicId` used by read
responses. Upstream acceptance should be verified with a dedicated test list.

## Source-code licensing

- `macokay/hacs-etilbudsavis`: MIT license; inspected for endpoint and response
  evidence. This project does not copy its implementation.
- `olgasafonova/tilbudstrolden-mcp`: MIT license; inspected for offer and store
  endpoint evidence.
- `CagosDk/hacs-etilbudsavis`: no license file found at the inspected revision;
  do not copy or adapt its code.

## Permission and service risks

Tjek's API page says API access is available to customers. Its current terms
restrict use of APIs and API-based content to agreed services, restrict sharing
with third parties/systematic reuse absent written agreement, and restrict
using service data to train, develop or improve AI/ML models absent written
approval. The terms do not clearly resolve private use of the
consumer-facing, undocumented endpoints through Home Assistant or connected
LLM tools. This is a documented risk, not a legal conclusion.

Until the endpoint is independently verified, avoid aggressive polling, bulk
catalogue downloads, bypassing authentication, and any attempt to defeat rate
limits or other access controls. Keep all account credentials and session data
inside Home Assistant.

## Capability matrix

| Capability | Evidence status |
|---|---|
| Offer search | Endpoint and parameters observed in source; not live-tested |
| Geographic/store filtering | Parameters observed; not live-tested |
| Offer price/quantity/validity | Fields observed; completeness not guaranteed |
| Offer/store image fields | Search omits images; live detail endpoint provides crop URLs; v0.1.7 adds bounded enrichment, deployment verification pending |
| Email OTP account login | Current community HA source shows a public app client key and OTP flow; our client is mock-tested only; live authentication remains unverified |
| List discovery and item CRUD | Implemented from observed contract; fake-tested, not live-verified |
| Add an offer preserving its offer reference | Payload includes the observed nested offer and business identifiers; verify against a dedicated test list |
| Session renewal/reauthentication | Not established |
| API usage rights for private Home Assistant use | Unresolved |
| Home Assistant MCP access | The integration registers an LLM API; verify its discovery and write behavior on the target Home Assistant instance. |
