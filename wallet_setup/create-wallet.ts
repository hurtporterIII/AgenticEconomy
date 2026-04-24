import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  registerEntitySecretCiphertext,
  initiateDeveloperControlledWalletsClient
} from "@circle-fin/developer-controlled-wallets";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = path.join(__dirname, "output");
const ENV_PATH = path.join(__dirname, ".env");
const API_KEY = process.env.CIRCLE_API_KEY;

async function main() {
  if (!API_KEY) throw new Error("Missing CIRCLE_API_KEY");

  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  let entitySecret = process.env.CIRCLE_ENTITY_SECRET;
  if (!entitySecret) {
    entitySecret = crypto.randomBytes(32).toString("hex");
    console.log("Registering Entity Secret...");
    try {
      await registerEntitySecretCiphertext({
        apiKey: API_KEY,
        entitySecret,
        recoveryFileDownloadPath: OUTPUT_DIR
      });
    } catch (error: any) {
      if (error?.status === 409 || error?.code === 156015) {
        throw new Error(
          "Entity secret already exists for this Circle account. Set CIRCLE_ENTITY_SECRET in .env (recover it from your recovery file or reset entity secret in Circle)."
        );
      }
      throw error;
    }

    fs.appendFileSync(ENV_PATH, `\nCIRCLE_ENTITY_SECRET=${entitySecret}\n`, "utf-8");
    console.log("Entity Secret registered and saved to .env");
  } else {
    console.log("Using existing CIRCLE_ENTITY_SECRET from .env");
  }

  const client = initiateDeveloperControlledWalletsClient({
    apiKey: API_KEY,
    entitySecret
  });

  console.log("Creating wallet set...");
  const walletSet = (
    await client.createWalletSet({
      name: `Arc Wallet Set ${Date.now()}`
    })
  ).data.walletSet;

  if (!walletSet?.id) throw new Error("Failed to create wallet set");

  console.log("Creating wallet...");
  const wallet = (
    await client.createWallets({
      walletSetId: walletSet.id,
      blockchains: ["ARC-TESTNET"],
      count: 1,
      accountType: "EOA"
    })
  ).data.wallets[0];

  console.log("WALLET ADDRESS:", wallet.address);
  fs.appendFileSync(ENV_PATH, `CIRCLE_WALLET_ADDRESS=${wallet.address}\n`, "utf-8");
  fs.appendFileSync(ENV_PATH, `CIRCLE_WALLET_BLOCKCHAIN=${wallet.blockchain}\n`, "utf-8");
  fs.writeFileSync(path.join(OUTPUT_DIR, "wallet-info.json"), JSON.stringify(wallet, null, 2), "utf-8");
}

main().catch(console.error);
