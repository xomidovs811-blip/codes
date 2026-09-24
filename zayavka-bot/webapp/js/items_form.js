// Logic for items.html — the "Tovarlar ro'yxati" Mini App form, opened from
// the chat wizard after object/date/from/payment are already picked there.
// Collects one or more item rows in one go, then POSTs them to the API.
//
// Edit mode: opened with ?edit_id=<id> (from the "✏️ Tahrirlash" button on a
// zayavka's detail view in table.html) instead of a blank form - fetches
// that record, pre-fills every row + the approval fields, and PUTs back to
// /api/zayavka/{id} on save instead of POSTing a new one. Object/date and
// the Номер заявки stay fixed either way (see update_zayavka_record).

const EDIT_ID = new URLSearchParams(window.location.search).get("edit_id") || null;
let EDIT_NUMBER = null; // set once the existing record loads, in edit mode
// The two-digit minute in the Номер заявки, fixed ONCE when the form opens and
// sent with the first save. That way the number shown - and printed - before
// saving is exactly the one that gets stored (no "##" placeholder).
const CODE_MINUTE = String(new Date().getMinutes()).padStart(2, "0");

function qs(name) {
  return new URLSearchParams(window.location.search).get(name) || "";
}

/**
 * Losing a filled-in form with no warning (print doesn't save anything -
 * only "Saqlash" does - so printing, then leaving, throws everything away
 * silently) is the exact complaint this whole block exists to fix. Three
 * layers, since no single one covers every way someone can leave:
 *   1. The in-app "Orqaga"/Telegram BackButton (setupNavButtons' `goBack`)
 *      is guarded - dirty and about to navigate away asks first.
 *   2. Telegram's own native close ("X"/swipe down) can't be intercepted by
 *      this page at all, but tg.enableClosingConfirmation() makes TELEGRAM
 *      ITSELF ask before closing while the form is dirty.
 *   3. Whatever still slips through (a hardware back button, a crash, the
 *      WebView simply being killed) - the form is continuously autosaved to
 *      localStorage as a draft, offered back the next time items.html opens.
 * None of this replaces "Saqlash" - it only protects against losing work
 * before that button is pressed.
 */
const DRAFT_KEY = "zayavka_draft";
const DRAFT_SAVE_DELAY = 800;
let formDirty = false;
let draftSaveTimer = null;

function lsGet(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}
function lsSet(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* unavailable - draft just won't persist */ }
}
function lsRemove(key) {
  try { localStorage.removeItem(key); } catch (e) { /* ignore */ }
}

function currentDraftContext() {
  return {
    edit_id: EDIT_ID || null,
    object: qs("object"),
    date: qs("date"),
    from: qs("from"),
    payment: qs("payment"),
  };
}

function draftMatchesHere(draft) {
  const c = currentDraftContext();
  if (c.edit_id || draft.edit_id) return String(draft.edit_id || "") === String(c.edit_id || "");
  return draft.object === c.object && draft.date === c.date && draft.from === c.from;
}

function draftUrl(draft) {
  if (draft.edit_id) return `items.html?edit_id=${encodeURIComponent(draft.edit_id)}`;
  const p = new URLSearchParams({ object: draft.object || "", date: draft.date || "", from: draft.from || "", payment: draft.payment || "" });
  return `items.html?${p.toString()}`;
}

function collectDraft() {
  return {
    ...currentDraftContext(),
    number: document.getElementById("numberPreview") ? document.getElementById("numberPreview").textContent : "",
    items: collectItems(),
    inspector: document.getElementById("inspectorSelect") ? document.getElementById("inspectorSelect").value : "",
    cashier: document.getElementById("cashierSelect") ? document.getElementById("cashierSelect").value : "",
    tech_supervisor: document.getElementById("techSelect") ? document.getElementById("techSelect").value : "",
    savedAt: new Date().toISOString(),
  };
}

function saveDraftNow() {
  lsSet(DRAFT_KEY, JSON.stringify(collectDraft()));
}

function scheduleDraftSave() {
  clearTimeout(draftSaveTimer);
  draftSaveTimer = setTimeout(saveDraftNow, DRAFT_SAVE_DELAY);
}

