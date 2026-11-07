/**
 * Node-runnable test for src/api/socket.js — the PDA real-time channel.
 *
 * This is the half of the offline loop that a simulator is worst at proving:
 * what happens when the link drops mid-shift.  The behaviours that matter are
 * all decisions the class makes on its own — dial or not without a token,
 * reconnect or not after a 4001, how long to wait before trying again, and
 * whether it notices a socket a proxy killed silently — and none of them need
 * a device, a network, or Expo.
 *
 * Like test_offline_queue.mjs, the module under test is loaded through a
 * data: URL, with a fake WebSocket and a fake clock standing in for the two
 * things this class actually touches.
 *
 *   node mobile/scripts/test_pda_socket.mjs
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";

const modulePath = fileURLToPath(new URL("../src/api/socket.js", import.meta.url));
const source = readFileSync(modulePath, "utf8");

// Same contract as offline.js: nothing here may reach for React Native, or
// this file stops being able to run it.
assert.deepEqual(
  source.match(/from\s+["'][^"']*(react-native|expo|async-storage|secure-store)[^"']*["']/g) ?? [],
  [],
  "socket.js must not import React Native / Expo modules",
);

const {
  createPdaSocket,
  WS_PING_INTERVAL_MS,
  WS_PONG_TIMEOUT_MS,
  WS_OFFLINE,
  WS_CONNECTING,
  WS_ONLINE,
} = await import(`data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`);

// ── Fakes ──────────────────────────────────────────────────────────────────

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  static created = [];

  // The socket code assigns these; declaring them here keeps the fake's shape
  // the same as the real one's.
  onopen = null;
  onmessage = null;
  onerror = null;
  onclose = null;

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    this.closeCode = null;
    FakeWebSocket.created.push(this);
  }

  /** Not part of the WebSocket API: the test's way of completing the handshake. */
  fireOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  fireMessage(data) {
    this.onmessage?.({ data });
  }

  /** Fires onclose the way a real stack does, so the class sees the code. */
  fireClose(code = 1006) {
    this.readyState = FakeWebSocket.CLOSED;
    this.closeCode = code;
    this.onclose?.({ code });
  }

  send(payload) {
    this.sent.push(payload);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSING;
    // A close initiated by the client still has to reach the class's close
    // handler: that is the whole point of the ping deadline.
    this.onclose?.({ code: 1000 });
  }

  get lastSent() {
    return this.sent[this.sent.length - 1];
  }
}

class FakeClock {
  constructor() {
    this.now = 0;
    this.timers = new Map();
    this.seq = 0;
    this.scheduled = [];
  }

  setTimeout(fn, ms) {
    const id = ++this.seq;
    this.timers.set(id, { id, at: this.now + ms, fn, kind: "timeout" });
    this.scheduled.push(ms);
    return id;
  }

  setInterval(fn, ms) {
    const id = ++this.seq;
    this.timers.set(id, { id, at: this.now + ms, fn, kind: "interval", every: ms });
    this.scheduled.push(ms);
    return id;
  }

  clearTimeout(id) {
    this.timers.delete(id);
  }

  clearInterval(id) {
    this.timers.delete(id);
  }

  /** Move time forward, running everything that comes due, including work the
   *  fired callbacks schedule themselves. */
  advance(ms) {
    const target = this.now + ms;
    for (let guard = 0; guard < 1000; guard += 1) {
      const due = [...this.timers.values()].filter((t) => t.at <= target).sort((a, b) => a.at - b.at)[0];
      if (!due) break;
      this.now = due.at;
      if (due.kind === "timeout") this.timers.delete(due.id);
      else due.at = this.now + due.every;
      due.fn();
    }
    this.now = target;
  }

  get pendingCount() {
    return this.timers.size;
  }
}

const realTimers = {
  setImmediate: globalThis.setImmediate,
  setTimeout: globalThis.setTimeout,
  clearTimeout: globalThis.clearTimeout,
  setInterval: globalThis.setInterval,
  clearInterval: globalThis.clearInterval,
};

