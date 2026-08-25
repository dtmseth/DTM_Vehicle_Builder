import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes,
  randomUUID,
} from "node:crypto";

import { getStore } from "@netlify/blobs";
import { createRemoteJWKSet, errors as joseErrors, jwtVerify } from "jose";

import {
  BUILDER_ADMIN_ROLE,
  ServiceError,
  createCentralCore,
} from "./central-core.mjs";

const INTUIT_AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2";
const INTUIT_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer";
const DEFAULT_REDIRECT_URI = "https://dtmvehiclebuilder.netlify.app/.netlify/functions/qb-callback";
const DEFAULT_MINOR_VERSION = "75";
const REFRESH_SKEW_SECONDS = 120;
const LEASE_SECONDS = 30;

function truthy(value) {
  return ["1", "true", "yes", "on"].includes(String(value || "").trim().toLowerCase());
}

export function centralQboEnabled(environment = process.env) {
  return truthy(environment.CENTRAL_QBO_ENABLED);
}

function required(environment, name) {
  const value = String(environment[name] || "").trim();
  if (!value) throw new ServiceError("central_service_not_configured", 503);
  return value;
}

export function loadCentralConfig(environment = process.env) {
  const tenantId = required(environment, "ENTRA_TENANT_ID");
  const audience = required(environment, "BUILDER_API_AUDIENCE");
  const clientId = required(environment, "INTUIT_CLIENT_ID");
  const clientSecret = required(environment, "INTUIT_CLIENT_SECRET");
  const redirectUri = String(environment.INTUIT_REDIRECT_URI || DEFAULT_REDIRECT_URI).trim();
  const realmKey = String(environment.QBO_REALM_KEY || "dtm-company").trim();
  const qboEnvironment = String(environment.QBO_ENVIRONMENT || "production").trim().toLowerCase();
  const encryptionKey = parseEncryptionKey(required(environment, "QBO_TOKEN_ENCRYPTION_KEY"));
  const jwksUrl = String(
    environment.ENTRA_JWKS_URL
      || `https://login.microsoftonline.com/${tenantId}/discovery/v2.0/keys`,
  ).trim();
  const minorVersion = String(environment.QBO_MINOR_VERSION || DEFAULT_MINOR_VERSION).trim();
  if (
    !/^https:\/\//i.test(redirectUri)
    || !/^https:\/\//i.test(jwksUrl)
    || !/^[A-Za-z0-9_-]{1,100}$/.test(realmKey)
    || !/^\d{1,4}$/.test(minorVersion)
    || !["production", "sandbox"].includes(qboEnvironment)
  ) {
    throw new ServiceError("central_service_not_configured", 503);
  }
  return {
    tenantId,
    audience,
    clientId,
    clientSecret,
    redirectUri,
    realmKey,
    qboEnvironment,
    encryptionKey,
    issuer: `https://login.microsoftonline.com/${tenantId}/v2.0`,
    jwksUrl,
    minorVersion,
  };
}

export function parseEncryptionKey(value) {
  let key;
  try {
    key = Buffer.from(String(value || ""), "base64");
  } catch {
    throw new ServiceError("central_service_not_configured", 503);
  }
  if (key.length !== 32) throw new ServiceError("central_service_not_configured", 503);
  return key;
}

export function encryptDocument(key, value, purpose) {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  cipher.setAAD(Buffer.from(String(purpose), "utf8"));
  const ciphertext = Buffer.concat([
    cipher.update(JSON.stringify(value), "utf8"),
    cipher.final(),
  ]);
  return {
    v: 1,
    iv: iv.toString("base64url"),
    tag: cipher.getAuthTag().toString("base64url"),
    ciphertext: ciphertext.toString("base64url"),
  };
}

export function decryptDocument(key, envelope, purpose) {
  try {
    if (envelope?.v !== 1) throw new Error("unsupported envelope");
    const decipher = createDecipheriv(
      "aes-256-gcm",
      key,
      Buffer.from(String(envelope.iv), "base64url"),
    );
    decipher.setAAD(Buffer.from(String(purpose), "utf8"));
    decipher.setAuthTag(Buffer.from(String(envelope.tag), "base64url"));
    const plaintext = Buffer.concat([
      decipher.update(Buffer.from(String(envelope.ciphertext), "base64url")),
      decipher.final(),
    ]);
    return JSON.parse(plaintext.toString("utf8"));
  } catch {
    throw new ServiceError("internal_error", 500);
  }
}

