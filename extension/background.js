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

async function save(url, title) {
  if (!/^https?:/i.test(url || "")) {
    flashBadge("!", "#b3261e");
    return;
  }
  try {
    const base = await apiBase();
    const response = await fetch(`${base}/api/articles`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, title: title || undefined }),
    });
    if (!response.ok) throw new Error(String(response.status));
    const data = await response.json();
    if (data.duplicate) {
      flashBadge("dup", "#6d675e");
    } else {
      flashBadge("✓", "#3d7a3f");
    }
  } catch {
    flashBadge("!", "#b3261e");
  }
}

chrome.action.onClicked.addListener((tab) => {
  save(tab.url, tab.title);
});

chrome.commands.onCommand.addListener((command, tab) => {
  if (command === "save-page" && tab) {
    save(tab.url, tab.title);
  }
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "save-link",
    title: "Save link to nano::nerd",
    contexts: ["link"],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "save-link") {
    save(info.linkUrl, undefined);
  }
});
