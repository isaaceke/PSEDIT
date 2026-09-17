globalThis.PSEditAdapters = globalThis.PSEditAdapters || {};
globalThis.PSEditAdapters.chatgpt = {
  site: "chatgpt",
  hosts: ["chatgpt.com", "chat.openai.com"],
  inputSelectors: [
    "#prompt-textarea",
    'div[aria-label="Chat with ChatGPT"]'
  ],
  sendSelectors: [
    'button[data-testid="send-button"]',
    "#composer-submit-button"
  ],
  assistantSelectors: [
    '[data-message-author-role="assistant"]',
    '[data-testid="conversation-turn-assistant"]'
  ]
};