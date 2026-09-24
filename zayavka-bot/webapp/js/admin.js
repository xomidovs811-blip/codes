// Logic for admin.html - "Foydalanuvchilar va Ruxsatlar" (simple version):
// one list of users, each showing who they are (name, phone/username, the
// Telegram channel/person they submit as) and a flat set of permission
// checkboxes right on the card - no separate matrix pages or side panels.
// Users are added by PHONE NUMBER (they confirm it in the bot).

const ICONS = {
  user: '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  check: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  edit: '<path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  power: '<path d="M18.36 6.64a9 9 0 1 1-12.73 0"/><line x1="12" y1="2" x2="12" y2="12"/>',
  hash: '<line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/>',
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
  send: '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>',
  userplus: '<path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/>',
  left: '<polyline points="15 18 9 12 15 6"/>',
  right: '<polyline points="9 18 15 12 9 6"/>',
};
const icon = (name, cls = "") =>
  `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;

const PERM_ICON = {
  can_view: "eye", can_view_others: "users", can_view_all_objects: "layers", can_create: "plus",
  can_edit: "edit", can_delete: "trash", can_export: "download", can_report: "send",
  can_manage_lists: "list", can_manage_users: "userplus",
};
// Short checkbox labels (the full explanation is the title= tooltip, from the server's catalog).
const PERM_SHORT = {
  can_view: "O'qish", can_view_others: "Boshqalarniki", can_view_all_objects: "Barcha obyektlar",
  can_create: "To'ldirish", can_edit: "Tahrirlash", can_delete: "O'chirish", can_export: "Fayl yuklash",
  can_report: "Hisobot", can_manage_lists: "Ro'yxatlar", can_manage_users: "Foydalanuvchi qo'shish",
};

const STATUS = {
  approved: { label: "Aktiv", cls: "st-ok" },
  pending: { label: "Kutmoqda", cls: "st-wait" },
  invited: { label: "Taklif qilingan", cls: "st-inv" },
  blocked: { label: "Nofaol", cls: "st-off" },
};
const SOURCE = { channel: "Kanal a'zosi", admin: "Admin qo'shgan", request: "So'rov yuborgan" };
const ROLE_LABEL = { owner: "Bosh administrator", admin: "Administrator", user: "Foydalanuvchi" };

const PAGE_SIZE = 10;

const S = {
  users: [], owners: [], persons: [], objects: [], catalog: [], defaults: {},
  me: { is_admin: false, is_owner: false, persons: [], objects: [], perms: {} },
  counts: { pending: 0, approved: 0, blocked: 0, invited: 0, admins: 0 },
  q: "", role: "", status: "", page: 1,
};
// Card ids whose persons/objects chip editor is expanded (collapsed by default - keeps the list short).
const OPEN_PERSONS = new Set();
const OPEN_OBJECTS = new Set();
// The "add a user" form while its dialog is open.
const ADD = { role: "user", persons: new Set(), objects: new Set(), perms: {} };

const $ = (id) => document.getElementById(id);
const isWide = () => document.body.classList.contains("force-desktop");

function errText(e) {
  let msg = e.message;
  try { msg = JSON.parse(msg); } catch (_) { /* plain text */ }
  return typeof msg === "string" ? msg : JSON.stringify(msg);
}

function initials(name) {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

function avatar(u) {
  const key = Math.abs(Number(u.telegram_id || String(u.phone || "0").slice(-6) || 0)) % 6;
  return `<span class="am-av av${key}">${esc(initials(u.name))}</span>`;
}

const byId = (id) => S.users.find((u) => u.id === id);
const permKeys = () => S.catalog.map((p) => p.key);
const isAdminRole = (u) => u.role === "admin";

function ownerRow(o) {
  const row = {
    id: null, owner: true, telegram_id: o.telegram_id, name: o.name || "Administrator", username: o.username,
    phone: null, role: "owner", status: "approved", source: "owner", persons: [], objects: [],
    last_seen_at: o.last_seen_at, created_at: null, can_view_all_objects: true,
  };
  permKeys().forEach((k) => { row[k] = true; });
  return row;
}
const allRows = () => [...S.owners.map(ownerRow), ...S.users];

function applyData(data) {
  S.users = data.users;
  S.owners = data.owners || [];
  S.persons = data.persons;
  S.objects = data.objects || [];
  S.catalog = data.catalog || [];
  S.defaults = data.defaults || {};
  S.me = data.me;
  S.counts = data.counts;
  S.users.forEach((u) => {
    if (u.status === "pending" && !(u.persons || []).length && u.requested_person) {
      u.persons = [u.requested_person];
    }
  });
}

const canGrant = (key) => S.me.is_admin || (key !== "can_manage_users" && !!S.me.perms[key]);
const canTouch = (u) => !u.owner && (S.me.is_admin || !(isAdminRole(u) || u.can_manage_users));
const isSelf = (u) => u.telegram_id != null && u.telegram_id === S.me.user_id;

// ---------------------------------------------------------------- rendering

function statusBadge(u) {
  const st = STATUS[u.status] || { label: u.status, cls: "" };
  return `<span class="am-st ${st.cls}">${st.label}</span>`;
}
function roleBadge(u) {
  const key = u.role === "owner" ? "owner" : isAdminRole(u) ? "admin" : "user";
  return `<span class="am-role role-${key}">${ROLE_LABEL[key]}</span>`;
}

function chipsHtml(names, selectedSet, kind, uid, disabled, allowed) {
  return names.map((n) => {
    const on = selectedSet.has(n);
    const dis = disabled || (!on && allowed && !allowed(n));
    return `<label class="am-chip ${on ? "on" : ""} ${dis ? "dis" : ""}">
      <input type="checkbox" data-kind="${kind}" data-uid="${uid}" data-name="${esc(n)}" ${on ? "checked" : ""} ${dis ? "disabled" : ""} />${esc(n)}</label>`;
  }).join("");
}

function permCheckboxesHtml(u, disabled) {
  return S.catalog.map((p) => {
    const on = !!u[p.key];
    const dis = disabled || (!on && !canGrant(p.key)) || (p.key === "can_manage_users" && !S.me.is_admin);
    return `<label class="am-cb ${dis ? "dis" : ""}" title="${esc(p.desc)}">
      <input type="checkbox" data-kind="perm" data-uid="${u.id}" data-perm="${p.key}" ${on ? "checked" : ""} ${dis ? "disabled" : ""} />
      ${icon(PERM_ICON[p.key] || "check")}<span>${esc(PERM_SHORT[p.key] || p.label)}</span>
    </label>`;
  }).join("");
}

function roleSegHtml(role, kind, uid, disabled) {
  return `<div class="am-seg ${disabled ? "dis" : ""}">
    <button type="button" class="${role === "user" ? "on" : ""}" data-act="${kind}" data-uid="${uid}" data-role="user" ${disabled ? "disabled" : ""}>${icon("user")}Foydalanuvchi</button>
    <button type="button" class="${role === "admin" ? "on" : ""}" data-act="${kind}" data-uid="${uid}" data-role="admin" ${disabled ? "disabled" : ""}>${icon("shield")}Administrator</button>
  </div>`;
}

function identityLine(u) {
  const bits = [];
  bits.push(u.phone ? `${icon("phone", "inl")}${esc(fmtPhone(u.phone))}` : (u.username ? `@${esc(u.username)}` : `ID ${u.telegram_id ?? "—"}`));
  return bits.join(" · ");
}

function userCardHtml(u) {
  const admin = isAdminRole(u) || u.role === "owner";
  const blocked = u.status === "blocked";
  const touch = canTouch(u);
  const locked = blocked || !touch;
  const personsOpen = OPEN_PERSONS.has(u.id) || u.status === "pending";
  const objectsOpen = OPEN_OBJECTS.has(u.id);
  const personAllowed = (n) => S.me.is_admin || (S.me.persons || []).includes(n);
  const objectAllowed = (n) => S.me.is_admin || (S.me.objects || []).includes(n);

  let actions = "";
  if (touch && !isSelf(u)) {
    if (u.status === "pending") {
      actions = `
        <button type="button" class="am-btn am-btn-primary sm" data-act="approve" data-uid="${u.id}">${icon("check")}Tasdiqlash</button>
        <button type="button" class="am-btn am-btn-danger sm" data-act="block" data-uid="${u.id}">${icon("x")}Rad etish</button>`;
    } else if (u.status === "approved") {
      actions = `<button type="button" class="am-btn am-btn-warn sm" data-act="block" data-uid="${u.id}">${icon("power")}Nofaol qilish</button>`;
    } else if (u.status === "invited") {
      actions = `<span class="am-muted">Foydalanuvchi telefonini tasdiqlashi kutilmoqda</span>`;
    } else {
      actions = `<button type="button" class="am-btn am-btn-primary sm" data-act="unblock" data-uid="${u.id}">${icon("power")}Aktiv qilish</button>`;
    }
    if (u.source !== "channel") {
      actions += `<button type="button" class="am-btn am-btn-danger sm" data-act="delete" data-uid="${u.id}">${icon("trash")}${u.status === "invited" ? "Bekor qilish" : "O'chirish"}</button>`;
    }
  }

  const personsBlock = admin ? `<div class="am-idline">${icon("users", "inl")}Barcha shaxslar (kanallar)</div>` : `
    <div class="am-persons">
      <button type="button" class="am-idline am-linklike" data-act="toggle-persons" data-uid="${u.id}">
        ${icon("users", "inl")}${u.persons.length ? esc(u.persons.join(", ")) : "Hech qaysi shaxs/kanalga bog'lanmagan"}
        ${!locked ? icon("edit", "inl edit-hint") : ""}
      </button>
      ${personsOpen && !locked ? `<div class="am-chips">${chipsHtml(S.persons, new Set(u.persons), "person", u.id, locked, personAllowed)}</div>` : ""}
    </div>`;

  const objectsBlock = admin || u.can_view_all_objects ? "" : `
    <div class="am-objects">
      <button type="button" class="am-idline am-linklike" data-act="toggle-objects" data-uid="${u.id}">
        ${icon("layers", "inl")}Obyektlar: ${u.objects.length ? esc(u.objects.join(", ")) : "tanlanmagan"}
        ${!locked ? icon("edit", "inl edit-hint") : ""}
      </button>
      ${objectsOpen && !locked ? `<div class="am-chips">${chipsHtml(S.objects, new Set(u.objects), "object", u.id, locked, objectAllowed)}</div>` : ""}
    </div>`;

  return `
    <div class="am-card am-ucard ${blocked ? "is-blocked" : ""}" data-uid="${u.id ?? ""}">
      <div class="am-uhead">
        ${avatar(u)}
        <div class="am-uinfo">
          <div class="am-uname-row"><b>${esc(u.name || "Nomsiz")}</b>${roleBadge(u)}${statusBadge(u)}</div>
          <div class="am-idline">${identityLine(u)}</div>
        </div>
        ${u.owner ? `<span class="am-lock" title="O'zgartirilmaydi (.env)">${icon("shield")}</span>` : ""}
      </div>

      ${!u.owner ? `<div class="am-urole">${roleSegHtml(u.role, "set-role", u.id, !S.me.is_admin || isSelf(u) || locked)}</div>` : ""}

      ${personsBlock}
      ${objectsBlock}

      ${admin
        ? `<p class="am-admin-note">Administrator: barcha shaxslar, obyektlar va zayavkalarni ko'radi, hamma amallarni bajaradi.</p>`
        : `<div class="am-perms">${permCheckboxesHtml(u, locked)}</div>`}

      ${actions ? `<div class="am-uactions">${actions}</div>` : ""}
    </div>`;
}

function filteredRows() {
  const q = S.q.trim().toLowerCase();
  const qDigits = q.replace(/\D/g, "");
  return allRows().filter((u) => {
    const roleKey = u.role === "owner" ? "owner" : isAdminRole(u) ? "admin" : "user";
    if (S.role && roleKey !== S.role) return false;
    if (S.status && u.status !== S.status) return false;
    if (!q) return true;
    const hay = [u.name, u.username, String(u.telegram_id || ""), ...(u.persons || [])].join(" ").toLowerCase();
    return hay.includes(q) || (qDigits.length >= 3 && (u.phone || "").includes(qDigits));
  });
}

function renderRequests() {
  const list = S.users.filter((u) => u.status === "pending");
  const sec = $("secRequests");
  if (!list.length) { sec.innerHTML = ""; sec.style.display = "none"; return; }
  sec.style.display = "";
  sec.innerHTML = `
    <div class="am-sec-title">${icon("clock")}Kirish so'rovlari <span class="am-badge">${list.length}</span></div>
    <div class="am-reqs">${list.map((u) => `
      <div class="am-card am-req" data-uid="${u.id}">
        <div class="am-uhead">${avatar(u)}<div class="am-uinfo">
          <div class="am-uname-row"><b>${esc(u.name || "Nomsiz")}</b></div>
          <div class="am-idline">${identityLine(u)} · ${esc(fmtSentAt(u.created_at))}</div></div></div>
        <div class="am-req-body">
          <div><span class="am-muted">So'ralgan shaxs/kanal:</span> <b>${esc(u.requested_person || "—")}</b></div>
          ${u.note ? `<div class="am-note">${esc(u.note)}</div>` : ""}
        </div>
        <div class="am-uactions">
          <button type="button" class="am-btn am-btn-primary sm" data-act="approve" data-uid="${u.id}">${icon("check")}Tasdiqlash</button>
          <button type="button" class="am-btn am-btn-danger sm" data-act="block" data-uid="${u.id}">${icon("x")}Rad etish</button>
        </div>
      </div>`).join("")}</div>`;
}

// An already-approved (or blocked) user who joined ANOTHER person's channel
// shows up here instead of either silently gaining that person or being
// silently blocked (see flag_person_request in app/access.py) - one tap adds
// it to what they already have, without touching their existing access.
function extraRequests() {
  return S.users.filter((u) => u.status !== "pending" && u.requested_person && !(u.persons || []).includes(u.requested_person));
}

function renderExtraRequests() {
  const list = extraRequests();
  const sec = $("secExtraRequests");
  if (!list.length) { sec.innerHTML = ""; sec.style.display = "none"; return; }
  sec.style.display = "";
  sec.innerHTML = `
    <div class="am-sec-title">${icon("userplus")}Qo'shimcha shaxs so'rovlari <span class="am-badge">${list.length}</span></div>
    <div class="am-reqs">${list.map((u) => `
      <div class="am-card am-req" data-uid="${u.id}">
        <div class="am-uhead">${avatar(u)}<div class="am-uinfo">
          <div class="am-uname-row"><b>${esc(u.name || "Nomsiz")}</b>${statusBadge(u)}</div>
          <div class="am-idline">${identityLine(u)}</div></div></div>
        <div class="am-req-body">
          <div><span class="am-muted">Hozirgi shaxs(lar):</span> <b>${u.persons.length ? esc(u.persons.join(", ")) : "—"}</b></div>
          <div><span class="am-muted">Yana shu kanalga a'zo bo'lgan:</span> <b>${esc(u.requested_person)}</b></div>
        </div>
        <div class="am-uactions">
          <button type="button" class="am-btn am-btn-primary sm" data-act="approve-extra" data-uid="${u.id}">${icon("check")}"${esc(u.requested_person)}" ni qo'shish</button>
        </div>
      </div>`).join("")}</div>`;
}

function renderList() {
  const list = filteredRows();
  const pages = Math.max(1, Math.ceil(list.length / PAGE_SIZE));
  if (S.page > pages) S.page = pages;
  const from = (S.page - 1) * PAGE_SIZE;
  const rows = list.slice(from, from + PAGE_SIZE);

  $("userList").innerHTML = rows.length
    ? rows.map(userCardHtml).join("")
    : `<div class="am-card am-empty">Foydalanuvchi topilmadi</div>`;

  const nums = [];
  for (let i = 1; i <= pages; i++) nums.push(i);
  $("amPager").innerHTML = pages <= 1 ? "" : `
    <span class="am-muted">${from + 1}–${Math.min(from + rows.length, list.length)} / ${list.length} ta</span>
    <div class="am-pages">
      <button type="button" class="am-pg" data-act="page" data-page="${S.page - 1}" ${S.page <= 1 ? "disabled" : ""}>${icon("left")}</button>
      ${nums.map((n) => `<button type="button" class="am-pg ${n === S.page ? "on" : ""}" data-act="page" data-page="${n}">${n}</button>`).join("")}
      <button type="button" class="am-pg" data-act="page" data-page="${S.page + 1}" ${S.page >= pages ? "disabled" : ""}>${icon("right")}</button>
    </div>`;
}

function renderStatus() {
  const c = S.counts;
  const extra = extraRequests().length;
  $("amStatus").textContent =
    `${S.users.length + S.owners.length} ta foydalanuvchi · ${c.approved + S.owners.length} aktiv` +
    (c.pending ? ` · ${c.pending} so'rov kutmoqda` : "") +
    (extra ? ` · ${extra} qo'shimcha so'rov` : "") +
    (c.admins ? ` · ${c.admins} administrator` : "");
}