export function createEntraIdentity(config, { keyResolver } = {}) {
  const jwks = keyResolver || createRemoteJWKSet(new URL(config.jwksUrl));
  return {
    async verify(token) {
      try {
        const { payload } = await jwtVerify(token, jwks, { algorithms: ["RS256"] });
        if (payload.iss !== config.issuer || payload.tid !== config.tenantId) {
          throw new ServiceError("wrong_tenant", 401);
        }
        const audiences = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
        if (!audiences.includes(config.audience)) {
          throw new ServiceError("wrong_audience", 401);
        }
        if (!Number.isFinite(payload.exp) || payload.exp <= Date.now() / 1000) {
          throw new ServiceError("expired_token", 401);
        }
        return {
          tenant_id: String(payload.tid || ""),
          subject: String(payload.sub || ""),
          object_id: String(payload.oid || ""),
          roles: Array.isArray(payload.roles) ? payload.roles.map(String) : [],
        };
      } catch (error) {
        if (error instanceof ServiceError) throw error;
        if (error instanceof joseErrors.JWTExpired) {
          throw new ServiceError("expired_token", 401);
        }
        throw new ServiceError("invalid_token", 401);
      }
    },
  };
}

function credentialsKey(realmKey) {
  return `realms/${encodeURIComponent(realmKey)}/credentials`;
}

async function blobJson(store, key) {
  const result = await store.getWithMetadata(key, { type: "json", consistency: "strong" });
  if (!result) return null;
  return { data: result.data, etag: result.etag };
}

function modified(result) {
  return result?.modified === true;
}

function validateCredentials(value) {
  const realmId = String(value?.realm_id || "").trim();
  const accessToken = String(value?.access_token || "").trim();
  const refreshToken = String(value?.refresh_token || "").trim();
  const expiresAt = Number(value?.access_expires_at);
  if (!realmId || !accessToken || !refreshToken || !Number.isFinite(expiresAt)) {
    throw new ServiceError("invalid_provider_data", 502);
  }
  const version = Number(value?.version || 0);
  if (!Number.isFinite(version) || version < 0) {
    throw new ServiceError("invalid_provider_data", 502);
  }
  return {
    realm_id: realmId,
    access_token: accessToken,
    refresh_token: refreshToken,
    access_expires_at: expiresAt,
    version: Math.floor(version),
  };
}

export function createCredentialRepository({
  credentialStore,
  lockStore,
  encryptionKey,
  realmKey,
  qbo,
  nowSeconds = () => Date.now() / 1000,
}) {
  const key = credentialsKey(realmKey);
  const purpose = `qbo-credentials:${realmKey}`;
  const lockKey = `realms/${encodeURIComponent(realmKey)}/refresh-lock`;

  async function load(optional = false) {
    const record = await blobJson(credentialStore, key);
    if (!record) {
      if (optional) return null;
      throw new ServiceError("not_connected", 503);
    }
    return {
      value: validateCredentials(decryptDocument(encryptionKey, record.data, purpose)),
      etag: record.etag,
    };
  }

  async function compareAndSet(value, etag) {
    const envelope = encryptDocument(encryptionKey, value, purpose);
    const options = etag ? { onlyIfMatch: etag } : { onlyIfNew: true };
    const result = await credentialStore.setJSON(key, envelope, options);
    if (!modified(result)) throw new ServiceError("credential_conflict", 409);
  }

  async function acquireLease() {
    const holder = randomUUID();
    const lease = { holder, expires_at: nowSeconds() + LEASE_SECONDS };
    const existing = await blobJson(lockStore, lockKey);
    if (!existing) {
      const result = await lockStore.setJSON(lockKey, lease, { onlyIfNew: true });
      if (modified(result)) return holder;
      throw new ServiceError("credential_busy", 409);
    }
    if (Number(existing.data?.expires_at) > nowSeconds()) {
      throw new ServiceError("credential_busy", 409);
    }
    const result = await lockStore.setJSON(lockKey, lease, { onlyIfMatch: existing.etag });
    if (!modified(result)) throw new ServiceError("credential_busy", 409);
    return holder;
  }

  async function releaseLease(holder) {
    try {
      const existing = await blobJson(lockStore, lockKey);
      if (!existing || existing.data?.holder !== holder) return;
      await lockStore.setJSON(
        lockKey,
        { holder: "released", expires_at: 0 },
        { onlyIfMatch: existing.etag },
      );
    } catch {
      // The short lease expires safely; release failures never expose storage detail.
    }
  }

  return {
    async authorize(input) {
      const existing = await load(true);
      const next = validateCredentials({
        ...input,
        version: existing ? existing.value.version + 1 : 1,
      });
      await compareAndSet(next, existing?.etag);
    },

    async getFresh() {
      let current = await load();
      if (current.value.access_expires_at > nowSeconds() + REFRESH_SKEW_SECONDS) {
        return current.value;
      }
      const holder = await acquireLease();
      try {
        current = await load();
        if (current.value.access_expires_at > nowSeconds() + REFRESH_SKEW_SECONDS) {
          return current.value;
        }
        const rotated = validateCredentials({
          ...(await qbo.refreshCredentials(current.value)),
          realm_id: current.value.realm_id,
          version: current.value.version + 1,
        });
        await compareAndSet(rotated, current.etag);
        return rotated;
      } finally {
        await releaseLease(holder);
      }
    },
  };
}

