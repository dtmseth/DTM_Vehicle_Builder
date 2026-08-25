import {
  ServiceError,
  correlationId,
  safeResult,
} from "./_shared/central-core.mjs";
import {
  buildCentralService,
  centralQboEnabled,
} from "./_shared/netlify-central.mjs";

function json(statusCode, body) {
  return {
    statusCode,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "Referrer-Policy": "no-referrer",
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY",
    },
    body: JSON.stringify(body),
  };
}

function header(event, name) {
  const entries = Object.entries(event.headers || {});
  const found = entries.find(([key]) => key.toLowerCase() === name.toLowerCase());
  return found ? String(found[1] || "") : "";
}

function requestPath(event) {
  try {
    if (event.rawUrl) return new URL(event.rawUrl).pathname;
  } catch {
    // Fall through to the normalized event path.
  }
  return String(event.path || "").replace("/.netlify/functions/qb-central", "/v1/quickbooks");
}

function asResponse(result) {
  return json(result.statusCode, result.body);
}

export async function handler(event) {
  const cid = correlationId(header(event, "x-correlation-id"));
  if (!centralQboEnabled()) {
    return asResponse(safeResult(new ServiceError("central_service_disabled", 503), cid));
  }
  if ((event.body || "").length > 8192) {
    return asResponse(safeResult(new ServiceError("invalid_request", 413), cid));
  }

  try {
    const service = buildCentralService();
    const path = requestPath(event);
    const authorization = header(event, "authorization");
    const method = String(event.httpMethod || "GET").toUpperCase();

    if (method === "GET" && path === "/v1/quickbooks/health") {
      return asResponse(await service.health({ authorization, correlation: cid }));
    }
    if (method === "GET" && path === "/v1/quickbooks/admin/health") {
      return asResponse(await service.health({ authorization, correlation: cid, admin: true }));
    }
    if (method === "GET" && path === "/v1/quickbooks/items") {
      return asResponse(await service.items({ authorization, correlation: cid }));
    }
    if (method === "POST" && path === "/v1/quickbooks/admin/oauth/start") {
      return asResponse(await service.startOAuth({ authorization, correlation: cid }));
    }
    return asResponse(safeResult(new ServiceError("invalid_request", 404), cid));
  } catch (error) {
    return asResponse(safeResult(error, cid));
  }
}