function renderAll() {
  $("am").classList.toggle("am-wide", isWide());
  renderStatus();
  renderRequests();
  renderExtraRequests();
  renderList();
}

function permGroupsHtmlForAdd() {
  return S.catalog.map((p) => {
    const on = !!ADD.perms[p.key];
    const dis = (!on && !canGrant(p.key)) || (p.key === "can_manage_users" && !S.me.is_admin);
    return `<label class="am-cb ${dis ? "dis" : ""}" title="${esc(p.desc)}">
      <input type="checkbox" data-kind="add-perm" data-perm="${p.key}" ${on ? "checked" : ""} ${dis ? "disabled" : ""} />
      ${icon(PERM_ICON[p.key] || "check")}<span>${esc(PERM_SHORT[p.key] || p.label)}</span>
    </label>`;
  }).join("");
}

function renderAddModal() {
  const admin = ADD.role === "admin";
  if (!Object.keys(ADD.perms).length) {
    permKeys().forEach((k) => { ADD.perms[k] = !!S.defaults[k] && canGrant(k); });
  }
  const personAllowed = (n) => S.me.is_admin || (S.me.persons || []).includes(n);
  const objectAllowed = (n) => S.me.is_admin || (S.me.objects || []).includes(n);
  $("addModal").innerHTML = `
    <button type="button" class="modal-close" data-act="close-add">${icon("x")}</button>
    <h2 style="margin-top:0;">Yangi foydalanuvchi</h2>
    <p class="hint">Telefon raqamini yozing. Foydalanuvchi botga kirib <b>/start</b> bosadi va
      <b>"📱 Telefon raqamimni yuborish"</b> tugmasini bosadi - raqam mos kelsa, u avtomatik ulanadi va quyidagi ruxsatlar beriladi.</p>
    <div class="field"><label>Telefon raqami</label>
      <input type="tel" id="addPhone" inputmode="tel" placeholder="+998 90 123 45 67" autocomplete="off" /></div>
    <div class="field"><label>Ismi (ixtiyoriy)</label><input type="text" id="addName" placeholder="Ism Familiya" /></div>
    ${S.me.is_admin ? `<div class="am-sec">Rol</div>${roleSegHtml(ADD.role, "add-role", "", false)}` : ""}
    ${admin ? `<p class="am-foot">Administrator hamma narsani ko'radi va hamma amallarni bajara oladi.</p>` : `
      <div class="am-sec">Qaysi shaxs(lar)/kanal(lar) nomidan ishlaydi</div>
      <div class="am-chips">${chipsHtml(S.persons, ADD.persons, "add-person", "", false, personAllowed)}</div>
      ${!ADD.perms.can_view_all_objects ? `
      <div class="am-sec">Qurilish obyektlari</div>
      <div class="am-chips">${chipsHtml(S.objects, ADD.objects, "add-object", "", false, objectAllowed)}</div>` : ""}
      <div class="am-sec">Ruxsatlar</div>
      <div class="am-perms">${permGroupsHtmlForAdd()}</div>`}
    <button type="button" class="am-btn am-btn-primary am-block" data-act="add-submit">${icon("plus")}Qo'shish</button>`;
}

