// Logic for version.html - a read-only look at what one saved version of a
// zayavka contained (the same data its Excel was built from).

const params = new URLSearchParams(window.location.search);
const ZID = params.get("id");
const VNO = Number(params.get("v"));
let VERSION = null;

function actionLabel(action) {
  return action === "created" ? "Yaratildi" : "Tahrirlandi";
}

function cell(value) {
  return value === null || value === undefined || value === "" ? "" : esc(value);
}

function render(d) {
  VERSION = d;
  const isLatest = d.version_no === d.version_count;

  document.getElementById("pageTitle").innerHTML =
    `📄 ${d.version_no}-versiya${isLatest ? ' <span class="ver-latest">Oxirgi</span>' : ""}`;
  document.getElementById("versionMeta").textContent =
    [actionLabel(d.action), fmtSentAt(d.saved_at), d.saved_by].filter(Boolean).join(" · ")
    + `  (${d.version_no} / ${d.version_count})`;

  document.getElementById("hObject").textContent = d.object_name || "—";
  document.getElementById("hDate").textContent = fmtDate(d.date) || "—";
  document.getElementById("hFrom").textContent = d.from_whom || "—";
  document.getElementById("hKomu").textContent = d.to_whom || "—";
  document.getElementById("hPayment").textContent = d.payment_type || "—";
  document.getElementById("hNumber").textContent = d.number || "—";

  const items = d.items || [];
  document.getElementById("itemsBody").innerHTML = items.map((i, idx) => `
    <tr>
      <td>${idx + 1}</td>
      <td>${cell(i.product_name)}</td>
      <td>${cell(i.supplier)}</td>
      <td>${cell(i.block)}</td>
      <td>${cell(i.floor)}</td>
      <td>${cell(i.unit)}</td>
      <td class="right">${fmtNumber(i.qty)}</td>
      <td class="right">${fmtNumber(i.price)}</td>
      <td class="right">${fmtNumber(i.total)}</td>
      <td class="right">${fmtNumber(i.advance)}</td>
      <td class="right strong">${fmtNumber(i.remainder)}</td>
      <td>${cell(i.work_type)}</td>
      <td>${cell(i.comment)}</td>
    </tr>`).join("");

  const sum = (field) => items.reduce((s, i) => s + (Number(i[field]) || 0), 0);
  document.getElementById("totalSumma").textContent = fmtNumber(sum("total"));
  document.getElementById("totalAvans").textContent = fmtNumber(sum("advance"));
  document.getElementById("totalQoldiq").textContent = fmtNumber(sum("remainder"));

  document.getElementById("aInspector").textContent = d.inspector || "—";
  document.getElementById("aCashier").textContent = d.cashier || "—";
  document.getElementById("aFrom").textContent = d.from_whom || "—";
  document.getElementById("aTech").textContent = d.tech_supervisor || "—";
  document.getElementById("aDirector").textContent = d.to_whom || "—";

  document.getElementById("prevVerBtn").disabled = d.version_no <= 1;
  document.getElementById("nextVerBtn").disabled = d.version_no >= d.version_count;
}

// Stepping between versions replaces the current history entry instead of
// adding one, so Orqaga still returns to wherever you came from (the
// versions list) rather than walking back through every version you viewed.
function gotoVersion(n) {
  window.location.replace(`version.html?id=${ZID}&v=${n}`);
}

document.addEventListener("DOMContentLoaded", async () => {
  setupViewToggle();
  setupNavButtons();

  document.getElementById("prevVerBtn").addEventListener("click", () => gotoVersion(VNO - 1));
  document.getElementById("nextVerBtn").addEventListener("click", () => gotoVersion(VNO + 1));
  document.getElementById("historyBtn").addEventListener("click", () => {
    window.location.href = `history.html?id=${ZID}`;
  });
  document.getElementById("downloadBtn").addEventListener("click", () => {
    downloadExcelFile(
      `/api/zayavka/${ZID}/versions/${VNO}/excel`,
      `Zayavka-${VERSION ? VERSION.number : ZID}-v${VNO}.xlsx`,
    );
  });
  document.getElementById("sendBtn").addEventListener("click", (e) => {
    sendExcelToMe(`/api/zayavka/${ZID}/versions/${VNO}/send_me`, e.currentTarget);
  });

  document.getElementById("prevVerBtn").disabled = true;
  document.getElementById("nextVerBtn").disabled = true;

  if (!ZID || !VNO) {
    document.getElementById("versionMeta").textContent = "Versiya tanlanmagan";
    return;
  }
  try {
    render(await apiGet(`/api/zayavka/${ZID}/versions/${VNO}`));
  } catch (e) {
    document.getElementById("versionMeta").textContent = "Yuklab bo'lmadi";
    showToast("Xatolik: " + e.message, true);
  }
});
