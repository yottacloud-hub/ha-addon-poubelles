/**
 * Poubelles Card - Custom Lovelace card for Gestion Poubelles addon.
 * Works for ALL HA users (admin and non-admin).
 *
 * Config:
 *   type: custom:poubelles-card
 *   entity: sensor.poubelles_prochaine_collecte
 *   max_items: 5
 */
class PoubellesCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._pendingActions = new Set();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  setConfig(config) {
    this._config = {
      entity: "sensor.poubelles_prochaine_collecte",
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

  /**
   * Confirm a bin by writing to a command sensor that the addon polls.
   * Uses hass.callApi which works for ALL authenticated users.
   */
  async _confirmBin(date, binType, status) {
    const actionKey = `${date}:${binType}`;
    if (this._pendingActions.has(actionKey)) return;
    this._pendingActions.add(actionKey);

    // Optimistic UI immediately
    this._optimisticUpdate(date, binType, status);
    this._showToast(
      status === "done" ? "Poubelle confirmee !" : "Marquee comme manquee"
    );

    try {
      // Write command to a sensor the addon polls
      const cmd = `${status}:${date}:${binType}:${Date.now()}`;
      await this._hass.callApi("POST", "states/sensor.poubelles_command", {
        state: cmd,
        attributes: {
          friendly_name: "Poubelles Command",
          icon: "mdi:delete-check",
          action: status,
          date: date,
          bin_type: binType,
          timestamp: Date.now(),
        },
      });
    } catch (e) {
      console.error("Poubelles card: confirm failed", e);
      this._showToast("Erreur - reessayez");
    }

    setTimeout(() => this._pendingActions.delete(actionKey), 3000);
  }

  _optimisticUpdate(date, binType, status) {
    const btns = this.shadowRoot.querySelectorAll(
      `[data-date="${date}"][data-bin="${binType}"]`
    );
    btns.forEach((btn) => {
      const row = btn.closest(".actions");
      if (row) {
        // Replace all buttons for this bin with status text
        const siblings = row.querySelectorAll(`[data-bin="${binType}"]`);
        siblings.forEach((s) => s.remove());
        const span = document.createElement("span");
        span.className = `status ${status === "done" ? "done" : "missed"}`;
        span.textContent = status === "done" ? "Sortie !" : "Manquee";
        row.appendChild(span);
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

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { overflow: hidden; }
        .header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 16px 16px 8px;
        }
        .header h2 {
          margin: 0; font-size: 1.15rem; font-weight: 600;
          display: flex; align-items: center; gap: 8px;
        }
        .header .count {
          font-size: 0.75rem; color: var(--secondary-text-color);
          background: var(--divider-color); padding: 2px 8px;
          border-radius: 10px;
        }
        .items { padding: 4px 16px 16px; }
        .item {
          padding: 14px; margin-bottom: 8px;
          border-radius: 12px; border: 1px solid var(--divider-color);
          transition: background 0.15s;
        }
        .item:last-child { margin-bottom: 0; }
        .item.tomorrow {
          border-color: #f5c842; background: rgba(245,200,66,0.08);
        }
        .item.today {
          border-color: #4ade80; background: rgba(74,222,128,0.08);
        }
        .item-top {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 10px;
        }
        .date-text { font-weight: 600; font-size: 0.95rem; }
        .date-label {
          font-size: 0.7rem; font-weight: 700; margin-left: 8px;
          padding: 2px 8px; border-radius: 6px; text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .date-label.today-label { background: rgba(74,222,128,0.2); color: #16a34a; }
        .date-label.tomorrow-label { background: rgba(245,200,66,0.2); color: #b8860b; }
        .bins { display: flex; gap: 6px; }
        .bin-badge {
          font-size: 0.78rem; font-weight: 600; padding: 3px 10px;
          border-radius: 12px; display: inline-flex; align-items: center; gap: 4px;
        }
        .bin-badge.jaune { background: rgba(245,200,66,0.15); color: #b8860b; }
        .bin-badge.verte { background: rgba(74,222,128,0.15); color: #16a34a; }

        /* Big action buttons */
        .actions {
          display: flex; gap: 8px; margin-top: 10px;
        }
        .btn {
          flex: 1; border: none; border-radius: 10px;
          padding: 12px 16px; font-size: 0.9rem; font-weight: 700;
          cursor: pointer; font-family: inherit;
          transition: all 0.15s; display: flex; align-items: center;
          justify-content: center; gap: 6px;
          -webkit-tap-highlight-color: transparent;
        }
        .btn:active { transform: scale(0.97); }
        .btn-ok {
          background: rgba(34,197,94,0.18); color: #16a34a;
          border: 2px solid rgba(34,197,94,0.35);
        }
        .btn-ok:active { background: rgba(34,197,94,0.3); }
        .btn-miss {
          background: rgba(248,113,113,0.12); color: #dc2626;
          border: 2px solid rgba(248,113,113,0.25);
          flex: 0.5;
        }
        .btn-miss:active { background: rgba(248,113,113,0.25); }

        .status {
          font-size: 0.85rem; font-weight: 700; padding: 8px 12px;
          border-radius: 8px; text-align: center;
        }
        .status.done { color: #16a34a; background: rgba(34,197,94,0.1); }
        .status.missed { color: #dc2626; background: rgba(248,113,113,0.1); }

        .empty {
          text-align: center; padding: 24px 16px;
          color: var(--secondary-text-color); font-size: 0.9rem;
        }
        .empty-icon { font-size: 2rem; margin-bottom: 8px; }
        #toast {
          position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%) translateY(60px);
          background: var(--primary-color); color: #fff; padding: 10px 20px;
          border-radius: 10px; font-size: 0.88rem; font-weight: 600; opacity: 0;
          transition: all 0.25s; z-index: 999; pointer-events: none;
        }
        #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
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

    // Attach event listeners to buttons
    this.shadowRoot.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._confirmBin(btn.dataset.date, btn.dataset.bin, btn.dataset.action);
      });
    });
  }

  _renderItem(col) {
    const cls = col.is_today ? "today" : col.is_tomorrow ? "tomorrow" : "";
    const label = col.is_today
      ? '<span class="date-label today-label">Aujourd\'hui</span>'
      : col.is_tomorrow
        ? '<span class="date-label tomorrow-label">Demain</span>'
        : "";

    const binsHtml = col.bins
      .map((b) => {
        const icon = b === "jaune" ? "🟡" : "🟢";
        const name = b === "jaune" ? "Jaune" : "Verte";
        return `<span class="bin-badge ${b}">${icon} ${name}</span>`;
      })
      .join("");

    // Action buttons per bin - big and clear
    const actionsHtml = col.bins
      .map((b) => {
        const st = col.status[b] || "";
        if (st === "done") {
          return `<span class="status done">✅ Sortie</span>`;
        }
        if (st === "missed") {
          return `<span class="status missed">❌ Manquee</span>`;
        }
        const name = b === "jaune" ? "Jaune" : "Verte";
        const icon = b === "jaune" ? "🟡" : "🟢";
        return `
          <button class="btn btn-ok" data-action="done" data-date="${col.date}" data-bin="${b}">
            ✅ ${icon} Sortie ${name}
          </button>
          <button class="btn btn-miss" data-action="missed" data-date="${col.date}" data-bin="${b}">
            ❌
          </button>
        `;
      })
      .join("");

    return `
      <div class="item ${cls}">
        <div class="item-top">
          <div>
            <span class="date-text">${col.date_formatted}</span>${label}
          </div>
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
  description:
    "Affiche les prochaines collectes de poubelles avec boutons de confirmation.",
  preview: true,
});
