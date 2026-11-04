const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const test = require("node:test");

const pricing = require("../lib/shopmonkey-pricing");
const adminModule = require("../netlify/functions/shopmonkey-pricing-admin");
const healthModule = require("../netlify/functions/shopmonkey-health");
const reconcileModule = require("../lib/shopmonkey-reconcile");
const webhookModule = require("../netlify/functions/shopmonkey-webhook");

const ORIGINAL_ENV = { ...process.env };
const NOW = 1_800_000_000;
let blobRows;
let blobVersion;

function installBlobStore(config = null) {
  blobRows = new Map();
  blobVersion = 0;
  if (config) blobRows.set("config-v1", { data: config, etag: '"1"' });
  pricing.setStoreFactoryForTests(() => ({
    getWithMetadata: async (key) => {
      const row = blobRows.get(key);
      return row ? { data: structuredClone(row.data), etag: row.etag, metadata: {} } : null;
    },
    setJSON: async (key, value, options = {}) => {
      const current = blobRows.get(key);
      if (options.onlyIfNew && current) return { modified: false };
      if (options.onlyIfMatch && (!current || current.etag !== options.onlyIfMatch)) {
        return { modified: false };
      }
      blobVersion += 1;
      const etag = `"${blobVersion + 1}"`;
      blobRows.set(key, { data: structuredClone(value), etag });
      return { modified: true, etag };
    },
  }));
}

function signedEvent(body, { secret = "test-secret", messageId = "delivery-1", now = NOW } = {}) {
  const raw = JSON.stringify(body);
  const signature = crypto
    .createHmac("sha256", secret)
    .update(`${messageId}.${now}.${raw}`, "utf8")
    .digest("base64");
  return {
    httpMethod: "POST",
    headers: {
      "content-type": "application/json",
      "webhook-id": messageId,
      "webhook-timestamp": String(now),
      "webhook-signature": `v1,${signature}`,
      "webhook-version": "3",
    },
    body: raw,
  };
}

function jsonResponse(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => ({ success: true, data }) };
}

function jsonEnvelope(data, meta, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => ({ success: true, data, meta }) };
}

function managementEvent(method, payload, nonce) {
  const body = payload === undefined ? Buffer.alloc(0) : Buffer.from(JSON.stringify(payload), "utf8");
  const timestamp = String(NOW);
  return {
    httpMethod: method,
    headers: {
      ...(payload === undefined ? {} : { "content-type": "application/json" }),
      "x-dtm-timestamp": timestamp,
      "x-dtm-nonce": nonce,
      "x-dtm-signature": pricing.managementSignature({
        secret: "api-key", timestamp, nonce, method, body,
      }),
    },
    body: body.toString("utf8"),
  };
}

function orderEvent() {
  return { apiVersion: 3, operation: "UPDATE", table: "order", data: { id: "order-test" } };
}

function installEnvironment() {
  process.env.SHOPMONKEY_WEBHOOK_SECRET = "test-secret";
  process.env.SHOPMONKEY_API_KEY = "api-key";
  process.env.SHOPMONKEY_PRICING_TEST_ORDER_ID = "order-test";
  installBlobStore();
}

test.afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  global.fetch = undefined;
  pricing.setStoreFactoryForTests(null);
});
test("validates current and rotated Shopmonkey signatures", () => {
  const payload = Buffer.from('{"ok":true}', "utf8");
  const current = crypto.createHmac("sha256", "secret").update(`id.${NOW}.`).update(payload).digest("base64");
  assert.equal(webhookModule.__test.verifySignature({
    secret: "secret",
    messageId: "id",
    timestamp: String(NOW),
    signature: `v1,invalid v1,${current}`,
    payload,
    nowSeconds: NOW,
  }), true);
  assert.equal(webhookModule.__test.verifySignature({
    secret: "secret",
    messageId: "id",
    timestamp: String(NOW - 301),
    signature: `v1,${current}`,
    payload,
    nowSeconds: NOW,
  }), false);

  const standardKey = crypto.randomBytes(32);
  const serializedSecret = standardKey.toString("base64url");
  const standardSignature = crypto
    .createHmac("sha256", standardKey)
    .update(`id.${NOW}.`)
    .update(payload)
    .digest("base64");
  assert.equal(webhookModule.__test.verifySignature({
    secret: serializedSecret,
    messageId: "id",
    timestamp: String(NOW),
    signature: `v1,${standardSignature}`,
    payload,
    nowSeconds: NOW,
  }), true);
});

