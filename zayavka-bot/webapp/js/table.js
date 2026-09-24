// Logic for table.html — "Zayavkalar jadvali"

let allZayavka = [];
// This user's own permissions (from /api/meta); the server enforces them, this only hides buttons.
let currentMe = {
  user_id: null, can_view: true, can_view_others: false,
  can_edit: true, can_delete: true, can_export: true, can_report: true, can_create: true,
};
// Whether this user can see forms submitted by OTHER individual users (not just their
// own) - if so, the "Yuborgan" filter/column are worth showing; otherwise every row is
// theirs anyway. Set once meta loads.
let showCreator = false;
// The criteria the list on screen was actually loaded with (what the Excel export uses).
let appliedFilters = {};

function buildQuery(params) {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v) usp.set(k, v);
  });
  const s = usp.toString();
  return s ? `?${s}` : "";
}

async function loadFilterOptions() {
  const meta = await apiGet("/api/meta");
  const objSel = document.getElementById("fObject");
  const fromSel = document.getElementById("fFrom");
  meta.objects.forEach((o) => {
    const opt = document.createElement("option");
    opt.value = o;
    opt.textContent = o;
    objSel.appendChild(opt);
  });
  (meta.view_persons || meta.from_whom).forEach((f) => {
    const opt = document.createElement("option");
    opt.value = f;
    opt.textContent = f;
    fromSel.appendChild(opt);
  });
  return meta;
}

// Says whose zayavkas this list shows - a user only ever sees the persons
// whose Telegram channel they belong to (the server enforces it; this just
// tells them).
function showWhoAmI(me, allPersons) {
  const el = document.getElementById("whoami");
  const card = document.getElementById("accessCard");
  if (!me) return;
  document.getElementById("adminLink").style.display = (me.is_admin || me.is_manager) ? "" : "none";
  card.style.display = "none";
  // Someone waiting for approval (or blocked) has nothing to filter or list.
  const noAccess = me.status === "pending" || me.status === "blocked";
  document.querySelectorAll("#filtersCard, #tableCard").forEach((c) => { c.style.display = noAccess ? "none" : ""; });

  if (me.is_admin) {
    el.textContent = `👤 ${me.name} - administrator: barcha zayavkalar ko'rinadi`;
  } else if (me.status === "blocked") {
    el.textContent = "";
    showAccessCard("🚫 Kirish yopilgan", "Administrator sizning kirishingizni bekor qilgan. Kerak bo'lsa u bilan bog'laning.", false);
  } else if (me.status === "pending") {
    el.textContent = "";
    showAccessCard(
      "⏳ Kirish kerak",
      "Administrator sizni ilgari qo'shgan bo'lsa - \"Kirish\" orqali telefon raqamingizni yuboring. Birinchi marta bo'lsangiz - \"Ro'yxatdan o'tish\"ni to'ldiring, administrator tasdiqlagach kirish ochiladi.",
      true,
      allPersons || [],
    );
  } else if (!me.can_view) {
    el.textContent = `👤 ${me.name} - zayavkalarni ko'rish huquqi berilmagan`;
    document.querySelectorAll("#filtersCard, #tableCard").forEach((c) => { c.style.display = "none"; });
    showAccessCard(
      "👁️ Ko'rish huquqi yo'q",
      me.can_create
        ? "Sizga faqat zayavka to'ldirish ruxsat etilgan (botdagi \"Zayavka berish\" tugmasi). Ro'yxatni ko'rish uchun administratorga murojaat qiling."
        : "Sizga zayavkalarni ko'rish huquqi berilmagan. Administratorga murojaat qiling.",
      false,
    );
  } else if (me.persons.length || me.can_view_others) {
    const rights = [
      me.can_create ? "to'ldirish" : null,
      me.can_edit ? "tahrirlash" : null,
      me.can_delete ? "o'chirish" : null,
      me.can_export ? "fayl yuklash" : null,
      me.can_report ? "hisobot" : null,
    ].filter(Boolean);
    // Ko'rish (view) is now scoped by the INDIVIDUAL submitter (phone/Telegram ID), not
    // by person/channel - so it's told apart from "to'ldirish" (fill), which stays
    // person-scoped (me.persons: who they may file forms as).
    const scope = me.can_view_others
      ? "barcha foydalanuvchilar yuborgan zayavkalar"
      : "faqat siz yuborgan zayavkalar";
    const persons = me.persons.length ? ` · to'ldirish: ${me.persons.join(", ")}` : "";
    const objects = me.objects ? ` · obyektlar: ${me.objects.join(", ") || "yo'q"}` : "";
    el.textContent = `👤 ${me.name} - ko'rish: ${scope}${persons}${objects}` +
      ` · ruxsatlar: ${rights.length ? rights.join(", ") : "faqat ko'rish"}`;
  } else {
    el.textContent = "⛔ Sizga hech qaysi shaxs biriktirilmagan - zayavkalar ko'rinmaydi. Administratorga murojaat qiling.";
  }
}

