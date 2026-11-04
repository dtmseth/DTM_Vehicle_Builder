"use strict";

const crypto = require("node:crypto");
const { getStore } = require("@netlify/blobs");

const STORE_NAME = "shopmonkey-pricing";
const CONFIG_KEY = "config-v1";
const HEALTH_KEY = "health-v1";
const MANAGEMENT_TOLERANCE_SECONDS = 5 * 60;

let storeFactoryOverride = null;

function clean(value) {
  return String(value == null ? "" : value).trim();
}

function normalized(value) {
  return clean(value).toLowerCase();
}

function defaultConfig(testOrderId = process.env.SHOPMONKEY_PRICING_TEST_ORDER_ID || "") {
  return {
    schema_version: 1,
    revision: "",
    updated_at: "",
    enabled: true,
    mode: "test",
    test_order_id: clean(testOrderId),
    max_line_age_seconds: 600,
    preserve_custom_prices: true,
    customer_types: [
      { id: "retail", name: "Retail", label: "$ Retail $", enabled: true },
      { id: "wholesale", name: "Wholesale", label: "$ Wholesale $", enabled: true },
      { id: "default", name: "Default / untagged", label: "", match_untagged: true, enabled: true },
    ],
    rules: [
      {
        id: "whelen-retail",
        brand: "Whelen",
        customer_type_id: "retail",
        basis: "retail",
        operation: "discount",
        percent: 36,
        enabled: true,
      },
      {
        id: "whelen-wholesale",
        brand: "Whelen",
        customer_type_id: "wholesale",
        basis: "retail",
        operation: "discount",
        percent: 43,
        enabled: true,
      },
    ],
  };
}

function slug(value, fallback) {
  const result = normalized(value)
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
  return result || fallback;
}