function loadDraft() {
  const raw = lsGet(DRAFT_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch (e) { return null; }
}

function clearDraft() {
  lsRemove(DRAFT_KEY);
  clearTimeout(draftSaveTimer);
}

// Marks the form as having unsaved work: arms Telegram's own "are you sure?"
// on close and starts autosaving a recoverable draft. Called from real user
// edits AND from anything that changes the form programmatically (restoring
// a draft, pasting from Telegram, deleting a row) - none of those alone fire
// a normal 'input' event.
function markDirty() {
  formDirty = true;
  if (tg && typeof tg.enableClosingConfirmation === "function") tg.enableClosingConfirmation();
  scheduleDraftSave();
}

function markClean() {
  formDirty = false;
  if (tg && typeof tg.disableClosingConfirmation === "function") tg.disableClosingConfirmation();
  clearDraft();
}

/**
 * The guard passed to setupNavButtons(): if nothing has changed, leaves
 * immediately (no interruption for normal browsing). If it has, saves the
 * draft right away (no debounce - about to possibly leave) and shows the
 * confirmation card instead of a native confirm() (unsupported in Telegram's
 * WebView, as elsewhere in this app) - "Saqlash va chiqish" reuses the same
 * submitForm() the button uses, "Saqlamasdan chiqish" needs a second tap.
 */
// If a double-tap on "Orqaga" (or the button + Telegram's BackButton firing
// together) called this again while the card was already up, a SECOND set
// of click listeners used to get piled onto the same buttons - one tap on
// "Saqlash va chiqish" then ran submitForm() twice, saving the same form as
// two separate zayavkas. Now a second call while one is already open just
// gets the SAME pending promise, no new listeners.
let pendingLeaveConfirm = null;

function confirmLeaveIfDirty() {
  if (!formDirty) return Promise.resolve(true);
  if (pendingLeaveConfirm) return pendingLeaveConfirm;
  saveDraftNow();
  pendingLeaveConfirm = new Promise((resolve) => {
    const backdrop = document.getElementById("leaveModalBackdrop");
    const discardBtn = document.getElementById("leaveDiscardBtn");
    backdrop.classList.add("show");
    discardBtn.classList.remove("confirming");
    discardBtn.textContent = "🚪 Saqlamasdan chiqish";

    const cleanup = (result) => {
      backdrop.classList.remove("show");
      saveBtn.removeEventListener("click", onSave);
      discardBtn.removeEventListener("click", onDiscard);
      cancelBtn.removeEventListener("click", onCancel);
      pendingLeaveConfirm = null;
      resolve(result);
    };
    const saveBtn = document.getElementById("leaveSaveBtn");
    const cancelBtn = document.getElementById("leaveCancelBtn");

    const onSave = async () => {
      if (saveBtn.disabled) return; // belt and braces: ignore a second click mid-save
      saveBtn.disabled = true;
      saveBtn.textContent = "Saqlanmoqda...";
      const ok = await submitForm({ suppressClose: true });
      saveBtn.disabled = false;
      saveBtn.textContent = "💾 Saqlash va chiqish";
      if (ok) cleanup(true);
    };
    const onDiscard = () => {
      if (!discardBtn.classList.contains("confirming")) {
        discardBtn.classList.add("confirming");
        discardBtn.textContent = "Ha, saqlamasdan chiqaman";
        setTimeout(() => {
          discardBtn.classList.remove("confirming");
          discardBtn.textContent = "🚪 Saqlamasdan chiqish";
        }, 3000);
        return;
      }
      // Deliberately NOT clearDraft() here - they chose not to save, but the
      // whole point of the draft is to still be able to find this again.
      cleanup(true);
    };
    const onCancel = () => cleanup(false);

    saveBtn.addEventListener("click", onSave);
    discardBtn.addEventListener("click", onDiscard);
    cancelBtn.addEventListener("click", onCancel);
  });
  return pendingLeaveConfirm;
}

function setupUnsavedGuard() {
  const body = document.getElementById("itemsBody");
  const onEdit = (e) => {
    markDirty();
    // Clears the "required" highlight the moment Сметная группа is filled in
    // (typed, or picked from the autocomplete panel - that fires 'change'),
    // rather than making the user re-submit just to see it clear.
    if (e.target.classList.contains("work-input") && e.target.value.trim()) {
      e.target.classList.remove("field-required-missing");
    }
  };
  if (body) {
    body.addEventListener("input", onEdit);
    body.addEventListener("change", onEdit);
  }
  ["inspectorSelect", "cashierSelect", "techSelect"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", onEdit);
  });

  // Best-effort extra layer for exits this page can't otherwise see coming
  // (a hardware back button, the WebView being closed outright) - not
  // reliable in every WebView, which is exactly why the draft exists too.
  window.addEventListener("beforeunload", (e) => {
    if (!formDirty) return;
    saveDraftNow();
    e.preventDefault();
    e.returnValue = "";
  });
}

/**
 * Offers back whatever autosaved draft is sitting in localStorage - for
 * THIS exact form if the ids/context match, or as a "found one elsewhere"
 * link otherwise (e.g. the bot wizard opened a different new form since).
 * Only ever read on load; never overwrites what the server/edit_id already
 * gave this page unless the user explicitly taps "Tiklash".
 */
function setupDraftBanner(applyDraft) {
  const draft = loadDraft();
  const banner = document.getElementById("draftBanner");
  if (!draft || !banner) return;

  const rows = (draft.items || []).length;
  const when = fmtSentAt(draft.savedAt) || draft.savedAt || "";

  if (draftMatchesHere(draft)) {
    banner.innerHTML = `
      <div class="draft-text">
        📝 <b>Saqlanmagan qoralama topildi</b> (${when}, ${rows} ta qator) - shu forma uchun.
        Uni tiklaysizmi, yo'qsa o'chirib, yangidan boshlaysizmi?
      </div>
      <div class="draft-actions">
        <button type="button" class="btn btn-primary" id="draftRestoreBtn">♻️ Tiklash</button>
        <button type="button" class="btn btn-secondary" id="draftDismissBtn">🗑️ Bekor qilish</button>
      </div>`;
    banner.style.display = "";
    document.getElementById("draftRestoreBtn").addEventListener("click", () => {
      applyDraft(draft);
      banner.style.display = "none";
      markDirty();
      showToast("♻️ Qoralama tiklandi");
    });
    document.getElementById("draftDismissBtn").addEventListener("click", () => {
      clearDraft();
      banner.style.display = "none";
    });
  } else {
    banner.innerHTML = `
      <div class="draft-text">
        📝 Boshqa forma uchun saqlanmagan qoralama bor (${when}, ${draft.object || "—"} · ${draft.from || "—"}).
      </div>
      <div class="draft-actions">
        <a class="btn btn-secondary" href="${draftUrl(draft)}">U yerga o'tish</a>
        <button type="button" class="btn btn-secondary" id="draftDismissBtn">🗑️ Bekor qilish</button>
      </div>`;
    banner.style.display = "";
    document.getElementById("draftDismissBtn").addEventListener("click", () => {
      clearDraft();
      banner.style.display = "none";
    });
  }
}

function renumberRows() {
  document.querySelectorAll("#itemsBody tr").forEach((tr, idx) => {
    tr.querySelector(".row-no").textContent = idx + 1;
  });
}

function optionsHtml(list, placeholder) {
  return `<option value="">${placeholder}</option>` +
    list.map((o) => `<option value="${o}">${o}</option>`).join("");
}