function withFakes(run) {
  const clock = new FakeClock();
  FakeWebSocket.created = [];
  globalThis.WebSocket = FakeWebSocket;
  globalThis.setTimeout = clock.setTimeout.bind(clock);
  globalThis.clearTimeout = clock.clearTimeout.bind(clock);
  globalThis.setInterval = clock.setInterval.bind(clock);
  globalThis.clearInterval = clock.clearInterval.bind(clock);
  // console.warn fires on the paths under test (a refused token, a dropped
  // link); silence keeps the report readable.
  const warn = console.warn;
  console.warn = () => {};
  const restore = () => {
    Object.assign(globalThis, {
      setTimeout: realTimers.setTimeout,
      clearTimeout: realTimers.clearTimeout,
      setInterval: realTimers.setInterval,
      clearInterval: realTimers.clearInterval,
    });
    console.warn = warn;
    delete globalThis.WebSocket;
  };
  return Promise.resolve()
    .then(() => run({
      clock,
      // connect() reads the token before it dials, so a reconnect timer firing
      // does not put a socket on the record until the microtask queue drains.
      drain: () => new Promise((resolve) => realTimers.setImmediate(resolve)),
      socketOf: (over = {}) =>
        createPdaSocket({
          getToken: async () => "jwt.token-value",
          url: "ws://test.local/pda/ws",
          ...over,
        }),
    }))
    .finally(restore);
}

// ── Checks ─────────────────────────────────────────────────────────────────

const results = [];
async function check(name, fn) {
  try {
    await fn();
    results.push([true, name]);
    console.log(`  ok   ${name}`);
  } catch (err) {
    results.push([false, name]);
    console.error(`  FAIL ${name}\n       ${String(err.message).split("\n")[0]}`);
  }
}

/**
 * The server closes 4001 unless client_id *and* token arrive.  A logged-out
 * device dialing anyway gets closed instantly and reconnects forever — battery
 * spent on a handshake that cannot succeed.
 */
await check("no token, no dial", () => withFakes(async ({ socketOf }) => {
  const socket = socketOf({ getToken: async () => null });
  await socket.connect("pda-1");
  assert.equal(FakeWebSocket.created.length, 0, "dialled a socket without a token");
  assert.equal(socket.getState(), WS_OFFLINE);
}));

await check("a token we cannot read does not dial either", () => withFakes(async ({ socketOf }) => {
  const socket = socketOf({ getToken: async () => { throw new Error("keychain unlocked elsewhere"); } });
  await socket.connect("pda-1");
  assert.equal(FakeWebSocket.created.length, 0);
  assert.equal(socket.getState(), WS_OFFLINE, "a failed token read left the state optimistic");
}));

await check("client_id and token travel as encoded query params", () => withFakes(async ({ socketOf }) => {
  const socket = socketOf({ getToken: async () => "a b/c+d" });
  await socket.connect("device 1");
  const ws = FakeWebSocket.created[0];
  assert.equal(
    ws.url,
    "ws://test.local/pda/ws?client_id=device%201&token=a%20b%2Fc%2Bd",
    "the socket URL is what the server authenticates against",
  );
  assert.equal(socket.getState(), WS_CONNECTING);
}));

await check("an open socket pumps the offline queue", () => withFakes(async ({ socketOf }) => {
  let pumped = 0;
  const socket = socketOf({ onOnline: () => { pumped += 1; } });
  await socket.connect("pda-1");
  FakeWebSocket.created[0].fireOpen();
  assert.equal(pumped, 1, "a live link is the cheapest proof the queue can be replayed");
  assert.equal(socket.getState(), WS_ONLINE);
}));

await check("one device, one socket", () => withFakes(async ({ socketOf }) => {
  const socket = socketOf();
  // Two callers at the same moment: a reconnect timer and a screen.
  await Promise.all([socket.connect("pda-1"), socket.connect("pda-1")]);
  assert.equal(FakeWebSocket.created.length, 1, "the connect guard let two sockets out");
  FakeWebSocket.created[0].fireOpen();
  await socket.connect("pda-1");
  assert.equal(FakeWebSocket.created.length, 1, "connect() re-dialled a socket that was already OPEN");
}));