// ------------------------------------------------------------------ actions

function needsSecondTap(btn, text) {
  if (btn.dataset.armed) return false;
  btn.dataset.armed = "1";
  const original = btn.innerHTML;
  btn.textContent = text;
  btn.classList.add("armed");
  setTimeout(() => {
    if (!btn.isConnected) return;
    delete btn.dataset.armed;
    btn.classList.remove("armed");
    btn.innerHTML = original;
  }, 3500);
  return true;
}

async function call(promise, okText) {
  try {
    applyData(await promise);
    if (okText) showToast(okText);
    return true;
  } catch (e) {
    showToast("Xatolik: " + errText(e), true);
    return false;
  }
}

async function onFieldToggle(input) {
  const uid = Number(input.dataset.uid);
  const u = byId(uid);
  if (!u) return;
  const kind = input.dataset.kind;
  input.closest("label").classList.toggle("on", input.checked);

  const patch = {};
  if (kind === "person" || kind === "object") {
    const field = kind === "person" ? "persons" : "objects";
    const universe = kind === "person" ? S.persons : S.objects;
    const set = new Set(u[field] || []);
    if (input.checked) set.add(input.dataset.name); else set.delete(input.dataset.name);
    u[field] = universe.filter((n) => set.has(n));
    patch[field] = u[field];
  } else if (kind === "perm") {
    u[input.dataset.perm] = input.checked;
    patch[input.dataset.perm] = input.checked;
  }
  if (u.status === "pending" || u.status === "blocked") { renderList(); return; }

  if (await call(apiPatch(`/api/admin/users/${uid}`, patch), "💾 Saqlandi")) {
    renderStatus();
    renderList();
  } else {
    await reload();
  }
}

