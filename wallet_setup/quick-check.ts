import crypto from "node:crypto";
import { initiateDeveloperControlledWalletsClient } from "@circle-fin/developer-controlled-wallets";

const apiKey = process.env.CIRCLE_API_KEY;
const entitySecret = crypto.randomBytes(32).toString("hex");

const client = initiateDeveloperControlledWalletsClient({ apiKey, entitySecret });

try {
  const response = await client.listWalletSets({ pageSize: 1 });
  console.log("OK", response?.data?.walletSets?.length ?? 0);
} catch (e) {
  console.error(String(e));
}
