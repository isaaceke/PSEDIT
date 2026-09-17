importScripts("protocol.js");

(() => {
  "use strict";

  const NATIVE_HOST = "com.psedit.bridge";
  let nativePort = null;
  let reconnectTimer = null;
  const pending = new Map();

  function connectNative() {
    if (nativePort) return nativePort;
    try {
      const port = chrome.runtime.connectNative(NATIVE_HOST);
      nativePort = port;
      port.onMessage.addListener(handleNativeMessage);
      port.onDisconnect.addListener(() => {
        nativePort = null;
        const err = chrome.runtime.lastError?.message || "Native host disconnected.";
        for (const [requestId, entry] of pending) {
          pending.delete(requestId);
          if (entry.tabId != null) {
            const options = entry.documentId ? { documentId: entry.documentId } : { frameId: entry.frameId ?? 0 };
            void chrome.tabs.sendMessage(entry.tabId, {
              type: "PSEDIT_ERROR",
              request_id: requestId,
              error: err
            }, options).catch(() => {});
          }
        }
        if (!reconnectTimer) {
          reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connectNative();
          }, 1500);
        }
      });
      port.postMessage({
        v: 2,
        protocol: "PSEDIT/2",
        type: "hello",
        app: "PSEdit AI Runtime",
        version: "12.0.0"
      });
      return port;
    } catch (error) {
      nativePort = null;
      throw error;
    }
  }

  async function handleCandidate(message, sender) {
    if (!message || message.type !== "PSEDIT_CANDIDATE") return;
    if (!sender.tab?.id) return;

    const source = {
      site: message.site,
      tab_id: sender.tab.id,
      document_id: sender.documentId || message.document_id || null,
      frame_id: sender.frameId ?? 0,
      conversation_id: message.conversation_id,
      message_id: message.message_id
    };

    const request = await PSEditProtocol.createRequest(message.candidate, source);
    pending.set(request.request_id, {
      tabId: source.tab_id,
      documentId: source.document_id,
      frameId: source.frame_id,
      site: source.site,
      createdAt: Date.now(),
    });

    try {
      connectNative().postMessage(request);
    } catch (error) {
      pending.delete(request.request_id);
      try {
        await chrome.tabs.sendMessage(source.tab_id, {
          type: "PSEDIT_ERROR",
          request_id: request.request_id,
          error: String(error)
        }, source.document_id ? { documentId: source.document_id } : { frameId: source.frame_id });
      } catch (_) {}
    }
  }

  async function routeResult(message) {
    const job = pending.get(message.request_id);
    if (!job) return;
    pending.delete(message.request_id);

    if (job.tabId == null) return;
    const payload = {
      type: "PSEDIT_RESULT",
      request_id: message.request_id,
      result: message.psresult || message.result || message
    };
    const options = job.documentId ? { documentId: job.documentId } : { frameId: job.frameId ?? 0 };
    try {
      await chrome.tabs.sendMessage(job.tabId, payload, options);
    } catch (error) {
      console.error("[PSEdit] result routing failed", message.request_id, error);
    }
  }

  function handleNativeMessage(message) {
    if (!PSEditProtocol.isValidEnvelope(message)) return;
    if (message.type === "result" || message.type === "error") {
      void routeResult(message);
    }
  }

  chrome.runtime.onMessage.addListener((message, sender) => {
    if (message?.type === "PSEDIT_CANDIDATE") void handleCandidate(message, sender);
  });

  connectNative();
})();
