/*
 * ONVIF Motion & Snapshot – ready-made dashboard cards.
 *
 * Loaded automatically by the integration (no resource to add). Each card
 * finds the cameras of this integration by itself and builds standard Home
 * Assistant cards (tiles, picture-elements, headings…), so they follow your
 * theme. Pick specific cameras with `cameras:` (camera entity IDs).
 *
 *   type: custom:onvif-motion-last-motion-card   – latest snapshots
 *   type: custom:onvif-motion-live-card          – live views
 *   type: custom:onvif-motion-detections-card    – last detection + today's count
 *   type: custom:onvif-motion-alerts-card        – snapshot / Telegram / WhatsApp switches
 *   type: custom:onvif-motion-controls-card      – one camera: live view, PTZ, spotlight, siren…
 */
const DOMAIN = "onvif_motion";
const VERSION = "1.4.0";

const SHADOW = "0 0 4px rgba(0,0,0,0.9), 0 1px 2px rgba(0,0,0,0.9)";
const LABEL = {
  transform: "none",
  color: "white",
  background: "none",
  "white-space": "nowrap",
  "text-shadow": SHADOW,
};

/* ------------------------------------------------------------------ data */

/** Cameras of this integration: [{id, name, ents: {translation_key: entity_id}}]. */
export function findCameras(hass, wanted) {
  const byDevice = {};
  for (const [entityId, entry] of Object.entries(hass.entities || {})) {
    if (entry.platform !== DOMAIN || !entry.device_id) continue;
    const ents = (byDevice[entry.device_id] ||= {});
    const key =
      entry.translation_key || (entityId.startsWith("camera.") ? "live" : null);
    if (key && !ents[key]) ents[key] = entityId;
    if (key) ents[`${entityId.split(".")[0]}:${key}`] ||= entityId;
  }
  let list = Object.entries(byDevice)
    .filter(([, ents]) => ents.live)
    .map(([id, ents]) => {
      const dev = (hass.devices || {})[id] || {};
      return { id, name: dev.name_by_user || dev.name || ents.live, ents };
    });
  if (Array.isArray(wanted) && wanted.length) {
    list = wanted
      .map((w) => list.find((c) => c.ents.live === w || c.id === w || c.name === w))
      .filter(Boolean);
  } else {
    list.sort((a, b) => a.name.localeCompare(b.name));
  }
  return list;
}

const press = (entity) => ({
  action: "perform-action",
  perform_action: "button.press",
  target: { entity_id: entity },
});

const empty = (text) => ({
  type: "markdown",
  content: text || "No ONVIF Motion & Snapshot cameras found.",
});

/* ------------------------------------------------------- card builders */

export function lastMotionConfig(cams, cfg) {
  if (!cams.length) return empty();
  const cards = cams
    .filter((c) => c.ents.last_snapshot)
    .map((c) => {
      const tap = { action: "more-info", entity: c.ents.live };
      const elements = [
        {
          type: "state-label",
          entity: c.ents.live,
          attribute: "friendly_name",
          tap_action: tap,
          style: { ...LABEL, top: "8px", left: "8px", "font-size": "14px", "font-weight": "600" },
        },
      ];
      if (c.ents.last_snapshot_time) {
        elements.push({
          type: "state-label",
          entity: c.ents.last_snapshot_time,
          tap_action: tap,
          style: { ...LABEL, bottom: "8px", left: "8px", "font-size": "11px" },
        });
      }
      return { type: "picture-elements", image_entity: c.ents.last_snapshot, elements };
    });
  return withHeading(cfg, "Last Motion", "mdi:camera-burst", {
    type: "grid",
    columns: cfg.columns || 2,
    square: false,
    cards,
  });
}

export function liveConfig(cams, cfg) {
  if (!cams.length) return empty();
  return withHeading(cfg, "Live", "mdi:cctv", {
    type: "grid",
    columns: cfg.columns || 2,
    square: false,
    cards: cams.map((c) => ({
      type: "picture-entity",
      entity: c.ents.live,
      camera_image: c.ents.live,
      camera_view: cfg.camera_view || "auto",
      show_name: cfg.show_name === true,
      show_state: false,
    })),
  });
}

export function detectionsConfig(cams, cfg) {
  if (!cams.length) return empty();
  const cards = [];
  for (const c of cams) {
    if (c.ents.last_event_type) {
      cards.push({
        type: "tile",
        entity: c.ents.last_event_type,
        name: c.name,
        icon: "mdi:cctv",
        state_content: ["state", "last_changed"],
        tap_action: { action: "more-info", entity: c.ents.live },
      });
    }
    if (c.ents.events_today) {
      cards.push({ type: "tile", entity: c.ents.events_today, name: "Today" });
    }
  }
  return withHeading(cfg, "Detections", "mdi:motion-sensor", {
    type: "grid",
    columns: 2,
    square: false,
    cards,
  });
}