/**
 * Поставщик, Ед.изм and Сметная группа are all searchable autocompletes (a text input
 * backed by a shared <datalist>), not fixed <select>s - values get added ad
 * hoc, and typing one that already exists must reuse the exact same
 * spelling to stay consistent (for Поставщик this matters for prepayment
 * tracking). Each field gets its own controller instance below; a new value
 * is added to its in-memory list/datalist immediately (wireInput) so later
 * rows in the same form autocomplete it too, and persisted server-side on
 * save (_register_new_names in app/services.py) so future zayavkas suggest
 * it as well.
 *
 * The "manage" modal (renderManageList/setupManageModal) lets a bad/stray
 * entry (e.g. a single letter left behind from tabbing away mid-typing) be
 * deleted. No native confirm() - Telegram's WebView doesn't support it - so
 * deleting is a two-tap affair: the first tap turns the row's button into
 * "Tasdiqlash ✓" for a few seconds, and only a second tap within that
 * window actually deletes it.
 */
function createNameListController(category, datalistId) {
  let list = [];

  function render() {
    document.getElementById(datalistId).innerHTML =
      list.map((s) => `<option value="${s}"></option>`).join("");
  }

  function setList(names) {
    list = (names || []).slice().sort((a, b) => a.localeCompare(b));
    render();
  }

  function addLocally(name) {
    name = (name || "").trim();
    if (name && !list.includes(name)) {
      list.push(name);
      list.sort((a, b) => a.localeCompare(b));
      render();
    }
  }

  function wireInput(input) {
    input.addEventListener("change", () => addLocally(input.value));
  }

  async function deleteName(name) {
    const res = await apiDelete(`/api/names?${new URLSearchParams({ category, name })}`);
    // Trust the server's list back for this category - but only when it's
    // really there. Blindly doing setList(res.names || []) turned any odd
    // response (e.g. a body that didn't parse the way expected) into "the
    // whole list is now empty", which looked like deleting one entry wiped
    // every other name too. Falling back to removing just this one name
    // locally keeps that failure contained to the single row being deleted.
    if (res && Array.isArray(res.names)) setList(res.names);
    else { list = list.filter((n) => n !== name); render(); }
  }

  return {
    setList,
    addLocally,
    wireInput,
    deleteName,
    getList: () => list,
  };
}

const supplierList = createNameListController("supplier", "supplierOptions");
const unitList = createNameListController("unit", "unitOptions");
const workTypeList = createNameListController("work_type", "workTypeOptions");

/**
 * The "type or pick" suggestion panel for Поставщик / Ед.изм / Сметная группа
 * row inputs (still plain free-text fields underneath - this only adds a
 * picker). Replaces the browser's native <datalist> popup, which sizes and
 * truncates its rows to the input's own column width - on a long name like
 * "Иситиш ва кондиционер ишлари (отопление...)" that cut the text off
 * unreadably, and nothing in CSS can resize or restyle that native popup.
 * This one is a plain styled <div> (full control over width/wrapping) and
 * fixed-positioned via JS from the input's on-screen position, so the
 * item table's horizontal scroll (.table-wrap { overflow-x: auto }) never
 * clips it the way an absolutely-positioned one inside the scrolling table
 * would. One shared panel element is reused for whichever field is focused.
 */
let acPanel = null;
let acActiveInput = null;
let acController = null;

function acEnsurePanel() {
  if (acPanel) return acPanel;
  acPanel = document.createElement("div");
  acPanel.className = "ac-panel";
  document.body.appendChild(acPanel);
  // mousedown (not click) fires before the input's blur, so the value is
  // applied before the panel would otherwise close itself on blur.
  acPanel.addEventListener("mousedown", (e) => {
    const row = e.target.closest(".ac-row");
    if (!row || !acActiveInput) return;
    e.preventDefault();
    acActiveInput.value = row.dataset.name;
    acActiveInput.dispatchEvent(new Event("change", { bubbles: true }));
    acClose();
  });
  const reposition = () => { if (acActiveInput) acPosition(); };
  window.addEventListener("scroll", reposition, true);
  window.addEventListener("resize", reposition);
  return acPanel;
}

function acPosition() {
  const r = acActiveInput.getBoundingClientRect();
  const width = Math.max(r.width, 240);
  const left = Math.max(8, Math.min(r.left, window.innerWidth - width - 8));
  acPanel.style.left = `${left}px`;
  acPanel.style.top = `${r.bottom + 4}px`;
  acPanel.style.width = `${width}px`;
}

function acRender() {
  const q = acActiveInput.value.trim().toLowerCase();
  const list = acController.getList().filter((n) => !q || n.toLowerCase().includes(q));
  acPanel.innerHTML = list.length
    ? list.map((n) => `<div class="ac-row" data-name="${esc(n)}"><span class="ac-name">${esc(n)}</span></div>`).join("")
    : `<div class="ac-empty">${q ? "Mos keladigan nom yo'q" : "Ro'yxat bo'sh"}</div>`;
}

function acClose() {
  if (acPanel) acPanel.classList.remove("show");
  acActiveInput = null;
  acController = null;
}

function wireAutocomplete(input, controller) {
  const open = () => {
    acEnsurePanel();
    acActiveInput = input;
    acController = controller;
    acRender();
    acPosition();
    acPanel.classList.add("show");
  };
  input.addEventListener("focus", open);
  input.addEventListener("input", () => {
    if (acActiveInput !== input) open();
    else { acRender(); acPosition(); }
  });
  // A short delay so a click on a panel row (mousedown -> this blur -> click)
  // still lands before the panel closes.
  input.addEventListener("blur", () => setTimeout(() => { if (acActiveInput === input) acClose(); }, 150));
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { acClose(); input.blur(); }
  });
}

