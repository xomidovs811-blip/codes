/**
 * Fino — qurilish sohasi uchun moliyaviy boshqaruv ilovasi
 * gstemplate.gs : web-app routing, template rendering va umumiy yordamchi funksiyalar.
 *
 * Navigatsiya:  <WEB_APP_URL>?page=dashboard | xodimlar | sozlamalar
 * template.html umumiy layout (sidebar, header, footer) bo'lib, tanlangan sahifa
 * mazmuni uning ichiga include() orqali joylashtiriladi.
 */

var APP_NAME = 'Fino';
var DB_FILE_NAME = 'Database';
var DEFAULT_PAGE = 'dashboard';

/** Ruxsat etilgan sahifalar: kalit = ?page= qiymati va .html fayl nomi. */
var PAGES = {
  dashboard:  { title: 'Dashboard',  icon: 'fa-chart-pie' },
  xodimlar:   { title: 'Xodimlar',   icon: 'fa-users' },
  sozlamalar: { title: 'Sozlamalar', icon: 'fa-gear' }
};

/** Web-app kirish nuqtasi. */
function doGet(e) {
  var requested = (e && e.parameter && e.parameter.page) || DEFAULT_PAGE;
  var page = PAGES.hasOwnProperty(requested) ? requested : DEFAULT_PAGE;

  var tpl = HtmlService.createTemplateFromFile('template');
  tpl.page = page;
  tpl.pages = PAGES;
  tpl.pageTitle = PAGES[page].title;
  tpl.appName = APP_NAME;
  tpl.appUrl = getScriptUrl();
  tpl.year = new Date().getFullYear();

  return tpl.evaluate()
    .setTitle(APP_NAME + ' | ' + PAGES[page].title)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * Boshqa .html faylni template ichiga qo'shish.
 * Fayl ham template sifatida baholanadi, shuning uchun sahifalarda <?= ?> ishlatish mumkin.
 */
function include(filename) {
  var tpl = HtmlService.createTemplateFromFile(filename);
  tpl.appUrl = getScriptUrl();
  tpl.pages = PAGES;
  return tpl.evaluate().getContent();
}

/** Joriy deploy qilingan web-app URL manzili. */
function getScriptUrl() {
  return ScriptApp.getService().getUrl();
}

/** Klient tomonidan chaqirish uchun: sahifa URL manzili. */
function getPageUrl(page) {
  return getScriptUrl() + '?page=' + (PAGES.hasOwnProperty(page) ? page : DEFAULT_PAGE);
}

/**
 * "Database" spreadsheet faylini qaytaradi.
 * Skript spreadsheetga bog'langan bo'lsa — o'sha fayl, aks holda Drive'dan nomi bo'yicha qidiradi
 * va topilmasa yangisini yaratadi.
 */
function getDatabase() {
  var active = SpreadsheetApp.getActiveSpreadsheet();
  if (active) return active;

  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('DB_ID');
  if (id) {
    try { return SpreadsheetApp.openById(id); } catch (err) { /* qayta qidiramiz */ }
  }

  var files = DriveApp.getFilesByName(DB_FILE_NAME);
  var ss = files.hasNext() ? SpreadsheetApp.open(files.next()) : SpreadsheetApp.create(DB_FILE_NAME);
  props.setProperty('DB_ID', ss.getId());
  return ss;
}

/** Nomi bo'yicha varaqni qaytaradi, mavjud bo'lmasa sarlavhalar bilan yaratadi. */
function getSheet(name, headers) {
  var ss = getDatabase();
  var sheet = ss.getSheetByName(name);
  if (!sheet) {
    sheet = ss.insertSheet(name);
    if (headers && headers.length) {
      sheet.getRange(1, 1, 1, headers.length)
        .setValues([headers])
        .setFontWeight('bold')
        .setBackground('#0B2545')
        .setFontColor('#FFFFFF');
      sheet.setFrozenRows(1);
    }
  }
  return sheet;
}
