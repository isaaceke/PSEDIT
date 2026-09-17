globalThis.PSEditAdapters = globalThis.PSEditAdapters || {};
globalThis.PSEditAdapters.grok = {
  site: "grok",
  hosts: ["grok.com", "x.com"],
  inputSelectors: [
    'div[aria-label="Ask Grok anything"]',
    'div[data-testid="chat-input"] .ProseMirror'
  ],
  sendSelectors: [
    'button[data-testid="chat-submit"]',
    'button[aria-label="Submit message"]'
  ],
  assistantSelectors: [
    '[data-message-author-role="assistant"]',
    '[data-testid="assistant-message"]'
  ]
};