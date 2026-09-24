// Shared helpers used by index.html / table.html / search.html

const tg = window.Telegram ? window.Telegram.WebApp : null;
if (tg) {
  tg.ready();
  tg.expand();
}

// Same-origin API (FastAPI serves both the API and these static files).
const API_BASE = "";

function getInitData() {
  return tg ? tg.initData || "" : "";
}

/**
 * PC/Mobile view toggle (top-right of the header, buttons #viewDesktopBtn /
 * #viewMobileBtn). Auto-picks a starting mode from the real screen width,
 * but the user can override it either way. Remembered in localStorage per
 * device. Shared by every page that renders the toggle (items.html,
 * table.html) so they all behave identically.
 *
 * "🖥️" also requests true fullscreen (Bot API 8.0's requestFullscreen(),
 * not the expand() already called on load, which only maximizes height
 * inside Telegram Desktop's small windowed popup - without it the wide
 * desktop layout needs scrolling in every direction to see anything).
 * "📱" exits fullscreen if it was on, to go back to the normal small popup.
 */
function applyViewMode(mode) {
  document.body.classList.remove("force-desktop", "force-mobile");
  document.body.classList.add(mode === "desktop" ? "force-desktop" : "force-mobile");
  document.getElementById("viewDesktopBtn").classList.toggle("active", mode === "desktop");
  document.getElementById("viewMobileBtn").classList.toggle("active", mode === "mobile");
  try {
    localStorage.setItem("zayavka_view_mode", mode);
  } catch (e) {
    // localStorage can be unavailable in some WebViews - view still works, just isn't remembered.
  }

  if (tg) {
    if (mode === "desktop") {
      const supported = typeof tg.requestFullscreen === "function"
        && (typeof tg.isVersionAtLeast !== "function" || tg.isVersionAtLeast("8.0"));
      if (supported) {
        try {
          tg.requestFullscreen();
        } catch (e) {
          showToast("Fullscreen so'rovi rad etildi: " + e.message, true);
        }
      } else {
        showToast("Telegram versiyasi eski - fullscreen qo'llab-quvvatlanmaydi. Telegramni yangilang.", true);
      }
    } else if (mode === "mobile" && tg.isFullscreen && typeof tg.exitFullscreen === "function") {
      try { tg.exitFullscreen(); } catch (e) { /* ignore */ }
    }
  }
}

function setupViewToggle() {
  let saved = null;
  try {
    saved = localStorage.getItem("zayavka_view_mode");
  } catch (e) {
    // ignore
  }
  const initial = saved || (window.innerWidth <= 700 ? "mobile" : "desktop");
  applyViewMode(initial);

  document.getElementById("viewDesktopBtn").addEventListener("click", () => applyViewMode("desktop"));
  document.getElementById("viewMobileBtn").addEventListener("click", () => applyViewMode("mobile"));

  if (tg && typeof tg.onEvent === "function") {
    tg.onEvent("fullscreenFailed", (e) => {
      showToast("Fullscreen ishlamadi: " + (e && e.error ? e.error : "noma'lum xato"), true);
    });
  }
}

/**
 * Every API call carries Telegram's signed identity (initData) in a header.
 * The server uses it to decide what this user may see and change - it never
 * trusts anything else the page sends - so outside Telegram the data routes
 * simply answer 401.
 */
