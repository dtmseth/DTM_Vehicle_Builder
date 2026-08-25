import { randomUUID } from "node:crypto";

export const BUILDER_USER_ROLE = "Builder.User";
export const BUILDER_ADMIN_ROLE = "Builder.Admin";

const SAFE_MESSAGES = Object.freeze({
  unauthenticated: "Authentication is required.",
  invalid_token: "The Builder API token is invalid.",
  wrong_tenant: "This account is not authorized for the Builder API.",
  wrong_audience: "The token was not issued for the Builder API.",
  expired_token: "The Builder API session has expired.",
  missing_subject: "The Builder API token has no usable subject.",
  forbidden: "The signed-in user does not have the required Builder role.",
  not_connected: "The managed QuickBooks company connection is unavailable.",
  credential_busy: "The managed QuickBooks connection is busy; retry shortly.",
  credential_conflict: "The managed QuickBooks credential changed; retry the request.",
  provider_unavailable: "QuickBooks is temporarily unavailable.",
  invalid_provider_data: "QuickBooks returned data the Builder API could not accept.",
  central_service_disabled: "The central QuickBooks service is not enabled.",
  central_service_not_configured: "The central QuickBooks service is not configured.",
  invalid_request: "The Builder API could not accept the request.",
  internal_error: "The Builder API could not complete the request.",
});

export class ServiceError extends Error {
  constructor(code, statusCode = 500) {
    const safeCode = Object.hasOwn(SAFE_MESSAGES, code) ? code : "internal_error";
    super(safeCode);
    this.code = safeCode;
    this.statusCode = statusCode;
  }
}

export function safeResult(error, correlationId) {
  const safe = error instanceof ServiceError ? error : new ServiceError("internal_error");
  return {
    statusCode: safe.statusCode,
    body: {
      ok: false,
      error: { code: safe.code, message: SAFE_MESSAGES[safe.code] },
      correlation_id: correlationId,
    },
  };
}

export function correlationId(value) {
  const candidate = String(value || "").trim();
  return /^[A-Za-z0-9_-]{1,64}$/.test(candidate) ? candidate : randomUUID().replaceAll("-", "");
}

function bearer(authorization) {
  const match = /^Bearer\s+([^\s]+)$/i.exec(String(authorization || "").trim());
  if (!match) throw new ServiceError("unauthenticated", 401);
  return match[1];
}

function permits(principal, requiredRole) {
  const roles = new Set(principal.roles || []);
  return roles.has(requiredRole)
    || (requiredRole === BUILDER_USER_ROLE && roles.has(BUILDER_ADMIN_ROLE));
}

function normalizeItem(value) {
  const id = String(value?.qb_item_id || "").trim();
  if (!id) throw new ServiceError("invalid_provider_data", 502);
  const price = value?.unit_price;
  if (price !== null && price !== undefined && !Number.isFinite(Number(price))) {
    throw new ServiceError("invalid_provider_data", 502);
  }
  return {
    qb_item_id: id.slice(0, 128),
    name: String(value?.name || "").trim().slice(0, 500),
    sku: String(value?.sku || "").trim().slice(0, 256),
    description: String(value?.description || "").trim().slice(0, 4000),
    unit_price: price === null || price === undefined ? null : Number(price),
    type: String(value?.type || "").trim().slice(0, 100),
    active: value?.active !== false,
  };
}

