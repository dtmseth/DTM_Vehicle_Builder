import { getStore } from "@netlify/blobs";
import pricing from "../../lib/shopmonkey-pricing.js";
import reconcile from "../../lib/shopmonkey-reconcile.js";

export default async () => {
  // Bridge the modern scheduled-function runtime's Blob context into the
  // shared CommonJS pricing module. This also keeps the dependency bundled.
  pricing.setStoreFactory((name) => getStore(name));
  console.log(JSON.stringify({ event: "shopmonkey_reconciliation_started" }));
  const result = await reconcile.runReconciliation({
    onStage: (stage, details = {}) => console.log(JSON.stringify({
      event: "shopmonkey_reconciliation_stage",
      stage,
      ...details,
    })),
  });
  console.log(JSON.stringify({
    event: "shopmonkey_reconciliation_complete",
    orders: Number(result.orders || 0),
    repriced: Number(result.repriced || 0),
  }));
};