function stateKey(state) {
  return `states/${createHash("sha256").update(state).digest("hex")}`;
}

export function createOAuthStateStore({ store, encryptionKey, nowSeconds = () => Date.now() / 1000 }) {
  return {
    async create(principal) {
      const state = randomBytes(32).toString("base64url");
      const key = stateKey(state);
      const value = {
        tenant_id: principal.tenant_id,
        subject: principal.subject,
        object_id: principal.object_id,
        roles: [BUILDER_ADMIN_ROLE],
        expires_at: nowSeconds() + 600,
        used: false,
      };
      const result = await store.setJSON(
        key,
        encryptDocument(encryptionKey, value, `oauth-state:${key}`),
        { onlyIfNew: true },
      );
      if (!modified(result)) throw new ServiceError("internal_error", 500);
      return state;
    },

    async consume(state) {
      const key = stateKey(state);
      const record = await blobJson(store, key);
      if (!record) throw new ServiceError("invalid_request", 400);
      const value = decryptDocument(encryptionKey, record.data, `oauth-state:${key}`);
      if (value.used === true || Number(value.expires_at) <= nowSeconds()) {
        throw new ServiceError("invalid_request", 400);
      }
      const consumed = encryptDocument(
        encryptionKey,
        { ...value, used: true, used_at: nowSeconds() },
        `oauth-state:${key}`,
      );
      const result = await store.setJSON(key, consumed, { onlyIfMatch: record.etag });
      if (!modified(result)) throw new ServiceError("invalid_request", 400);
      return value;
    },
  };
}

function createAuditStore(store) {
  return {
    async append(record) {
      const day = String(record.occurred_at || "unknown").slice(0, 10);
      const safe = {
        occurred_at: String(record.occurred_at || ""),
        tenant_id: String(record.tenant_id || ""),
        user_object_id: String(record.user_object_id || ""),
        action: String(record.action || ""),
        outcome: String(record.outcome || ""),
        correlation_id: String(record.correlation_id || ""),
        entity_type: String(record.entity_type || ""),
        entity_id: String(record.entity_id || ""),
        project_id: String(record.project_id || ""),
        vehicle_id: String(record.vehicle_id || ""),
        error_code: String(record.error_code || ""),
      };
      const result = await store.setJSON(`${day}/${randomUUID()}`, safe, { onlyIfNew: true });
      if (!modified(result)) throw new ServiceError("internal_error", 500);
    },
  };
}

function tokenExpiry(payload) {
  const seconds = Number(payload?.expires_in);
  if (!Number.isFinite(seconds) || seconds <= 0) {
    throw new ServiceError("invalid_provider_data", 502);
  }
  return Date.now() / 1000 + seconds;
}

function tokenValues(payload) {
  const accessToken = String(payload?.access_token || "").trim();
  const refreshToken = String(payload?.refresh_token || "").trim();
  if (!accessToken || !refreshToken) throw new ServiceError("invalid_provider_data", 502);
  return {
    access_token: accessToken,
    refresh_token: refreshToken,
    access_expires_at: tokenExpiry(payload),
  };
}

