// Logic for index.html — "Zayavka berish" form

let rowCounter = 0;

function firstLetter(text) {
  text = (text || "").trim();
  return text ? text[0].toUpperCase() : "X";
}

function firstTwoDigits(total) {
  let value = Math.abs(Math.round(Number(total) || 0));
  let digits = String(value);
  if (digits.length < 2) digits = digits.padStart(2, "0");
  return digits.slice(0, 2);
}

function computeNumberPreview() {
  const objectName = document.getElementById("objectName").value;
  const dateVal = document.getElementById("zayavkaDate").value; // yyyy-mm-dd
  const fromWhom = document.getElementById("fromWhom").value;

  if (!objectName || !dateVal || !fromWhom) {
    document.getElementById("numberPreview").textContent = "—";
    return;
  }

  const [y, m, d] = dateVal.split("-");

  const firstRow = document.querySelector("#itemsBody tr");
  let total = 0;
  if (firstRow) {
    const qty = parseFloat(firstRow.querySelector(".qty-input").value) || 0;
    const price = parseFloat(firstRow.querySelector(".price-input").value) || 0;
    total = qty * price;
  }

  const code = `${d}-${m}-${y}-${firstLetter(objectName)}-${firstLetter(fromWhom)}-${firstTwoDigits(total)}`;
  document.getElementById("numberPreview").textContent = code;
}

function renumberRows() {
  document.querySelectorAll("#itemsBody tr").forEach((tr, idx) => {
    tr.querySelector(".row-no").textContent = idx + 1;
  });
}

function addRow() {
  rowCounter += 1;
  const tbody = document.getElementById("itemsBody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td class="row-no narrow" style="text-align:center;"></td>
    <td><input type="text" class="product-input" placeholder="Наименование" /></td>
    <td><input type="text" class="supplier-input" placeholder="Поставщик" /></td>
    <td class="narrow"><input type="text" class="block-input" /></td>
    <td class="narrow"><input type="text" class="floor-input" /></td>
    <td class="narrow"><input type="text" class="unit-input" placeholder="шт" /></td>
    <td class="narrow"><input type="number" step="any" class="qty-input" /></td>
    <td class="narrow"><input type="number" step="any" class="price-input" /></td>
    <td class="total-cell narrow"><input type="text" class="total-input" readonly /></td>
    <td class="narrow"><input type="number" step="any" class="advance-input" /></td>
    <td class="narrow"><input type="number" step="any" class="remainder-input" /></td>
    <td><input type="text" class="work-input" placeholder="Смета группа" /></td>
    <td><input type="text" class="comment-input" /></td>
    <td class="row-actions"><button type="button" class="btn-danger" title="O'chirish">✕</button></td>
  `;

  tbody.appendChild(tr);

  const qtyInput = tr.querySelector(".qty-input");
  const priceInput = tr.querySelector(".price-input");
  const totalInput = tr.querySelector(".total-input");

  const recalc = () => {
    const qty = parseFloat(qtyInput.value) || 0;
    const price = parseFloat(priceInput.value) || 0;
    const total = qty * price;
    totalInput.value = total ? fmtNumber(total) : "";
    computeNumberPreview();
  };

  qtyInput.addEventListener("input", recalc);
  priceInput.addEventListener("input", recalc);

  tr.querySelector(".btn-danger").addEventListener("click", () => {
    if (document.querySelectorAll("#itemsBody tr").length <= 1) {
      showToast("Kamida bitta qator bo'lishi kerak", true);
      return;
    }
    tr.remove();
    renumberRows();
    computeNumberPreview();
  });

  renumberRows();
}

function collectItems() {
  const rows = document.querySelectorAll("#itemsBody tr");
  const items = [];
  rows.forEach((tr, idx) => {
    const qty = parseFloat(tr.querySelector(".qty-input").value) || null;
    const price = parseFloat(tr.querySelector(".price-input").value) || null;
    items.push({
      row_no: idx + 1,
      product_name: tr.querySelector(".product-input").value || null,
      supplier: tr.querySelector(".supplier-input").value || null,
      block: tr.querySelector(".block-input").value || null,
      floor: tr.querySelector(".floor-input").value || null,
      unit: tr.querySelector(".unit-input").value || null,
      qty: qty,
      price: price,
      advance: parseFloat(tr.querySelector(".advance-input").value) || null,
      remainder: parseFloat(tr.querySelector(".remainder-input").value) || null,
      work_type: tr.querySelector(".work-input").value || null,
      comment: tr.querySelector(".comment-input").value || null,
    });
  });
  return items;
}

function resetForm() {
  document.getElementById("itemsBody").innerHTML = "";
  addRow();
  document.getElementById("zayavkaDate").value = todayIso();
  computeNumberPreview();
}

async function loadMeta() {
  const meta = await apiGet("/api/meta");
  const objectSelect = document.getElementById("objectName");
  const fromSelect = document.getElementById("fromWhom");

  objectSelect.innerHTML = meta.objects
    .map((o) => `<option value="${o}">${o}</option>`)
    .join("");
  fromSelect.innerHTML = meta.from_whom
    .map((f) => `<option value="${f}">${f}</option>`)
    .join("");

  document.getElementById("toWhom").value = meta.to_whom;
  document.getElementById("paymentType").value = meta.payment_type;
}

async function submitForm() {
  const objectName = document.getElementById("objectName").value;
  const dateVal = document.getElementById("zayavkaDate").value;
  const fromWhom = document.getElementById("fromWhom").value;

  if (!objectName || !dateVal || !fromWhom) {
    showToast("Barcha maydonlarni to'ldiring", true);
    return;
  }

  const items = collectItems();
  const hasContent = items.some((i) => i.product_name || i.qty || i.price);
  if (!hasContent) {
    showToast("Kamida bitta tovar qatorini to'ldiring", true);
    return;
  }

  const payload = {
    object_name: objectName,
    date: dateVal,
    from_whom: fromWhom,
    to_whom: document.getElementById("toWhom").value,
    payment_type: document.getElementById("paymentType").value,
    items: items,
    init_data: getInitData(),
    tg_user_id: tg && tg.initDataUnsafe && tg.initDataUnsafe.user ? tg.initDataUnsafe.user.id : null,
    tg_user_name: tg && tg.initDataUnsafe && tg.initDataUnsafe.user
      ? `${tg.initDataUnsafe.user.first_name || ""} ${tg.initDataUnsafe.user.last_name || ""}`.trim()
      : null,
  };

  const submitBtn = document.getElementById("submitBtn");
  submitBtn.disabled = true;
  submitBtn.textContent = "Yuborilmoqda...";

  try {
    const result = await apiPost("/api/zayavka", payload);
    showToast(`Yuborildi! Raqam: ${result.number}`);
    if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
    resetForm();
  } catch (e) {
    showToast("Xatolik: " + e.message, true);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "✅ Yuborish";
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("zayavkaDate").value = todayIso();
  document.getElementById("addRowBtn").addEventListener("click", addRow);
  document.getElementById("submitBtn").addEventListener("click", submitForm);
  document.getElementById("objectName").addEventListener("change", computeNumberPreview);
  document.getElementById("fromWhom").addEventListener("change", computeNumberPreview);
  document.getElementById("zayavkaDate").addEventListener("change", computeNumberPreview);

  try {
    await loadMeta();
  } catch (e) {
    showToast("Ma'lumotlarni yuklashda xatolik", true);
  }
  addRow();
  computeNumberPreview();
});