function validateAndNormalizeConfig(input, { testOrderId = "" } = {}) {
  const source = input && typeof input === "object" ? input : {};
  const errors = [];
  const schemaVersion = Number(source.schema_version) >= 2 ? 2 : 1;
  const mode = source.mode === "production" ? "production" : "test";
  const configuredTestOrderId = clean(source.test_order_id || testOrderId);
  if (mode === "test" && !configuredTestOrderId) {
    errors.push("A test order ID is required in test mode.");
  }

  const customerTypes = [];
  const typeIds = new Set();
  const labels = new Set();
  let untaggedTypes = 0;
  for (const [index, row] of (Array.isArray(source.customer_types) ? source.customer_types : []).entries()) {
    if (!row || typeof row !== "object") continue;
    const name = clean(row.name).slice(0, 80);
    const matchUntagged = row.match_untagged === true;
    const label = matchUntagged ? "" : clean(row.label).slice(0, 120);
    const labelId = matchUntagged ? "" : clean(row.label_id).slice(0, 128);
    const id = slug(row.id || name, `customer-type-${index + 1}`);
    if (!name || (!matchUntagged && !label)) {
      errors.push(`Customer type ${index + 1} needs a name and exact Shopmonkey label, or must match untagged customers.`);
      continue;
    }
    if (schemaVersion >= 2 && row.enabled !== false && !matchUntagged && !labelId) {
      errors.push(`Customer type ${index + 1} must use an existing Shopmonkey Customer label.`);
    }
    if (matchUntagged) untaggedTypes += 1;
    if (typeIds.has(id)) errors.push(`Customer type ID “${id}” is duplicated.`);
    if (label && labels.has(normalized(label))) errors.push(`Customer label “${label}” is duplicated.`);
    typeIds.add(id);
    if (label) labels.add(normalized(label));
    customerTypes.push({
      id, name, label_id: labelId, label, match_untagged: matchUntagged,
      enabled: row.enabled !== false,
    });
  }
  if (untaggedTypes > 1) errors.push("Only one customer type may match untagged customers.");
  if (!customerTypes.some((row) => row.enabled)) {
    errors.push("At least one customer type must be enabled.");
  }

  const rules = [];
  const ruleKeys = new Set();
  for (const [index, row] of (Array.isArray(source.rules) ? source.rules : []).entries()) {
    if (!row || typeof row !== "object") continue;
    const brand = clean(row.brand).slice(0, 120);
    const brandId = clean(row.brand_id).slice(0, 128);
    const customerTypeId = slug(row.customer_type_id, "");
    const basis = row.basis === "cost" ? "cost" : "retail";
    const operation = row.operation === "markup" ? "markup" : "discount";
    const percent = Number(row.percent);
    if (!brand || !customerTypeId) {
      errors.push(`Price rule ${index + 1} needs a brand and customer type.`);
      continue;
    }
    if (schemaVersion >= 2 && row.enabled !== false && !brandId) {
      errors.push(`Price rule ${index + 1} must use an existing Shopmonkey Part brand.`);
    }
    if (!typeIds.has(customerTypeId)) {
      errors.push(`Price rule ${index + 1} refers to an unknown customer type.`);
    }
    if (!Number.isFinite(percent) || percent < 0 || percent > 500 || (row.enabled !== false && percent === 0)) {
      errors.push(`Price rule ${index + 1} needs a percentage greater than 0 when enabled and no more than 500.`);
    }
    if (operation === "discount" && percent >= 100) {
      errors.push(`Price rule ${index + 1} discount must be less than 100%.`);
    }
    const key = `${normalized(brand)}|${customerTypeId}`;
    if (ruleKeys.has(key)) {
      errors.push(`Only one rule is allowed for ${brand} and ${customerTypeId}.`);
    }
    ruleKeys.add(key);
    rules.push({
      id: slug(row.id || `${brand}-${customerTypeId}`, `rule-${index + 1}`),
      brand_id: brandId,
      brand,
      customer_type_id: customerTypeId,
      basis,
      operation,
      percent: Math.round(percent * 1000) / 1000,
      enabled: row.enabled !== false,
    });
  }
  if (!rules.some((row) => row.enabled)) errors.push("At least one price rule must be enabled.");

  const requestedAge = Number(source.max_line_age_seconds);
  const maxLineAgeSeconds = Number.isFinite(requestedAge)
    ? Math.min(3600, Math.max(60, Math.round(requestedAge)))
    : 600;

  return {
    ok: errors.length === 0,
    errors,
    config: {
      schema_version: schemaVersion,
      revision: clean(source.revision),
      updated_at: clean(source.updated_at),
      enabled: source.enabled !== false,
      mode,
      test_order_id: configuredTestOrderId,
      max_line_age_seconds: maxLineAgeSeconds,
      // This is a production invariant, not a user-disableable preference.
      preserve_custom_prices: true,
      customer_types: customerTypes,
      rules,
    },
  };
}

function targetPriceCents({ retailCostCents, wholesaleCostCents }, rule) {
  const base = Number(rule.basis === "cost" ? wholesaleCostCents : retailCostCents);
  if (!Number.isSafeInteger(base) || base <= 0) return null;
  const factor = rule.operation === "markup"
    ? 1 + Number(rule.percent) / 100
    : 1 - Number(rule.percent) / 100;
  const target = Math.round(base * factor);
  return Number.isSafeInteger(target) && target > 0 ? target : null;
}

async function pricingStore() {
  if (storeFactoryOverride) return storeFactoryOverride(STORE_NAME);
  // Lambda-compatible functions receive the site and token context, but not
  // the uncached endpoint required by Netlify Blobs' strong-read mode. ETag
  // conditional writes below still prevent blind concurrent replacement.
  return getStore(STORE_NAME);
}

async function readJSON(key) {
  const store = await pricingStore();
  const entry = await store.getWithMetadata(key, { type: "json" });
  return entry || null;
}

async function loadConfig() {
  const entry = await readJSON(CONFIG_KEY).catch(() => null);
  if (!entry) {
    const result = validateAndNormalizeConfig(defaultConfig(), {
      testOrderId: process.env.SHOPMONKEY_PRICING_TEST_ORDER_ID || "",
    });
    if (!result.ok) throw new Error("pricing_config_invalid");
    return { config: result.config, etag: "", persisted: false };
  }
  const result = validateAndNormalizeConfig(entry.data, {
    testOrderId: process.env.SHOPMONKEY_PRICING_TEST_ORDER_ID || "",
  });
  if (!result.ok) throw new Error("pricing_config_invalid");
  return { config: result.config, etag: entry.etag || "", persisted: true };
}

