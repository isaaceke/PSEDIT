(() => {
  "use strict";

  const adapters = globalThis.PSEditAdapters || {};
  const protocol = globalThis.PSEditProtocol;
  const adapter = Object.values(adapters).find(a =>
    a.hosts.some(h => location.hostname === h || location.hostname.endsWith("." + h))
  ) || null;

  if (!adapter || !protocol) return;

  const seenHashes = new Set();
  let scanTimer = null;

  function latestAssistantMessage() {
    const nodes = [];
    for (const selector of adapter.assistantSelectors || []) {
      try { document.querySelectorAll(selector).forEach(n => nodes.push(n)); } catch (_) {}
    }
    const unique = [...new Set(nodes)];
    unique.sort((a, b) => a === b ? 0 : (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    return unique.at(-1) || null;
  }

  function extractPSEdit(message) {
    if (!message) return null;
    for (const block of [...message.querySelectorAll("pre code, pre")]) {
      const text = block.innerText || block.textContent || "";
      const begin = text.indexOf("__PSEDIT_BEGIN__");
      const finish = text.lastIndexOf("__finish__");
      if (begin === -1 || finish <= begin) continue;
      const candidate = text.slice(begin, finish + "__finish__".length).trim();
      if (candidate.startsWith("__PSEDIT_BEGIN__") && candidate.endsWith("__finish__")) return candidate;
    }
    return null;
  }

  async function scan() {
    const candidate = extractPSEdit(latestAssistantMessage());
    if (!candidate) return;
    const hash = await protocol.sha256(candidate);
    if (seenHashes.has(hash)) return;
    seenHashes.add(hash);
    chrome.runtime.sendMessage({
      type: "PSEDIT_CANDIDATE",
      candidate,
      payload_hash: hash,
      site: adapter.site,
      conversation_id: location.pathname + location.search,
      message_id: null
    });
  }

  function findInput() {
    for (const selector of adapter.inputSelectors || []) {
      try {
        const element = document.querySelector(selector);
        if (element) return element;
      } catch (_) {}
    }
    return null;
  }

  function insertResult(text) {
    const input = findInput();
    if (!input) return false;
    input.focus();
    if (input instanceof HTMLTextAreaElement || input instanceof HTMLInputElement) {
      const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) setter.call(input, text); else input.value = text;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    if (input.isContentEditable) {
      input.textContent = text;
      input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
      return true;
    }
    return false;
  }

  function sendInput() {
    for (const selector of adapter.sendSelectors || []) {
      try {
        const button = document.querySelector(selector);
        if (button && !button.disabled && button.getAttribute("aria-disabled") !== "true") {
          button.click();
          return true;
        }
      } catch (_) {}
    }
    return false;
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message) return;
    if (message.type === "PSEDIT_RESULT") {
      const text = typeof message.result === "string"
        ? message.result
        : JSON.stringify(message.result, null, 2);
      const inserted = insertResult(text);
      const sent = inserted && sendInput();
      sendResponse({ ok: inserted, sent });
      return true;
    }
    if (message.type === "PSEDIT_ERROR") {
      console.error("[PSEdit] native job failed", message.request_id, message.error);
      sendResponse({ ok: false });
      return true;
    }
  });

  const observer = new MutationObserver(() => {
    clearTimeout(scanTimer);
    scanTimer = setTimeout(scan, 500);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(scan, 1200);
})();