test("rejects unsigned deliveries before calling Shopmonkey", async () => {
  installEnvironment();
  global.fetch = async () => assert.fail("fetch must not be called");
  const event = signedEvent(orderEvent());
  event.headers["webhook-signature"] = "v1,invalid";

  const result = await webhookModule.handler(event);

  assert.equal(result.statusCode, 401);
  assert.deepEqual(JSON.parse(result.body), { ok: false, error: "invalid_signature" });
});

test("stores hosted pricing with optimistic revision checks", async () => {
  installEnvironment();
  const realNow = Date.now;
  Date.now = () => NOW * 1000;
  try {
    const config = pricing.defaultConfig("order-test");
    const first = await adminModule.handler(managementEvent(
      "PUT", { config, expected_revision: "" }, "0123456789abcdef0123456789abcdef",
    ));
    assert.equal(first.statusCode, 200);
    const saved = JSON.parse(first.body).config;
    assert.ok(saved.revision);

    const conflict = await adminModule.handler(managementEvent(
      "PUT", { config, expected_revision: "" }, "1123456789abcdef0123456789abcdef",
    ));
    assert.equal(conflict.statusCode, 409);
    assert.equal(JSON.parse(conflict.body).error, "pricing_config_conflict");
  } finally {
    Date.now = realNow;
  }
});
test("health fails closed until reconciliation is current", async () => {
  installEnvironment();
  const config = pricing.defaultConfig("order-test");
  config.revision = "revision";
  config.updated_at = new Date(NOW * 1000).toISOString();
  installBlobStore(config);
  const realNow = Date.now;
  Date.now = () => NOW * 1000;
  try {
    const before = await healthModule.handler({ httpMethod: "GET" });
    assert.equal(before.statusCode, 503);
    await pricing.recordHealth({
      last_reconcile_success_at: new Date((NOW - (76 * 60)) * 1000).toISOString(),
      last_api_check_ok: true,
    });
    const stale = await healthModule.handler({ httpMethod: "GET" });
    assert.equal(stale.statusCode, 503);
    await pricing.recordHealth({
      last_reconcile_success_at: new Date((NOW - 60) * 1000).toISOString(),
      last_api_check_ok: true,
    });
    const after = await healthModule.handler({ httpMethod: "GET" });
    assert.equal(after.statusCode, 200);
    assert.equal(JSON.parse(after.body).status, "healthy");
    await pricing.recordHealth({
      last_received_at: new Date(NOW * 1000).toISOString(),
      last_success_at: new Date(NOW * 1000).toISOString(),
      last_result: "no_change",
    });
    const afterWebhook = await healthModule.handler({ httpMethod: "GET" });
    assert.equal(afterWebhook.statusCode, 200);
    assert.equal(JSON.parse(afterWebhook.body).reconciliation_fresh, true);
  } finally {
    Date.now = realNow;
  }
});
test("reconciliation only selects recently changed orders", () => {
  assert.equal(reconcileModule.recentlyUpdated({
    updatedDate: new Date((NOW - 60) * 1000).toISOString(),
  }, NOW), true);
  assert.equal(reconcileModule.recentlyUpdated({
    updatedDate: new Date((NOW - 901) * 1000).toISOString(),
  }, NOW), false);
});

test("scheduled reconciliation records health through the shared runner", async () => {
  installEnvironment();
  const config = pricing.defaultConfig("order-test");
  config.enabled = false;
  config.revision = "revision";
  installBlobStore(config);

  const result = await reconcileModule.runReconciliation();
  const health = blobRows.get("health-v1").data;

  assert.equal(result.result, "pricing_disabled");
  assert.equal(health.last_api_check_ok, true);
  assert.equal(health.last_reconcile_result, "pricing_disabled");
});

test("reconciliation pages from the order-list tail because descending sort is ignored", async () => {
  const urls = [];
  global.fetch = async (url) => {
    urls.push(url);
    if (url.endsWith("/order?limit=1&skip=0")) return jsonEnvelope([], { total: 60 });
    if (url.endsWith("/order?limit=75&skip=10")) return jsonEnvelope([
      { id: "old", updatedDate: new Date((NOW - 901) * 1000).toISOString() },
      { id: "deleted", deleted: true, updatedDate: new Date((NOW - 10) * 1000).toISOString() },
      { id: "recent", updatedDate: new Date((NOW - 10) * 1000).toISOString() },
    ], { total: 60 });
    assert.fail(`unexpected URL: ${url}`);
  };
  assert.deepEqual(await reconcileModule.recentOrderIds("api-key", NOW), ["recent"]);
  assert.equal(urls.length, 2);
});

