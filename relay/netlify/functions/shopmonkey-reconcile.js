"use strict";

const { connectLambda } = require("@netlify/blobs");
const reconcile = require("../../lib/shopmonkey-reconcile");

exports.handler = async (event) => {
  if (event.blobs) connectLambda(event);
  await reconcile.runReconciliation();
  return { statusCode: 200, body: "" };
};
