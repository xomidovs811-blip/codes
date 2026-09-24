// Logic for search.html — "Zayavkani qidirish"

let searchResults = [];
let debounceTimer = null;

function renderResults(items) {
  const container = document.getElementById("listContainer");
  document.getElementById("resultCount").textContent = items.length
    ? `Topildi: ${items.length} ta`
    : "Hech narsa topilmadi";

  if (!items.length) {
    container.innerHTML = `<div class="empty">Natija yo'q</div>`;
    return;
  }

  container.innerHTML = items.map(renderListItemHtml).join("");
  container.querySelectorAll(".list-item").forEach((el) => {
    el.addEventListener("click", () => openDetail(Number(el.dataset.id)));
  });
}

async function openDetail(id) {
  const z = searchResults.find((x) => x.id === id) || (await apiGet(`/api/zayavka/${id}`));
  document.getElementById("modalContent").innerHTML = renderZayavkaDetailHtml(z);
  document.getElementById("modalBackdrop").classList.add("show");
}

function closeDetail() {
  document.getElementById("modalBackdrop").classList.remove("show");
}

async function runSearch() {
  const q = document.getElementById("searchInput").value.trim();
  if (!q) {
    searchResults = [];
    document.getElementById("resultCount").textContent = "Qidiruv so'zini kiriting";
    document.getElementById("listContainer").innerHTML = "";
    return;
  }
  document.getElementById("resultCount").textContent = "Qidirilmoqda...";
  try {
    const data = await apiGet(`/api/zayavka?q=${encodeURIComponent(q)}&limit=200`);
    searchResults = data.items;
    renderResults(searchResults);
  } catch (e) {
    showToast("Qidirishda xatolik: " + e.message, true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("searchBtn").addEventListener("click", runSearch);
  document.getElementById("searchInput").addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runSearch, 400);
  });
  document.getElementById("searchInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });
  document.getElementById("modalClose").addEventListener("click", closeDetail);
  document.getElementById("modalBackdrop").addEventListener("click", (e) => {
    if (e.target.id === "modalBackdrop") closeDetail();
  });
});