async function apiRequest(method, path, body) {
  const headers = {};
  const initData = getInitData();
  if (initData) headers["X-Telegram-Init-Data"] = initData;
  const options = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const res = await fetch(API_BASE + path, options);
  if (!res.ok) {
    let detail = `${method} ${path} failed: ${res.status}`;
    try {
      const err = await res.json();
      if (err && err.detail) detail = typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail);
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

const apiGet = (path) => apiRequest("GET", path);
const apiPost = (path, body) => apiRequest("POST", path, body === undefined ? {} : body);
const apiPut = (path, body) => apiRequest("PUT", path, body);
const apiDelete = (path) => apiRequest("DELETE", path);
const apiPatch = (path, body) => apiRequest("PATCH", path, body);

/**
 * Who am I (from /api/meta's `me`), remembered for this Telegram session so any
 * page can show admin-only things right away. The ⋮ menu's "Settings" item is
 * the admin's way into the users page (admin.html); Telegram forgets that
 * button on every page load, so it is re-applied here each time.
 */
const ME_KEY = "zayavka_me";
let settingsButtonWired = false;

function rememberMe(me) {
  try { sessionStorage.setItem(ME_KEY, JSON.stringify(me || null)); } catch (e) { /* not remembered */ }
  applySettingsButton(me);
}

function cachedMe() {
  try { return JSON.parse(sessionStorage.getItem(ME_KEY) || "null"); } catch (e) { return null; }
}

function applySettingsButton(me) {
  if (!tg || !tg.SettingsButton || document.body.dataset.admin === "1") return;
  if (me && (me.is_admin || me.is_manager)) {
    if (!settingsButtonWired) {
      settingsButtonWired = true;
      tg.SettingsButton.onClick(() => { window.location.href = "admin.html?v=6"; });
    }
    tg.SettingsButton.show();
  } else {
    tg.SettingsButton.hide();
  }
}

function showToast(message, isError = false) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.className = "toast show" + (isError ? " error" : "");
  setTimeout(() => {
    el.className = "toast";
  }, 2800);
}

/**
 * Orqaga / Oldinga buttons (#navBackBtn / #navForwardBtn) - step through the
 * pages you've opened (table -> history -> a version -> ...) like a
 * browser's back/forward. Needed because in fullscreen a Mini App has no
 * browser chrome, only a close (X) button, so once you open another page
 * there'd be no way back short of closing everything.
 *
 * Also shows Telegram's own native back arrow (BackButton) on every page
 * except the table list, which is the entry point. `window.navigation`
 * (Chromium) tells us whether back/forward are actually possible so the
 * buttons can grey out; where it's missing they simply stay enabled.
 */
/**
 * `beforeLeave`: an optional `async () => boolean` guard (items.html passes
 * one to stop 30 minutes of typing from vanishing silently - see
 * setupUnsavedGuard). Every way this page's own "back" happens - the ⬅️
 * button, Telegram's native BackButton, all route through this one `goBack`,
 * so wiring the guard here covers every one of them - resolving false keeps
 * the user on the page instead of navigating away.
 */
function setupNavButtons(beforeLeave) {
  applySettingsButton(cachedMe());
  const back = document.getElementById("navBackBtn");
  const forward = document.getElementById("navForwardBtn");
  if (!back || !forward) return;

  const isRoot = document.body.dataset.root === "1";
  const nav = window.navigation;
  const can = (dir) => {
    if (nav && typeof nav.canGoBack === "boolean") {
      return dir === "back" ? nav.canGoBack : nav.canGoForward;
    }
    return true;
  };

  const goBack = async () => {
    if (beforeLeave && !(await beforeLeave())) return;
    if (can("back")) window.history.back();
    else if (!isRoot) window.location.href = "table.html";
  };

  const refresh = () => {
    back.disabled = isRoot && !can("back");
    forward.disabled = !can("forward");
  };

  back.addEventListener("click", goBack);
  forward.addEventListener("click", () => window.history.forward());
  window.addEventListener("pageshow", refresh);
  window.addEventListener("popstate", refresh);
  if (nav && typeof nav.addEventListener === "function") {
    nav.addEventListener("currententrychange", refresh);
  }
  refresh();

  if (tg && tg.BackButton && !isRoot
      && typeof tg.isVersionAtLeast === "function" && tg.isVersionAtLeast("6.1")) {
    tg.BackButton.show();
    tg.BackButton.onClick(goBack);
  }
}

// Unexpected script errors would otherwise fail silently inside Telegram's
// WebView (no console) - show them so a "nothing happens" report has a cause.
window.addEventListener("error", (e) => {
  try { showToast("Xato: " + e.message, true); } catch (_) { /* ignore */ }
});
window.addEventListener("unhandledrejection", (e) => {
  try { showToast("Xato: " + ((e.reason && e.reason.message) || e.reason), true); } catch (_) { /* ignore */ }
});

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// created_at is stored as naive UTC by the API - show it in Tashkent time.
function fmtSentAt(iso) {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("ru-RU", {
    timeZone: "Asia/Tashkent",
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/**
 * Downloads an Excel served by the API at `path` (e.g. /api/zayavka/5/excel).
 * Bot API 8.0+ has a native download prompt; older clients/plain browsers
 * fall back to opening the URL (the response is an attachment).
 */
async function downloadExcelFile(path, fileName) {
  let link;
  try {
    // path is the file's route (e.g. /api/zayavka/5/excel); its "_link" twin
    // checks this user's access and returns a short-lived signed URL.
    link = await apiPost(path + "_link", {});
  } catch (e) {
    showToast("Xatolik: " + e.message, true);
    return;
  }
  const url = `${window.location.origin}${link.url}`;
  if (tg && typeof tg.downloadFile === "function"
      && typeof tg.isVersionAtLeast === "function" && tg.isVersionAtLeast("8.0")) {
    tg.downloadFile({ url, file_name: fileName });
  } else if (tg && typeof tg.openLink === "function") {
    tg.openLink(url);
  } else {
    window.open(url, "_blank");
  }
}

/** Re-sends an Excel to the current user's own Telegram chat (POST `path`, e.g. .../send_me). */
async function sendExcelToMe(path, btn) {
  const initData = getInitData();
  if (!initData) {
    showToast("Telegram ichida oching - bu tugma faqat bot orqali ishlaydi", true);
    return;
  }
  btn.disabled = true;
  try {
    await apiPost(path, { init_data: initData });
    showToast("📨 Excel chatingizga yuborildi");
  } catch (e) {
    let msg = e.message;
    try { msg = JSON.parse(msg); } catch (_) {}
    showToast("Xatolik: " + msg, true);
  } finally {
    btn.disabled = false;
  }
}

function fmtNumber(n) {
  if (n === null || n === undefined || n === "") return "";
  const num = Number(n);
  if (Number.isNaN(num)) return "";
  return num.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}

function fmtDate(isoDate) {
  if (!isoDate) return "";
  const [y, m, d] = isoDate.split("-");
  return `${d}.${m}.${y}`;
}

// 998901234567 -> +998 90 123 45 67
function fmtPhone(digits) {
  if (!digits) return "";
  const d = String(digits);
  if (d.length === 12 && d.startsWith("998")) {
    return `+998 ${d.slice(3, 5)} ${d.slice(5, 8)} ${d.slice(8, 10)} ${d.slice(10)}`;
  }
  return "+" + d;
}

function todayIso() {
  const d = new Date();
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function renderListItemHtml(z) {
  // Light list rows carry items_count/first_product; full records carry items.
  const firstProduct = z.first_product ?? (z.items && z.items.length ? z.items[0].product_name || "" : "");
  const itemsCount = z.items_count ?? (z.items ? z.items.length : 0);
  return `
    <div class="list-item" data-id="${z.id}">
      <div class="number">${z.number}</div>
      <div class="meta">${fmtDate(z.date)} · ${z.object_name} · ${z.from_whom}</div>
      <div class="meta">${itemsCount} qator${firstProduct ? " · " + firstProduct : ""}</div>
    </div>
  `;
}

function renderZayavkaDetailHtml(z) {
  const rows = (z.items || [])
    .map(
      (i) => `
      <tr>
        <td>${i.row_no ?? ""}</td>
        <td>${i.product_name ?? ""}</td>
        <td>${i.supplier ?? ""}</td>
        <td>${i.block ?? ""}</td>
        <td>${i.floor ?? ""}</td>
        <td>${i.unit ?? ""}</td>
        <td>${fmtNumber(i.qty)}</td>
        <td>${fmtNumber(i.price)}</td>
        <td>${fmtNumber(i.total)}</td>
        <td>${fmtNumber(i.advance)}</td>
        <td>${fmtNumber(i.remainder)}</td>
        <td>${i.work_type ?? ""}</td>
        <td>${i.comment ?? ""}</td>
      </tr>`
    )
    .join("");

  const grandTotal = (z.items || []).reduce((sum, i) => sum + (i.total || 0), 0);

  return `
    <h2 style="margin-top:0">${z.number}</h2>
    <div class="field"><label>Название объекта</label><div>${z.object_name}</div></div>
    <div class="field"><label>Дата</label><div>${fmtDate(z.date)}</div></div>
    <div class="field"><label>От кого</label><div>${z.from_whom}</div></div>
    <div class="field"><label>Кому</label><div>${z.to_whom}</div></div>
    <div class="field"><label>Вид оплаты</label><div>${z.payment_type}</div></div>
    <div class="field"><label>Yuborgan</label><div>${z.created_by_name || "—"}</div></div>
    <div class="table-wrap" style="margin-top:12px;">
      <table>
        <thead>
          <tr>
            <th>т/р</th><th>Наименование товара</th><th>Поставщик</th><th>Блок</th>
            <th>Этаж</th><th>Ед.изм</th><th>Кол-во</th><th>Цена</th><th>Общая сумма</th>
            <th>Аванс получил</th><th>Остатка</th><th>Выполняемая работа</th><th>Комментарие</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <p class="hint" style="margin-top:10px;">Jami summa: <b>${fmtNumber(grandTotal)}</b></p>
    <button class="btn btn-primary btn-block" id="editZayavkaBtn" type="button"
      data-id="${z.id}" data-object="${encodeURIComponent(z.object_name)}"
      data-date="${z.date}" data-from="${encodeURIComponent(z.from_whom)}"
      data-payment="${encodeURIComponent(z.payment_type)}">✏️ Tahrirlash</button>
  `;
}