export function createCentralCore({ identity, credentials, qbo, audit, oauthState, now = () => new Date() }) {
  async function authorize(authorization, requiredRole) {
    let principal;
    try {
      principal = await identity.verify(bearer(authorization));
    } catch (error) {
      if (error instanceof ServiceError) throw error;
      throw new ServiceError("invalid_token", 401);
    }
    if (!principal?.tenant_id) throw new ServiceError("wrong_tenant", 401);
    if (!principal?.subject || !principal?.object_id) {
      throw new ServiceError("missing_subject", 401);
    }
    if (!permits(principal, requiredRole)) throw new ServiceError("forbidden", 403);
    return principal;
  }

  async function appendAudit(principal, details, { bestEffort = false } = {}) {
    try {
      await audit.append({
        occurred_at: now().toISOString(),
        tenant_id: principal.tenant_id,
        user_object_id: principal.object_id,
        entity_type: "QuickBooksConnection",
        entity_id: "",
        project_id: "",
        vehicle_id: "",
        error_code: "",
        ...details,
      });
    } catch {
      if (!bestEffort) throw new ServiceError("internal_error", 500);
      // Failure-path audit remains best-effort and never exposes storage detail.
    }
  }

  async function runAuthorized({ authorization, requiredRole, action, entityType, correlation }, callback) {
    const cid = correlationId(correlation);
    let principal;
    try {
      principal = await authorize(authorization, requiredRole);
      const body = await callback(principal, cid);
      await appendAudit(principal, {
        action,
        outcome: "success",
        correlation_id: cid,
        entity_type: entityType,
      });
      return { statusCode: 200, body: { ok: true, ...body, correlation_id: cid } };
    } catch (error) {
      const safe = error instanceof ServiceError ? error : new ServiceError("internal_error");
      if (principal) {
        await appendAudit(principal, {
          action,
          outcome: "failure",
          correlation_id: cid,
          entity_type: entityType,
          error_code: safe.code,
        }, { bestEffort: true });
      }
      return safeResult(safe, cid);
    }
  }

  return {
    health({ authorization, correlation, admin = false }) {
      return runAuthorized({
        authorization,
        correlation,
        requiredRole: admin ? BUILDER_ADMIN_ROLE : BUILDER_USER_ROLE,
        action: admin ? "quickbooks.connection_health.admin" : "quickbooks.connection_health",
        entityType: "QuickBooksConnection",
      }, async () => {
        const current = await credentials.getFresh();
        let providerHealth;
        try {
          providerHealth = await qbo.connectionHealth(current);
        } catch {
          throw new ServiceError("provider_unavailable", 503);
        }
        const connected = providerHealth?.connected === true;
        const result = {
          connected,
          connection_status: connected ? "connected" : "unavailable",
          managed_by_dtm: true,
          environment: String(providerHealth?.environment || "production"),
        };
        if (admin) {
          result.admin = {
            realm_bound: Boolean(current.realm_id),
            credential_generation: Number(current.version || 0),
          };
        }
        return result;
      });
    },

    items({ authorization, correlation }) {
      return runAuthorized({
        authorization,
        correlation,
        requiredRole: BUILDER_USER_ROLE,
        action: "quickbooks.catalog.active_items.read",
        entityType: "ItemCatalog",
      }, async () => {
        const current = await credentials.getFresh();
        let values;
        try {
          values = await qbo.fetchActiveItems(current);
        } catch (error) {
          if (error instanceof ServiceError) throw error;
          throw new ServiceError("provider_unavailable", 503);
        }
        if (!Array.isArray(values)) throw new ServiceError("invalid_provider_data", 502);
        const items = values.map(normalizeItem);
        return { items, item_count: items.length };
      });
    },

    startOAuth({ authorization, correlation }) {
      return runAuthorized({
        authorization,
        correlation,
        requiredRole: BUILDER_ADMIN_ROLE,
        action: "quickbooks.connection_authorization.start",
        entityType: "QuickBooksConnection",
      }, async (principal) => {
        const state = await oauthState.create(principal);
        return { authorization_url: qbo.authorizationUrl(state) };
      });
    },

    async completeOAuth({ state, code, realmId, correlation }) {
      const cid = correlationId(correlation);
      let principal;
      try {
        if (!state || !code || !/^\d{1,64}$/.test(String(realmId || ""))) {
          throw new ServiceError("invalid_request", 400);
        }
        principal = await oauthState.consume(String(state));
        await appendAudit(principal, {
          action: "quickbooks.connection_authorization.complete",
          outcome: "attempt",
          correlation_id: cid,
          entity_type: "QuickBooksConnection",
        });
        let exchanged;
        try {
          exchanged = await qbo.exchangeAuthorizationCode(String(code));
        } catch {
          throw new ServiceError("provider_unavailable", 503);
        }
        await credentials.authorize({
          realm_id: String(realmId),
          access_token: exchanged.access_token,
          refresh_token: exchanged.refresh_token,
          access_expires_at: exchanged.access_expires_at,
        });
        await appendAudit(principal, {
          action: "quickbooks.connection_authorization.complete",
          outcome: "success",
          correlation_id: cid,
          entity_type: "QuickBooksConnection",
        }, { bestEffort: true });
        return { statusCode: 302, body: { ok: true }, location: "/?qb=connected" };
      } catch (error) {
        const safe = error instanceof ServiceError ? error : new ServiceError("internal_error");
        if (principal) {
          await appendAudit(principal, {
            action: "quickbooks.connection_authorization.complete",
            outcome: "failure",
            correlation_id: cid,
            entity_type: "QuickBooksConnection",
            error_code: safe.code,
          }, { bestEffort: true });
        }
        return { ...safeResult(safe, cid), location: "/?qb=error" };
      }
    },
  };
}
