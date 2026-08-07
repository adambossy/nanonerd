const DEFAULT_API_BASE = "http://localhost:8000";

async function apiBase() {
  const { apiBase: base } = await chrome.storage.sync.get({
    apiBase: DEFAULT_API_BASE,
  });
  return base.replace(/\/+$/, "");
}

function flashBadge(text, color) {
  chrome.action.setBadgeBackgroundColor({ color });
  chrome.action.setBadgeText({ text });
  setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
}

function renderToast(message, ok) {
  const id = "nanonerd-toast";
  document.getElementById(id)?.remove();
  const el = document.createElement("div");
  el.id = id;
  el.textContent = message;
  el.style.cssText = `
    position: fixed; top: 16px; right: 16px; z-index: 2147483647;
    background: ${ok ? "#3d7a3f" : "#b3261e"}; color: #fff;
    padding: 10px 16px; border-radius: 8px;
    font: 14px/1.4 -apple-system, BlinkMacSystemFont, sans-serif;
    box-shadow: 0 2px 10px rgba(0,0,0,.35); max-width: 320px;
    transition: opacity .3s ease;
  `;
  document.documentElement.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

async function showToast(tabId, message, ok) {
  if (!tabId) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: renderToast,
      args: [message, ok],
    });
  } catch {
    // page doesn't allow content injection (chrome:// pages, web store, etc.)
  }
}

async function save(url, title, tabId) {
  if (!/^https?:/i.test(url || "")) {
    flashBadge("!", "#b3261e");
    showToast(tabId, "nano::nerd: can't save this page (not http/https).", false);
    return;
  }
  try {
    const base = await apiBase();
    const response = await fetch(`${base}/api/articles`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, title: title || undefined }),
    });
    if (!response.ok) {
      let detail = "";
      try {
        detail = await response.text();
      } catch {
        // ignore
      }
      throw new Error(`server returned ${response.status}${detail ? `: ${detail}` : ""}`);
    }
    const data = await response.json();
    if (data.duplicate) {
      flashBadge("dup", "#6d675e");
      showToast(tabId, "nano::nerd: already saved.", true);
    } else {
      flashBadge("✓", "#3d7a3f");
      showToast(tabId, "nano::nerd: saved.", true);
    }
  } catch (err) {
    flashBadge("!", "#b3261e");
    showToast(tabId, `nano::nerd: save failed — ${err.message}`, false);
  }
}

chrome.action.onClicked.addListener((tab) => {
  save(tab.url, tab.title, tab.id);
});

chrome.commands.onCommand.addListener((command, tab) => {
  if (command === "save-page" && tab) {
    save(tab.url, tab.title, tab.id);
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "save-link",
    title: "Save link to nano::nerd",
    contexts: ["link"],
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "save-link") {
    save(info.linkUrl, undefined, tab?.id);
  }
});