async function setRole(uid, role) {
  const u = byId(uid);
  if (!u || u.role === role) return;
  if (u.status === "pending" || u.status === "blocked") { u.role = role; renderList(); return; }
  if (await call(apiPatch(`/api/admin/users/${uid}`, { role }), role === "admin" ? "🛡️ Administrator qilindi" : "Foydalanuvchi qilindi")) {
    renderAll();
  }
}

async function userAction(act, btn) {
  const uid = Number(btn.dataset.uid);
  const u = byId(uid);
  if (!u) return;

  if (act === "block" && u.status === "approved" && needsSecondTap(btn, "Ha, nofaol qilinsin")) return;
  if (act === "delete" && needsSecondTap(btn, u.status === "invited" ? "Ha, bekor qilinsin" : "Ha, o'chirilsin")) return;

  let request;
  let ok;
  if (act === "approve") {
    const persons = (u.persons || []).length ? u.persons : (u.requested_person ? [u.requested_person] : []);
    if (!persons.length && !isAdminRole(u)) {
      showToast("Avval kamida bitta shaxs/kanalni tanlang", true);
      OPEN_PERSONS.add(uid);
      renderList();
      return;
    }
    request = apiPost(`/api/admin/users/${uid}/approve`, {
      persons, objects: u.objects || [], role: u.role,
      ...Object.fromEntries(permKeys().map((k) => [k, !!u[k]])),
    });
    ok = "✅ Tasdiqlandi";
  } else if (act === "block") {
    request = apiPost(`/api/admin/users/${uid}/block`, {});
    ok = u.status === "pending" ? "❌ Rad etildi" : "🚫 Nofaol qilindi";
  } else if (act === "unblock") {
    request = apiPost(`/api/admin/users/${uid}/unblock`, {});
    ok = "♻️ Aktiv qilindi";
  } else {
    request = apiDelete(`/api/admin/users/${uid}`);
    ok = "🗑️ O'chirildi";
  }
  btn.disabled = true;
  if (await call(request, ok)) {
    renderAll();
  } else {
    btn.disabled = false;
  }
}