export function alertsConfig(cams, cfg) {
  if (!cams.length) return empty();
  const show = cfg.show || ["snapshots", "telegram_alerts", "whatsapp_alerts"];
  const names = { snapshots: "Snapshots", telegram_alerts: "Telegram", whatsapp_alerts: "WhatsApp" };
  const blocks = [];
  for (const c of cams) {
    const badges = c.ents.event_subscription
      ? [{ type: "entity", entity: c.ents.event_subscription, show_state: true, show_icon: true, color: "green" }]
      : [];
    blocks.push({ type: "heading", heading: c.name, heading_style: "subtitle", badges });
    blocks.push({
      type: "grid",
      columns: show.length,
      square: false,
      cards: show
        .filter((k) => c.ents[k])
        .map((k) => ({ type: "tile", entity: c.ents[k], name: names[k] || k, vertical: true })),
    });
  }
  return withHeading(cfg, "Alerts & snapshots", "mdi:bell-cog", {
    type: "vertical-stack",
    cards: blocks,
  });
}

const PTZ = [
  ["ptz_zoom_out", "mdi:magnify-minus"],
  ["ptz_tilt_up", "mdi:chevron-up"],
  ["ptz_zoom_in", "mdi:magnify-plus"],
  ["ptz_pan_left", "mdi:chevron-left"],
  ["ptz_tilt_down", "mdi:chevron-down"],
  ["ptz_pan_right", "mdi:chevron-right"],
];

export function controlsConfig(cams, cfg) {
  const cam =
    (cfg.camera && cams.find((c) => c.ents.live === cfg.camera)) ||
    cams.find((c) => c.ents.ptz_pan_left) ||
    cams[0];
  if (!cam) return empty();
  const e = cam.ents;
  const cards = [
    {
      type: "picture-entity",
      entity: e.live,
      camera_image: e.live,
      camera_view: cfg.camera_view || "auto",
      show_name: false,
      show_state: false,
    },
  ];
  const ptz = PTZ.filter(([k]) => e[k]);
  if (ptz.length) {
    cards.push({
      type: "grid",
      columns: 3,
      square: false,
      cards: ptz.map(([k, icon]) => ({
        type: "button",
        icon,
        show_name: false,
        icon_height: "32px",
        tap_action: press(e[k]),
      })),
    });
  }
  const rows = [];
  if (e.ptz_preset) rows.push({ type: "tile", entity: e.ptz_preset, name: "Go to preset", features: [{ type: "select-options" }], features_position: "inline" });
  if (e["light:spotlight"]) rows.push({ type: "tile", entity: e["light:spotlight"], name: "Spotlight", features: [{ type: "light-brightness" }] });
  if (e.night_vision) rows.push({ type: "tile", entity: e.night_vision, name: "Night vision", features: [{ type: "select-options" }], features_position: "inline" });
  cards.push(...rows);
  const pairs = [];
  if (e["switch:target_tracking"]) pairs.push({ type: "tile", entity: e["switch:target_tracking"], name: "Auto tracking", vertical: true });
  const alarm = e["switch:alarm"];
  if (alarm) pairs.push({ type: "tile", entity: alarm, name: "Alarm armed", vertical: true });
  if (e.alarm_trigger)
    pairs.push({
      type: "tile",
      entity: e.alarm_trigger,
      name: "Sound alarm",
      vertical: true,
      color: "red",
      tap_action: { ...press(e.alarm_trigger), confirmation: { text: `Sound the ${cam.name} siren?` } },
    });
  if (e.alarm_stop) pairs.push({ type: "tile", entity: e.alarm_stop, name: "Stop alarm", vertical: true, tap_action: press(e.alarm_stop) });
  if (e.take_snapshot) pairs.push({ type: "tile", entity: e.take_snapshot, name: "Take snapshot", vertical: true, tap_action: press(e.take_snapshot) });
  if (pairs.length) cards.push({ type: "grid", columns: 2, square: false, cards: pairs });
  return withHeading(cfg, cam.name, "mdi:cctv", { type: "vertical-stack", cards });
}

