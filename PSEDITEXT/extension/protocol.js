(() => {
  "use strict";
  const root = globalThis;

  function makeId(prefix) {
    const bytes = crypto.getRandomValues(new Uint8Array(12));
    return prefix + "_" + Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  }

  async function sha256(text) {
    const data = new TextEncoder().encode(text);
    const digest = await crypto.subtle.digest("SHA-256", data);
    return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, "0")).join("");
  }

  async function createRequest(candidate, source) {
    return {
      v: 2,
      protocol: "PSEDIT/2",
      type: "submit",
      request_id: makeId("req"),
      session_id: source.session_id || makeId("sess"),
      payload_hash: await sha256(candidate),
      source: {
        site: source.site || null,
        tab_id: source.tab_id ?? null,
        document_id: source.document_id || null,
        frame_id: source.frame_id ?? 0,
        conversation_id: source.conversation_id || null,
        message_id: source.message_id || null
      },
      payload: candidate
    };
  }

  function isValidEnvelope(message) {
    return !!(
      message && message.v === 2 &&
      typeof message.type === "string" &&
      typeof message.request_id === "string"
    );
  }

  root.PSEditProtocol = { makeId, sha256, createRequest, isValidEnvelope };
})();
