import assert from "node:assert/strict";
import test from "node:test";

import {
  BUILDER_ADMIN_ROLE,
  BUILDER_USER_ROLE,
  createCentralCore,
} from "../netlify/functions/_shared/central-core.mjs";

function fixture() {
  const audit = [];
  let authorized;
  const principals = {
    user: {
      tenant_id: "dtm-tenant",
      subject: "user-subject",
      object_id: "user-object-id",
      roles: [BUILDER_USER_ROLE],
    },
    admin: {
      tenant_id: "dtm-tenant",
      subject: "admin-subject",
      object_id: "admin-object-id",
      roles: [BUILDER_ADMIN_ROLE],
    },
    roleless: {
      tenant_id: "dtm-tenant",
      subject: "roleless-subject",
      object_id: "roleless-object-id",
      roles: [],
    },
  };
  const credentials = {
    async getFresh() {
      return {
        realm_id: "private-realm",
        access_token: "private-access-token",
        refresh_token: "private-refresh-token",
        access_expires_at: 2_000_000_000,
        version: 7,
      };
    },
    async authorize(value) {
      authorized = value;
    },
  };
  const qbo = {
    connectionHealth: async () => ({ connected: true, environment: "production" }),
    fetchActiveItems: async () => [{
      qb_item_id: "item-1",
      name: "Light",
      sku: "L-1",
      unit_price: 125,
      active: true,
    }],
    authorizationUrl: (state) => `https://appcenter.intuit.test/connect?state=${state}`,
    exchangeAuthorizationCode: async () => ({
      access_token: "new-private-access",
      refresh_token: "new-private-refresh",
      access_expires_at: 2_000_000_000,
    }),
  };
  const service = createCentralCore({
    identity: {
      async verify(token) {
        if (token === "invalid") throw new Error("raw token validation detail");
        return principals[token];
      },
    },
    credentials,
    qbo,
    audit: { append: async (record) => audit.push(record) },
    oauthState: {
      create: async () => "safe-state",
      consume: async (state) => {
        if (state !== "safe-state") throw new Error("private state detail");
        return principals.admin;
      },
    },
    now: () => new Date("2026-08-19T12:00:00.000Z"),
  });
  return { service, audit, getAuthorized: () => authorized };
}

test("Builder User and Builder Admin can use narrow read endpoints", async () => {
  const { service, audit } = fixture();

  const user = await service.health({ authorization: "Bearer user", correlation: "user-health" });
  const admin = await service.health({
    authorization: "Bearer admin",
    correlation: "admin-health",
    admin: true,
  });
  const items = await service.items({ authorization: "Bearer admin", correlation: "items" });

  assert.equal(user.statusCode, 200);
  assert.equal(user.body.connected, true);
  assert.equal(admin.body.admin.credential_generation, 7);
  assert.equal(items.body.items[0].qb_item_id, "item-1");
  assert.deepEqual(audit.map((record) => record.user_object_id), [
    "user-object-id",
    "admin-object-id",
    "admin-object-id",
  ]);
});

test("admin connection action rejects a normal user", async () => {
  const { service } = fixture();
  const result = await service.startOAuth({ authorization: "Bearer user", correlation: "admin-only" });

  assert.equal(result.statusCode, 403);
  assert.equal(result.body.error.code, "forbidden");
});

test("unauthenticated, invalid, and missing-role errors are structured", async () => {
  const { service } = fixture();
  const missing = await service.health({ authorization: "", correlation: "missing" });
  const invalid = await service.health({ authorization: "Bearer invalid", correlation: "invalid" });
  const roleless = await service.items({ authorization: "Bearer roleless", correlation: "roleless" });

  assert.deepEqual(
    [missing.body.error.code, invalid.body.error.code, roleless.body.error.code],
    ["unauthenticated", "invalid_token", "forbidden"],
  );
  assert.equal(JSON.stringify(invalid.body).includes("raw token validation detail"), false);
});

test("admin OAuth completion stores tokens server-side and returns only a redirect", async () => {
  const { service, audit, getAuthorized } = fixture();
  const start = await service.startOAuth({ authorization: "Bearer admin", correlation: "start" });
  const complete = await service.completeOAuth({
    state: "safe-state",
    code: "one-time-code",
    realmId: "123456789",
    correlation: "complete",
  });

  assert.equal(start.statusCode, 200);
  assert.match(start.body.authorization_url, /^https:\/\/appcenter\.intuit\.test/);
  assert.equal(complete.statusCode, 302);
  assert.equal(complete.location, "/?qb=connected");
  assert.deepEqual(getAuthorized(), {
    realm_id: "123456789",
    access_token: "new-private-access",
    refresh_token: "new-private-refresh",
    access_expires_at: 2_000_000_000,
  });
  assert.equal(JSON.stringify(complete).includes("new-private"), false);
  assert.equal(audit.at(-1).user_object_id, "admin-object-id");
});

test("provider exceptions never expose tokens, URLs, or response detail", async () => {
  const broken = createCentralCore({
    identity: {
      verify: async () => ({
        tenant_id: "dtm-tenant",
        subject: "subject",
        object_id: "object",
        roles: [BUILDER_USER_ROLE],
      }),
    },
    credentials: { getFresh: async () => ({ access_token: "secret-token" }) },
    qbo: {
      fetchActiveItems: async () => {
        throw new Error("secret-token https://quickbooks.example/private-customer");
      },
    },
    audit: { append: async () => {} },
    oauthState: {},
  });
  const result = await broken.items({ authorization: "Bearer token", correlation: "safe-error" });
  const rendered = JSON.stringify(result);

  assert.equal(result.statusCode, 503);
  assert.equal(result.body.error.code, "provider_unavailable");
  assert.equal(rendered.includes("secret-token"), false);
  assert.equal(rendered.includes("quickbooks.example"), false);
  assert.equal(rendered.includes("private-customer"), false);
});
