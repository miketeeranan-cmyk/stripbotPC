// t(lang, key, kwargs) looks up window.__STRINGS__[key][lang] (falling back
// to English) and does simple {name}-style formatting, mirroring the old
// Textual dashboard's Python-side t() helper -- kept client-side now since
// the server never localizes.
function t(lang, key, kwargs) {
  const entry = window.__STRINGS__[key];
  if (!entry) return key;
  let text = entry[lang] || entry.en || key;
  if (kwargs) {
    for (const k in kwargs) {
      text = text.split(`{${k}}`).join(kwargs[k]);
    }
  }
  return text;
}

// Walks every element with a data-i18n="key" attribute and fills its text.
function applyI18n(lang) {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(lang, el.getAttribute("data-i18n"));
  });
}