function showAccessCard(title, text, canRequest, persons) {
  document.getElementById("accessCard").style.display = "";
  document.getElementById("accessTitle").textContent = title;
  document.getElementById("accessText").textContent = text;
  document.getElementById("requestForm").style.display = canRequest ? "" : "none";
  if (!canRequest) return;
  const sel = document.getElementById("reqPerson");
  if (sel.options.length <= 1) {
    persons.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      sel.appendChild(opt);
    });
  }
}

// "🔑 Kirish" / "📝 Ro'yxatdan o'tish" - which pane of the access card is shown.
function setupAuthTabs() {
  const tabs = document.getElementById("authTabs");
  if (!tabs) return;
  tabs.addEventListener("click", (e) => {
    const btn = e.target.closest(".auth-tab");
    if (!btn) return;
    tabs.querySelectorAll(".auth-tab").forEach((b) => b.classList.toggle("active", b === btn));
    document.getElementById("loginPane").style.display = btn.dataset.tab === "login" ? "" : "none";
    document.getElementById("registerPane").style.display = btn.dataset.tab === "register" ? "" : "none";
  });
}

function switchToRegisterTab() {
  document.querySelector('#authTabs .auth-tab[data-tab="register"]')?.click();
}

// The admin adds people by phone number; sharing your own number with the bot
// (Telegram vouches it is yours) links this account to that entry immediately.
// If that's not available in this Telegram client, "📝 Ro'yxatdan o'tish" is
// the fallback - filled in by hand, entirely inside the app, never leaving to
// the bot chat - just reviewed and approved by the admin afterwards.
function sharePhone() {
  if (tg && typeof tg.requestContact === "function") {
    tg.requestContact((sent) => {
      if (sent) {
        showToast("📱 Raqam yuborildi - tekshirilmoqda...");
        setTimeout(() => window.location.reload(), 2500);
      } else {
        showToast("Raqam yuborilmadi", true);
      }
    });
  } else {
    showToast("Bu Telegram ilovasida ishlamaydi - \"Ro'yxatdan o'tish\" bo'limidan foydalaning", true);
    switchToRegisterTab();
  }
}

async function submitRegister() {
  const btn = document.getElementById("reqBtn");
  const first = document.getElementById("regFirst").value.trim();
  const last = document.getElementById("regLast").value.trim();
  const phone = document.getElementById("regPhone").value.trim();
  if (!first) { showToast("Ismingizni kiriting", true); return; }
  if (phone.replace(/\D/g, "").length < 9) { showToast("Telefon raqamini to'g'ri kiriting", true); return; }
  btn.disabled = true;
  try {
    await apiPost("/api/me/request", {
      name: [first, last].filter(Boolean).join(" "),
      phone,
      person: document.getElementById("reqPerson").value,
      note: document.getElementById("reqNote").value.trim(),
    });
    showToast("📩 Ma'lumotlaringiz administratorga yuborildi");
    btn.textContent = "✅ Yuborildi";
  } catch (e) {
    showToast("Xatolik: " + errMsg(e), true);
    btn.disabled = false;
  }
}

function errMsg(e) {
  let msg = e.message;
  try { msg = JSON.parse(msg); } catch (_) { /* plain text */ }
  return typeof msg === "string" ? msg : JSON.stringify(msg);
}

// Each form is stamped with the Telegram user who submitted it (their id, and
// phone/name when known) - this is the actual privacy boundary now, not just
// "От кого". Your own rows say "Siz"; anyone else's (only visible at all with
// "Boshqa arizachilar zayavkalari") show who they were.
function creatorCellHtml(z) {
  if (currentMe.user_id && z.created_by_tg_id === currentMe.user_id) {
    return `<span class="creator-chip creator-me">Siz</span>`;
  }
  const name = z.created_by_name || "Noma'lum";
  const phone = z.created_by_phone ? fmtPhone(z.created_by_phone) : "";
  return `<span class="creator-chip" title="${esc(phone)}">${esc(name)}</span>`;
}