/** Everything at once: Last Motion, Live, controls of each PTZ camera, Detections, Alerts. */
export function dashboardConfig(cams, cfg) {
  if (!cams.length) return empty();
  const sub = { ...cfg, title: undefined };
  const cards = [lastMotionConfig(cams, sub), liveConfig(cams, sub)];
  for (const cam of cams.filter((c) => c.ents.ptz_pan_left || c.ents["light:spotlight"])) {
    cards.push(controlsConfig(cams, { ...sub, camera: cam.ents.live }));
  }
  cards.push(detectionsConfig(cams, sub), alertsConfig(cams, sub));
  return { type: "vertical-stack", cards };
}

function withHeading(cfg, fallback, icon, body) {
  if (cfg.title === false || cfg.title === "") return body;
  return {
    type: "vertical-stack",
    cards: [{ type: "heading", heading: cfg.title || fallback, heading_style: "title", icon: cfg.icon || icon }, body],
  };
}

/* --------------------------------------------------------- card element */

const CAMERAS_FIELD = {
  name: "cameras",
  selector: { entity: { multiple: true, filter: { integration: DOMAIN, domain: "camera" } } },
};
const TITLE_FIELD = { name: "title", selector: { text: {} } };
const COLUMNS_FIELD = { name: "columns", selector: { number: { min: 1, max: 4, mode: "box" } } };

function defineCard(tag, name, description, build, schema) {
  if (customElements.get(tag)) return;

  class OnvifMotionCard extends HTMLElement {
    setConfig(config) {
      this._config = { ...(config || {}) };
      this._signature = null;
      if (this._hass) this._render();
    }

    set hass(hass) {
      this._hass = hass;
      this._render();
    }

    _render() {
      if (!this._config || !this._hass) return;
      const cams = findCameras(this._hass, this._config.cameras);
      const signature = JSON.stringify([this._config, cams]);
      if (signature !== this._signature) {
        this._signature = signature;
        this._build(build(cams, this._config));
      } else if (this._card) {
        this._card.hass = this._hass;
      }
    }

    async _build(cardConfig) {
      const token = (this._token = Symbol("build"));
      const helpers = await window.loadCardHelpers();
      if (token !== this._token) return;
      const card = helpers.createCardElement(cardConfig);
      card.hass = this._hass;
      this._card = card;
      this.replaceChildren(card);
    }

    getCardSize() {
      return this._card && this._card.getCardSize ? this._card.getCardSize() : 6;
    }

    getGridOptions() {
      return { columns: 12, min_columns: 6 };
    }

    static getConfigForm() {
      return { schema };
    }

    static getStubConfig() {
      return {};
    }
  }

  customElements.define(tag, OnvifMotionCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: tag,
    name,
    description,
    preview: true,
    documentationURL: "https://github.com/sariyamon/ha-onvif-motion-camera#dashboard-cards",
  });
}

if (typeof customElements !== "undefined") {
  defineCard(
    "onvif-motion-last-motion-card",
    "ONVIF Motion: Last Motion",
    "Latest snapshot of each camera with its name and time.",
    lastMotionConfig,
    [CAMERAS_FIELD, TITLE_FIELD, COLUMNS_FIELD]
  );
  defineCard(
    "onvif-motion-live-card",
    "ONVIF Motion: Live",
    "Live view of each camera.",
    liveConfig,
    [CAMERAS_FIELD, TITLE_FIELD, COLUMNS_FIELD]
  );
  defineCard(
    "onvif-motion-detections-card",
    "ONVIF Motion: Detections",
    "Last detection and today's count for each camera.",
    detectionsConfig,
    [CAMERAS_FIELD, TITLE_FIELD]
  );
  defineCard(
    "onvif-motion-alerts-card",
    "ONVIF Motion: Alerts & snapshots",
    "Snapshot, Telegram and WhatsApp switches for each camera.",
    alertsConfig,
    [CAMERAS_FIELD, TITLE_FIELD]
  );
  defineCard(
    "onvif-motion-controls-card",
    "ONVIF Motion: Camera controls",
    "One camera: live view, pan/tilt/zoom, presets, spotlight, siren.",
    controlsConfig,
    [
      { name: "camera", selector: { entity: { filter: { integration: DOMAIN, domain: "camera" } } } },
      TITLE_FIELD,
    ]
  );
  defineCard(
    "onvif-motion-dashboard-card",
    "ONVIF Motion: All cameras (full view)",
    "Last Motion, Live, camera controls, Detections and Alerts in one card.",
    dashboardConfig,
    [CAMERAS_FIELD, COLUMNS_FIELD]
  );
  console.info(`%c ONVIF Motion cards %c ${VERSION} `, "background:#1565C0;color:#fff", "background:#FF9800;color:#000");
}
