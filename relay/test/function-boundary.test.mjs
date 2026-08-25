import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import { handler as centralHandler } from "../netlify/functions/qb-central.mjs";

const require = createRequire(import.meta.url);
const { handler: callbackHandler } = require("../netlify/functions/qb-callback.js");

test("central HTTP service is fail-closed and default-off without secrets", async () => {
  const previous = process.env.CENTRAL_QBO_ENABLED;
  delete process.env.CENTRAL_QBO_ENABLED;
  try {
    const response = await centralHandler({
      httpMethod: "GET",
      path: "/v1/quickbooks/health",
      headers: {},
    });
    const body = JSON.parse(response.body);

    assert.equal(response.statusCode, 503);
    assert.equal(body.error.code, "central_service_disabled");
    assert.equal(response.headers["Cache-Control"], "no-store");
  } finally {
    if (previous === undefined) delete process.env.CENTRAL_QBO_ENABLED;
    else process.env.CENTRAL_QBO_ENABLED = previous;
  }
});

test("default callback behavior remains the existing localhost 302 relay", async () => {
  const previous = process.env.CENTRAL_QBO_ENABLED;
  process.env.CENTRAL_QBO_ENABLED = "false";
  try {
    const response = await callbackHandler({
      queryStringParameters: { code: "one-time", state: "state", realmId: "123" },
    });

    assert.equal(response.statusCode, 302);
    assert.match(response.headers.Location, /^http:\/\/localhost:7655\/api\/quickbooks\/callback\?/);
    assert.equal(response.body, "");
  } finally {
    if (previous === undefined) delete process.env.CENTRAL_QBO_ENABLED;
    else process.env.CENTRAL_QBO_ENABLED = previous;
  }
});
