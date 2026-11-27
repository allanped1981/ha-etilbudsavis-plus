class EtilbudsavisPlusCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._loaded = false;
    this._offers = [];
    this._items = [];
    this._lists = [];
    this._savedSearches = [];
    this._stores = [];
    this._preferredStoreIds = [];
    this._selectedList = "";
    this._loading = false;
    this._refreshing = false;
    this._refreshTimer = null;
    this._listError = "";
    this._pendingCompletionStates = new Map();
    this._activeCompletionUpdates = new Set();
    this._error = "";
    this._query = "";
    this._limitPrice = null;
    this._storeScope = "preferred";
    this._addingOfferId = "";
    this._notice = "";
    this._searchOpen = false;
    this._addOpen = false;
    this._editOpen = false;
    this._editItem = null;
    this._editStoreId = "";
    this._editStoreChanged = false;
    this._addStoreId = "";
    this._addDraft = { name: "", count: "1", note: "" };
    this._suggestions = { status: "", offers: [] };
    this._suggestionTimer = null;
    this._savingAdd = false;
    this._groupMode = "none";
    this._groupMenuOpen = false;
  }

  setConfig(config) {
    this.config = config;
    this._render();
  }

  connectedCallback() {
    if (this._refreshTimer) return;
    // Keep the card in sync with changes made outside this card (e.g. HA To-do
    // or the eTilbudsavis app), while the button below allows an immediate read.
    this._refreshTimer = window.setInterval(() => this._refreshItems(false), 60_000);
  }

  disconnectedCallback() {
    if (this._refreshTimer) window.clearInterval(this._refreshTimer);
    this._refreshTimer = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._loadInitialData();
    }
  }

  getCardSize() {
    return 12;
  }

  async _call(type, fields = {}) {
    if (!this._hass?.connection) throw new Error("Home Assistant connection is unavailable");
    return this._hass.connection.sendMessagePromise({
      type: `etilbudsavis_plus/${type}`,
      ...fields,
    });
  }

  async _loadInitialData() {
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const [lists, saved, stores] = await Promise.all([
        this._call("get_lists"),
        this._call("saved_searches/list"),
        this._call("list_stores").catch(() => ({ stores: [] })),
      ]);
      this._lists = lists.lists || [];
      this._savedSearches = saved.items || [];
      this._stores = stores.stores || [];
      this._preferredStoreIds = (stores.preferred_store_ids || []).map(String);
      if (!this._selectedList && this._lists.length) {
        this._selectedList = String(this._lists[0].id);
      }
      await this._loadItems();
    } catch (error) {
      this._error = error.message || "Could not load eTilbudsavis data";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _loadItems() {
    if (!this._selectedList) {
      this._items = [];
      return;
    }
    const result = await this._call("get_items", { list_id: Number(this._selectedList) });
    this._items = (result.items || []).filter((item) => item.isActive !== false);
  }

  async _loadItemsAfterMutation(previousItems, listId, removedItemId = null) {
    // The integration/API can be briefly eventually consistent after a write.
    // Re-read a few times so list changes appear without a manual refresh.
    const delays = [0, 250, 500, 1000, 2000, 3500];
    for (const delay of delays) {
      if (delay) await new Promise((resolve) => window.setTimeout(resolve, delay));
      if (this._selectedList !== listId) return false;
      const result = await this._call("get_items", { list_id: Number(listId) });
      const items = (result.items || []).filter((item) => item.isActive !== false);
      if (this._selectedList !== listId) return false;
      if (removedItemId !== null) {
        if (!items.some((item) => String(item.id) === String(removedItemId))) {
          this._items = items;
          return true;
        }
      } else {
        this._items = items;
        if (JSON.stringify(items) !== previousItems) return true;
      }
    }
    return false;
  }

  async _refreshItems(showFeedback = true) {
    if (!this._selectedList || this._refreshing || (!showFeedback && (this._searchOpen || this._addOpen))) return;
    this._refreshing = true;
    const listId = this._selectedList;
    const previousError = this._listError;
    if (showFeedback) {
      this._listError = "";
      this._render();
    }
    let changed = false;
    try {
      const result = await this._call("get_items", { list_id: Number(listId) });
      const items = (result.items || []).filter((item) => item.isActive !== false);
      if (this._selectedList === listId) {
        changed = JSON.stringify(items) !== JSON.stringify(this._items);
        this._items = items;
        this._listError = "";
      }
    } catch (error) {
      if (showFeedback) this._listError = error.message || "Could not refresh shopping list";
    } finally {
      this._refreshing = false;
      if (showFeedback || changed || previousError !== this._listError) this._render();
    }
  }

  async _search(query = this.shadowRoot.querySelector("#query")?.value || "", maxPrice = null) {
    this._query = query.trim();
    if (!this._query) return;
    this._searchOpen = true;
    this._limitPrice = maxPrice;
    this._storeScope = this.shadowRoot.querySelector("#store-scope")?.value || "preferred";
    this._loading = true;
    this._error = "";
    this._render();
    try {
      const result = await this._call("search_offers", {
        query: this._query,
        limit: 30,
        store_scope: this._storeScope,
      });
      this._offers = result.offers || [];
    } catch (error) {
      this._error = error.message || "Offer search failed";
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _saveSearch() {
    const query = this.shadowRoot.querySelector("#query")?.value.trim();
    if (!query) return;
    const name = this.shadowRoot.querySelector("#search-name")?.value.trim() || query;
    const value = this.shadowRoot.querySelector("#max-price")?.value;
    try {
      await this._call("saved_searches/save", {
        name,
        query,
        ...(value ? { max_price: Number(value) } : {}),
      });
      const result = await this._call("saved_searches/list");
      this._savedSearches = result.items || [];
      this._render();
    } catch (error) {
      this._error = error.message || "Could not save search";
      this._render();
    }
  }

  async _removeSearch(searchId) {
    try {
      await this._call("saved_searches/remove", { search_id: searchId });
      this._savedSearches = this._savedSearches.filter((item) => item.id !== searchId);
      this._render();
    } catch (error) {
      this._error = error.message || "Could not remove saved search";
      this._render();
    }
  }

  _scheduleSuggestions() {
    window.clearTimeout(this._suggestionTimer);
    const query = this._addDraft.name.trim();
    const state = { status: query.length >= 2 ? "loading" : "", offers: [] };
    this._suggestions = state;
    this._renderSuggestions();
    if (!state.status) return;
    this._suggestionTimer = window.setTimeout(async () => {
      if (!this._addOpen || this._suggestions !== state) return;
      try {
        const response = await this._call("search_offers", {
          query,
          limit: 6,
          store_scope: "preferred",
        });
        state.offers = response.offers || [];
        state.status = "ready";
      } catch {
        state.status = "error";
      }
      if (this._addOpen && this._suggestions === state) this._renderSuggestions();
    }, 350);
  }

  _renderSuggestions() {
    const region = this.shadowRoot.querySelector("#add-suggestions");
    if (!region) return;
    const { status, offers } = this._suggestions;
    const t = this._labels();
    region.hidden = !status;
    if (!status) {
      region.innerHTML = "";
      return;
    }
    const message = status === "loading" ? t.loading : status === "error" ? t.suggestionError : t.noOffers;
    region.innerHTML = `<h3>${this._text(t.suggestions)}</h3><div class="suggestion-offers">${offers.length
      ? offers.map((offer) => this._offerCard(offer, t, true)).join("")
      : `<div class="muted" role="status">${this._text(message)}</div>`}</div>`;
  }

  _addValues() {
    const form = this.shadowRoot.querySelector("#add-form");
    if (!form.reportValidity()) return null;
    const name = this._addDraft.name.trim();
    if (!name) return null;
    return {
      name,
      count: Number(this._addDraft.count),
      note: this._addDraft.note.trim(),
    };
  }

  async _addTextItem() {
    if (this._savingAdd || !this._selectedList) return;
    const values = this._addValues();
    if (!values) return;
    const storeId = this._addStoreId;
    const listId = this._selectedList;
    const previousItems = JSON.stringify(this._items);
    this._savingAdd = true;
    this._error = "";
    this._render();
    try {
      await this._call("add_item", {
        list_id: Number(listId),
        ...values,
        store_id: storeId,
      });
      await this._notifyItemAdded({
        name: values.name,
        count: values.count,
        storeName: this._storeFor(storeId)?.name || "",
      });
      await this._loadItemsAfterMutation(previousItems, listId);
      this._addOpen = false;
    } catch (error) {
      this._error = error.message || "Could not add item";
    } finally {
      this._savingAdd = false;
      this._render();
    }
  }

  async _addOffer(offer, fromAdd = false) {
    if (!offer?.id || !this._selectedList || this._addingOfferId || this._savingAdd) return;
    const values = fromAdd ? this._addValues() : null;
    if (fromAdd && !values) return;
    if (fromAdd) this._savingAdd = true;
    this._addingOfferId = String(offer.id);
    this._notice = "";
    this._error = "";
    const listId = this._selectedList;
    const previousItems = JSON.stringify(this._items);
    this._render();
    try {
      const result = await this._call("add_offer", {
        list_id: Number(listId),
        query: values?.name ?? this._query,
        offer_id: String(offer.id),
        count: values?.count ?? 1,
        ...(values?.note ? { note: values.note } : {}),
        store_scope: fromAdd ? "preferred" : this._storeScope,
      });
      await this._notifyItemAdded({
        name: offer.title || values?.name || this._query,
        count: values?.count ?? 1,
        storeName: result.store_name || offer.store_name || this._storeFor(offer.store_id)?.name || "",
        price: this._price(offer.price, offer.currency || "DKK"),
      });
      await this._loadItemsAfterMutation(previousItems, listId);
      if (fromAdd) this._addOpen = false;
      if (result.note_saved === false) {
        this._error = this._labels().noteNotSaved;
      } else if (result.offer_metadata_attached) {
        this._notice = "Tilbud og butik er knyttet til varen.";
      } else {
        this._error = "Varen blev sendt, men tilbudslinket kunne ikke bekræftes. Undgå at tilføje den igen.";
      }
    } catch (error) {
      this._error = error.message || "Tilbuddet kunne ikke føjes til listen";
    } finally {
      this._addingOfferId = "";
      if (fromAdd) this._savingAdd = false;
      this._render();
    }
  }

  async _notifyItemAdded({ name, count, storeName = "", price = "" }) {
    const configuredService = this.config?.notification_service;
    if (!configuredService) return;
    const service = String(configuredService).replace(/^notify\./, "");
    const details = [String(count) + "× " + name, storeName, price].filter(Boolean).join(" · ");
    try {
      await this._hass.callService("notify", service, {
        title: "Vare tilføjet",
        message: details,
      });
    } catch (error) {
      this._listError = "Varen blev tilføjet, men mobilnotifikationen kunne ikke sendes.";
    }
  }

  async _setCompleted(item, completed) {
    const listId = this._selectedList;
    const itemId = String(item.id);
    const updateKey = `${listId}:${itemId}`;
    this._pendingCompletionStates.set(updateKey, completed);
    if (this._selectedList === listId) {
      this._items = this._items.map((candidate) =>
        String(candidate.id) === itemId ? { ...candidate, ticked: completed } : candidate
      );
      this._render();
    }
    if (this._activeCompletionUpdates.has(updateKey)) return;
    this._activeCompletionUpdates.add(updateKey);
    let lastCompleted = Boolean(item.ticked);
    try {
      while (this._pendingCompletionStates.has(updateKey)) {
        const nextCompleted = this._pendingCompletionStates.get(updateKey);
        this._pendingCompletionStates.delete(updateKey);
        if (nextCompleted === lastCompleted) continue;
        await this._call("set_item_completed", {
          list_id: Number(listId),
          client_id: String(item.clientId),
          completed: nextCompleted,
        });
        lastCompleted = nextCompleted;
      }
    } catch (error) {
      this._pendingCompletionStates.delete(updateKey);
      this._error = error.message || "Could not update item";
      if (this._selectedList === listId) {
        try {
          await this._loadItems();
        } catch {
          // Keep the optimistic state if the follow-up read also fails.
        }
      }
    } finally {
      this._activeCompletionUpdates.delete(updateKey);
      if (this._selectedList === listId) this._render();
    }
  }

  _preferredStores() {
    return this._stores.filter((store) => this._preferredStoreIds.includes(String(store.id)));
  }

  _storePicker(mode, selectedId = "") {
    const stores = this._preferredStores();
    const buttons = [
      { id: "", name: "Ingen butik", logo_url: "" },
      ...stores,
    ].map((store) => {
      const id = String(store.id || "");
      const selected = id === String(selectedId || "");
      const image = store.logo_url
        ? `<img src="${this._text(store.logo_url)}" alt="" loading="lazy" onerror="this.remove()">`
        : `<span>${this._text((store.name || "—").slice(0, 2))}</span>`;
      return `<button type="button" class="store-choice ${selected ? "selected" : ""}" data-store-picker="${mode}" data-store-id="${this._text(id)}" title="${this._text(store.name)}" aria-label="${this._text(store.name)}" aria-pressed="${selected}">${id ? image : '<ha-icon icon="mdi:store-off-outline"></ha-icon>'}</button>`;
    }).join("");
    return `<div class="store-field"><span class="field-label">Butik</span><div class="store-picker" role="group" aria-label="Vælg foretrukken butik">${buttons || '<span class="muted">Vælg foretrukne butikker i integrationens indstillinger.</span>'}</div><input type="hidden" id="${mode}-store-id" value="${this._text(selectedId)}"></div>`;
  }

  _selectStore(mode, storeId) {
    if (mode === "add") this._addStoreId = storeId;
    if (mode === "edit") {
      this._editStoreId = storeId;
      this._editStoreChanged = true;
    }
    const field = this.shadowRoot.querySelector(`#${mode}-store-id`);
    if (field) field.value = storeId;
    this.shadowRoot.querySelectorAll(`[data-store-picker="${mode}"]`).forEach((button) => {
      const selected = button.dataset.storeId === storeId;
      button.classList.toggle("selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  _openEditItem(item) {
    this._editItem = item;
    this._editStoreId = String(item.businessPublicId || "");
    this._editStoreChanged = false;
    this._editOpen = true;
    this._addOpen = false;
    this._searchOpen = false;
    this._error = "";
    this._render();
    this.shadowRoot.querySelector("#edit-name")?.focus();
  }

  async _saveItemEdit() {
    const item = this._editItem;
    if (!item || !this._selectedList || !item.clientId) return;
    const listId = this._selectedList;
    const name = this.shadowRoot.querySelector("#edit-name")?.value.trim();
    const count = Number(this.shadowRoot.querySelector("#edit-count")?.value || 1);
    const note = this.shadowRoot.querySelector("#edit-note")?.value.trim() || "";
    if (!name || !Number.isInteger(count) || count < 1 || count > 99) return;
    const previousItems = this._items;
    this._items = previousItems.map((candidate) => String(candidate.id) === String(item.id)
      ? {
          ...candidate,
          name,
          count,
          shortDescription: note,
          ...(this._editStoreChanged ? { businessPublicId: this._editStoreId || null } : {}),
        }
      : candidate);
    this._error = "";
    this._render();
    try {
      await this._call("update_item", {
        list_id: Number(listId),
        item_id: Number(item.id),
        client_id: String(item.clientId),
        name,
        count,
        note,
        ...(this._editStoreChanged ? { store_id: this._editStoreId } : {}),
      });
      await this._loadItems();
      this._editOpen = false;
      this._editItem = null;
    } catch (error) {
      if (this._selectedList === listId) this._items = previousItems;
      this._error = error.message || "Could not update item";
    } finally {
      this._render();
    }
  }

  async _removeItem(item) {
    const listId = this._selectedList;
    const previousItems = this._items;
    this._items = previousItems.filter((candidate) => String(candidate.id) !== String(item.id));
    this._error = "";
    this._render();
    try {
      await this._call("remove_item", {
        list_id: Number(listId),
        item_id: Number(item.id),
      });
      await this._loadItemsAfterMutation(JSON.stringify(previousItems), listId, item.id);
      this._render();
    } catch (error) {
      if (this._selectedList === listId) this._items = previousItems;
      this._error = error.message || "Could not remove item";
      this._render();
    }
  }

  _text(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[char]);
  }

  _price(value, currency = "DKK") {
    if (value === null || value === undefined || value === "") return "—";
    return new Intl.NumberFormat(this._hass?.locale?.language || "da-DK", {
      style: "currency", currency, maximumFractionDigits: 2,
    }).format(Number(value));
  }

  _offerPeriod(from, until) {
    if (!from && !until) return null;
    const formatter = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Europe/Copenhagen",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    });
    const dateParts = (date) => Object.fromEntries(
      formatter.formatToParts(date).map(({ type, value }) => [type, value]),
    );
    const partsFor = (value, isEnd = false) => {
      if (!value) return null;
      const dateOnly = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
      const date = new Date(dateOnly ? `${value}T12:00:00Z` : value);
      if (Number.isNaN(date.valueOf())) return null;
      let parts = dateParts(date);
      // An offer ending at local midnight is valid through the previous day.
      if (isEnd && !dateOnly && parts.hour === "00" && parts.minute === "00"
          && parts.second === "00" && date.getUTCMilliseconds() === 0) {
        parts = dateParts(new Date(date.getTime() - 1));
      }
      return {
        key: Number(`${parts.year}${parts.month}${parts.day}`),
        label: `${parts.day}/${parts.month}`,
      };
    };
    const start = partsFor(from);
    const end = partsFor(until, true);
    if (!start && !end) return null;
    const today = partsFor(new Date().toISOString());
    const status = start && today.key < start.key
      ? "upcoming"
      : end && today.key > end.key
        ? "expired"
        : "valid";
    return {
      status,
      range: start && end ? `${start.label}–${end.label}` : (start || end).label,
    };
  }

  _filteredOffers() {
    return this._offers.filter((offer) => {
      if (this._limitPrice === null || this._limitPrice === undefined) return true;
      return offer.price !== null && Number(offer.price) <= this._limitPrice;
    });
  }

  _storeFor(id) {
    return this._stores.find((store) => String(store.id) === String(id));
  }

  _storeLogo(item) {
    const business = item?.business || {};
    const store = this._storeFor(item?.businessPublicId);
    return business.positiveLogoImage || business.logo || business.logoUrl || store?.logo_url || "";
  }

  _itemImage(item) {
    return item?.offer?.image || item?.offer?.imageUrl || item?.image || "";
  }

  _labels() {
    const isDanish = (this._hass?.locale?.language || "da").toLowerCase().startsWith("da");
    return isDanish
      ? { search: "Søg tilbud", query: "Søg efter produkt", preferred: "Foretrukne butikker", all: "Alle butikker", save: "Gem søgning", saved: "Gemte søgninger", list: "Indkøbsliste", newItem: "Vare", manualAdd: "Tilføj som almindelig vare", suggestions: "Matchende tilbud", choose: "Vælg", suggestionError: "Tilbud kunne ikke hentes", noteNotSaved: "Tilbuddet blev tilføjet, men noten kunne ikke gemmes.", add: "Tilføj", quantity: "Antal", note: "Note", noLists: "Ingen valgte lister", noOffers: "Ingen tilbud fundet", addOffer: "Tilføj tilbud til indkøbslisten", remove: "Fjern", loading: "Henter…", name: "Navn på søgning", maxPrice: "Maks. pris", items: "Varer", close: "Luk", addItem: "Tilføj vare", editItem: "Rediger vare", saveItem: "Gem ændringer", refresh: "Opdater indkøbslisten", groupBy: "Grupper efter", ungrouped: "Ingen gruppering", byStore: "Butik", byDepartment: "Afdeling", noStore: "Ingen butik", noDepartment: "Ingen afdeling", unknownGroup: "Ukendt", refreshing: "Opdaterer…", valid: "Gyldig", upcoming: "Kommende tilbud", expired: "Udløbet" }
      : { search: "Search offers", query: "Search for a product", preferred: "Preferred stores", all: "All stores", save: "Save search", saved: "Saved searches", list: "Shopping list", newItem: "Item", manualAdd: "Add as regular item", suggestions: "Matching offers", choose: "Choose", suggestionError: "Could not load offers", noteNotSaved: "The offer was added, but the note could not be saved.", add: "Add", quantity: "Quantity", note: "Note", noLists: "No selected lists", noOffers: "No offers found", addOffer: "Add offer to shopping list", remove: "Remove", loading: "Loading…", name: "Search name", maxPrice: "Max price", items: "Items", close: "Close", addItem: "Add item", editItem: "Edit item", saveItem: "Save changes", refresh: "Refresh shopping list", groupBy: "Group by", ungrouped: "No grouping", byStore: "Store", byDepartment: "Department", noStore: "No store", noDepartment: "No department", unknownGroup: "Unknown", refreshing: "Refreshing…", valid: "Valid", upcoming: "Upcoming offer", expired: "Expired" };
  }

  _offerCard(offer, t, suggestion = false) {
    const store = this._storeFor(offer.store_id);
    const storeLogo = offer.store_logo_url || store?.logo_url || "";
    const image = offer.image_url || offer.image || "";
    const period = this._offerPeriod(offer.valid_from, offer.valid_until);
    const periodLabel = period ? (period.status === "upcoming" ? t.upcoming : period.status === "expired" ? t.expired : t.valid) : "";
    return `
    <article class="offer">
      <div class="offer-photo">${image ? `<img src="${this._text(image)}" alt="${this._text(offer.title)}" loading="lazy" onerror="this.remove()">` : `<ha-icon icon="mdi:tag-heart-outline"></ha-icon>`}</div>
      <div class="offer-main">
        <div class="store">${storeLogo ? `<img class="store-logo" src="${this._text(storeLogo)}" alt="" loading="lazy" onerror="this.remove()">` : `<ha-icon icon="mdi:store"></ha-icon>`}${this._text(offer.store_name || store?.name || "")}</div>
        <h3>${this._text(offer.title || "")}</h3>
        ${!suggestion && offer.description ? `<p>${this._text(offer.description)}</p>` : ""}
        <div class="meta">${this._text(offer.quantity || "")}${offer.unit_price !== null && offer.unit_price !== undefined ? ` · ${this._price(offer.unit_price)} ${this._text(offer.unit_price_unit || "")}` : ""}${period ? ` <span class="validity ${period.status}">${this._text(periodLabel)} ${this._text(period.range)}</span>` : ""}</div>
      </div>
      <div class="offer-side"><strong>${this._text(this._price(offer.price, offer.currency || "DKK"))}</strong><button class="offer-add" data-action="${suggestion ? "add-suggested-offer" : "add-offer"}" data-id="${this._text(offer.id)}" ${!this._selectedList || this._addingOfferId || this._savingAdd ? "disabled" : ""} title="${this._text(t.addOffer)}" aria-label="${this._text(t.addOffer)}">${this._addingOfferId === String(offer.id) ? "…"  : suggestion ? this._text(t.choose) : "＋"}</button></div>
    </article>`;
  }

  _render() {
    if (!this.shadowRoot) return;
    const t = this._labels();
    const listOptions = this._lists.map((list) => `<option value="${this._text(list.id)}" ${String(list.id) === this._selectedList ? "selected" : ""}>${this._text(list.name)}</option>`).join("");
    const visibleOffers = this._filteredOffers();
    const offerCards = visibleOffers.map((offer) => this._offerCard(offer, t)).join("");
    const itemRows = this._items.map((item) => {
      const done = Boolean(item.ticked);
      const image = this._itemImage(item);
      const store = this._storeFor(item.businessPublicId);
      const storeName = store?.name || item.business?.name || "";
      const logo = store?.logo_url || this._storeLogo(item);
      const period = this._offerPeriod(item.offer?.validFrom || item.offer?.valid_from, item.offer?.validUntil || item.offer?.valid_until);
      const periodLabel = period ? (period.status === "upcoming" ? t.upcoming : period.status === "expired" ? t.expired : t.valid) : "";
      const offerPrice = item.offer?.price ? this._price(item.offer.price, item.offer.currencyCode || "DKK") : "";
      return `<div class="list-item ${done ? "done" : ""}">
        <label><input type="checkbox" data-action="toggle" data-id="${this._text(item.id)}" ${done ? "checked" : ""} ${item.clientId ? "" : "disabled"}>${image ? `<img class="item-photo" src="${this._text(image)}" alt="" loading="lazy" onerror="this.remove()">` : ""}<span class="item-content"><span class="item-title">${this._text(item.count || 1)}× ${this._text(item.name || "")}</span>${item.shortDescription ? `<span class="item-note">${this._text(item.shortDescription)}</span>` : ""}${storeName || offerPrice || period ? `<span class="item-store">${storeName ? `${logo ? `<img class="store-logo" src="${this._text(logo)}" alt="" loading="lazy" onerror="this.remove()">` : `<ha-icon icon="mdi:store"></ha-icon>`}${this._text(storeName)}` : ""}${offerPrice ? ` · ${this._text(offerPrice)}` : ""}${period ? ` <span class="validity ${period.status}">${this._text(periodLabel)} ${this._text(period.range)}</span>` : ""}</span>` : ""}</span></label>
        <div class="item-actions"><button class="icon-button" data-action="edit-item" data-id="${this._text(item.id)}" title="${this._text(t.editItem)}" aria-label="${this._text(t.editItem)}" ${item.clientId ? "" : "disabled"}><ha-icon icon="mdi:pencil-outline"></ha-icon></button><button class="icon-button" data-action="remove-item" data-id="${this._text(item.id)}" title="${this._text(t.remove)}" aria-label="${this._text(t.remove)}">×</button></div>
      </div>`;
    });
    const groupedItemRows = this._groupMode === "none" ? itemRows.join("") : (() => {
      const groups = new Map();
      this._items.forEach((item, index) => {
        const store = this._storeFor(item.businessPublicId) || item.business;
        const department = String(item.departmentSlug || item.offer?.departmentSlug || "").trim();
        const storeId = String(item.businessPublicId || store?.publicId || "").trim();
        const rawName = this._groupMode === "store"
          ? (store?.name || (storeId ? t.unknownGroup : t.noStore))
          : (department || t.noDepartment);
        const departmentNames = { beverages: "Drikkevarer", household: "Husholdning" };
        const label = this._groupMode === "store"
          ? rawName
          : (departmentNames[department.toLowerCase()] || department.replace(/[-_]+/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase()) || t.noDepartment);
        const key = this._groupMode === "store"
          ? (storeId ? `store:${storeId}` : (store?.name ? `store-name:${store.name}` : "store:none"))
          : (department ? `department:${department.toLowerCase()}` : "department:none");
        if (!groups.has(key)) groups.set(key, { label, store, items: [] });
        groups.get(key).items.push(itemRows[index]);
      });
      return [...groups.values()]
        .sort((left, right) => left.label.localeCompare(right.label, "da"))
        .map((group) => {
          const logo = group.store?.logo_url || group.store?.positiveLogoImage || this._storeLogo({ business: group.store });
          const icon = this._groupMode === "store" ? "mdi:store" : "mdi:shape-outline";
          return `<section class="item-group"><h3>${logo && this._groupMode === "store" ? `<img src="${this._text(logo)}" alt="" loading="lazy" onerror="this.remove()">` : `<ha-icon icon="${icon}"></ha-icon>`}<span>${this._text(group.label)}</span><small>${group.items.length}</small></h3><div class="items">${group.items.join("")}</div></section>`;
        }).join("");
    })();
    const savedRows = this._savedSearches.map((search) => `<div class="saved-row"><button class="saved-query" data-action="run-search" data-query="${this._text(search.query)}" data-price="${this._text(search.max_price ?? "")}">${this._text(search.name)}${search.max_price !== null && search.max_price !== undefined ? ` <small>≤ ${this._text(this._price(search.max_price))}</small>` : ""}</button><button class="icon-button" data-action="remove-search" data-id="${this._text(search.id)}" aria-label="${this._text(t.remove)}">×</button></div>`).join("");
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;color:var(--primary-text-color);font-family:var(--primary-font-family,inherit)}
        *{box-sizing:border-box} .shell{display:flex;flex-direction:column;gap:12px;max-width:1050px;margin:auto;padding:12px}
        .modal{display:none}.modal.open{display:block;position:fixed;inset:5vh 50% auto auto;transform:translateX(50%);z-index:1000;width:min(760px,calc(100vw - 24px));max-height:90vh;overflow:auto;box-shadow:0 20px 60px #0009}.modal-backdrop{display:none}.modal-backdrop.open{display:block;position:fixed;inset:0;background:#0009;z-index:999}.modal-head{display:flex;align-items:center;justify-content:space-between}.modal-head button{background:transparent;color:var(--secondary-text-color);font-size:1.4rem;padding:3px 10px}
        .panel{background:var(--ha-card-background,var(--card-background-color));border:1px solid var(--divider-color);border-radius:14px;padding:16px;box-shadow:var(--ha-card-box-shadow,none);min-width:0}
        h2{font-size:1.1rem;margin:0 0 12px} h3{font-size:1rem;margin:4px 0} p{margin:4px 0;color:var(--secondary-text-color);font-size:.9rem}
        .toolbar,.row,.offer,.list-item,.saved-row{display:flex;align-items:center;gap:8px}.toolbar{margin-bottom:10px}.toolbar input{flex:1}
        input,select,button{font:inherit} input,select{min-height:40px;border:1px solid var(--divider-color);border-radius:8px;padding:8px 10px;color:var(--primary-text-color);background:var(--card-background-color)}
        button{border:0;border-radius:8px;padding:9px 12px;color:var(--card-background-color,#111);background:var(--primary-text-color,#f5f5f5);cursor:pointer;min-height:40px}
        button:disabled{opacity:.45;cursor:not-allowed}.muted{color:var(--secondary-text-color)} .error{color:var(--error-color);padding:8px 0}.notice{color:var(--success-color,#4caf50);padding:8px 0}
        .offers{display:grid;gap:8px;max-height:55vh;overflow:auto}.offer{justify-content:space-between;border:1px solid var(--divider-color);border-radius:12px;padding:9px;background:var(--secondary-background-color,var(--card-background-color))}.offer-main{min-width:0;flex:1}.offer-side{display:flex;align-items:center;gap:10px;white-space:nowrap}.offer-side strong{font-size:1.15rem}.offer-add{font-size:1.2rem;padding:5px 10px;min-width:38px}
        .offer-photo{width:70px;height:78px;display:grid;place-items:center;flex:none;background:white;border-radius:9px;overflow:hidden;color:#9aab16}.offer-photo img{width:100%;height:100%;object-fit:contain}.offer-photo ha-icon{--mdc-icon-size:32px}.store{display:flex;align-items:center;gap:5px}.store-logo{width:22px;height:22px;object-fit:contain;border-radius:50%;background:white;padding:2px}.store ha-icon,.item-store ha-icon{--mdc-icon-size:19px;color:var(--primary-color)}
        .store{font-size:.76rem;color:var(--secondary-text-color);font-weight:600}.meta{font-size:.78rem;color:var(--secondary-text-color);margin-top:5px}
        .validity{display:inline-flex;align-items:center;padding:2px 7px;margin:2px 0 0 4px;border-radius:999px;font-size:.76rem;font-weight:600;white-space:nowrap}.validity.valid{color:var(--success-color,#2e7d32);background:color-mix(in srgb,var(--success-color,#2e7d32) 14%,transparent)}.validity.upcoming{color:var(--warning-color,#ef6c00);background:color-mix(in srgb,var(--warning-color,#ef6c00) 16%,transparent)}.validity.expired{color:var(--error-color,#c62828);background:color-mix(in srgb,var(--error-color,#c62828) 14%,transparent)}
        .list-header{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:10px}
        .list-header h2{flex:none;max-width:100%;overflow-wrap:anywhere}
        .header-actions{position:relative;display:flex;align-items:center;gap:6px;max-width:100%;margin-inline-start:auto}
        .header-actions > button,.header-actions > .group-menu{flex:none}
        .header-actions select{min-width:0}.group-menu{position:relative;display:flex;align-items:center}.group-menu .header-icon.active{background:var(--secondary-background-color,var(--card-background-color))}.group-popover{display:none;position:absolute;top:calc(100% + 8px);right:0;z-index:30;min-width:170px;padding:6px;border:1px solid var(--divider-color);border-radius:10px;background:var(--card-background-color);box-shadow:0 8px 24px #0008}.group-popover.open{display:grid;gap:3px}.group-option{width:100%;min-height:38px;padding:8px 10px!important;text-align:left!important;background:transparent!important;color:var(--primary-text-color)!important;border-radius:6px!important}.group-option.selected{background:var(--secondary-background-color,var(--card-background-color))!important;font-weight:600}.item-group{display:grid;gap:7px}.item-group h3{display:flex;align-items:center;gap:8px;margin:8px 2px 0;color:var(--primary-text-color);font-size:1rem}.item-group h3 ha-icon{color:var(--primary-color);--mdc-icon-size:20px}.item-group h3 img{width:23px;height:23px;object-fit:contain;border-radius:50%;background:#fff;padding:2px}.item-group h3 small{margin-left:auto;padding:2px 8px;border-radius:999px;background:var(--secondary-background-color,var(--card-background-color));font-size:.8rem}.items{display:grid;gap:8px;max-height:none;overflow:auto}.list-item{justify-content:space-between;min-height:70px;border:1px solid var(--divider-color);border-radius:12px;padding:8px 10px;background:var(--secondary-background-color,var(--card-background-color))}.list-item label{display:flex;align-items:center;gap:8px;min-width:0;flex:1}.item-content{display:flex;flex-direction:column;gap:3px;min-width:0}.item-title,.item-note{overflow-wrap:anywhere}.list-item.done .item-title,.list-item.done .item-note{text-decoration:line-through;color:var(--secondary-text-color)}.item-note{font-size:.84rem;color:var(--secondary-text-color);white-space:pre-wrap}.item-photo{width:48px;height:54px;object-fit:contain;background:#fff;border-radius:8px;flex:none}.item-store{display:flex;align-items:center;gap:5px;flex-wrap:wrap;font-size:.8rem;color:var(--secondary-text-color);margin-top:5px}.item-actions{display:flex;align-items:center;flex:none}.item-actions ha-icon{--mdc-icon-size:19px}small{color:var(--secondary-text-color)}
        .icon-button{background:transparent;color:var(--secondary-text-color);padding:4px 9px;min-width:34px}.saved{margin-top:16px}.saved-row{justify-content:space-between;border-bottom:1px solid var(--divider-color);min-height:40px}.saved-query{background:transparent;color:var(--primary-text-color);text-align:left;padding:6px;flex:1}.header-icon{background:transparent;color:var(--primary-text-color);border:1px solid var(--divider-color);min-width:42px;padding:7px}.header-icon ha-icon{color:var(--primary-text-color,#f5f5f5);--mdc-icon-size:21px}.header-icon.refreshing ha-icon{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.list-error{color:var(--error-color);padding:4px 0 8px}
        .add-form,.edit-form{display:grid;grid-template-columns:minmax(0,1fr) 96px;gap:8px;margin-top:12px}.add-form input:first-child,.edit-form input:first-child{grid-column:1/-1}.add-form button,.edit-form>button{grid-column:1/-1}textarea{font:inherit;min-height:88px;resize:vertical;border:1px solid var(--divider-color);border-radius:8px;padding:9px 10px;color:var(--primary-text-color);background:var(--card-background-color);width:100%}.note-field{grid-column:1/-1}.field-label{display:block;font-size:.9rem;color:var(--secondary-text-color);margin-bottom:6px}.store-field{grid-column:1/-1}.store-picker{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.store-choice{width:44px;height:44px;min-height:44px;padding:4px;border:2px solid var(--divider-color);border-radius:50%;display:grid;place-items:center;background:var(--card-background-color);color:var(--primary-text-color)}.store-choice.selected{border-color:var(--primary-color);box-shadow:0 0 0 2px color-mix(in srgb,var(--primary-color) 25%,transparent)}.store-choice img{width:100%;height:100%;object-fit:contain;border-radius:50%;background:#fff}.store-choice ha-icon{--mdc-icon-size:23px;color:var(--secondary-text-color)}
        .add-form fieldset{display:grid;grid-column:1/-1;grid-template-columns:76px minmax(0,1fr);gap:10px;min-width:0;margin:0;padding:0;border:0}.add-form .add-name{grid-column:1/-1}.add-form input:not([type=hidden]){width:100%}.add-form .store-field{grid-column:auto}.add-form .store-choice{grid-column:auto}
        #add-suggestions{border-top:1px solid var(--divider-color);margin-top:14px;padding-top:12px}#add-suggestions h3{margin:0 0 8px}.suggestion-offers{display:grid;gap:8px}.suggestion-offers .offer-photo{width:50px;height:56px}.suggestion-offers .offer-add{font-size:.9rem}
        .save-form{display:grid;grid-template-columns:1fr 110px;gap:7px;margin-top:9px}.save-form input:first-child{grid-column:1/-1}
        .empty{padding:18px 4px;color:var(--secondary-text-color);text-align:center}
        @media(max-width:850px){.offers{max-height:55vh}.panel{padding:13px}}
        @media(max-width:520px){.toolbar{flex-wrap:wrap}.toolbar input{flex-basis:100%}.toolbar select{flex:1}.offer{align-items:flex-start}.offer-side{flex-direction:column;align-items:flex-end}.save-form{grid-template-columns:1fr}.save-form input:first-child{grid-column:auto}}
      </style>
      <div class="shell">
        <div class="modal-backdrop ${this._searchOpen || this._addOpen || this._editOpen ? "open" : ""}"></div>
        <section class="panel modal search-panel ${this._searchOpen ? "open" : ""}">
          <div class="modal-head"><h2>${this._text(t.search)}</h2><button id="close-search" aria-label="${this._text(t.close || "Luk")}">×</button></div>
          <form id="search-form" class="toolbar">
            <input id="query" type="search" placeholder="${this._text(t.query)}" value="${this._text(this._query)}" required>
            <select id="store-scope"><option value="preferred" ${this._storeScope === "preferred" ? "selected" : ""}>${this._text(t.preferred)}</option><option value="all" ${this._storeScope === "all" ? "selected" : ""}>${this._text(t.all)}</option></select>
            <button type="submit">${this._text(t.search)}</button>
          </form>
          ${this._error ? `<div class="error">${this._text(this._error)}</div>` : ""}
          ${this._notice ? `<div class="notice">${this._text(this._notice)}</div>` : ""}
          ${this._loading ? `<div class="empty">${this._text(t.loading)}</div>` : ""}
          <div class="offers">${!this._loading && !visibleOffers.length && this._query ? `<div class="empty">${this._text(t.noOffers)}</div>` : offerCards}</div>
          <div class="save-form"><input id="search-name" placeholder="${this._text(t.name)}"><input id="max-price" type="number" min="0" step="0.01" placeholder="${this._text(t.maxPrice)}"><button id="save-search" type="button">${this._text(t.save)}</button></div>
          <div class="saved"><h2>${this._text(t.saved)}</h2>${savedRows || `<div class="muted">—</div>`}</div>
        </section>
        <section class="panel modal add-panel ${this._addOpen ? "open" : ""}">
          <div class="modal-head"><h2>${this._text(t.addItem)}</h2><button id="close-add" aria-label="${this._text(t.close || "Luk")}">×</button></div>
          <form id="add-form" class="add-form">
            <fieldset ${this._savingAdd ? "disabled" : ""}>
              <label class="add-name"><span class="field-label">${this._text(t.newItem)}</span><input id="new-item" maxlength="200" value="${this._text(this._addDraft.name)}" required></label>
              <label><span class="field-label">${this._text(t.quantity)}</span><input id="item-count" type="number" min="1" max="99" value="${this._text(this._addDraft.count)}" required></label>
              ${this._storePicker("add", this._addStoreId)}
              <div class="note-field"><label class="field-label" for="item-note">${this._text(t.note)}</label><textarea id="item-note" maxlength="200">${this._text(this._addDraft.note)}</textarea></div>
              <button id="add-item" type="submit" ${this._selectedList ? "" : "disabled"}>${this._text(t.manualAdd)}</button>
            </fieldset>
          </form>
          ${this._error && this._addOpen ? `<div class="error" role="alert">${this._text(this._error)}</div>` : ""}
          <section id="add-suggestions" hidden></section>
        </section>
        <section class="panel modal edit-panel ${this._editOpen ? "open" : ""}">
          <div class="modal-head"><h2>${this._text(t.editItem)}</h2><button id="close-edit" aria-label="${this._text(t.close)}">×</button></div>
          <form id="edit-form" class="edit-form">
            <input id="edit-name" maxlength="200" value="${this._text(this._editItem?.name || "")}" required>
            <input id="edit-count" type="number" min="1" max="99" value="${this._text(this._editItem?.count || 1)}" aria-label="${this._text(t.quantity)}">
            <div class="note-field"><label class="field-label" for="edit-note">${this._text(t.note)}</label><textarea id="edit-note" maxlength="200" placeholder="${this._text(t.note)}">${this._text(this._editItem?.shortDescription || "")}</textarea></div>
            ${this._storePicker("edit", this._editStoreId)}
            <button id="save-item" type="submit">${this._text(t.saveItem)}</button>
          </form>
        </section>
        <section class="panel list-panel">
          <div class="list-header"><h2>${this._text(t.list)}</h2><div class="header-actions"><button id="open-search" class="header-icon" title="${this._text(t.search)}" aria-label="${this._text(t.search)}"><ha-icon icon="mdi:magnify"></ha-icon></button><button id="open-add" class="header-icon" title="${this._text(t.addItem)}" aria-label="${this._text(t.addItem)}" ${this._selectedList ? "" : "disabled"}><ha-icon icon="mdi:plus"></ha-icon></button><button id="refresh-items" class="header-icon ${this._refreshing ? "refreshing" : ""}" title="${this._text(this._refreshing ? t.refreshing : t.refresh)}" aria-label="${this._text(this._refreshing ? t.refreshing : t.refresh)}" ${!this._selectedList || this._refreshing ? "disabled" : ""}><ha-icon icon="mdi:refresh"></ha-icon></button><div class="group-menu"><button id="open-group-menu" class="header-icon ${this._groupMenuOpen ? "active" : ""}" title="${this._text(t.groupBy)}" aria-label="${this._text(t.groupBy)}" aria-haspopup="menu" aria-expanded="${this._groupMenuOpen}"><ha-icon icon="mdi:format-list-bulleted"></ha-icon></button><div class="group-popover ${this._groupMenuOpen ? "open" : ""}" role="menu" aria-label="${this._text(t.groupBy)}"><button class="group-option ${this._groupMode === "none" ? "selected" : ""}" data-group-mode="none" role="menuitemradio" aria-checked="${this._groupMode === "none"}">${this._text(t.ungrouped)}</button><button class="group-option ${this._groupMode === "store" ? "selected" : ""}" data-group-mode="store" role="menuitemradio" aria-checked="${this._groupMode === "store"}">${this._text(t.byStore)}</button><button class="group-option ${this._groupMode === "department" ? "selected" : ""}" data-group-mode="department" role="menuitemradio" aria-checked="${this._groupMode === "department"}">${this._text(t.byDepartment)}</button></div></div><select id="list-select" ${this._lists.length ? "" : "disabled"}>${listOptions || `<option value="">${this._text(t.noLists)}</option>`}</select></div></div>
          ${this._listError ? `<div class="list-error">${this._text(this._listError)}</div>` : ""}
          <div class="items">${groupedItemRows || `<div class="empty">${this._text(this._lists.length ? t.items : t.noLists)}</div>`}</div>
        </section>
      </div>`;
    this._bindEvents();
  }

  _bindEvents() {
    this.shadowRoot.querySelector("#refresh-items")?.addEventListener("click", () => this._refreshItems(true));
    this.shadowRoot.querySelector("#open-search")?.addEventListener("click", () => {
      this._searchOpen = true;
      this._addOpen = false;
      this._editOpen = false;
      this._render();
      this.shadowRoot.querySelector("#query")?.focus();
    });
    this.shadowRoot.querySelector("#open-add")?.addEventListener("click", () => {
      this._addOpen = true;
      this._searchOpen = false;
      this._editOpen = false;
      this._addStoreId = "";
      this._addDraft = { name: "", count: "1", note: "" };
      this._suggestions = { status: "", offers: [] };
      this._error = "";
      this._render();
      this.shadowRoot.querySelector("#new-item")?.focus();
    });
    this.shadowRoot.querySelector("#close-edit")?.addEventListener("click", () => {
      this._editOpen = false;
      this._editItem = null;
      this._render();
    });
    this.shadowRoot.querySelector("#close-search")?.addEventListener("click", () => {
      this._searchOpen = false;
      this._render();
    });
    this.shadowRoot.querySelector("#close-add")?.addEventListener("click", () => {
      if (this._savingAdd) return;
      this._addOpen = false;
      this._render();
    });
    this.shadowRoot.querySelector(".modal-backdrop")?.addEventListener("click", () => {
      if (this._savingAdd) return;
      this._searchOpen = false;
      this._addOpen = false;
      this._editOpen = false;
      this._editItem = null;
      this._render();
    });
    this.shadowRoot.querySelector("#search-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      this._search();
    });
    this.shadowRoot.querySelector("#save-search")?.addEventListener("click", () => this._saveSearch());
    this.shadowRoot.querySelector("#open-group-menu")?.addEventListener("click", () => {
      this._groupMenuOpen = !this._groupMenuOpen;
      this._render();
    });
    this.shadowRoot.querySelectorAll("[data-group-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        this._groupMode = button.dataset.groupMode;
        this._groupMenuOpen = false;
        this._render();
      });
    });
    this.shadowRoot.querySelector(".list-panel")?.addEventListener("click", (event) => {
      if (!this._groupMenuOpen || event.target.closest(".group-menu")) return;
      this._groupMenuOpen = false;
      this._render();
    });
    this.shadowRoot.querySelector("#list-select")?.addEventListener("change", async (event) => {
      this._selectedList = event.target.value;
      this._loading = true;
      this._render();
      try {
        await this._loadItems();
      } catch (error) {
        this._error = error.message || "Could not load list";
      } finally {
        this._loading = false;
        this._render();
      }
    });
    this._renderSuggestions();
    this.shadowRoot.querySelector("#add-suggestions")?.addEventListener("click", (event) => {
      const button = event.target.closest('[data-action="add-suggested-offer"]');
      if (!button) return;
      const offer = this._suggestions.offers.find((candidate) => String(candidate.id) === button.dataset.id);
      if (offer) this._addOffer(offer, true);
    });
    this.shadowRoot.querySelector("#new-item")?.addEventListener("input", (event) => {
      this._addDraft.name = event.target.value;
      if (!event.isComposing) this._scheduleSuggestions();
    });
    this.shadowRoot.querySelector("#new-item")?.addEventListener("compositionend", () => this._scheduleSuggestions());
    this.shadowRoot.querySelector("#item-count")?.addEventListener("input", (event) => {
      this._addDraft.count = event.target.value;
    });
    this.shadowRoot.querySelector("#item-note")?.addEventListener("input", (event) => {
      this._addDraft.note = event.target.value;
    });
    this.shadowRoot.querySelector("#add-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      this._addTextItem();
    });
    this.shadowRoot.querySelector("#edit-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      this._saveItemEdit();
    });
    this.shadowRoot.querySelectorAll("[data-store-picker]").forEach((element) => {
      element.addEventListener("click", () => this._selectStore(element.dataset.storePicker, element.dataset.storeId || ""));
    });
    this.shadowRoot.querySelectorAll('[data-action="toggle"]').forEach((element) => {
      element.addEventListener("change", (event) => {
        const item = this._items.find((candidate) => String(candidate.id) === event.target.dataset.id);
        if (item) this._setCompleted(item, event.target.checked);
      });
    });
    this.shadowRoot.querySelectorAll('[data-action="remove-item"]').forEach((element) => {
      element.addEventListener("click", () => {
        const item = this._items.find((candidate) => String(candidate.id) === element.dataset.id);
        if (item) this._removeItem(item);
      });
    });
    this.shadowRoot.querySelectorAll('[data-action="edit-item"]').forEach((element) => {
      element.addEventListener("click", () => {
        const item = this._items.find((candidate) => String(candidate.id) === element.dataset.id);
        if (item) this._openEditItem(item);
      });
    });
    this.shadowRoot.querySelectorAll('[data-action="run-search"]').forEach((element) => {
      element.addEventListener("click", () => {
        this._storeScope = "preferred";
        this._search(
          element.dataset.query,
          element.dataset.price ? Number(element.dataset.price) : null,
        );
      });
    });
    this.shadowRoot.querySelectorAll('[data-action="add-offer"]').forEach((element) => {
      element.addEventListener("click", () => {
        const offer = this._offers.find((candidate) => String(candidate.id) === element.dataset.id);
        if (offer) this._addOffer(offer);
      });
    });
    this.shadowRoot.querySelectorAll('[data-action="remove-search"]').forEach((element) => {
      element.addEventListener("click", () => this._removeSearch(element.dataset.id));
    });
  }
}

if (!customElements.get("etilbudsavis-plus-card")) {
  customElements.define("etilbudsavis-plus-card", EtilbudsavisPlusCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "etilbudsavis-plus-card",
  name: "eTilbudsavis Plus",
  description: "Offer search, saved searches and selected shopping lists.",
});
