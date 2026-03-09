/**
 * Poubelles Card - Custom Lovelace card for Gestion Poubelles addon.
 * Displays upcoming bin collections with confirm/miss buttons.
 * Works for ALL HA users (admin and non-admin).
 *
 * Configuration:
 *   type: custom:poubelles-card
 *   entity: sensor.poubelles_prochaine_collecte  (default)
 *   show_calendar: true  (optional, show mini calendar)
 *   max_items: 5          (optional)
 */
class PoubellesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._ingressReady = false;
    this._ingressEntry = "";
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    this._config = {
      entity: "sensor.poubelles_prochaine_collecte",
      show_calendar: false,
      max_items: 5,
      ...config,
    };
  }

  getCardSize() {
    return 4;
  }

  static getConfigElement() {
    return document.createElement("poubelles-card-editor");
  }

  static getStubConfig() {
    return { entity: "sensor.poubelles_prochaine_collecte" };
  }

  async _ensureIngress() {
    if (this._ingressReady) return true;
    const stateObj = this._hass.states[this._config.entity];
    if (!stateObj) return false;
    this._ingressEntry = stateObj.attributes.ingress_entry || "";
    const slug = stateObj.attributes.addon_slug || "local_gestion_poubelles";
    if (!this._ingressEntry) return false;
    try {
      await this._hass.callWS({
        type: "supervisor/api",
        endpoint: "/ingress/session",
        method: "post",
        data: { addon: slug },
      });
      this._ingressReady = true;
      return true;
    } catch (e) {
      // Non-admin users might not have WS access, but HTTP ingress
      // still works with HA session cookie when admin: false
      this._ingressReady = true;
      return true;
    }
  }

  async _confirmBin(date, binType, status) {
    const ok = await this._ensureIngress();
    if (!ok || !this._ingressEntry) {
      this._showToast("Impossible de contacter l'addon");
      return;
    }
    try {
      const resp = await fetch(this._ingressEntry + "/api/confirm", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, bin_type: binType, status }),
      });
      if (resp.ok) {
        this._showToast(
          status === "done" ? "Poubelle confirmee !" : "Marquee comme manquee"
        );
        // Optimistic UI update
        this._optimisticUpdate(date, binType, status);
      } else {
        this._showToast("Erreur serveur");
      }
    } catch (e) {
      this._showToast("Erreur de connexion");
    }
  }

  _optimisticUpdate(date, binType, status) {
    const items = this.shadowRoot.querySelectorAll(
      `[data-date="${date}"][data-bin="${binType}"]`
    );
    items.forEach((item) => {
      const actions = item.querySelector(".actions");
      if (actions) {
        actions.innerHTML =
          status === "done"
            ? '<span class="status done">Sortie</span>'
            : '<span class="status missed">Manquee</span>';
      }
    });
  }

  _showToast(msg) {
    const toast = this.shadowRoot.getElementById("toast");
    if (toast) {
      toast.textContent = msg;
      toast.classList.add("show");
      setTimeout(() => toast.classList.remove("show"), 2500);
    }
  }

  _render() {
    if (!this._hass || !this._config) return;
    const entityId = this._config.entity;
    const stateObj = this._hass.states[entityId];

    if (!stateObj) {
      this.shadowRoot.innerHTML = `
        <ha-card header="Poubelles">
          <div style="padding:16px;color:var(--secondary-text-color);">
            Entite <code>${entityId}</code> introuvable.<br>
            <small>Verifiez que l'addon Gestion Poubelles est demarre.</small>
          </div>
        </ha-card>`;
      return;
    }

    const upcoming = stateObj.attributes.upcoming || [];
    const maxItems = this._config.max_items || 5;
    const items = upcoming.slice(0, maxItems);
    this._ingressEntry = stateObj.attributes.ingress_entry || "";

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { overflow: hidden; }
        .header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 16px 16px 0;
        }
        .header h2 {
          margin: 0; font-size: 1.1rem; font-weight: 600;
          display: flex; align-items: center; gap: 8px;
        }
        .header .count {
          font-size: 0.75rem; color: var(--secondary-text-color);
          background: var(--divider-color); padding: 2px 8px;
          border-radius: 10px;
        }
        .items { padding: 8px 16px 16px; }
        .item {
          display: flex; align-items: center; justify-content: space-between;
          padding: 10px 12px; margin-bottom: 6px;
          border-radius: 10px; border: 1px solid var(--divider-color);
          transition: background 0.15s;
        }
        .item:last-child { margin-bottom: 0; }
        .item.tomorrow {
          border-color: #f5c842; background: rgba(245,200,66,0.08);
        }
        .item.today {
          border-color: #4ade80; background: rgba(74,222,128,0.08);
        }
        .date-info { flex: 1; min-width: 0; }
        .date-text { font-weight: 600; font-size: 0.88rem; }
        .date-label {
          font-size: 0.72rem; font-weight: 700; margin-left: 6px;
          padding: 1px 6px; border-radius: 4px;
        }
        .date-label.today-label { background: rgba(74,222,128,0.2); color: #16a34a; }
        .date-label.tomorrow-label { background: rgba(245,200,66,0.2); color: #b8860b; }
        .bins { display: flex; gap: 4px; margin-top: 3px; }
        .bin-badge {
          font-size: 0.72rem; font-weight: 600; padding: 2px 8px;
          border-radius: 12px; display: inline-flex; align-items: center; gap: 3px;
        }
        .bin-badge.jaune { background: rgba(245,200,66,0.15); color: #b8860b; }
        .bin-badge.verte { background: rgba(74,222,128,0.15); color: #16a34a; }
        .actions { display: flex; gap: 4px; flex-shrink: 0; margin-left: 8px; }
        .btn {
          border: none; border-radius: 8px; padding: 6px 10px;
          font-size: 0.75rem; font-weight: 600; cursor: pointer;
          font-family: inherit; transition: opacity 0.15s;
        }
        .btn:hover { opacity: 0.8; }
        .btn-ok { background: rgba(34,197,94,0.15); color: #16a34a; }
        .btn-miss { background: rgba(248,113,113,0.15); color: #dc2626; }
        .status { font-size: 0.75rem; font-weight: 600; padding: 4px 8px; }
        .status.done { color: #16a34a; }
        .status.missed { color: #dc2626; }
        .empty {
          text-align: center; padding: 24px 16px;
          color: var(--secondary-text-color); font-size: 0.9rem;
        }
        .empty-icon { font-size: 2rem; margin-bottom: 8px; }
        #toast {
          position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%) translateY(60px);
          background: var(--primary-color); color: #fff; padding: 8px 16px;
          border-radius: 8px; font-size: 0.82rem; opacity: 0;
          transition: all 0.25s; z-index: 999; pointer-events: none;
        }
        #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
        @media (max-width: 500px) {
          .item { flex-direction: column; align-items: flex-start; gap: 8px; }
          .actions { margin-left: 0; width: 100%; justify-content: flex-end; }
        }
      </style>
      <ha-card>
        <div class="header">
          <h2>Poubelles</h2>
          ${stateObj.attributes.total_scheduled ? `<span class="count">${stateObj.attributes.total_scheduled} dates</span>` : ""}
        </div>
        <div class="items">
          ${
            items.length === 0
              ? `<div class="empty"><div class="empty-icon">📭</div><p>Aucune collecte planifiee.</p></div>`
              : items.map((col) => this._renderItem(col)).join("")
          }
        </div>
      </ha-card>
      <div id="toast"></div>
    `;

    // Attach event listeners
    this.shadowRoot.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        this._confirmBin(btn.dataset.date, btn.dataset.bin, btn.dataset.action);
      });
    });
  }

  _renderItem(col) {
    const cls = col.is_today ? "today" : col.is_tomorrow ? "tomorrow" : "";
    const label = col.is_today
      ? '<span class="date-label today-label">AUJOURD\'HUI</span>'
      : col.is_tomorrow
        ? '<span class="date-label tomorrow-label">DEMAIN</span>'
        : "";

    const binsHtml = col.bins
      .map((b) => {
        const icon = b === "jaune" ? "🟡" : "🟢";
        const name = b === "jaune" ? "Jaune" : "Verte";
        const st = col.status[b] || "";
        let suffix = "";
        if (st === "done") suffix = " ✅";
        else if (st === "missed") suffix = " ❌";
        return `<span class="bin-badge ${b}">${icon} ${name}${suffix}</span>`;
      })
      .join("");

    // Build action buttons for each unconfirmed bin
    const actionsHtml = col.bins
      .map((b) => {
        const st = col.status[b] || "";
        if (st) return ""; // Already confirmed
        const name = b === "jaune" ? "Jaune" : "Verte";
        return `
          <button class="btn btn-ok" data-action="done" data-date="${col.date}" data-bin="${b}" title="Sortie ${name}">✓</button>
          <button class="btn btn-miss" data-action="missed" data-date="${col.date}" data-bin="${b}" title="Manquee ${name}">✗</button>
        `;
      })
      .join("");

    return `
      <div class="item ${cls}" data-date="${col.date}" data-bin="${col.bins.join(",")}">
        <div class="date-info">
          <div class="date-text">${col.date_formatted}${label}</div>
          <div class="bins">${binsHtml}</div>
        </div>
        <div class="actions">${actionsHtml}</div>
      </div>
    `;
  }
}

// Simple card editor
class PoubellesCardEditor extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  _render() {
    this.innerHTML = `
      <div style="padding:8px;">
        <p style="margin-bottom:12px;font-size:0.9rem;color:var(--secondary-text-color);">
          La carte utilise automatiquement le sensor <code>sensor.poubelles_prochaine_collecte</code>
          cree par l'addon Gestion Poubelles.
        </p>
        <label style="display:block;margin-bottom:8px;">
          Nombre max de collectes affichees:
          <input type="number" min="1" max="15" value="${this._config.max_items || 5}"
            style="width:60px;margin-left:8px;" id="max-items-input">
        </label>
      </div>
    `;
    this.querySelector("#max-items-input").addEventListener("change", (e) => {
      this._config = { ...this._config, max_items: parseInt(e.target.value) };
      this.dispatchEvent(
        new CustomEvent("config-changed", { detail: { config: this._config } })
      );
    });
  }
}

customElements.define("poubelles-card", PoubellesCard);
customElements.define("poubelles-card-editor", PoubellesCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "poubelles-card",
  name: "Poubelles",
  description: "Affiche les prochaines collectes de poubelles avec boutons de confirmation.",
  preview: true,
});