async function submitAdd(btn) {
  const phone = $("addPhone").value.trim();
  if (phone.replace(/\D/g, "").length < 9) { showToast("Telefon raqamini to'g'ri kiriting", true); return; }
  const admin = ADD.role === "admin";
  if (!admin && !ADD.persons.size) { showToast("Kamida bitta shaxs/kanalni tanlang", true); return; }
  btn.disabled = true;
  const body = { phone, name: $("addName").value.trim(), role: ADD.role };
  if (!admin) {
    body.persons = S.persons.filter((p) => ADD.persons.has(p));
    body.objects = S.objects.filter((o) => ADD.objects.has(o));
    Object.assign(body, ADD.perms);
  }
  const ok = await call(apiPost("/api/admin/users", body), "✅ Qo'shildi - endi u botda raqamini tasdiqlashi kerak");
  btn.disabled = false;
  if (!ok) return;
  $("addBackdrop").classList.remove("show");
  Object.assign(ADD, { role: "user", persons: new Set(), objects: new Set(), perms: {} });
  S.q = ""; S.role = ""; S.status = ""; S.page = 1;
  const search = $("amSearch"); if (search) search.value = "";
  renderAll();
}

async function reload() {
  applyData(await apiGet("/api/admin/users"));
  renderAll();
}