// Rebuilds the "Yuborgan" filter's options from the submitters actually present
// in the current (already filtered) list, keeping the selection if still valid.
function refreshCreatorFilter(items) {
  const sel = document.getElementById("fCreator");
  if (!sel) return;
  const seen = new Map();
  items.forEach((z) => {
    if (z.created_by_tg_id) seen.set(z.created_by_tg_id, z.created_by_name || String(z.created_by_tg_id));
  });
  const current = sel.value;
  sel.innerHTML = `<option value="">Barchasi</option>` + [...seen.entries()]
    .sort((a, b) => a[1].localeCompare(b[1]))
    .map(([id, name]) => `<option value="${id}">${esc(name)}</option>`).join("");
  if ([...seen.keys()].some((id) => String(id) === current)) sel.value = current;
}

function renderList(items) {
  const body = document.getElementById("zayavkaBody");
  const foot = document.getElementById("zayavkaFoot");
  document.getElementById("resultCount").textContent = `Jami: ${items.length} ta zayavka (Excel fayl)`;
  if (showCreator) refreshCreatorFilter(items);

  if (!items.length) {
    body.innerHTML = `<tr><td colspan="14" class="empty">Hech narsa topilmadi</td></tr>`;
    foot.innerHTML = "";
    return;
  }

  let grandTotal = 0;
  let grandAdvance = 0;
  let grandRemainder = 0;

  body.innerHTML = items.map((z, idx) => {
    // The list API returns per-zayavka totals already summed (not every item).
    const total = z.total || 0;
    const advance = z.advance || 0;
    const remainder = z.remainder || 0;
    grandTotal += total;
    grandAdvance += advance;
    grandRemainder += remainder;
    return `
      <tr class="clickable" data-id="${z.id}">
        <td>${idx + 1}</td>
        <td class="num-cell">${esc(z.number)}</td>
        <td>${esc(fmtDate(z.date))}</td>
        <td>${esc(z.object_name)}</td>
        <td>${esc(z.from_whom)}</td>
        <td>${creatorCellHtml(z)}</td>
        <td>${esc(z.to_whom)}</td>
        <td>${esc(z.payment_type)}</td>
        <td class="right">${z.items_count || 0}</td>
        <td class="right">${fmtNumber(total)}</td>
        <td class="right">${fmtNumber(advance)}</td>
        <td class="right strong">${fmtNumber(remainder)}</td>
        <td>${esc(fmtSentAt(z.last_saved_at || z.created_at))}</td>
        <td class="row-btns">
          ${currentMe.can_edit && z.can_write ? `<button type="button" class="tbl-btn" data-act="edit" title="Tahrirlash">✏️</button>` : ""}
          ${currentMe.can_export ? `<button type="button" class="tbl-btn" data-act="download" title="Oxirgi versiyani yuklab olish">📥 ${z.version_count || 1}-versiya</button>
          <button type="button" class="tbl-btn" data-act="send" title="Oxirgi versiyani menga Telegramda yuborish">📨</button>` : ""}
          <button type="button" class="tbl-btn" data-act="history" title="Barcha versiyalar tarixi">🕘 Tarix</button>
          ${currentMe.can_delete && z.can_write ? `<button type="button" class="tbl-btn tbl-del" data-act="delete" title="O'chirish">🗑️</button>` : ""}
        </td>
      </tr>`;
  }).join("");

  foot.innerHTML = `
    <tr>
      <td colspan="9">JAMI</td>
      <td class="right">${fmtNumber(grandTotal)}</td>
      <td class="right">${fmtNumber(grandAdvance)}</td>
      <td class="right">${fmtNumber(grandRemainder)}</td>
      <td colspan="2"></td>
    </tr>`;

  body.querySelectorAll("tr.clickable").forEach((tr) => {
    const id = Number(tr.dataset.id);
    tr.addEventListener("click", () => {
      const z = allZayavka.find((x) => x.id === id);
      if (currentMe.can_edit && z && z.can_write) openForEdit(id);
      else window.location.href = `history.html?id=${id}`;
    });
    tr.querySelectorAll(".tbl-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const act = btn.dataset.act;
        const z = allZayavka.find((x) => x.id === id);
        if (act === "edit") openForEdit(id);
        else if (act === "download") downloadExcelFile(`/api/zayavka/${id}/excel`, `Zayavka-${z ? z.number : id}.xlsx`);
        else if (act === "send") sendExcelToMe(`/api/zayavka/${id}/send_me`, btn);
        else if (act === "history") window.location.href = `history.html?id=${id}`;
        else if (act === "delete") deleteZayavka(id, btn);
      });
    });
  });
}

