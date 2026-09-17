globalThis.PSEditAdapters = globalThis.PSEditAdapters || {};
globalThis.PSEditAdapters.gemini = {
  site: "gemini",
  hosts: ["gemini.google.com"],
  inputSelectors: [
    'div.ql-editor[contenteditable="true"]',
    'div[aria-label="Enter a prompt for Gemini"]'
  ],
  sendSelectors: [
    'button[aria-label="Send message"]'
  ],
  assistantSelectors: [
    '[data-message-author-role="model"]',
    "model-response",
    ".model-response"
  ]
};