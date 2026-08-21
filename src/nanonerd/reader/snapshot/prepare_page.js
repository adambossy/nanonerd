// Runs before serialization: defeat lazy loading and walk the page so
// scroll-triggered images/fonts/MathJax get a chance to load. Bounded by
// `maxMs` (passed from Python).
async (maxMs) => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  for (const img of document.querySelectorAll("img")) {
    if (img.getAttribute("loading") === "lazy") img.setAttribute("loading", "eager");
    const lazy = img.getAttribute("data-src") || img.getAttribute("data-lazy-src");
    if (lazy && !img.getAttribute("src")) img.setAttribute("src", lazy);
  }
  const started = Date.now();
  const step = Math.max(200, Math.floor(window.innerHeight * 0.8));
  let y = 0;
  while (Date.now() - started < maxMs) {
    const limit = document.documentElement.scrollHeight - window.innerHeight;
    if (y >= limit) break;
    y = Math.min(y + step, limit);
    window.scrollTo(0, y);
    await sleep(120);
  }
  window.scrollTo(0, 0);
  await sleep(250);
  return { scrolledTo: y, elapsedMs: Date.now() - started };
}
