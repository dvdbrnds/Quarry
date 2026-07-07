/**
 * Quarry Alert Banner — Embeddable JS Snippet
 *
 * Drop this into any website:
 *   <script src="https://quarry.moravian.edu/alerts/banner.js"></script>
 *
 * Polls GET /api/alerts/active every 30 seconds. When an active alert exists,
 * injects a fixed banner at the top of the page. Removes it when cleared.
 *
 * Optional attributes on the <script> tag:
 *   data-quarry-url="https://quarry.moravian.edu"  (override base URL)
 *   data-quarry-poll="30000"                        (poll interval in ms)
 *   data-quarry-position="top"                      (top or bottom)
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var baseUrl = (script && script.getAttribute("data-quarry-url")) || "";
  var pollMs = parseInt((script && script.getAttribute("data-quarry-poll")) || "30000", 10);
  var position = (script && script.getAttribute("data-quarry-position")) || "top";

  var BANNER_ID = "quarry-alert-banner";
  var STYLE_ID = "quarry-alert-banner-style";

  var categoryColors = {
    emergency: "#dc2626",
    weather: "#0284c7",
    campus_closing: "#d97706",
    parking: "#4f46e5",
    general: "#4b5563"
  };

  function injectStyle() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = [
      "#" + BANNER_ID + " {",
      "  position: fixed;",
      "  " + position + ": 0;",
      "  left: 0;",
      "  right: 0;",
      "  z-index: 999999;",
      "  padding: 12px 20px;",
      "  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;",
      "  font-size: 15px;",
      "  color: #fff;",
      "  text-align: center;",
      "  box-shadow: 0 2px 8px rgba(0,0,0,0.3);",
      "  display: flex;",
      "  align-items: center;",
      "  justify-content: center;",
      "  gap: 12px;",
      "  animation: quarryBannerSlide 0.3s ease-out;",
      "}",
      "#" + BANNER_ID + " .quarry-banner-cat {",
      "  font-size: 11px;",
      "  font-weight: 700;",
      "  text-transform: uppercase;",
      "  letter-spacing: 0.05em;",
      "  opacity: 0.85;",
      "  white-space: nowrap;",
      "}",
      "#" + BANNER_ID + " .quarry-banner-subject {",
      "  font-weight: 600;",
      "}",
      "#" + BANNER_ID + " .quarry-banner-body {",
      "  font-weight: 400;",
      "  opacity: 0.9;",
      "}",
      "#" + BANNER_ID + " .quarry-banner-close {",
      "  background: rgba(255,255,255,0.2);",
      "  border: none;",
      "  color: #fff;",
      "  font-size: 18px;",
      "  cursor: pointer;",
      "  padding: 2px 8px;",
      "  border-radius: 4px;",
      "  line-height: 1;",
      "  margin-left: 8px;",
      "}",
      "#" + BANNER_ID + " .quarry-banner-close:hover {",
      "  background: rgba(255,255,255,0.35);",
      "}",
      "@keyframes quarryBannerSlide {",
      "  from { transform: translateY(" + (position === "top" ? "-100%" : "100%") + "); }",
      "  to { transform: translateY(0); }",
      "}",
      "@media (max-width: 600px) {",
      "  #" + BANNER_ID + " { flex-direction: column; gap: 4px; padding: 10px 14px; font-size: 13px; }",
      "}"
    ].join("\n");
    document.head.appendChild(style);
  }

  function showBanner(alert) {
    injectStyle();
    var existing = document.getElementById(BANNER_ID);
    if (existing && existing.dataset.alertId === alert.id) return;
    if (existing) existing.remove();

    var bg = categoryColors[alert.category] || categoryColors.general;
    var div = document.createElement("div");
    div.id = BANNER_ID;
    div.dataset.alertId = alert.id;
    div.style.backgroundColor = bg;

    if (alert.category === "emergency") {
      div.style.animation = "quarryBannerSlide 0.3s ease-out, quarryPulse 2s infinite 0.3s";
      var pulseRule = "@keyframes quarryPulse { 0%,100%{opacity:1} 50%{opacity:0.85} }";
      var styleEl = document.getElementById(STYLE_ID);
      if (styleEl && styleEl.textContent.indexOf("quarryPulse") === -1) {
        styleEl.textContent += pulseRule;
      }
    }

    var cat = document.createElement("span");
    cat.className = "quarry-banner-cat";
    cat.textContent = alert.category.replace("_", " ") + " ALERT";

    var subj = document.createElement("span");
    subj.className = "quarry-banner-subject";
    subj.textContent = alert.subject;

    div.appendChild(cat);
    div.appendChild(subj);

    if (alert.body_text) {
      var body = document.createElement("span");
      body.className = "quarry-banner-body";
      body.textContent = alert.body_text.substring(0, 200);
      div.appendChild(body);
    }

    var close = document.createElement("button");
    close.className = "quarry-banner-close";
    close.textContent = "\u00d7";
    close.setAttribute("aria-label", "Dismiss banner");
    close.onclick = function () { div.remove(); };
    div.appendChild(close);

    document.body.appendChild(div);
  }

  function hideBanner() {
    var el = document.getElementById(BANNER_ID);
    if (el) el.remove();
  }

  var lastAlertId = null;

  function poll() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", baseUrl + "/api/alerts/active", true);
    xhr.timeout = 10000;
    xhr.onload = function () {
      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          if (data && data.id && data.status === "active") {
            lastAlertId = data.id;
            showBanner(data);
          } else {
            lastAlertId = null;
            hideBanner();
          }
        } catch (e) {
          hideBanner();
        }
      }
    };
    xhr.onerror = function () {};
    xhr.send();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      poll();
      setInterval(poll, pollMs);
    });
  } else {
    poll();
    setInterval(poll, pollMs);
  }
})();
