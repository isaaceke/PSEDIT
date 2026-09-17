const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

let onMessage;
let onDisconnect;
const sentNative = [];
const sentTabs = [];
const port = {
  onMessage: { addListener(fn) { this.fn = fn; } },
  onDisconnect: { addListener(fn) { onDisconnect = fn; } },
  postMessage(msg) { sentNative.push(msg); },
};
const chrome = {
  runtime: {
    connectNative() { return port; },
    onMessage: { addListener(fn) { onMessage = fn; } },
    lastError: null,
  },
  tabs: {
    async sendMessage(tabId, message, options) {
      sentTabs.push({ tabId, message, options });
      return { ok: true };
    }
  }
};

const context = vm.createContext({
  console,
  chrome,
  crypto: require('crypto').webcrypto,
  TextEncoder,
  TextDecoder,
  setTimeout,
  clearTimeout,
});

const protocol = fs.readFileSync('PSEDITEXT/extension/protocol.js', 'utf8');
vm.runInContext(protocol, context, { filename: 'protocol.js' });
const bg = fs.readFileSync('PSEDITEXT/extension/background.js', 'utf8').replace(/^importScripts\([^\n]+\);\s*/m, '');
vm.runInContext(bg, context, { filename: 'background.js' });

assert.equal(sentNative[0].type, 'hello');
assert.equal(sentNative[0].v, 2);
assert.equal(sentNative[0].protocol, 'PSEDIT/2');

(async () => {
  onMessage({
    type: 'PSEDIT_CANDIDATE',
    candidate: '__PSEDIT_BEGIN__ session=x\npscopy::\n"C:\\x.txt"\n__finish__',
    site: 'deepseek',
    conversation_id: '/chat/abc',
    message_id: 'm1'
  }, {
    tab: { id: 42 },
    documentId: 'doc-abc',
    frameId: 0
  });
  await new Promise(r => setTimeout(r, 100));

  const request = sentNative.find(x => x.type === 'submit');
  assert(request, 'submit not sent');
  assert.equal(request.source.tab_id, 42);
  assert.equal(request.source.document_id, 'doc-abc');
  assert.equal(request.source.frame_id, 0);
  assert.equal(request.v, 2);

  port.onMessage.fn({
    v: 2,
    type: 'result',
    protocol: 'PSEDIT/2',
    request_id: request.request_id,
    session_id: request.session_id,
    status: 'success',
    psresult: 'PSRESULT::1\n{}\n__PSRESULT_END__'
  });

  await new Promise(r => setImmediate(r));
  const routed = sentTabs.at(-1);
  assert.equal(routed.tabId, 42);
  assert.equal(routed.options.documentId, 'doc-abc');
  assert.equal(routed.message.request_id, request.request_id);
  assert.equal(routed.message.result, 'PSRESULT::1\n{}\n__PSRESULT_END__');

  console.log('extension routing: PASS');
})().catch(err => { console.error(err); process.exit(1); });
