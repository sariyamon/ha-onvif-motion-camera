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
const VERSION = "1.5.0";

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

/** Tap action that opens the snapshot viewer (works in any picture-elements card). */
export function viewerAction(camera, image, time) {
  return {
    action: "fire-dom-event",
    onvif_motion_viewer: { camera, image, ...(time ? { time } : {}) },
  };
}

// 1×1 transparent pixel stretched over the whole picture, so a tap anywhere opens the viewer.
const TAP_LAYER = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";

export function lastMotionConfig(cams, cfg) {
  if (!cams.length) return empty();
  const cards = cams
    .filter((c) => c.ents.last_snapshot)
    .map((c) => {
      const tap =
        cfg.tap === "more-info"
          ? { action: "more-info", entity: c.ents.live }
          : viewerAction(c.ents.live, c.ents.last_snapshot, c.ents.last_snapshot_time);
      const elements = [
        {
          type: "image",
          image: TAP_LAYER,
          tap_action: tap,
          hold_action: { action: "more-info", entity: c.ents.live },
          style: { left: "50%", top: "50%", width: "100%", height: "100%" },
        },
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

/* ------------------------------------------------------ snapshot viewer */

const VIEWER_CSS = `
.omv-backdrop{position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,.88);display:flex;
  align-items:center;justify-content:center;padding:16px;box-sizing:border-box;
  font-family:var(--ha-font-family-body,Roboto,sans-serif);animation:omv-in .15s ease-out}
@keyframes omv-in{from{opacity:0}to{opacity:1}}
.omv-box{width:100%;max-width:1100px;display:flex;flex-direction:column;gap:10px}
.omv-head{display:flex;align-items:center;gap:12px;color:#fff}
.omv-title{flex:1;min-width:0}
.omv-name{font-size:18px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.omv-sub{font-size:13px;opacity:.75;margin-top:2px}
.omv-media{position:relative;width:100%;border-radius:12px;overflow:hidden;background:#000;
  aspect-ratio:16/9;display:flex;align-items:center;justify-content:center}
.omv-media img{width:100%;height:100%;object-fit:contain;display:block}
.omv-media .omv-live{width:100%}
.omv-play{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:76px;height:76px;
  border-radius:50%;border:2px solid rgba(255,255,255,.85);background:rgba(0,0,0,.45);color:#fff;
  display:flex;align-items:center;justify-content:center;cursor:pointer;backdrop-filter:blur(4px);
  transition:transform .12s,background .12s}
.omv-play:hover{background:rgba(0,0,0,.65);transform:translate(-50%,-50%) scale(1.06)}
.omv-play ha-icon{--mdc-icon-size:44px;margin-left:4px}
.omv-badge{position:absolute;top:10px;left:10px;padding:3px 10px;border-radius:999px;font-size:12px;
  font-weight:600;letter-spacing:.04em;color:#fff;background:rgba(0,0,0,.55)}
.omv-badge.live{background:#d32f2f}
.omv-bar{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}
.omv-btn{display:inline-flex;align-items:center;gap:6px;padding:9px 16px;border-radius:999px;
  border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.08);color:#fff;font:inherit;
  font-size:14px;cursor:pointer}
.omv-btn:hover{background:rgba(255,255,255,.18)}
.omv-btn ha-icon{--mdc-icon-size:20px}
.omv-x{background:none;border:none;color:#fff;cursor:pointer;padding:6px;border-radius:50%;display:flex}
.omv-x:hover{background:rgba(255,255,255,.12)}
`;

function currentHass() {
  const ha = document.querySelector("home-assistant");
  return ha && ha.hass;
}

function formatState(hass, entityId) {
  const st = entityId && hass.states[entityId];
  if (!st || ["unknown", "unavailable"].includes(st.state)) return "";
  try {
    if (hass.formatEntityState) return hass.formatEntityState(st);
  } catch (_e) {
    /* fall through */
  }
  const d = new Date(st.state);
  return isNaN(d) ? st.state : d.toLocaleString();
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

const icon = (name) => el("ha-icon", { icon: name });

export function openViewer({ camera, image, time }) {
  const hass = currentHass();
  if (!hass || !camera) return;
  closeViewer();
  const camState = hass.states[camera];
  const name = (camState && camState.attributes.friendly_name) || camera;
  const imgState = image && hass.states[image];
  const src = imgState && imgState.attributes.entity_picture;

  const root = el("div", { class: "omv-backdrop", role: "dialog", "aria-modal": "true", "aria-label": name });
  root.append(el("style", { text: VIEWER_CSS }));
  const media = el("div", { class: "omv-media" });
  const sub = el("div", { class: "omv-sub", text: time ? `Last motion · ${formatState(hass, time)}` : "Last motion" });
  const bar = el("div", { class: "omv-bar" });
  let liveCard = null;
  let timer = null;

  const showSnapshot = () => {
    if (timer) clearInterval(timer);
    liveCard = null;
    media.replaceChildren();
    if (src) media.append(el("img", { src, alt: `${name} last motion snapshot` }));
    else media.append(el("div", { class: "omv-sub", text: "No snapshot yet" }));
    media.append(el("span", { class: "omv-badge", text: "SNAPSHOT" }));
    media.append(el("button", { class: "omv-play", title: "Play live stream", "aria-label": "Play live stream", onclick: showLive }, [icon("mdi:play")]));
    sub.textContent = time ? `Last motion · ${formatState(hass, time)}` : "Last motion";
    bar.replaceChildren(
      el("button", { class: "omv-btn", onclick: showLive }, [icon("mdi:play-circle"), "Watch live"]),
      el("button", { class: "omv-btn", onclick: moreInfo }, [icon("mdi:cctv"), "Camera details"])
    );
  };

  const showLive = async (ev) => {
    if (ev) ev.stopPropagation();
    const helpers = await window.loadCardHelpers();
    liveCard = helpers.createCardElement({
      type: "picture-entity",
      entity: camera,
      camera_image: camera,
      camera_view: "live",
      show_name: false,
      show_state: false,
      tap_action: { action: "none" },
      hold_action: { action: "none" },
    });
    liveCard.classList.add("omv-live");
    liveCard.hass = currentHass() || hass;
    timer = setInterval(() => {
      const h = currentHass();
      if (h && liveCard) liveCard.hass = h;
    }, 2000);
    media.replaceChildren(liveCard, el("span", { class: "omv-badge live", text: "● LIVE" }));
    sub.textContent = "Live stream";
    bar.replaceChildren(
      el("button", { class: "omv-btn", onclick: showSnapshot }, [icon("mdi:image"), "Back to snapshot"]),
      el("button", { class: "omv-btn", onclick: moreInfo }, [icon("mdi:cctv"), "Camera details"])
    );
  };

  const moreInfo = () => {
    closeViewer();
    const ha = document.querySelector("home-assistant");
    ha && ha.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId: camera }, bubbles: true, composed: true }));
  };

  const head = el("div", { class: "omv-head" }, [
    el("div", { class: "omv-title" }, [el("div", { class: "omv-name", text: name }), sub]),
    el("button", { class: "omv-x", title: "Close", "aria-label": "Close", onclick: closeViewer }, [icon("mdi:close")]),
  ]);
  const box = el("div", { class: "omv-box" }, [head, media, bar]);
  box.addEventListener("click", (e) => e.stopPropagation());
  root.addEventListener("click", closeViewer);
  root.append(box);
  root._cleanup = () => timer && clearInterval(timer);
  document.body.append(root);
  document.addEventListener("keydown", onKey);
  showSnapshot();
}

function onKey(e) {
  if (e.key === "Escape") closeViewer();
}

export function closeViewer() {
  document.querySelectorAll(".omv-backdrop").forEach((n) => {
    n._cleanup && n._cleanup();
    n.remove();
  });
  document.removeEventListener("keydown", onKey);
}

if (typeof window !== "undefined" && !window.__onvifMotionViewer) {
  window.__onvifMotionViewer = true;
  window.addEventListener("ll-custom", (ev) => {
    const cfg = ev.detail && ev.detail.onvif_motion_viewer;
    if (cfg) openViewer(cfg);
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

export function notifyConfig(cams, cfg) {
  return alertsConfig(cams, {
    ...cfg,
    title: cfg.title ?? "Telegram & WhatsApp",
    icon: cfg.icon || "mdi:message-badge",
    show: ["telegram_alerts", "whatsapp_alerts"],
  });
}

export function snapshotsConfig(cams, cfg) {
  if (!cams.length) return empty();
  const cards = cams
    .filter((c) => c.ents.snapshots || c.ents.take_snapshot)
    .map((c) => ({
      type: "tile",
      entity: c.ents.snapshots || c.ents.take_snapshot,
      name: c.name,
      icon: "mdi:image-multiple",
      vertical: true,
      hold_action: c.ents.take_snapshot ? press(c.ents.take_snapshot) : { action: "more-info" },
    }));
  return withHeading(cfg, "Snapshots", "mdi:image-multiple", {
    type: "grid",
    columns: cfg.columns || 3,
    square: false,
    cards,
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

function pickCamera(cams, cfg, prefer) {
  return (
    (cfg.camera && cams.find((c) => c.ents.live === cfg.camera || c.id === cfg.camera)) ||
    cams.find(prefer) ||
    cams[0]
  );
}

const hasPtz = (c) => PTZ.some(([k]) => c.ents[k]) || c.ents.ptz_preset;
const hasSettings = (c) =>
  ["light:spotlight", "night_vision", "switch:target_tracking", "switch:alarm", "alarm_trigger"].some((k) => c.ents[k]);

const liveTile = (e, cfg) => ({
  type: "picture-entity",
  entity: e.live,
  camera_image: e.live,
  camera_view: cfg.camera_view || "auto",
  show_name: false,
  show_state: false,
});

/** PTZ pad (pan / tilt / zoom) and preset positions, optionally with the live view on top. */
function ptzCards(cam, cfg) {
  const e = cam.ents;
  const cards = [];
  if (cfg.show_live !== false) cards.push(liveTile(e, cfg));
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
        hold_action: press(e[k]),
      })),
    });
  }
  if (e.ptz_preset)
    cards.push({ type: "tile", entity: e.ptz_preset, name: "Go to preset", features: [{ type: "select-options" }], features_position: "inline" });
  return cards;
}

/** Camera settings: spotlight, night vision, auto tracking, alarm, siren, snapshot. */
function settingsCards(cam) {
  const e = cam.ents;
  const cards = [];
  if (e["light:spotlight"]) cards.push({ type: "tile", entity: e["light:spotlight"], name: "Spotlight", features: [{ type: "light-brightness" }] });
  if (e.night_vision) cards.push({ type: "tile", entity: e.night_vision, name: "Night vision", features: [{ type: "select-options" }], features_position: "inline" });
  const pairs = [];
  if (e["switch:target_tracking"]) pairs.push({ type: "tile", entity: e["switch:target_tracking"], name: "Auto tracking", vertical: true });
  if (e["switch:alarm"]) pairs.push({ type: "tile", entity: e["switch:alarm"], name: "Alarm armed", vertical: true });
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
  return cards;
}

export function ptzConfig(cams, cfg) {
  const cam = pickCamera(cams, cfg, hasPtz);
  if (!cam) return empty();
  const cards = ptzCards(cam, cfg);
  if (cards.length <= 1 && !hasPtz(cam)) return empty(`${cam.name} has no pan / tilt / zoom.`);
  return withHeading(cfg, `${cam.name} PTZ`, "mdi:camera-control", { type: "vertical-stack", cards });
}

export function settingsConfig(cams, cfg) {
  const cam = pickCamera(cams, cfg, hasSettings);
  if (!cam) return empty();
  const cards = settingsCards(cam);
  if (!cards.length) return empty(`${cam.name} has no adjustable settings.`);
  return withHeading(cfg, `${cam.name} controls`, "mdi:tune-variant", { type: "vertical-stack", cards });
}

/** One camera complete (e.g. a 360 / PTZ camera): live view, PTZ pad, presets and settings. */
export function controlsConfig(cams, cfg) {
  const cam = pickCamera(cams, cfg, hasPtz);
  if (!cam) return empty();
  const cards = [...ptzCards(cam, { ...cfg, show_live: cfg.show_live !== false }), ...settingsCards(cam)];
  return withHeading(cfg, cam.name, "mdi:rotate-360", { type: "vertical-stack", cards });
}

/** Everything at once: Last Motion, Live, controls of each PTZ camera, Detections, Alerts. */
export function dashboardConfig(cams, cfg) {
  if (!cams.length) return empty();
  const sub = { ...cfg, title: undefined };
  const cards = [lastMotionConfig(cams, sub), liveConfig(cams, sub)];
  for (const cam of cams.filter((c) => hasPtz(c) || hasSettings(c))) {
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
  const CAMERA_FIELD = {
    name: "camera",
    selector: { entity: { filter: { integration: DOMAIN, domain: "camera" } } },
  };
  const LIVE_FIELD = { name: "show_live", selector: { boolean: {} } };
  const cards = [
    ["last-motion", "Recent motion", "Latest motion snapshot of each camera with its name and time.", lastMotionConfig, [CAMERAS_FIELD, TITLE_FIELD, COLUMNS_FIELD]],
    ["live", "Live cameras", "Live view of each camera.", liveConfig, [CAMERAS_FIELD, TITLE_FIELD, COLUMNS_FIELD]],
    ["detections", "Detections", "Last detection and today's count for each camera.", detectionsConfig, [CAMERAS_FIELD, TITLE_FIELD]],
    ["notify", "Telegram & WhatsApp", "Telegram and WhatsApp alert switches for each camera.", notifyConfig, [CAMERAS_FIELD, TITLE_FIELD]],
    ["snapshots", "Snapshots", "Snapshot-on-motion switch per camera (hold to take one now).", snapshotsConfig, [CAMERAS_FIELD, TITLE_FIELD, COLUMNS_FIELD]],
    ["alerts", "Alerts & snapshots", "Connection status plus Snapshots, Telegram and WhatsApp switches per camera.", alertsConfig, [CAMERAS_FIELD, TITLE_FIELD]],
    ["ptz", "PTZ control", "Pan / tilt / zoom pad and presets for one camera.", ptzConfig, [CAMERA_FIELD, LIVE_FIELD, TITLE_FIELD]],
    ["settings", "Camera controls", "Spotlight, night vision, auto tracking, alarm and siren for one camera.", settingsConfig, [CAMERA_FIELD, TITLE_FIELD]],
    ["controls", "360 / PTZ camera", "One camera complete: live view, PTZ pad, presets and all controls.", controlsConfig, [CAMERA_FIELD, TITLE_FIELD]],
    ["dashboard", "All cameras (full view)", "Every section above in one card.", dashboardConfig, [CAMERAS_FIELD, COLUMNS_FIELD]],
  ];
  for (const [slug, name, description, build, schema] of cards) {
    defineCard(`onvif-motion-${slug}-card`, `ONVIF Motion: ${name}`, description, build, schema);
  }
  console.info(`%c ONVIF Motion cards %c ${VERSION} `, "background:#1565C0;color:#fff", "background:#FF9800;color:#000");
}