/**
 * 4001 means the token was refused — expired, forged, or absent.  Retrying it
 * is not recovery, it is a loop, and on a handheld it is a loop the operator
 * watches drain the battery while the banner still says 待同步.
 */
await check("a refused token stops the reconnect ladder", () => withFakes(async ({ clock, socketOf }) => {
  const socket = socketOf();
  await socket.connect("pda-1");
  FakeWebSocket.created[0].fireClose(4001);
  clock.advance(60_000);
  assert.equal(FakeWebSocket.created.length, 1, "a 4001 close was retried as if it were a dropped link");
  assert.equal(socket.getState(), WS_OFFLINE);
}));

await check("a dropped link reconnects, and backs off", () => withFakes(async ({ clock, drain, socketOf }) => {
  const socket = socketOf();
  await socket.connect("pda-1");
  FakeWebSocket.created[0].fireClose(1006);

  clock.advance(999);
  assert.equal(FakeWebSocket.created.length, 1, "reconnected before the first backoff step had passed");
  clock.advance(1);
  await drain();
  assert.equal(FakeWebSocket.created.length, 2, "never reconnected after a dropped link");

  // Second failure without an open in between: the ladder goes up.
  FakeWebSocket.created[1].fireClose(1006);
  const delays = clock.scheduled.filter((ms) => ms >= 1000);
  assert.deepEqual(delays, [1000, 2000], "backoff is not exponential");
}));

await check("backoff is capped, and a live socket resets it", () => withFakes(async ({ clock, socketOf }) => {
  const socket = socketOf();
  await socket.connect("pda-1");
  socket._retryCount = 10;
  FakeWebSocket.created[0].fireClose(1006);
  assert.equal(clock.scheduled.at(-1), 30_000, "backoff ran past its ceiling");

  await socket.connect("pda-1");
  FakeWebSocket.created[1].fireOpen();
  assert.equal(socket._retryCount, 0, "a successful open did not end the ladder");
  FakeWebSocket.created[1].fireClose(1006);
  assert.equal(clock.scheduled.at(-1), 1000, "reconnect after a healthy session did not start over at 1s");
}));

/**
 * The failure a connection badge lies about: a socket a middlebox threw away
 * still reads OPEN, so every request behind it looks online while nothing
 * reaches the server, and no close ever arrives to trigger a reconnect.
 */
await check("an unanswered ping closes the zombie socket", () => withFakes(async ({ clock, socketOf }) => {
  const socket = socketOf();
  await socket.connect("pda-1");
  const ws = FakeWebSocket.created[0];
  ws.fireOpen();

  clock.advance(WS_PING_INTERVAL_MS);
  assert.equal(ws.lastSent, "ping", 'the keepalive must be the text "ping" — the server compares that string, not JSON');

  clock.advance(WS_PONG_TIMEOUT_MS + 1);
  assert.equal(ws.readyState, FakeWebSocket.CLOSING, "a half-open socket was left open and the badge still said online");
  assert.equal(socket.getState(), WS_OFFLINE);
  assert.ok(clock.pendingCount > 0, "the close did not schedule a reconnect");
}));

await check("a pong holds the socket open", () => withFakes(async ({ clock, socketOf }) => {
  const socket = socketOf();
  await socket.connect("pda-1");
  const ws = FakeWebSocket.created[0];
  ws.fireOpen();

  for (let i = 0; i < 5; i += 1) {
    clock.advance(WS_PING_INTERVAL_MS);
    ws.fireMessage("pong");
  }
  // Stop short of the next interval tick, so this checks "answered pings keep
  // the link up" without adding a sixth unanswered one.
  clock.advance(WS_PONG_TIMEOUT_MS);
  assert.equal(ws.readyState, FakeWebSocket.OPEN, "a healthy link was dropped");
  assert.equal(ws.sent.length, 5, `expected 5 pings, saw ${ws.sent.length}`);
  assert.equal(socket.getState(), WS_ONLINE);
}));

/**
 * A pong answers the ping it answers.  The deadline has to be rearmed for the
 * next one, or a device that survives one exchange is trusted forever.
 *
 * The deadline being *shorter* than the interval is what makes that safe: an
 * answer so late that it lands after the next ping was sent has already closed
 * the socket, so it cannot clear a deadline it no longer belongs to.
 */
