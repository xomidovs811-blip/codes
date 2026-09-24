// Logic for history.html - every saved version of one zayavka, newest first.
// A version is written each time the form is saved (see ZayavkaVersion in
// app/models.py), so each row here is an Excel that was sent to Telegram.

const ZID = new URLSearchParams(window.location.search).get("id");
let ZAYAVKA = null;

function actionLabel(action) {
  return action === "created" ? "Yaratildi" : "Tahrirlandi";
}

function fillHeader(z) {
  document.getElementById("hObject").textContent = z.object_name || "—";
  document.getElementById("hDate").textContent = fmtDate(z.date) || "—";
  document.getElementById("hFrom").textContent = z.from_whom || "—";
  document.getElementById("hKomu").textContent = z.to_whom || "—";
  document.getElementById("hPayment").textContent = z.payment_type || "—";
  document.getElementById("hNumber").textContent = z.number || "—";
}

function renderVersions(versions) {
  const body = document.getElementById("versionBody");
  document.getElementById("versionCount").textContent = `Jami: ${versions.length} ta versiya`;

  body.innerHTML = versions.map((v, idx) => {
    const isLatest = idx === 0;
    return `
      <tr class="clickable ${isLatest ? "latest-row" : ""}" data-v="${v.version_no}">
        <td>
          <span class="ver-badge">${v.version_no}-versiya</span>
          ${isLatest ? '<span class="ver-latest">Oxirgi</span>' : ""}
        </td>
        <td>${actionLabel(v.action)}</td>
        <td>${esc(fmtSentAt(v.created_at))}</td>
        <td>${esc(v.saved_by || "—")}</td>
        <td class="right">${v.rows}</td>
        <td class="right">${fmtNumber(v.total)}</td>
        <td class="right">${fmtNumber(v.advance)}</td>
        <td class="right strong">${fmtNumber(v.remainder)}</td>
        <td class="row-btns">
          <button type="button" class="tbl-btn" data-act="view" data-v="${v.version_no}" title="Ichini ko'rish">👁 Ko'rish</button>
          <button type="button" class="tbl-btn" data-act="download" data-v="${v.version_no}" title="Yuklab olish">📥</button>
          <button type="button" class="tbl-btn" data-act="send" data-v="${v.version_no}" title="Menga Telegramda yuborish">📨</button>
        </td>
      </tr>`;
  }).join("");

  body.querySelectorAll("tr.clickable").forEach((tr) => {
    tr.addEventListener("click", () => openVersion(tr.dataset.v));
  });

  body.querySelectorAll(".tbl-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const n = btn.dataset.v;
      if (btn.dataset.act === "view") {
        openVersion(n);
      } else if (btn.dataset.act === "download") {
        downloadExcelFile(
          `/api/zayavka/${ZID}/versions/${n}/excel`,
          `Zayavka-${ZAYAVKA ? ZAYAVKA.number : ZID}-v${n}.xlsx`,
        );
      } else {
        sendExcelToMe(`/api/zayavka/${ZID}/versions/${n}/send_me`, btn);
      }
    });
  });
}

function openVersion(n) {
  window.location.href = `version.html?id=${ZID}&v=${n}`;
}

function openLatestForEdit() {
  if (!ZAYAVKA) return;
  const params = new URLSearchParams({
    edit_id: ZID,
    object: ZAYAVKA.object_name || "",
    date: ZAYAVKA.date || "",
    from: ZAYAVKA.from_whom || "",
    payment: ZAYAVKA.payment_type || "",
  });
  window.location.href = `items.html?${params.toString()}`;
}

document.addEventListener("DOMContentLoaded", async () => {
  setupViewToggle();
  setupNavButtons();
  document.getElementById("editBtn").addEventListener("click", openLatestForEdit);

  if (!ZID) {
    document.getElementById("versionCount").textContent = "Zayavka tanlanmagan";
    return;
  }

  try {
    const [z, hist] = await Promise.all([
      apiGet(`/api/zayavka/${ZID}`),
      apiGet(`/api/zayavka/${ZID}/versions`),
    ]);
    ZAYAVKA = z;
    fillHeader(z);
    renderVersions(hist.versions || []);
  } catch (e) {
    document.getElementById("versionCount").textContent = "Yuklab bo'lmadi";
    showToast("Xatolik: " + e.message, true);
  }
});
