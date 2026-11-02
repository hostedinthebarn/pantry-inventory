/**
 * Shared base for Home Assistant custom panels.
 *
 * Implements the documented panel_custom property contract (hass, narrow,
 * route, panel — see developers.home-assistant.io/docs/frontend/custom-ui/
 * creating-custom-panels/) as reactive LitElement properties, plus a
 * narrow-aware topbar helper.
 *
 * There is no supported way to reuse HA's native top-app-bar components
 * (ha-app-layout / hass-tabs-subpage / ha-menu-button) inside a custom
 * panel (see home-assistant/frontend#11131, unanswered). This base instead
 * renders a minimal topbar that only shows a menu button when `narrow` is
 * true, matching how built-in panels behave, rather than always-on.
 *
 * Vendor this file (and lit-core.min.js) into each panel's panel/dist/vendor/
 * directory — do not import across integration static paths, so each
 * integration stays independently installable/removable.
 */
import { LitElement, html, css } from "./lit-core.min.js";

export class HaPanelBase extends LitElement {
  static properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    route: { attribute: false },
    panel: { attribute: false },
  };

  static get topbarStyles() {
    return css`
      .hpk-topbar {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        min-width: 0;
      }
      .hpk-topbar-menu {
        flex: 0 0 auto;
        width: 40px;
        height: 40px;
        padding: 0;
        border: 0;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: color-mix(
          in srgb,
          var(--card-background-color, #fff) 92%,
          rgba(var(--rgb-primary-color), 0.08) 8%
        );
        color: var(--primary-text-color);
        cursor: pointer;
      }
      .hpk-topbar-menu ha-icon {
        width: 20px;
        height: 20px;
      }
      .hpk-hero-copy {
        min-width: 0;
      }
      .hpk-hero-copy h1 {
        margin: 0;
        font-size: 2rem;
      }
      .hpk-hero-copy p {
        margin: 8px 0 0;
        color: var(--secondary-text-color);
      }
      @media (max-width: 720px) {
        .hpk-topbar {
          flex-direction: column;
        }
      }
    `;
  }

  /** Dispatch HA's standard sidebar-toggle event. Only call this from a
   * control rendered when `narrow` is true (see renderTopbar below) — at
   * desktop width the sidebar is already visible. */
  toggleMenu() {
    this.dispatchEvent(
      new Event("hass-toggle-menu", { bubbles: true, composed: true })
    );
  }

  /** Render a topbar with the given title/subtitle. Menu button only
   * appears when this.narrow is true. */
  renderTopbar(title, subtitle) {
    return html`
      <div class="hpk-topbar">
        ${this.narrow
          ? html`
              <button
                class="hpk-topbar-menu"
                title="Open menu"
                aria-label="Open menu"
                @click=${this.toggleMenu}
              >
                <ha-icon icon="mdi:menu"></ha-icon>
              </button>
            `
          : ""}
        <div class="hpk-hero-copy">
          <h1>${title}</h1>
          ${subtitle ? html`<p>${subtitle}</p>` : ""}
        </div>
      </div>
    `;
  }
}

export { html, css };
