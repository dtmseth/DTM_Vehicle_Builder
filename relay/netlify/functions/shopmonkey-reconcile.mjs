import reconcile from "../../lib/shopmonkey-reconcile.js";

export default async () => {
  await reconcile.runReconciliation();
};
