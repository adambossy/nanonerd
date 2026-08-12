const DEFAULT_API_BASE = "http://localhost:8000";
const input = document.getElementById("apiBase");
const status = document.getElementById("status");

chrome.storage.sync.get({ apiBase: DEFAULT_API_BASE }).then(({ apiBase }) => {
  input.value = apiBase;
});

document.getElementById("save").addEventListener("click", () => {
  const value = input.value.trim().replace(/\/+$/, "") || DEFAULT_API_BASE;
  chrome.storage.sync.set({ apiBase: value }).then(() => {
    input.value = value;
    status.textContent = "saved";
    setTimeout(() => {
      status.textContent = "";
    }, 1500);
  });
});