function renderManageList(controller, containerId) {
  const container = document.getElementById(containerId);
  // Kept as its own array (not re-read from controller.getList() inside the
  // click handler) and referenced by INDEX, not by embedding the name in a
  // data-* attribute: a name with a quote or "&" in it (easy to end up with
  // from free typing, or from "Telegramdan joylashtirish") would otherwise
  // break the attribute and could misalign which button deletes which name.
  const items = controller.getList();
  if (!items.length) {
    container.innerHTML = `<p class="hint">Ro'yxat bo'sh.</p>`;
    return;
  }
  container.innerHTML = items.map((name, idx) => `
    <div class="list-item" style="display:flex;align-items:center;justify-content:space-between;gap:10px;cursor:default;">
      <span>${esc(name)}</span>
      <button type="button" class="btn-danger" data-idx="${idx}" title="O'chirish">🗑️</button>
    </div>
  `).join("");

  container.querySelectorAll("button[data-idx]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = items[Number(btn.dataset.idx)];
      if (!btn.classList.contains("confirming")) {
        btn.classList.add("confirming");
        btn.textContent = "Tasdiqlash ✓";
        btn.dataset.timer = setTimeout(() => {
          btn.classList.remove("confirming");
          btn.textContent = "🗑️";
        }, 3000);
        return;
      }
      clearTimeout(Number(btn.dataset.timer));
      try {
        await controller.deleteName(name);
        renderManageList(controller, containerId);
        showToast("O'chirildi");
      } catch (e) {
        showToast("Xatolik: " + e.message, true);
      }
    });
  });
}

function setupManageModal(controller, btnId, backdropId, closeId, listContainerId) {
  const backdrop = document.getElementById(backdropId);
  document.getElementById(btnId).addEventListener("click", () => {
    renderManageList(controller, listContainerId);
    backdrop.classList.add("show");
  });
  document.getElementById(closeId).addEventListener("click", () => {
    backdrop.classList.remove("show");
  });
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) backdrop.classList.remove("show");
  });
}

function firstLetter(text) {
  text = (text || "").trim();
  return text ? text[0].toUpperCase() : "X";
}

function computeNumberPreview() {
  if (EDIT_NUMBER) {
    // Editing an existing zayavka: the Номер заявки is fixed server-side
    // (update_zayavka_record never recomputes it), so show the real saved
    // number instead of a live preview that wouldn't match what gets saved.
    document.getElementById("numberPreview").textContent = EDIT_NUMBER;
    return;
  }

  const objectName = qs("object");
  const fromWhom = qs("from");
  const dateVal = qs("date"); // yyyy-mm-dd

  if (!objectName || !fromWhom || !dateVal) {
    document.getElementById("numberPreview").textContent = "—";
    return;
  }

  const [, m, d] = dateVal.split("-");
  const code = `${Number(d)}-${Number(m)}-${CODE_MINUTE}-${firstLetter(objectName)}-${firstLetter(fromWhom)}`;
  document.getElementById("numberPreview").textContent = code;
}

function computeTotals() {
  let summa = 0;
  let avans = 0;
  let qoldiq = 0;
  document.querySelectorAll("#itemsBody tr").forEach((tr) => {
    const qty = parseFloat(tr.querySelector(".qty-input").value) || 0;
    const price = parseFloat(tr.querySelector(".price-input").value) || 0;
    const advance = parseFloat(tr.querySelector(".advance-input").value) || 0;
    const total = qty * price;
    summa += total;
    avans += advance;
    qoldiq += total - advance;
  });
  document.getElementById("totalSumma").textContent = fmtNumber(summa);
  document.getElementById("totalAvans").textContent = fmtNumber(avans);
  document.getElementById("totalQoldiq").textContent = fmtNumber(qoldiq);
}