async function saveConfig(input, expectedRevision) {
  const current = await loadConfig();
  if (clean(expectedRevision) !== clean(current.config.revision)) {
    return { ok: false, conflict: true, config: current.config };
  }
  const validated = validateAndNormalizeConfig(input, {
    testOrderId: process.env.SHOPMONKEY_PRICING_TEST_ORDER_ID || "",
  });
  if (!validated.ok) return validated;
  const stored = {
    ...validated.config,
    revision: crypto.randomUUID(),
    updated_at: new Date().toISOString(),
  };
  const store = await pricingStore();
  const options = current.etag ? { onlyIfMatch: current.etag } : { onlyIfNew: true };
  const write = await store.setJSON(CONFIG_KEY, stored, options);
  if (!write.modified) {
    const latest = await loadConfig();
    return { ok: false, conflict: true, config: latest.config };
  }
  return { ok: true, config: stored };
}

async function loadHealth() {
  const entry = await readJSON(HEALTH_KEY).catch(() => null);
  return entry && entry.data && typeof entry.data === "object" ? entry.data : {};
}

async function recordHealth(patch) {
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const entry = await readJSON(HEALTH_KEY).catch(() => null);
    const current = entry && entry.data && typeof entry.data === "object" ? entry.data : {};
    const delta = Number.isSafeInteger(patch && patch.repriced_delta) ? patch.repriced_delta : 0;
    const safePatch = { ...(patch || {}) };
    delete safePatch.repriced_delta;
    const next = {
      last_received_at: clean(current.last_received_at),
      last_success_at: clean(current.last_success_at),
      last_error_at: clean(current.last_error_at),
      last_error: clean(current.last_error).slice(0, 80),
      last_result: clean(current.last_result).slice(0, 80),
      last_config_revision: clean(current.last_config_revision),
      last_reconcile_at: clean(current.last_reconcile_at),
      last_reconcile_success_at: clean(current.last_reconcile_success_at),
      last_reconcile_result: clean(current.last_reconcile_result).slice(0, 80),
      last_api_check_at: clean(current.last_api_check_at),
      last_api_check_ok: current.last_api_check_ok === true,
      repriced_total: (Number.isSafeInteger(current.repriced_total) ? current.repriced_total : 0) + delta,
      ...safePatch,
    };
    const store = await pricingStore();
    const write = await store.setJSON(
      HEALTH_KEY,
      next,
      entry && entry.etag ? { onlyIfMatch: entry.etag } : { onlyIfNew: true },
    );
    if (write.modified) return next;
  }
  throw new Error("health_write_conflict");
}

function managementSignature({ secret, timestamp, nonce, method, body }) {
  const bodyDigest = crypto.createHash("sha256").update(body).digest("hex");
  return crypto
    .createHmac("sha256", secret)
    .update(`${timestamp}.${nonce}.${String(method || "").toUpperCase()}.${bodyDigest}`, "utf8")
    .digest("base64");
}

function constantTimeTextEqual(left, right) {
  const a = Buffer.from(String(left), "utf8");
  const b = Buffer.from(String(right), "utf8");
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

function verifyManagementRequest({ secret, timestamp, nonce, method, body, signature, nowSeconds }) {
  if (!secret || !timestamp || !nonce || !signature || !/^\d+$/.test(String(timestamp))) return false;
  if (!/^[a-f0-9]{32,64}$/i.test(String(nonce))) return false;
  const sentAt = Number(timestamp);
  if (!Number.isSafeInteger(sentAt) || Math.abs(nowSeconds - sentAt) > MANAGEMENT_TOLERANCE_SECONDS) {
    return false;
  }
  const expected = managementSignature({ secret, timestamp, nonce, method, body });
  return constantTimeTextEqual(signature, expected);
}

function setStoreFactory(factory) {
  storeFactoryOverride = factory || null;
}

module.exports = {
  defaultConfig,
  loadConfig,
  loadHealth,
  managementSignature,
  normalized,
  recordHealth,
  saveConfig,
  setStoreFactory,
  setStoreFactoryForTests: setStoreFactory,
  targetPriceCents,
  validateAndNormalizeConfig,
  verifyManagementRequest,
};
