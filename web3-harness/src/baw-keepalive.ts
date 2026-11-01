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

    if (isUnbound) {
      await sendDiscordChannelEmbed(
        'positions',
        {
          title: '⚠️ [WARNING] Sesi Binance Agentic Wallet (.ai) Terputus / Unbind!',
          color: 0xef4444,
          description:
            'Heartbeat mendeteksi sesi `baw` telah logout/unbind. Segera SSH ke VPS dan jalankan `baw auth signin` untuk scan ulang QR dari aplikasi Binance.',
          fields: [
            { name: 'Output Status', value: `\`\`\`${statusRes.stdout || statusRes.stderr}\`\`\`` },
          ],
          timestamp,
        },
        'Pierre — BAW Session Monitor'
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
      await sendDiscordChannelEmbed(
        'positions',
        {
          title: '🟢 [KEEP-ALIVE] Sesi Binance Agentic Wallet (.ai) Aktif',
          color: 0x10b981,
          description:
            'Heartbeat 6-jam berhasil memperbarui aktivitas sesi `baw` (mencegah auto-unbind 48 jam).',
          fields: [
            {
              name: 'Wallet Status',
              value: `\`\`\`${(statusRes.stdout || 'ACTIVE').slice(0, 500)}\`\`\``,
            },
          ],
          timestamp,
        },
        'Pierre — BAW Session Monitor'
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

