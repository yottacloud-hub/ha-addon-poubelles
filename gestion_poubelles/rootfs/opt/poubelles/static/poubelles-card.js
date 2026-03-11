/**
 * Poubelles Card - Custom Lovelace card for Gestion Poubelles addon.
 * Works for ALL HA users (admin and non-admin).
 *
 * Config:
 *   type: custom:poubelles-card
 *   entity: sensor.poubelles_prochaine_collecte
 *   max_items: 5
 */
const POUBELLES_CARD_VERSION = "1.2.2";

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
    const row = this.shadowRoot.querySelector(`.item[data-date="${date}"]`);
    if (!row) return;
    const binRow = row.querySelector(`.bin-row[data-bin="${binType}"]`);
    if (!binRow) return;
    const actionsDiv = binRow.querySelector(".bin-actions");
    if (actionsDiv) {
      actionsDiv.innerHTML = status === "done"
        ? `<div class="status-badge done"><span class="status-icon">&#10003;</span> Sortie</div>`
        : `<div class="status-badge missed"><span class="status-icon">&#10007;</span> Pas sortie</div>`;
    }
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
        <ha-card>
          <div style="padding:24px;text-align:center;">
            <div style="font-size:2.5rem;margin-bottom:12px;">🗑️</div>
            <div style="font-weight:600;font-size:1rem;margin-bottom:8px;">Poubelles</div>
            <div style="color:var(--secondary-text-color);font-size:0.85rem;">
              Entite <code>${entityId}</code> introuvable.<br>
              <small>Verifiez que l'addon Gestion Poubelles est demarre.</small>
            </div>
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
        ha-card { overflow: hidden; padding-bottom: 8px; }

        /* Header */
        .card-header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 20px 20px 12px;
        }
        .card-title {
          display: flex; align-items: center; gap: 10px;
          font-size: 1.2rem; font-weight: 700;
          color: var(--primary-text-color);
        }
        .card-title-icon { font-size: 1.4rem; }
        .card-count {
          font-size: 0.72rem; font-weight: 600;
          color: var(--secondary-text-color);
          background: var(--divider-color, rgba(255,255,255,0.1));
          padding: 3px 10px; border-radius: 12px;
        }

        /* Items list */
        .items { padding: 0 12px; }

        /* Single collection item */
        .item {
          margin-bottom: 10px; border-radius: 16px;
          background: var(--card-background-color, var(--ha-card-background, rgba(255,255,255,0.05)));
          border: 1.5px solid var(--divider-color, rgba(255,255,255,0.08));
          overflow: hidden;
          transition: border-color 0.2s;
        }
        .item:last-child { margin-bottom: 4px; }
        .item.tomorrow {
          border-color: rgba(251, 191, 36, 0.5);
          background: linear-gradient(135deg, rgba(251,191,36,0.08) 0%, transparent 60%);
        }
        .item.today {
          border-color: rgba(34, 197, 94, 0.5);
          background: linear-gradient(135deg, rgba(34,197,94,0.08) 0%, transparent 60%);
        }

        /* Date header inside item */
        .item-header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 14px 16px 6px;
        }
        .date-info { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .date-text { font-weight: 700; font-size: 0.95rem; color: var(--primary-text-color); }
        .date-badge {
          font-size: 0.65rem; font-weight: 800; text-transform: uppercase;
          letter-spacing: 0.8px; padding: 3px 10px; border-radius: 8px;
        }
        .date-badge.today-badge {
          background: rgba(34,197,94,0.2); color: #22c55e;
        }
        .date-badge.tomorrow-badge {
          background: rgba(251,191,36,0.2); color: #fbbf24;
        }

        /* Bin rows */
        .bin-rows { padding: 4px 12px 12px; }
        .bin-row {
          display: flex; align-items: center; gap: 10px;
          padding: 8px 6px; border-radius: 12px;
          margin-bottom: 4px;
        }
        .bin-row:last-child { margin-bottom: 0; }

        /* Bin icon + name */
        .bin-info {
          display: flex; align-items: center; gap: 8px;
          min-width: 100px;
        }
        .bin-dot {
          width: 14px; height: 14px; border-radius: 50%;
          flex-shrink: 0;
        }
        .bin-dot.jaune { background: #fbbf24; box-shadow: 0 0 6px rgba(251,191,36,0.4); }
        .bin-dot.verte { background: #22c55e; box-shadow: 0 0 6px rgba(34,197,94,0.4); }
        .bin-name { font-weight: 600; font-size: 0.88rem; color: var(--primary-text-color); }

        /* Action buttons */
        .bin-actions { display: flex; gap: 8px; flex: 1; justify-content: flex-end; }

        .btn {
          border: none; border-radius: 12px; cursor: pointer;
          font-family: inherit; font-weight: 700; font-size: 0.85rem;
          display: flex; align-items: center; justify-content: center; gap: 6px;
          transition: all 0.15s ease;
          -webkit-tap-highlight-color: transparent;
          user-select: none;
        }
        .btn:active { transform: scale(0.95); }

        .btn-ok {
          flex: 1; padding: 12px 16px;
          background: rgba(34,197,94,0.15); color: #22c55e;
          border: 2px solid rgba(34,197,94,0.3);
        }
        .btn-ok:hover { background: rgba(34,197,94,0.25); }
        .btn-ok:active { background: rgba(34,197,94,0.35); }

        .btn-miss {
          padding: 12px 14px;
          background: rgba(239,68,68,0.1); color: #ef4444;
          border: 2px solid rgba(239,68,68,0.2);
        }
        .btn-miss:hover { background: rgba(239,68,68,0.2); }
        .btn-miss:active { background: rgba(239,68,68,0.3); }

        /* Status badges */
        .status-badge {
          display: flex; align-items: center; gap: 6px;
          padding: 10px 16px; border-radius: 12px;
          font-weight: 700; font-size: 0.85rem;
          flex: 1; justify-content: center;
        }
        .status-badge.done {
          background: rgba(34,197,94,0.12); color: #22c55e;
        }
        .status-badge.missed {
          background: rgba(239,68,68,0.1); color: #ef4444;
        }
        .status-icon { font-size: 1rem; }

        /* Empty state */
        .empty {
          text-align: center; padding: 32px 16px;
          color: var(--secondary-text-color);
        }
        .empty-icon { font-size: 2.5rem; margin-bottom: 12px; }
        .empty-text { font-size: 0.9rem; }

        /* Toast */
        #toast {
          position: fixed; bottom: 20px; left: 50%;
          transform: translateX(-50%) translateY(80px);
          background: var(--primary-color, #03a9f4); color: #fff;
          padding: 12px 24px; border-radius: 14px;
          font-size: 0.88rem; font-weight: 600;
          opacity: 0; transition: all 0.3s ease;
          z-index: 999; pointer-events: none;
          box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        #toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
      </style>
      <ha-card>
        <div class="card-header">
          <div class="card-title">
            <span class="card-title-icon">🗑️</span>
            Poubelles
          </div>
          ${stateObj.attributes.total_scheduled ? `<span class="card-count">${stateObj.attributes.total_scheduled} collectes</span>` : ""}
        </div>
        <div class="items">
          ${
            items.length === 0
              ? `<div class="empty"><div class="empty-icon">📭</div><p class="empty-text">Aucune collecte planifiee.</p></div>`
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
    const badge = col.is_today
      ? '<span class="date-badge today-badge">Aujourd\'hui</span>'
      : col.is_tomorrow
        ? '<span class="date-badge tomorrow-badge">Demain</span>'
        : "";

    const binRows = col.bins
      .map((b) => {
        const name = b === "jaune" ? "Jaune" : "Verte";
        const st = col.status[b] || "";

        let actionsHtml;
        if (st === "done") {
          actionsHtml = `<div class="status-badge done"><span class="status-icon">&#10003;</span> Sortie</div>`;
        } else if (st === "missed") {
          actionsHtml = `<div class="status-badge missed"><span class="status-icon">&#10007;</span> Pas sortie</div>`;
        } else {
          actionsHtml = `
            <button class="btn btn-ok" data-action="done" data-date="${col.date}" data-bin="${b}">
              &#10003; Sortie
            </button>
            <button class="btn btn-miss" data-action="missed" data-date="${col.date}" data-bin="${b}">
              &#10007;
            </button>
          `;
        }

        return `
          <div class="bin-row" data-bin="${b}">
            <div class="bin-info">
              <div class="bin-dot ${b}"></div>
              <span class="bin-name">${name}</span>
            </div>
            <div class="bin-actions">${actionsHtml}</div>
          </div>
        `;
      })
      .join("");

    return `
      <div class="item ${cls}" data-date="${col.date}">
        <div class="item-header">
          <div class="date-info">
            <span class="date-text">${col.date_formatted}</span>
            ${badge}
          </div>
        </div>
        <div class="bin-rows">${binRows}</div>
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