await check("each ping gets its own deadline", () => withFakes(async ({ clock, socketOf }) => {
  assert.ok(
    WS_PONG_TIMEOUT_MS < WS_PING_INTERVAL_MS,
    "a deadline longer than the ping interval lets a stale pong clear the current one",
  );

  const socket = socketOf();
  await socket.connect("pda-1");
  const ws = FakeWebSocket.created[0];
  ws.fireOpen();

  clock.advance(WS_PING_INTERVAL_MS);
  ws.fireMessage("pong");
  assert.equal(ws.readyState, FakeWebSocket.OPEN);

  clock.advance(WS_PING_INTERVAL_MS);          // second ping, no answer coming
  assert.equal(ws.sent.length, 2, "the heartbeat fired once and then stopped");
  clock.advance(WS_PONG_TIMEOUT_MS);
  assert.equal(ws.readyState, FakeWebSocket.CLOSING, "an unanswered second ping was tolerated forever");
}));

await check("an intentional disconnect stays disconnected", () => withFakes(async ({ clock, socketOf }) => {
  const socket = socketOf();
  await socket.connect("pda-1");
  FakeWebSocket.created[0].fireOpen();
  socket.disconnect();
  clock.advance(120_000);
  assert.equal(FakeWebSocket.created.length, 1, "logging out was followed by a reconnect");
  assert.equal(socket.getState(), WS_OFFLINE);
  assert.equal(clock.pendingCount, 0, "the ping heartbeat survived disconnect()");
}));

await check("screens hear the link state, and can stop listening", () => withFakes(async ({ socketOf }) => {
  const socket = socketOf();
  const seen = [];
  const unsubscribe = socket.subscribeState((state) => seen.push(state));
  assert.deepEqual(seen, [WS_OFFLINE], "a subscriber must learn the current state immediately");

  await socket.connect("pda-1");
  FakeWebSocket.created[0].fireOpen();
  FakeWebSocket.created[0].fireClose(1006);
  assert.deepEqual(seen, [WS_OFFLINE, WS_CONNECTING, WS_ONLINE, WS_OFFLINE]);

  unsubscribe();
  socket.disconnect();
  assert.equal(seen.length, 4, "an unsubscribed listener kept being called");
}));

await check("push messages reach subscribers; pong does not", () => withFakes(async ({ socketOf }) => {
  const socket = socketOf();
  const got = [];
  socket.onMessage((msg) => got.push(msg));
  await socket.connect("pda-1");
  const ws = FakeWebSocket.created[0];
  ws.fireOpen();
  ws.fireMessage(JSON.stringify({ entity_type: "inventory", entity_id: "sku-1", operation: "update" }));
  ws.fireMessage("pong");
  ws.fireMessage("{not json");
  assert.equal(got.length, 1, "keepalive or malformed text leaked into the message stream");
  assert.equal(got[0].entity_id, "sku-1");
}));

await check("outbound payloads are JSON, except the keepalive", () => withFakes(async ({ socketOf }) => {
  const socket = socketOf();
  await socket.connect("pda-1");
  const ws = FakeWebSocket.created[0];
  ws.fireOpen();
  socket.send("ping");
  socket.send({ type: "ack", mutation_id: 7 });
  assert.deepEqual(ws.sent, ["ping", '{"type":"ack","mutation_id":7}']);
  socket.disconnect();
  socket.send({ type: "late" });
  assert.equal(ws.sent.length, 2, "a send after disconnect reached a closed socket");
}));

await check("the socket refuses to be built without a token source or URL", () => withFakes(async () => {
  assert.throws(() => createPdaSocket({ url: "ws://x/pda/ws" }), /getToken/);
  assert.throws(() => createPdaSocket({ getToken: async () => "t" }), /socket URL/);
}));

// ── Report ─────────────────────────────────────────────────────────────────

const failed = results.filter(([ok]) => !ok).length;
console.log(`\n${results.length - failed}/${results.length} pda-socket checks passed`);
if (failed) process.exit(1);