function createQboProvider(config) {
  const apiOrigin = config.qboEnvironment === "sandbox"
    ? "https://sandbox-quickbooks.api.intuit.com"
    : "https://quickbooks.api.intuit.com";
  const basic = Buffer.from(`${config.clientId}:${config.clientSecret}`, "utf8").toString("base64");

  async function fetchJson(url, options = {}) {
    let response;
    try {
      response = await fetch(url, { ...options, signal: AbortSignal.timeout(20_000) });
    } catch {
      throw new ServiceError("provider_unavailable", 503);
    }
    if (!response.ok) throw new ServiceError("provider_unavailable", 503);
    try {
      return await response.json();
    } catch {
      throw new ServiceError("invalid_provider_data", 502);
    }
  }

  async function exchangeForm(form) {
    const payload = await fetchJson(INTUIT_TOKEN_URL, {
      method: "POST",
      headers: {
        Authorization: `Basic ${basic}`,
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: form.toString(),
    });
    return tokenValues(payload);
  }

  async function accountingJson(credentials, path, query = {}) {
    const url = new URL(`${apiOrigin}/v3/company/${encodeURIComponent(credentials.realm_id)}/${path}`);
    url.searchParams.set("minorversion", config.minorVersion);
    for (const [name, value] of Object.entries(query)) url.searchParams.set(name, value);
    return fetchJson(url, {
      headers: {
        Authorization: `Bearer ${credentials.access_token}`,
        Accept: "application/json",
      },
    });
  }

  return {
    authorizationUrl(state) {
      const url = new URL(INTUIT_AUTHORIZE_URL);
      url.searchParams.set("client_id", config.clientId);
      url.searchParams.set("redirect_uri", config.redirectUri);
      url.searchParams.set("response_type", "code");
      url.searchParams.set("scope", "com.intuit.quickbooks.accounting");
      url.searchParams.set("state", state);
      return url.toString();
    },

    exchangeAuthorizationCode(code) {
      return exchangeForm(new URLSearchParams({
        grant_type: "authorization_code",
        code,
        redirect_uri: config.redirectUri,
      }));
    },

    refreshCredentials(credentials) {
      return exchangeForm(new URLSearchParams({
        grant_type: "refresh_token",
        refresh_token: credentials.refresh_token,
      }));
    },

    async connectionHealth(credentials) {
      await accountingJson(
        credentials,
        `companyinfo/${encodeURIComponent(credentials.realm_id)}`,
      );
      return { connected: true, environment: config.qboEnvironment };
    },

    async fetchActiveItems(credentials) {
      const items = [];
      const pageSize = 1000;
      for (let start = 1; start <= 100_000; start += pageSize) {
        const query = `select * from Item where Active = true startposition ${start} maxresults ${pageSize}`;
        const payload = await accountingJson(credentials, "query", { query });
        const page = payload?.QueryResponse?.Item || [];
        if (!Array.isArray(page)) throw new ServiceError("invalid_provider_data", 502);
        for (const item of page) {
          items.push({
            qb_item_id: String(item?.Id || ""),
            name: String(item?.Name || ""),
            sku: String(item?.Sku || ""),
            description: String(item?.Description || ""),
            unit_price: item?.UnitPrice ?? null,
            type: String(item?.Type || ""),
            active: item?.Active !== false,
          });
        }
        if (page.length < pageSize) break;
      }
      return items;
    },
  };
}

function strongStore(name) {
  return getStore({ name, consistency: "strong" });
}

export function buildCentralService(environment = process.env) {
  const config = loadCentralConfig(environment);
  const qbo = createQboProvider(config);
  const credentials = createCredentialRepository({
    credentialStore: strongStore("dtm-qbo-credentials"),
    lockStore: strongStore("dtm-qbo-locks"),
    encryptionKey: config.encryptionKey,
    realmKey: config.realmKey,
    qbo,
  });
  const oauthState = createOAuthStateStore({
    store: strongStore("dtm-qbo-oauth-state"),
    encryptionKey: config.encryptionKey,
  });
  return createCentralCore({
    identity: createEntraIdentity(config),
    credentials,
    qbo,
    audit: createAuditStore(strongStore("dtm-qbo-audit")),
    oauthState,
  });
}

export async function completeCentralOAuth(parameters, environment = process.env) {
  try {
    if (!centralQboEnabled(environment)) return { location: "/?qb=error" };
    const result = await buildCentralService(environment).completeOAuth(parameters);
    return { location: result.location || "/?qb=error" };
  } catch {
    return { location: "/?qb=error" };
  }
}