// ------------------------------------------------------------------- events

function onClick(e) {
  const target = e.target.closest("[data-act]");
  if (!target) {
    if (e.target === $("addBackdrop")) $("addBackdrop").classList.remove("show");
    return;
  }
  const act = target.dataset.act;
  if (act === "toggle-persons") {
    const uid = Number(target.dataset.uid);
    OPEN_PERSONS.has(uid) ? OPEN_PERSONS.delete(uid) : OPEN_PERSONS.add(uid);
    renderList();
    return;
  }
  if (act === "toggle-objects") {
    const uid = Number(target.dataset.uid);
    OPEN_OBJECTS.has(uid) ? OPEN_OBJECTS.delete(uid) : OPEN_OBJECTS.add(uid);
    renderList();
    return;
  }
  if (act === "page") { S.page = Number(target.dataset.page); renderList(); return; }
  if (act === "set-role") { setRole(Number(target.dataset.uid), target.dataset.role); return; }
  if (act === "add-role") { ADD.role = target.dataset.role; renderAddModal(); return; }
  if (act === "open-add") { renderAddModal(); $("addBackdrop").classList.add("show"); return; }
  if (act === "close-add") { $("addBackdrop").classList.remove("show"); return; }
  if (act === "add-submit") { submitAdd(target); return; }
  if (act === "approve-extra") {
    const uid = Number(target.dataset.uid);
    const u = byId(uid);
    if (!u) return;
    const persons = [...new Set([...(u.persons || []), u.requested_person])];
    target.disabled = true;
    call(apiPatch(`/api/admin/users/${uid}`, { persons }), `✅ "${u.requested_person}" qo'shildi`).then((ok) => {
      if (ok) renderAll(); else target.disabled = false;
    });
    return;
  }
  if (["approve", "block", "unblock", "delete"].includes(act)) { userAction(act, target); return; }
}

