globalThis.PSEditAdapters = globalThis.PSEditAdapters || {};
globalThis.PSEditAdapters.deepseek = {
  site: "deepseek",
  hosts: ["chat.deepseek.com"],
  inputSelectors: [
    'textarea[placeholder="Message DeepSeek"]',
    'textarea[name="search"]',
    "textarea.ds-scroll-area"
  ],
  sendSelectors: [
    'div[role="button"].ds-button--primary',
    ".ds-button--primary"
  ],
  assistantSelectors: [
    '[data-message-author-role="assistant"]',
    ".ds-assistant-message-main-content"
  ]
};