test("reprices any recent Whelen line from its current inventory Retail value", async () => {
  installEnvironment();
  const realNow = Date.now;
  Date.now = () => NOW * 1000;
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/order/order-test")) {
      return jsonResponse({ id: "order-test", customerId: "customer-test", authorized: false, invoiced: false, readOnly: false });
    }
    if (url.endsWith("/order/order-test/service")) {
      return jsonResponse([{ id: "service-test", parts: [{
        id: "line-test",
        inventoryPartId: "inventory-test",
        retailCostCents: 30000,
        pricingMatrixId: null,
        createdDate: new Date((NOW - 2) * 1000).toISOString(),
      }] }]);
    }
    if (url.endsWith("/inventory_part/inventory-test")) {
      return jsonResponse({ id: "inventory-test", number: "IONT", retailCostCents: 30000, brand: { name: "Whelen" }, deleted: false });
    }
    if (url.endsWith("/customer/customer-test")) {
      return jsonResponse({ id: "customer-test", labels: [{ name: "$ Retail $" }] });
    }
    if (url.includes("/part/line-test?includeOrder=false")) return jsonResponse({ id: "line-test" });
    assert.fail(`unexpected URL: ${url}`);
  };
  try {
    const result = await webhookModule.handler(signedEvent(orderEvent(), { messageId: "reprice-delivery" }));
    const body = JSON.parse(result.body);

    assert.equal(result.statusCode, 200);
    assert.equal(body.result, "repriced");
    assert.equal(body.target_cents, 19200);
    assert.equal(body.eligible_lines, 1);
    assert.equal(body.customer_type, "retail");
    const update = calls.find((call) => call.options.method === "PUT");
    assert.deepEqual(JSON.parse(update.options.body), { retailCostCents: 19200 });
  } finally {
    Date.now = realNow;
  }
});

test("schema v2 matches stable Shopmonkey label and brand IDs instead of typed names", async () => {
  const config = pricing.defaultConfig("order-test");
  config.schema_version = 2;
  config.customer_types[0].label_id = "retail-label-id";
  config.customer_types[0].label = "old label name";
  config.customer_types[1].label_id = "wholesale-label-id";
  config.rules[0].brand_id = "whelen-brand-id";
  config.rules[0].brand = "old brand name";
  config.rules[1].brand_id = "whelen-brand-id";
  const validated = pricing.validateAndNormalizeConfig(config);
  assert.equal(validated.ok, true);

  const methods = [];
  global.fetch = async (url, options) => {
    methods.push(options.method);
    if (url.endsWith("/order/order-test")) {
      return jsonResponse({ id: "order-test", customerId: "customer-test", authorized: false, invoiced: false, readOnly: false });
    }
    if (url.endsWith("/order/order-test/service")) {
      return jsonResponse([{ id: "service-test", parts: [{
        id: "line-test", inventoryPartId: "inventory-test", retailCostCents: 10000,
        createdDate: new Date((NOW - 2) * 1000).toISOString(),
      }] }]);
    }
    if (url.endsWith("/customer/customer-test")) {
      return jsonResponse({ labels: [{ id: "retail-label-id", name: "renamed retail label" }] });
    }
    if (url.endsWith("/inventory_part/inventory-test")) {
      return jsonResponse({
        id: "inventory-test", retailCostCents: 10000,
        brand: { id: "whelen-brand-id", name: "renamed Whelen" }, deleted: false,
      });
    }
    if (url.includes("/part/line-test?includeOrder=false")) return jsonResponse({ id: "line-test" });
    assert.fail(`unexpected URL: ${url}`);
  };

  const result = await webhookModule.__test.applyPricingForOrder({
    apiKey: "api-key", orderId: "order-test", nowSeconds: NOW,
    maxLineAgeSeconds: 600, config: validated.config,
  });

  assert.equal(result.result, "repriced");
  assert.equal(result.target_cents, 6400);
  assert.equal(methods.includes("PUT"), true);
});

test("schema v2 rejects typed labels and brands without real Shopmonkey IDs", () => {
  const config = pricing.defaultConfig("order-test");
  config.schema_version = 2;
  const result = pricing.validateAndNormalizeConfig(config);
  assert.equal(result.ok, false);
  assert.match(result.errors.join(" "), /existing Shopmonkey Customer label/);
  assert.match(result.errors.join(" "), /existing Shopmonkey Part brand/);
});

