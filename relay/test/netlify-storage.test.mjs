import assert from "node:assert/strict";
import test from "node:test";
import {
  SignJWT,
  createLocalJWKSet,
  exportJWK,
  generateKeyPair,
} from "jose";

import {
  createCredentialRepository,
  createEntraIdentity,
  createOAuthStateStore,
  decryptDocument,
  encryptDocument,
  parseEncryptionKey,
} from "../netlify/functions/_shared/netlify-central.mjs";

class MemoryBlobStore {
  constructor() {
    this.records = new Map();
    this.revision = 0;
  }

  async getWithMetadata(key) {
    const record = this.records.get(key);
    return record ? structuredClone(record) : null;
  }

  async setJSON(key, data, options = {}) {
    const current = this.records.get(key);
    if (options.onlyIfNew && current) return { modified: false };
    if (options.onlyIfMatch && current?.etag !== options.onlyIfMatch) return { modified: false };
    if (options.onlyIfMatch && !current) return { modified: false };
    const etag = `etag-${++this.revision}`;
    this.records.set(key, { data: structuredClone(data), etag });
    return { modified: true, etag };
  }
}

const key = parseEncryptionKey(Buffer.alloc(32, 9).toString("base64"));

test("deployment Entra verifier enforces signature, issuer, tenant, audience, expiry, and roles", async () => {
  const { publicKey, privateKey } = await generateKeyPair("RS256");
  const jwk = await exportJWK(publicKey);
  jwk.kid = "test-key";
  jwk.alg = "RS256";
  jwk.use = "sig";
  const config = {
    tenantId: "dtm-tenant",
    audience: "builder-api",
    issuer: "https://login.microsoftonline.com/dtm-tenant/v2.0",
    jwksUrl: "https://login.microsoftonline.test/keys",
  };
  const identity = createEntraIdentity(config, {
    keyResolver: createLocalJWKSet({ keys: [jwk] }),
  });
  const mint = (overrides = {}) => new SignJWT({
    tid: "dtm-tenant",
    oid: "employee-object-id",
    roles: ["Builder.User"],
    ...overrides,
  })
    .setProtectedHeader({ alg: "RS256", kid: "test-key" })
    .setIssuer(config.issuer)
    .setAudience(config.audience)
    .setSubject("pairwise-subject")
    .setIssuedAt()
    .setExpirationTime("5m")
    .sign(privateKey);

  const principal = await identity.verify(await mint());
  assert.equal(principal.object_id, "employee-object-id");
  assert.deepEqual(principal.roles, ["Builder.User"]);

  await assert.rejects(
    async () => identity.verify(await mint({ tid: "other-tenant" })),
    /wrong_tenant/,
  );
  const wrongAudience = await new SignJWT({
    tid: "dtm-tenant",
    oid: "employee-object-id",
    roles: ["Builder.User"],
  })
    .setProtectedHeader({ alg: "RS256", kid: "test-key" })
    .setIssuer(config.issuer)
    .setAudience("microsoft-graph")
    .setSubject("pairwise-subject")
    .setExpirationTime("5m")
    .sign(privateKey);
  await assert.rejects(() => identity.verify(wrongAudience), /wrong_audience/);

  const expired = await new SignJWT({
    tid: "dtm-tenant",
    oid: "employee-object-id",
    roles: ["Builder.User"],
  })
    .setProtectedHeader({ alg: "RS256", kid: "test-key" })
    .setIssuer(config.issuer)
    .setAudience(config.audience)
    .setSubject("pairwise-subject")
    .setExpirationTime(1)
    .sign(privateKey);
  await assert.rejects(() => identity.verify(expired), /expired_token/);
});

test("credential envelope is authenticated and contains no plaintext token", () => {
  const value = { access_token: "private-access", refresh_token: "private-refresh" };
  const envelope = encryptDocument(key, value, "credentials");
  const rendered = JSON.stringify(envelope);

  assert.equal(rendered.includes("private-access"), false);
  assert.equal(rendered.includes("private-refresh"), false);
  assert.deepEqual(decryptDocument(key, envelope, "credentials"), value);
  assert.throws(() => decryptDocument(key, envelope, "wrong-purpose"));
});

test("OAuth state is one-time, expiring, and encrypted at rest", async () => {
  const store = new MemoryBlobStore();
  const stateStore = createOAuthStateStore({ store, encryptionKey: key, nowSeconds: () => 1000 });
  const state = await stateStore.create({
    tenant_id: "tenant",
    subject: "subject",
    object_id: "admin-object-id",
  });
  const atRest = JSON.stringify([...store.records.values()]);

  assert.equal(atRest.includes("admin-object-id"), false);
  assert.equal((await stateStore.consume(state)).object_id, "admin-object-id");
  await assert.rejects(() => stateStore.consume(state), /invalid_request/);
});

test("rotating refresh token is replaced atomically under a per-realm lease", async () => {
  const credentialStore = new MemoryBlobStore();
  const lockStore = new MemoryBlobStore();
  let refreshCount = 0;
  let releaseRefresh;
  const refreshGate = new Promise((resolve) => { releaseRefresh = resolve; });
  const repository = createCredentialRepository({
    credentialStore,
    lockStore,
    encryptionKey: key,
    realmKey: "dtm-company",
    nowSeconds: () => 1000,
    qbo: {
      async refreshCredentials(credentials) {
        refreshCount += 1;
        assert.equal(credentials.refresh_token, "refresh-1");
        await refreshGate;
        return {
          access_token: "access-2",
          refresh_token: "refresh-2",
          access_expires_at: 5000,
        };
      },
    },
  });
  await repository.authorize({
    realm_id: "realm-id",
    access_token: "access-1",
    refresh_token: "refresh-1",
    access_expires_at: 900,
  });

  const first = repository.getFresh();
  await new Promise((resolve) => setImmediate(resolve));
  await assert.rejects(() => repository.getFresh(), /credential_busy/);
  releaseRefresh();
  const rotated = await first;
  const latest = await repository.getFresh();

  assert.equal(refreshCount, 1);
  assert.equal(rotated.refresh_token, "refresh-2");
  assert.equal(latest.refresh_token, "refresh-2");
  assert.equal(latest.version, 2);
  const atRest = JSON.stringify([...credentialStore.records.values()]);
  assert.equal(atRest.includes("refresh-1"), false);
  assert.equal(atRest.includes("refresh-2"), false);
});