function onChange(e) {
  const input = e.target;
  if (input.id === "amRoleSel") { S.role = input.value; S.page = 1; renderList(); return; }
  if (input.id === "amStatusSel") { S.status = input.value; S.page = 1; renderList(); return; }
  const kind = input.dataset.kind;
  if (kind === "person" || kind === "object" || kind === "perm") { onFieldToggle(input); return; }
  if (kind === "add-person" || kind === "add-object") {
    const set = kind === "add-person" ? ADD.persons : ADD.objects;
    if (input.checked) set.add(input.dataset.name); else set.delete(input.dataset.name);
    input.closest("label").classList.toggle("on", input.checked);
  } else if (kind === "add-perm") {
    ADD.perms[input.dataset.perm] = input.checked;
    if (input.dataset.perm === "can_view_all_objects") {
      const phone = $("addPhone").value, name = $("addName").value;
      renderAddModal();
      $("addPhone").value = phone; $("addName").value = name;
    }
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  setupViewToggle();
  setupNavButtons();

  $("amBrandIc").innerHTML = icon("shield");
  $("amSearchBox").innerHTML = `${icon("search")}<input class="am-in" id="amSearch" type="search" placeholder="Ism, telefon yoki shaxs/kanal bo'yicha qidirish..." />`;
  document.querySelector(".am-add").innerHTML = `${icon("plus")}<span>Yangi foydalanuvchi</span>`;
  ["", ...Object.keys(ROLE_LABEL).filter((k) => k !== "owner")].forEach((k) => {
    if (!k) return;
    $("amRoleSel").insertAdjacentHTML("beforeend", `<option value="${k}">${ROLE_LABEL[k]}</option>`);
  });
  [["approved", "Aktiv"], ["pending", "Kutmoqda"], ["invited", "Taklif qilingan"], ["blocked", "Nofaol"]].forEach(([v, l]) => {
    $("amStatusSel").insertAdjacentHTML("beforeend", `<option value="${v}">${l}</option>`);
  });

  const root = $("am");
  root.addEventListener("click", onClick);
  root.addEventListener("change", onChange);
  root.addEventListener("input", (e) => {
    if (e.target.id === "amSearch") { S.q = e.target.value; S.page = 1; renderList(); }
  });
  ["viewDesktopBtn", "viewMobileBtn"].forEach((id) => $(id).addEventListener("click", () => {
    root.classList.toggle("am-wide", isWide());
    renderList();
  }));

  const status = $("amStatus");
  try {
    applyData(await apiGet("/api/admin/users"));
  } catch (e) {
    status.textContent = "⛔ " + errText(e);
    return;
  }
  $("amBody").style.display = "";
  renderAll();
});
