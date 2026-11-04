import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { runBawCli } from './mcp-server.js';
import { sendDiscordChannelEmbed } from './webhook.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, '..', '.env'), quiet: true });

// USDT on BNB Smart Chain for zero-cost authenticated MPC quote heartbeat
const BSC_USDT_ADDRESS = '0x55d398326f99059fF775485246999027B3197955';

export interface BawKeepAliveResult {
  alive: boolean;
  timestamp: string;
  statusOutput?: string;
  balanceOutput?: string;
  quoteHeartbeatOutput?: string;
  error?: string;
}

/**
 * Executes an authenticated session heartbeat against Binance Agentic Wallet (`baw` CLI)
 * to prevent the 48-hour inactivity auto-unbind/logout rule on Binance Web3 MPC wallets.
 * Recommended schedule: every 6 hours (8x safety margin inside the 48h window).
 */
export async function runBawKeepAlive(notifyDiscordOnSuccess = false): Promise<BawKeepAliveResult> {
  const timestamp = new Date().toISOString();
  console.error(`[BAW-KeepAlive] Menjalankan session heartbeat pada ${timestamp}...`);

  try {
    // 1. Check wallet authentication status & address
    const statusRes = await runBawCli(['wallet', 'status']);
    const balanceRes = await runBawCli(['wallet', 'balance']);

    // 2. Run a read-only authenticated MPC swap quote on BSC to refresh backend session activity
    let quoteOutput = '';
    try {
      const quoteRes = await runBawCli([
        'market-order',
        'quote',
        '--chain',
        'bsc',
        '--fromToken',
        'NATIVE',
        '--toToken',
        BSC_USDT_ADDRESS,
        '--fromTokenQty',
        '0.001',
      ]);
      quoteOutput = quoteRes.stdout;
    } catch (quoteErr) {
      quoteOutput = quoteErr instanceof Error ? quoteErr.message : String(quoteErr);
    }

    const combinedStatus = `${statusRes.stdout} ${statusRes.stderr}`.toLowerCase();
    const isUnbound =
      combinedStatus.includes('not signed in') ||
      combinedStatus.includes('unauthorized') ||
      combinedStatus.includes('unbind') ||
      combinedStatus.includes('expired') ||
      combinedStatus.includes('login');

    const bscLogoUrl =
      'https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/binance/info/logo.png';

    if (isUnbound) {
      const diagOut = (statusRes.stdout || statusRes.stderr || 'Disconnected').trim().slice(0, 400);
      await sendDiscordChannelEmbed(
        'positions',
        {
          author: {
            name: 'RŮŽE HOUSE  ·  SESSION MONITOR',
            icon_url: bscLogoUrl,
          },
          title: '🚨 Binance Agentic Wallet Session Unbound',
          url: 'https://bscscan.com',
          thumbnail: { url: bscLogoUrl },
          color: 0xef4444,
          description:
            '> **Action Required:** `baw` MPC session is disconnected or expired.\n> Run `baw auth signin` on the VPS and scan the QR code via the Binance mobile app.',
          fields: [
            { name: '🔴 SESSION STATE', value: '`UNBOUND / EXPIRED`', inline: true },
            { name: '🤖 WALLET ENGINE', value: '`BAW MPC (.ai)`', inline: true },
            { name: '⏱️ CADENCE', value: '`6h Interval`', inline: true },
            {
              name: '📋 DIAGNOSTIC TELEMETRY',
              value: `\`\`\`yaml\n${diagOut}\n\`\`\``,
              inline: false,
            },
          ],
          footer: {
            text: 'Pierre Execution Desk  ·  BAW Session Monitor',
            icon_url: bscLogoUrl,
          },
          timestamp,
        },
        'Pierre  |  Session Monitor'
      );

      return {
        alive: false,
        timestamp,
        statusOutput: statusRes.stdout,
        error: 'Session unbound or expired',
      };
    }

    console.error('[BAW-KeepAlive] Sesi Binance Agentic Wallet (.ai) aktif & ter-refresh.');

    if (notifyDiscordOnSuccess) {
      const statusClean = (statusRes.stdout || 'ACTIVE').trim().slice(0, 400);
      await sendDiscordChannelEmbed(
        'positions',
        {
          author: {
            name: 'RŮŽE HOUSE  ·  SESSION MONITOR',
            icon_url: bscLogoUrl,
          },
          title: '🛡️ Binance Agentic Wallet Session Verified',
          url: 'https://bscscan.com',
          thumbnail: { url: bscLogoUrl },
          color: 0x10b981,
          description:
            '> 🤖 6-hour authenticated MPC heartbeat completed (48h auto-unbind protection active).',
          fields: [
            { name: '🟢 SESSION STATE', value: '`ACTIVE / VERIFIED`', inline: true },
            { name: '🤖 WALLET ENGINE', value: '`BAW MPC (.ai)`', inline: true },
            { name: '⏱️ CADENCE', value: '`6h Interval`', inline: true },
            {
              name: '📋 SESSION TELEMETRY',
              value: `\`\`\`yaml\n${statusClean}\n\`\`\``,
              inline: false,
            },
          ],
          footer: {
            text: 'Pierre Execution Desk  ·  BAW Session Monitor',
            icon_url: bscLogoUrl,
          },
          timestamp,
        },
        'Pierre  |  Session Monitor'
      );
    }

    return {
      alive: true,
      timestamp,
      statusOutput: statusRes.stdout,
      balanceOutput: balanceRes.stdout,
      quoteHeartbeatOutput: quoteOutput,
    };
  } catch (err) {
    const errMsg = err instanceof Error ? err.message : String(err);
    console.error(`[BAW-KeepAlive] Peringatan: gagal menjalankan baw CLI (${errMsg}).`);
    return {
      alive: false,
      timestamp,
      error: errMsg,
    };
  }
}

// Allow running directly via `npx tsx src/baw-keepalive.ts` (for system cron / PM2 cron)
const isDirectRun =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename);

if (isDirectRun) {
  runBawKeepAlive(false)
    .then((res) => {
      console.error('[BAW-KeepAlive] Result:', JSON.stringify(res, null, 2));
      process.exit(0);
    })
    .catch((err) => {
      console.error('[BAW-KeepAlive] Fatal Error:', err);
      process.exit(1);
    });
}