test("schema v2 permits zero-percent placeholders only when disabled", () => {
  const config = pricing.defaultConfig("order-test");
  config.rules.push({
    id: "pending-brand", brand: "Pending", customer_type_id: "retail",
    basis: "retail", operation: "discount", percent: 0, enabled: false,
  });
  assert.equal(pricing.validateAndNormalizeConfig(config).ok, true);
  config.rules.at(-1).enabled = true;
  assert.equal(pricing.validateAndNormalizeConfig(config).ok, false);
});

test("uses the configured wholesale rule and cost-markup rules", () => {
  const defaults = pricing.defaultConfig("order-test");
  const wholesale = defaults.rules.find((rule) => rule.id === "whelen-wholesale");
  assert.equal(pricing.targetPriceCents({ retailCostCents: 30000 }, wholesale), 17100);
  assert.equal(pricing.targetPriceCents(
    { retailCostCents: 30000, wholesaleCostCents: 10000 },
    { basis: "cost", operation: "markup", percent: 25 },
  ), 12500);
});

test("does not treat a retained matrix ID as automatic after a later edit", () => {
  const createdDate = new Date(NOW * 1000).toISOString();
  assert.equal(webhookModule.__test.matrixPriceLooksAutomatic({
    pricingMatrixId: "matrix",
    createdDate,
    updatedDate: new Date((NOW + 2) * 1000).toISOString(),
  }), true);
  assert.equal(webhookModule.__test.matrixPriceLooksAutomatic({
    pricingMatrixId: "matrix",
    createdDate,
    updatedDate: new Date((NOW + 30) * 1000).toISOString(),
  }), false);
});

test("rejects ambiguous customer labels and duplicate brand/type rules", async () => {
  const config = pricing.defaultConfig("order-test");
  config.rules.push({ ...config.rules[0], id: "duplicate" });
  const invalid = pricing.validateAndNormalizeConfig(config);
  assert.equal(invalid.ok, false);
  assert.match(invalid.errors.join(" "), /Only one rule/);

  global.fetch = async (url) => {
    if (url.endsWith("/order/order-test")) {
      return jsonResponse({ id: "order-test", customerId: "customer-test", authorized: false, invoiced: false, readOnly: false });
    }
    if (url.endsWith("/order/order-test/service")) return jsonResponse([]);
    if (url.endsWith("/customer/customer-test")) {
      return jsonResponse({ labels: [{ name: "$ Retail $" }, { name: "$ Wholesale $" }] });
    }
    assert.fail(`unexpected URL: ${url}`);
  };
  const result = await webhookModule.__test.applyPricingForOrder({
    apiKey: "api-key",
    orderId: "order-test",
    nowSeconds: NOW,
    maxLineAgeSeconds: 600,
    config: pricing.defaultConfig("order-test"),
  });
  assert.deepEqual(result, { result: "customer_type_ambiguous", repriced: 0 });
});

test("preserves a recent custom price with no pricing matrix", async () => {
  installEnvironment();
  const realNow = Date.now;
  Date.now = () => NOW * 1000;
  const methods = [];
  global.fetch = async (url, options) => {
    methods.push(options.method);
    if (url.endsWith("/order/order-test")) {
      return jsonResponse({ id: "order-test", customerId: "customer-test", authorized: false, invoiced: false, readOnly: false });
    }
    if (url.endsWith("/order/order-test/service")) {
      return jsonResponse([{ id: "service-test", parts: [{
        id: "line-test",
        inventoryPartId: "inventory-test",
        partNumber: "M4",
        retailCostCents: 9000,
        pricingMatrixId: null,
        createdDate: new Date((NOW - 2) * 1000).toISOString(),
      }] }]);
    }
    if (url.endsWith("/inventory_part/inventory-test")) {
      return jsonResponse({ id: "inventory-test", number: "M4", retailCostCents: 10000, brand: { name: "Whelen" }, deleted: false });
    }
    if (url.endsWith("/customer/customer-test")) {
      return jsonResponse({ id: "customer-test", labels: [{ name: "$ Retail $" }] });
    }
    assert.fail(`unexpected URL: ${url}`);
  };
  try {
    const result = await webhookModule.handler(signedEvent(orderEvent(), { messageId: "manual-delivery" }));
    const body = JSON.parse(result.body);

    assert.equal(result.statusCode, 200);
    assert.equal(body.result, "no_change");
    assert.equal(body.manual_preserved, 1);
    assert.equal(methods.includes("PUT"), false);
  } finally {
    Date.now = realNow;
  }
});