// Native confirm() doesn't work in Telegram's WebView, so deleting takes a
// second tap on the same button (it turns red and asks). The zayavka is only
// hidden (soft delete) - the admin can restore it.
async function deleteZayavka(id, btn) {
  if (!btn.classList.contains("confirming")) {
    btn.classList.add("confirming");
    btn.textContent = "Ha, o'chirilsin";
    setTimeout(() => {
      if (!btn.isConnected) return;
      btn.classList.remove("confirming");
      btn.textContent = "🗑️";
    }, 3500);
    return;
  }
  btn.disabled = true;
  try {
    await apiDelete(`/api/zayavka/${id}`);
    allZayavka = allZayavka.filter((x) => x.id !== id);
    renderList(allZayavka);
    showToast("🗑️ Zayavka o'chirildi");
  } catch (e) {
    let msg = e.message;
    try { msg = JSON.parse(msg); } catch (_) {}
    showToast("Xatolik: " + msg, true);
    btn.disabled = false;
  }
}

// Tapping a zayavka goes straight into the same form used to fill one out -
// pre-filled with everything already saved - instead of a separate
// read-only preview step, so viewing and editing (and the equivalent of
// the Excel sheet's data) are the same place, not two.
function openForEdit(id) {
  const z = allZayavka.find((x) => x.id === id);
  const params = new URLSearchParams({
    edit_id: id,
    object: (z && z.object_name) || "",
    date: (z && z.date) || "",
    from: (z && z.from_whom) || "",
    payment: (z && z.payment_type) || "",
  });
  window.location.href = `items.html?${params.toString()}`;
}

async function loadList() {
  document.getElementById("resultCount").textContent = "Yuklanmoqda...";
  const creatorSel = document.getElementById("fCreator");
  appliedFilters = {
    object_name: document.getElementById("fObject").value,
    from_whom: document.getElementById("fFrom").value,
    date_from: document.getElementById("fDateFrom").value,
    date_to: document.getElementById("fDateTo").value,
    created_by: showCreator && creatorSel ? creatorSel.value : "",
  };
  const query = buildQuery({ ...appliedFilters, limit: 200 });
  try {
    const data = await apiGet(`/api/zayavka${query}`);
    allZayavka = data.items;
    renderList(allZayavka);
  } catch (e) {
    showToast("Yuklashda xatolik: " + e.message, true);
  }
}

/**
 * "Excelga yuklab olish": opens a confirmation dialog showing exactly what
 * will be sent (the filters the list on screen was loaded with, how many
 * zayavkas, the totals), then on confirm asks the server to build the Excel
 * report and post it to the Telegram channel. It goes to a shared channel,
 * so it's confirmed first - and native confirm() doesn't work in Telegram's
 * WebView, hence our own dialog. The result stays visible in the dialog
 * (a toast alone is easy to miss), including the server's error if it fails.
 */
