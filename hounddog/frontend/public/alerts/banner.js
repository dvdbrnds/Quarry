/**
 * Quarry Alert Banner — embeddable script
 *
 * Polls the Quarry active alert endpoint and injects a dismissible banner
 * at the top of the page when an alert is active. Zero dependencies.
 *
 * Usage:
 *   <script src="https://quarry.moravian.edu/alerts/banner.js"></script>
 *
 * The script reads its own src attribute to determine the Quarry base URL.
 */
(function () {
  "use strict";

  var POLL_INTERVAL = 30000;
  var BANNER_ID = "quarry-alert-banner";

  var baseUrl = (function () {
    var scripts = document.getElementsByTagName("script");
    for (var i = scripts.length - 1; i >= 0; i--) {
      var src = scripts[i].getAttribute("src") || "";
      if (src.indexOf("/alerts/banner.js") !== -1) {
        return src.replace(/\/alerts\/banner\.js.*$/, "");
      }
    }
    return "";
  })();

  if (!baseUrl) {
    console.warn("[Quarry Banner] Could not determine base URL from script src");
    return;
  }

  var CATEGORY_COLORS = {
    emergency: "#dc2626",
    weather: "#0284c7",
    campus_closing: "#d97706",
    parking: "#4f46e5",
    general: "#4b5563",
  };

  var dismissed = null;

  function createBanner(alert) {
    var existing = document.getElementById(BANNER_ID);
    if (existing) existing.remove();

    if (dismissed === alert.id) return;

    var bg = CATEGORY_COLORS[alert.category] || CATEGORY_COLORS.general;

    var banner = document.createElement("div");
    banner.id = BANNER_ID;
    banner.setAttribute("role", "alert");
    banner.style.cssText =
      "position:fixed;top:0;left:0;right:0;z-index:999999;padding:12px 20px;" +
      "font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;" +
      "font-size:14px;color:#fff;display:flex;align-items:center;gap:12px;" +
      "background:" + bg + ";box-shadow:0 2px 8px rgba(0,0,0,0.2);";

    var category = document.createElement("span");
    category.style.cssText =
      "font-weight:700;text-transform:uppercase;font-size:11px;letter-spacing:1px;opacity:0.9;";
    category.textContent = alert.category.replace(/_/g, " ");

    var text = document.createElement("span");
    text.style.cssText = "flex:1;font-weight:600;";
    text.textContent = alert.subject;

    var close = document.createElement("button");
    close.style.cssText =
      "background:rgba(255,255,255,0.2);border:none;color:#fff;cursor:pointer;" +
      "padding:4px 10px;border-radius:4px;font-size:12px;";
    close.textContent = "Dismiss";
    close.onclick = function () {
      dismissed = alert.id;
      banner.remove();
    };

    banner.appendChild(category);
    banner.appendChild(text);
    banner.appendChild(close);
    document.body.appendChild(banner);
  }

  function removeBanner() {
    var existing = document.getElementById(BANNER_ID);
    if (existing) existing.remove();
  }

  function poll() {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", baseUrl + "/api/alerts/active", true);
    xhr.timeout = 10000;
    xhr.onload = function () {
      if (xhr.status === 200) {
        try {
          var data = JSON.parse(xhr.responseText);
          if (data && data.id && data.status === "active") {
            createBanner(data);
          } else {
            removeBanner();
            dismissed = null;
          }
        } catch (e) {
          removeBanner();
        }
      } else {
        removeBanner();
      }
    };
    xhr.onerror = function () {};
    xhr.send();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      poll();
      setInterval(poll, POLL_INTERVAL);
    });
  } else {
    poll();
    setInterval(poll, POLL_INTERVAL);
  }
})();