function addRow(existing) {
  const tbody = document.getElementById("itemsBody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td class="row-no narrow" style="text-align:center;"></td>
    <td><input type="text" class="product-input" placeholder="Наименование" /></td>
    <td><input type="text" class="supplier-input" autocomplete="off" placeholder="Поставщик" /></td>
    <td class="narrow"><input type="text" class="block-input" /></td>
    <td class="narrow"><input type="text" class="floor-input" /></td>
    <td class="narrow"><input type="text" class="unit-input" autocomplete="off" placeholder="Ед.изм" /></td>
    <td class="narrow"><input type="number" step="any" class="qty-input" /></td>
    <td class="narrow"><input type="number" step="any" class="price-input" /></td>
    <td class="total-cell narrow"><input type="text" class="total-input" readonly /></td>
    <td class="narrow"><input type="number" step="any" class="advance-input" /></td>
    <td class="total-cell remainder-cell narrow"><input type="text" class="remainder-input" readonly /></td>
    <td><input type="text" class="work-input" autocomplete="off" placeholder="Сметная группа *" /></td>
    <td><input type="text" class="comment-input" /></td>
    <td class="row-actions"><button type="button" class="btn-danger" title="O'chirish">✕</button></td>
  `;

  tbody.appendChild(tr);

  if (existing) {
    tr.querySelector(".product-input").value = existing.product_name || "";
    tr.querySelector(".supplier-input").value = existing.supplier || "";
    tr.querySelector(".block-input").value = existing.block || "";
    tr.querySelector(".floor-input").value = existing.floor || "";
    tr.querySelector(".unit-input").value = existing.unit || "";
    tr.querySelector(".qty-input").value = existing.qty ?? "";
    tr.querySelector(".price-input").value = existing.price ?? "";
    tr.querySelector(".advance-input").value = existing.advance ?? "";
    tr.querySelector(".work-input").value = existing.work_type || "";
    tr.querySelector(".comment-input").value = existing.comment || "";
    // A value set programmatically here (loading a saved zayavka for edit,
    // or a row from "Telegramdan joylashtirish") never fires the input's own
    // 'change' event, so wireInput's listener alone wouldn't register it -
    // without this, a supplier/unit/work-type name visibly used by a row
    // could be completely absent from its own "ro'yxatini boshqarish" list.
    if (existing.supplier) supplierList.addLocally(existing.supplier);
    if (existing.unit) unitList.addLocally(existing.unit);
    if (existing.work_type) workTypeList.addLocally(existing.work_type);
  }

  supplierList.wireInput(tr.querySelector(".supplier-input"));
  unitList.wireInput(tr.querySelector(".unit-input"));
  workTypeList.wireInput(tr.querySelector(".work-input"));
  wireAutocomplete(tr.querySelector(".supplier-input"), supplierList);
  wireAutocomplete(tr.querySelector(".unit-input"), unitList);
  wireAutocomplete(tr.querySelector(".work-input"), workTypeList);

  const qtyInput = tr.querySelector(".qty-input");
  const priceInput = tr.querySelector(".price-input");
  const advanceInput = tr.querySelector(".advance-input");
  const totalInput = tr.querySelector(".total-input");
  const remainderInput = tr.querySelector(".remainder-input");

  const recalc = () => {
    const qty = parseFloat(qtyInput.value) || 0;
    const price = parseFloat(priceInput.value) || 0;
    const advance = parseFloat(advanceInput.value) || 0;
    const total = qty * price;
    totalInput.value = total ? fmtNumber(total) : "";
    remainderInput.value = (total || advance) ? fmtNumber(total - advance) : "";
    computeNumberPreview();
    computeTotals();
  };
  recalc(); // populate Общая сумма/Остатка immediately when prefilled from an existing row

  qtyInput.addEventListener("input", recalc);
  priceInput.addEventListener("input", recalc);
  advanceInput.addEventListener("input", recalc);

  tr.querySelector(".btn-danger").addEventListener("click", () => {
    if (document.querySelectorAll("#itemsBody tr").length <= 1) {
      showToast("Kamida bitta qator bo'lishi kerak", true);
      return;
    }
    if (acActiveInput && tr.contains(acActiveInput)) acClose();
    tr.remove();
    renumberRows();
    computeNumberPreview();
    computeTotals();
    markDirty();
  });

  renumberRows();
}

/**
 * "📋 Telegramdan joylashtirish": other users often report what's needed in
 * the Telegram channel/chat, and switching back and forth between reading
 * that and typing it into this form (sometimes on a second device) is the
 * whole reason this exists - copy the message once, paste it here once, and
 * every line becomes a row instead of retyping each one by hand.
 *
 * Each line is one item. If it has TAB or "|" characters, each piece between
 * them is classified: a number becomes Кол-во then Цена (in that order), a
 * piece that matches an existing Поставщик/Ед.изм/Сметная группа name (case-
 * insensitively) goes to that column, and anything else becomes the product
 * name (a second leftover piece becomes the comment). A line with no TAB/"|"
 * is treated as free text: up to its first two numbers become Кол-во/Цена
 * and the rest of the line (numbers removed) becomes the product name - so
 * even an unstructured line like "Sement 10 qop 45000" still helps.
 */
function isNumberToken(s) {
  return /^-?\d[\d\s.,]*$/.test(s.trim());
}

function toNumberToken(s) {
  let t = s.trim().replace(/\s+/g, "");
  if (t.includes(",") && t.includes(".")) t = t.replace(/,/g, "");
  else if ((t.match(/,/g) || []).length === 1) t = t.replace(",", ".");
  else t = t.replace(/,/g, "");
  const n = parseFloat(t);
  return Number.isNaN(n) ? null : n;
}

function parsePasteLine(line) {
  const item = { product_name: null, supplier: null, unit: null, qty: null, price: null, work_type: null, comment: null };
  const leftover = [];

  const assignCell = (raw) => {
    const s = raw.trim();
    if (!s) return;
    if (isNumberToken(s)) {
      if (item.qty === null) item.qty = toNumberToken(s);
      else if (item.price === null) item.price = toNumberToken(s);
      else leftover.push(s);
      return;
    }
    const low = s.toLowerCase();
    if (!item.unit && unitList.getList().some((n) => n.toLowerCase() === low)) { item.unit = s; return; }
    if (!item.supplier && supplierList.getList().some((n) => n.toLowerCase() === low)) { item.supplier = s; return; }
    if (!item.work_type && workTypeList.getList().some((n) => n.toLowerCase() === low)) { item.work_type = s; return; }
    if (!item.product_name) item.product_name = s;
    else leftover.push(s);
  };

  if (line.includes("\t")) line.split("\t").forEach(assignCell);
  else if (line.includes("|")) line.split("|").forEach(assignCell);
  else {
    let text = line;
    [...line.matchAll(/-?\d[\d\s.,]*\d|-?\d/g)].slice(0, 2).forEach((m) => {
      const val = toNumberToken(m[0]);
      if (item.qty === null) item.qty = val; else if (item.price === null) item.price = val;
      text = text.replace(m[0], " ");
    });
    text = text.replace(/\s{2,}/g, " ").trim();
    if (text) item.product_name = text;
  }

  if (leftover.length) item.comment = leftover.join(", ");
  return (item.product_name || item.qty !== null || item.price !== null) ? item : null;
}

function isRowBlank(tr) {
  return !tr.querySelector(".product-input").value.trim()
    && !tr.querySelector(".qty-input").value
    && !tr.querySelector(".price-input").value
    && !tr.querySelector(".supplier-input").value.trim()
    && !tr.querySelector(".work-input").value.trim();
}

function submitPaste() {
  const textarea = document.getElementById("pasteText");
  const lines = textarea.value.split("\n").map((l) => l.trim()).filter(Boolean);
  if (!lines.length) {
    showToast("Avval matn joylashtiring", true);
    return;
  }
  const items = lines.map(parsePasteLine).filter(Boolean);
  if (!items.length) {
    showToast("Qatorlarni aniqlab bo'lmadi", true);
    return;
  }

  // A fresh, still-untouched blank row is replaced rather than left dangling
  // in front of the pasted ones.
  const rows = document.querySelectorAll("#itemsBody tr");
  if (rows.length === 1 && isRowBlank(rows[0])) rows[0].remove();

  items.forEach((it) => addRow(it));
  document.getElementById("pasteModalBackdrop").classList.remove("show");
  textarea.value = "";
  markDirty();
  showToast(`✅ ${items.length} ta qator qo'shildi`);
}

// Column name shown per input class in the "full text" preview below the
// item table (setupCellPreview) - matches the header cells word for word.
const CELL_PREVIEW_LABELS = {
  "product-input": "Наименование товара",
  "supplier-input": "Поставщик",
  "block-input": "Блок",
  "floor-input": "Этаж",
  "unit-input": "Ед.изм",
  "qty-input": "Кол-во",
  "price-input": "Цена",
  "advance-input": "Аванс получил",
  "work-input": "Выполняемая работа (сметная группа)",
  "comment-input": "Комментарие",
};

/**
 * Mirrors whichever item-table cell is focused into a full-width readout in
 * the totals bar, live as it's typed: a narrow column (especially
 * Наименование/Комментарие/Сметная группа) hides most of a long value behind
 * its own internal scroll, so there was no way to see the whole thing while
 * editing it. Delegated on #itemsBody so it applies to every row, including
 * ones added later by "Qator qo'shish" or the Telegram-paste import.
 */
function setupCellPreview() {
  const body = document.getElementById("itemsBody");
  const box = document.getElementById("cellPreview");
  const labelEl = document.getElementById("cellPreviewLabel");
  const textEl = document.getElementById("cellPreviewText");
  if (!body || !box) return;

  const reset = () => {
    box.classList.add("empty");
    labelEl.textContent = "👁️ Katakcha ko'rinishi";
    textEl.textContent = "Matnni to'liq ko'rish uchun jadvaldagi katakchani bosing";
  };

  const show = (input) => {
    let label = null;
    for (const cls of input.classList) {
      if (CELL_PREVIEW_LABELS[cls]) { label = CELL_PREVIEW_LABELS[cls]; break; }
    }
    if (!label) { reset(); return; }
    const rowNo = input.closest("tr")?.querySelector(".row-no")?.textContent;
    box.classList.remove("empty");
    labelEl.textContent = `👁️ ${rowNo ? rowNo + "-qator - " : ""}${label}`;
    textEl.textContent = input.value || "(bo'sh)";
  };

  body.addEventListener("focusin", (e) => {
    if (e.target.tagName === "INPUT") show(e.target);
  });
  body.addEventListener("input", (e) => {
    if (e.target.tagName === "INPUT" && e.target === document.activeElement) show(e.target);
  });
  body.addEventListener("focusout", () => {
    setTimeout(() => { if (!body.contains(document.activeElement)) reset(); }, 0);
  });
  reset();
}

function collectItems() {
  const rows = document.querySelectorAll("#itemsBody tr");
  const items = [];
  rows.forEach((tr, idx) => {
    const qty = parseFloat(tr.querySelector(".qty-input").value) || null;
    const price = parseFloat(tr.querySelector(".price-input").value) || null;
    const advance = parseFloat(tr.querySelector(".advance-input").value) || null;
    items.push({
      row_no: idx + 1,
      product_name: tr.querySelector(".product-input").value || null,
      supplier: tr.querySelector(".supplier-input").value || null,
      block: tr.querySelector(".block-input").value || null,
      floor: tr.querySelector(".floor-input").value || null,
      unit: tr.querySelector(".unit-input").value || null,
      qty: qty,
      price: price,
      advance: advance,
      work_type: tr.querySelector(".work-input").value || null,
      comment: tr.querySelector(".comment-input").value || null,
    });
  });
  return items.filter((i) => i.product_name || i.qty || i.price);
}

/**
 * "Сметная группа" is mandatory on every real row (same "real" definition
 * collectItems() uses - a still-blank filler row doesn't count). Marks the
 * empty ones (a red outline, matching the header's own "*") and returns
 * their inputs so the caller can block the save and jump to the first one.
 */
function highlightMissingWorkType() {
  const empties = [];
  document.querySelectorAll("#itemsBody tr").forEach((tr) => {
    const work = tr.querySelector(".work-input");
    const isRealRow = tr.querySelector(".product-input").value.trim()
      || tr.querySelector(".qty-input").value
      || tr.querySelector(".price-input").value;
    const missing = !!isRealRow && !work.value.trim();
    work.classList.toggle("field-required-missing", missing);
    if (missing) empties.push(work);
  });
  return empties;
}

function fillHeader(meta, existing) {
  const fromWhom = (existing && existing.from_whom) || qs("from") || "—";
  document.getElementById("hObject").textContent = (existing && existing.object_name) || qs("object") || "—";
  document.getElementById("hDate").textContent = fmtDate((existing && existing.date) || qs("date")) || "—";
  document.getElementById("hFrom").textContent = fromWhom;
  document.getElementById("hPayment").textContent = (existing && existing.payment_type) || qs("payment") || "—";
  document.getElementById("hKomu").textContent = (existing && existing.to_whom) || (meta && meta.to_whom) || "—";

  // Заявитель = От кого (same person, no separate input) and Директор stays
  // fixed, same as Кому above - both just mirror already-known values.
  document.getElementById("approvalFrom").textContent = fromWhom;
  document.getElementById("approvalDirector").textContent = (existing && existing.to_whom) || (meta && meta.to_whom) || "—";
}

/**
 * Wires up an editable "combo box" for Инспектор / Кассир / Техданзор: a
 * dropdown of existing names plus a "+" button that reveals a small text
 * input. Typing a new name and confirming POSTs it to /api/names (persisted
 * server-side for every future form) and selects it immediately - no native
 * prompt() (Telegram's WebView doesn't support it), just inline DOM toggling.
 *
 * The dropdown itself is custom, not the native <select>: a native list
 * can't hold buttons, and each name needs a 🗑️ on its right so a wrongly
 * typed name can be removed. The real <select> is kept, hidden, as the
 * value holder, so reading/saving the field (select.value) is unchanged.
 * Deleting takes two taps (first turns the button into "Tasdiqlash ✓")
 * since native confirm() isn't available in Telegram's WebView; it only
 * removes the name from the list - zayavkas that already used it keep it.
 */
function setupCombo(category, names, ids, selected) {
  const select = document.getElementById(ids.select);
  const addBtn = document.getElementById(ids.addBtn);
  const addRow = document.getElementById(ids.addRow);
  const input = document.getElementById(ids.input);
  const saveBtn = document.getElementById(ids.saveBtn);

  const cdd = document.createElement("div");
  cdd.className = "cdd";
  cdd.innerHTML = `
    <button type="button" class="cdd-trigger"><span class="cdd-value">—</span></button>
    <div class="cdd-panel"></div>`;
  select.style.display = "none";
  select.parentElement.insertBefore(cdd, select);
  const trigger = cdd.querySelector(".cdd-trigger");
  const valueEl = cdd.querySelector(".cdd-value");
  const panel = cdd.querySelector(".cdd-panel");

  const closePanel = () => cdd.classList.remove("open");

  const renderPanel = (list) => {
    const current = select.value;
    panel.innerHTML =
      `<div class="cdd-row${current ? "" : " selected"}" data-name=""><span class="cdd-name">—</span></div>` +
      list.map((n) => `
        <div class="cdd-row${n === current ? " selected" : ""}" data-name="${esc(n)}">
          <span class="cdd-name">${esc(n)}</span>
          <button type="button" class="btn-danger cdd-del" title="O'chirish">🗑️</button>
        </div>`).join("");
  };

  const render = (list, sel) => {
    list = list.slice();
    // A value the zayavka already has must survive even if it was later
    // removed from the shared list - otherwise editing would blank it.
    if (sel && !list.includes(sel)) list.push(sel);
    select.innerHTML = optionsHtml(list, "—");
    select.value = sel || "";
    valueEl.textContent = select.value || "—";
    renderPanel(list);
  };
  render(names, selected);

  trigger.addEventListener("click", () => {
    document.querySelectorAll(".cdd.open").forEach((el) => { if (el !== cdd) el.classList.remove("open"); });
    cdd.classList.toggle("open");
  });
  document.addEventListener("click", (e) => {
    if (!cdd.contains(e.target)) closePanel();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePanel();
  });

  panel.addEventListener("click", async (e) => {
    const delBtn = e.target.closest(".cdd-del");
    const row = e.target.closest(".cdd-row");
    if (!row) return;

    if (!delBtn) {
      // tapped a name: select it
      const name = row.dataset.name;
      select.value = name;
      valueEl.textContent = name || "—";
      panel.querySelectorAll(".cdd-row").forEach((r) => r.classList.toggle("selected", r === row));
      closePanel();
      return;
    }

    const name = row.dataset.name;
    if (!delBtn.classList.contains("confirming")) {
      delBtn.classList.add("confirming");
      delBtn.textContent = "Tasdiqlash ✓";
      delBtn.dataset.timer = setTimeout(() => {
        delBtn.classList.remove("confirming");
        delBtn.textContent = "🗑️";
      }, 3000);
      return;
    }
    clearTimeout(Number(delBtn.dataset.timer));
    try {
      const res = await apiDelete(`/api/names?${new URLSearchParams({ category, name })}`);
      const current = select.value;
      render(res.names || [], current === name ? "" : current);
      showToast("O'chirildi");
    } catch (err) {
      showToast("Xatolik: " + err.message, true);
    }
  });

  addBtn.addEventListener("click", () => {
    addRow.classList.toggle("show");
    if (addRow.classList.contains("show")) input.focus();
  });

  saveBtn.addEventListener("click", async () => {
    const name = (input.value || "").trim();
    if (!name) {
      showToast("Ism kiriting", true);
      return;
    }
    try {
      const res = await apiPost("/api/names", { category, name });
      render(res.names || [], name);
      input.value = "";
      addRow.classList.remove("show");
    } catch (e) {
      showToast("Xatolik: " + e.message, true);
    }
  });
}

// Hard stop against ever POSTing/PUTing the same form twice at once - not
// just from the two buttons that can call this (submitBtn and the leave-
// confirmation card's "Saqlash va chiqish"), but from any future caller too.
// A per-button `disabled` check alone isn't enough: two click listeners on
// the SAME button both run their synchronous half before either one's
// `await` suspends, so both still reach the network call.
let submitInFlight = false;

async function submitForm(opts) {
  if (submitInFlight) return false;
  const suppressClose = !!(opts && opts.suppressClose);
  const items = collectItems();
  if (!items.length) {
    showToast("Kamida bitta tovar qatorini to'ldiring", true);
    return false;
  }
  const missingWorkType = highlightMissingWorkType();
  if (missingWorkType.length) {
    showToast("\"Сметная группа\" hamma qatorda to'ldirilishi shart", true);
    missingWorkType[0].scrollIntoView({ behavior: "smooth", block: "center" });
    missingWorkType[0].focus();
    return false;
  }

  submitInFlight = true;
  const submitBtn = document.getElementById("submitBtn");
  submitBtn.disabled = true;
  submitBtn.textContent = "Saqlanmoqda...";

  // Saves straight to the API (not Telegram.WebApp.sendData() - that only
  // works for Mini Apps opened via a Reply Keyboard button, not the inline
  // "Web App" button this form is opened from). The bot process then sends
  // the finished Excel over Telegram itself, from app/notify.py.
  const tgUser = tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user : null;
  const payload = {
    object_name: qs("object"),
    date: qs("date"),
    from_whom: qs("from"),
    payment_type: qs("payment"),
    items,
    inspector: document.getElementById("inspectorSelect").value || null,
    cashier: document.getElementById("cashierSelect").value || null,
    tech_supervisor: document.getElementById("techSelect").value || null,
    init_data: getInitData(),
    tg_user_id: tgUser ? tgUser.id : null,
    tg_user_name: tgUser ? `${tgUser.first_name || ""} ${tgUser.last_name || ""}`.trim() : null,
    code_minute: EDIT_ID ? null : CODE_MINUTE,
  };

  try {
    const result = EDIT_ID
      ? await apiPut(`/api/zayavka/${EDIT_ID}`, payload)
      : await apiPost("/api/zayavka", payload);
    showToast(`✅ Saqlandi! Raqam: ${result.number}`);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    submitBtn.textContent = "✅ Saqlandi";
    markClean(); // saved - the draft/close-confirmation were only for getting here safely
    if (!suppressClose) {
      setTimeout(() => {
        if (tg) tg.close();
      }, 1200);
    }
    return true;
  } catch (e) {
    showToast("Xatolik: " + e.message, true);
    submitBtn.disabled = false;
    submitBtn.textContent = EDIT_ID ? "💾 Yangilash" : "✅ Saqlash";
    return false;
  } finally {
    submitInFlight = false;
  }
}

// applyViewMode()/setupViewToggle() (the PC/Mobile toggle + fullscreen
// request) live in common.js, shared with table.html.

// Replaces the item rows with a restored draft's rows/approval fields - only
// ever called from the "♻️ Tiklash" button, once the draft is confirmed to
// match this exact form (setupDraftBanner/draftMatchesHere).
function applyDraftToForm(draft) {
  document.getElementById("itemsBody").innerHTML = "";
  (draft.items && draft.items.length ? draft.items : [{}]).forEach((item) => addRow(item));
  if (draft.inspector) document.getElementById("inspectorSelect").value = draft.inspector;
  if (draft.cashier) document.getElementById("cashierSelect").value = draft.cashier;
  if (draft.tech_supervisor) document.getElementById("techSelect").value = draft.tech_supervisor;
  computeNumberPreview();
  computeTotals();
}

document.addEventListener("DOMContentLoaded", async () => {
  setupViewToggle();
  setupNavButtons(confirmLeaveIfDirty);
  setupUnsavedGuard();

  let meta = {};
  try {
    meta = await apiGet("/api/meta");
    supplierList.setList(meta.suppliers || []);
    unitList.setList(meta.units || []);
    workTypeList.setList(meta.work_types || []);
    rememberMe(meta.me);
    if (!EDIT_ID && meta.me && !meta.me.can_create) {
      showToast("Sizga zayavka to'ldirish huquqi berilmagan - saqlab bo'lmaydi", true);
    }
    if (EDIT_ID && meta.me && !meta.me.can_edit) {
      showToast("Sizga tahrirlash huquqi berilmagan - o'zgarishlar saqlanmaydi", true);
    }
  } catch (e) {
    // Falls back to an empty dropdown/datalist; rows can still be filled in freely.
  }
  setupManageModal(supplierList, "manageSuppliersBtn", "suppliersModalBackdrop", "suppliersModalClose", "suppliersManageList");
  setupManageModal(unitList, "manageUnitsBtn", "unitsModalBackdrop", "unitsModalClose", "unitsManageList");
  setupManageModal(workTypeList, "manageWorkTypesBtn", "workTypesModalBackdrop", "workTypesModalClose", "workTypesManageList");

  let existing = null;
  if (EDIT_ID) {
    try {
      existing = await apiGet(`/api/zayavka/${EDIT_ID}`);
      EDIT_NUMBER = existing.number;
    } catch (e) {
      showToast("Zayavkani yuklab bo'lmadi: " + e.message, true);
    }
  }

  fillHeader(meta, existing);

  setupCombo("inspector", meta.inspectors || [], {
    select: "inspectorSelect", addBtn: "inspectorAddBtn", addRow: "inspectorAddRow",
    input: "inspectorNewInput", saveBtn: "inspectorSaveBtn",
  }, existing && existing.inspector);
  setupCombo("cashier", meta.cashiers || [], {
    select: "cashierSelect", addBtn: "cashierAddBtn", addRow: "cashierAddRow",
    input: "cashierNewInput", saveBtn: "cashierSaveBtn",
  }, existing && existing.cashier);
  setupCombo("tech_supervisor", meta.tech_supervisors || [], {
    select: "techSelect", addBtn: "techAddBtn", addRow: "techAddRow",
    input: "techNewInput", saveBtn: "techSaveBtn",
  }, existing && existing.tech_supervisor);

  setupCellPreview();
  document.getElementById("addRowBtn").addEventListener("click", () => addRow());
  document.getElementById("submitBtn").addEventListener("click", submitForm);
  document.getElementById("printBtn").addEventListener("click", () => window.print());

  const pasteBackdrop = document.getElementById("pasteModalBackdrop");
  document.getElementById("pasteBtn").addEventListener("click", () => {
    pasteBackdrop.classList.add("show");
    document.getElementById("pasteText").focus();
  });
  document.getElementById("pasteModalClose").addEventListener("click", () => pasteBackdrop.classList.remove("show"));
  document.getElementById("pasteSubmitBtn").addEventListener("click", submitPaste);
  pasteBackdrop.addEventListener("click", (e) => {
    if (e.target === pasteBackdrop) pasteBackdrop.classList.remove("show");
  });

  if (existing && existing.items && existing.items.length) {
    existing.items.forEach((item) => addRow(item));
    document.getElementById("submitBtn").textContent = "💾 Yangilash";
  } else {
    addRow();
  }
  computeNumberPreview();
  computeTotals();
  setupDraftBanner(applyDraftToForm);
});