function setupExport() {
  const backdrop = document.getElementById("exportModalBackdrop");
  const summaryEl = document.getElementById("exportSummary");
  const statusEl = document.getElementById("exportStatus");
  const confirmBtn = document.getElementById("exportConfirmBtn");
  const cancelBtn = document.getElementById("exportCancelBtn");
  let busy = false;

  const setStatus = (kind, text) => {
    statusEl.className = "export-status " + kind;
    statusEl.textContent = text;
  };

  const periodText = () => {
    const f = appliedFilters;
    if (f.date_from && f.date_to) return `${fmtDate(f.date_from)} - ${fmtDate(f.date_to)}`;
    if (f.date_from) return `${fmtDate(f.date_from)} dan`;
    if (f.date_to) return `${fmtDate(f.date_to)} gacha`;
    return "Barchasi";
  };

  const openDialog = () => {
    if (!allZayavka.length) {
      showToast("Yuboriladigan zayavka yo'q", true);
      return;
    }
    const total = allZayavka.reduce((s, z) => s + (z.total || 0), 0);
    const advance = allZayavka.reduce((s, z) => s + (z.advance || 0), 0);
    const remainder = allZayavka.reduce((s, z) => s + (z.remainder || 0), 0);
    const rowsCount = allZayavka.reduce((s, z) => s + (z.items_count || 0), 0);
    const creatorSel = document.getElementById("fCreator");
    const creatorName = showCreator && creatorSel && creatorSel.value
      ? creatorSel.options[creatorSel.selectedIndex].textContent : "";
    summaryEl.innerHTML = `
      <div><b>Название объекта:</b> ${esc(appliedFilters.object_name || "Barchasi")}</div>
      <div><b>От кого:</b> ${esc(appliedFilters.from_whom || "Barchasi")}</div>
      ${creatorName ? `<div><b>Yuborgan:</b> ${esc(creatorName)}</div>` : ""}
      <div><b>Дата:</b> ${esc(periodText())}</div>
      <div><b>Zayavkalar:</b> ${allZayavka.length} ta &nbsp; <b>Qatorlar:</b> ${rowsCount} ta</div>
      <div><b>Общая сумма:</b> ${fmtNumber(total)} &nbsp; <b>Аванс:</b> ${fmtNumber(advance)} &nbsp; <b>Остатка:</b> ${fmtNumber(remainder)}</div>`;
    setStatus("", "");
    confirmBtn.style.display = "";
    confirmBtn.disabled = false;
    confirmBtn.textContent = "✅ Yuborish";
    cancelBtn.textContent = "Bekor qilish";
    backdrop.classList.add("show");
  };

  const closeDialog = () => {
    if (!busy) backdrop.classList.remove("show");
  };

  const send = async () => {
    if (busy) return;
    if (!getInitData()) {
      setStatus("error", "❌ Telegram ichida oching - bu tugma faqat bot orqali ishlaydi");
      return;
    }
    busy = true;
    confirmBtn.disabled = true;
    setStatus("info", "⏳ Yuborilmoqda...");
    try {
      const res = await apiPost("/api/zayavka/export", {
        init_data: getInitData(),
        object_name: appliedFilters.object_name || null,
        from_whom: appliedFilters.from_whom || null,
        date_from: appliedFilters.date_from || null,
        date_to: appliedFilters.date_to || null,
        created_by: appliedFilters.created_by ? Number(appliedFilters.created_by) : null,
      });
      const where = res.destination === "own_chat" ? "sizning Telegram chatingizga" : "kanalingizga";
      setStatus("ok", `✅ ${res.count} ta zayavka Excel fayli ${where} yuborildi`);
      confirmBtn.style.display = "none";
      cancelBtn.textContent = "Yopish";
    } catch (e) {
      let msg = e.message;
      try { msg = JSON.parse(msg); } catch (_) {}
      setStatus("error", "❌ " + msg);
      confirmBtn.disabled = false;
      confirmBtn.textContent = "🔁 Qayta urinish";
    } finally {
      busy = false;
    }
  };

  document.getElementById("exportBtn").addEventListener("click", openDialog);
  confirmBtn.addEventListener("click", send);
  cancelBtn.addEventListener("click", closeDialog);
  document.getElementById("exportModalClose").addEventListener("click", closeDialog);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) closeDialog();
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  setupViewToggle();
  setupNavButtons();
  setupExport();
  setupAuthTabs();

  document.getElementById("applyFilters").addEventListener("click", loadList);
  document.getElementById("clearFilters").addEventListener("click", () => {
    document.getElementById("fObject").value = "";
    document.getElementById("fFrom").value = "";
    document.getElementById("fDateFrom").value = "";
    document.getElementById("fDateTo").value = "";
    const creatorSel = document.getElementById("fCreator");
    if (creatorSel) creatorSel.value = "";
    loadList();
  });
  let meta;
  try {
    meta = await loadFilterOptions();
  } catch (e) {
    // e.g. opened outside Telegram, or the identity is missing/expired
    document.getElementById("resultCount").textContent = e.message;
    return;
  }
  currentMe = meta.me || currentMe;
  rememberMe(meta.me);
  showWhoAmI(meta.me, meta.all_persons);
  showCreator = !!(currentMe.is_admin || currentMe.can_view_others);
  document.getElementById("fCreatorField").style.display = showCreator ? "" : "none";
  document.getElementById("exportBtn").style.display = currentMe.can_report ? "" : "none";
  document.getElementById("reqBtn").addEventListener("click", submitRegister);
  document.getElementById("phoneBtn").addEventListener("click", sharePhone);
  if (currentMe.status === "pending" || currentMe.status === "blocked" || currentMe.can_view === false) return;
  await loadList();
});
