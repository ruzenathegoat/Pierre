import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { TradeActionType } from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, '..', '.env'), quiet: true });

/**
 * Core channels:
 * - 'positions'       -> DISCORD_WEBHOOK_POSITIONS (#positions)
 * - 'order-execution' -> DISCORD_WEBHOOK_ORDER_EXECUTION (#order-execution)
 * - 'pnl'             -> DISCORD_WEBHOOK_PNL (#pnl)
 * Any future channel string (e.g. 'alerts', 'scanner') automatically resolves
 * to DISCORD_WEBHOOK_<UPPERCASE_SNAKE_NAME> in .env!
 */
export type WebhookChannel = 'positions' | 'order-execution' | 'pnl' | (string & {});

export interface DiscordBroadcastPayload {
  action: TradeActionType | string;
  chain: 'base' | 'ethereum' | 'bsc' | 'robinhood' | string;
  assetName: string;
  contractAddress: string;
  tokenId?: string;
  positionId?: number | null;
  entryPriceEth?: number;
  highWaterMarkEth?: number;
  priceEth: number;
  realizedPnlEth?: number;
  txHash: string;
  triggerSource: string;
}

export interface PositionWebhookPayload {
  event: 'POSITION_OPENED' | 'HWM_UPDATED' | 'TRAILING_PEAK_ALERT' | 'POSITION_CLOSED';
  positionId: number;
  chain: string;
  assetName: string;
  contractAddress: string;
  tokenId?: string;
  assetType?: string;
  entryPriceEth: number;
  currentBidEth?: number;
  highWaterMarkEth: number;
  status: 'OPEN' | 'CLOSED';
  txHash?: string;
  note?: string;
}

const ACTION_COLORS: Record<string, number> = {
  BUY: 0x3b82f6,            // Blue
  MINT: 0x8b5cf6,           // Purple
  CLAIM: 0x10b981,          // Emerald Green
  AUTO_SELL: 0xf59e0b,      // Amber Gold
  EMERGENCY_SELL: 0xef4444, // Red
};

export function getNativeCurrencySymbol(chain: string): 'ETH' | 'BNB' {
  const normalized = chain.trim().toLowerCase();
  if (normalized === 'bsc' || normalized === 'bnb') {
    return 'BNB';
  }
  return 'ETH';
}

export function getExplorerTxUrl(chain: string, txHash: string): string {
  const normalized = chain.trim().toLowerCase();
  if (normalized === 'base') {
    return `https://basescan.org/tx/${txHash}`;
  }
  if (normalized === 'bsc' || normalized === 'bnb') {
    return `https://bscscan.com/tx/${txHash}`;
  }
  if (normalized === 'robinhood' || normalized === 'rh') {
    return `https://robinhoodchain.blockscout.com/tx/${txHash}`;
  }
  return `https://etherscan.io/tx/${txHash}`;
}

/**
 * Dynamically resolves the Discord Webhook URL for a given channel name.
 * Example:
 * - 'positions'       -> process.env.DISCORD_WEBHOOK_POSITIONS
 * - 'order-execution' -> process.env.DISCORD_WEBHOOK_ORDER_EXECUTION
 * - 'pnl'             -> process.env.DISCORD_WEBHOOK_PNL
 * - 'whale-alerts'    -> process.env.DISCORD_WEBHOOK_WHALE_ALERTS
 * Falls back to DISCORD_TRADE_WEBHOOK_URL if the specific channel key is not configured.
 */
export function resolveWebhookUrl(channel: WebhookChannel): string | undefined {
  const envSuffix = channel
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_');
  const envKey = `DISCORD_WEBHOOK_${envSuffix}`;
  const specificUrl = process.env[envKey]?.trim();

  if (specificUrl && !specificUrl.includes('...')) {
    return specificUrl;
  }

  const fallbackUrl = process.env.DISCORD_TRADE_WEBHOOK_URL?.trim();
  if (fallbackUrl && !fallbackUrl.includes('...')) {
    return fallbackUrl;
  }

  return undefined;
}

export async function sendDiscordChannelEmbed(
  channel: WebhookChannel,
  embed: Record<string, unknown>,
  username = `Pierre — #${channel}`
): Promise<boolean> {
  const webhookUrl = resolveWebhookUrl(channel);

  if (!webhookUrl) {
    console.error(
      `[Webhook:${channel}] URL belum dikonfigurasi di .env (DISCORD_WEBHOOK_${channel
        .toUpperCase()
        .replace(/[^A-Z0-9]+/g, '_')}) — melewati pengiriman.`
    );
    return false;
  }

  try {
    const res = await fetch(webhookUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        embeds: [embed],
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error(`[Webhook:${channel}] Gagal mengirim (HTTP ${res.status}): ${errText}`);
      return false;
    }

    console.error(`[Webhook:${channel}] Embed berhasil dikirim ke channel #${channel}.`);
    return true;
  } catch (err) {
    console.error(`[Webhook:${channel}] Error saat mengirim webhook:`, err);
    return false;
  }
}

/**
 * Sends a dedicated Position lifecycle / HWM card to #positions (DISCORD_WEBHOOK_POSITIONS).
 */
export async function broadcastPositionUpdate(payload: PositionWebhookPayload): Promise<boolean> {
  const symbol = getNativeCurrencySymbol(payload.chain);
  const currentPrice = payload.currentBidEth ?? payload.highWaterMarkEth;
  const unrealizedRoiPct =
    payload.entryPriceEth > 0
      ? ((currentPrice - payload.entryPriceEth) / payload.entryPriceEth) * 100
      : 0;
  const roiSign = unrealizedRoiPct >= 0 ? '+' : '';

  const colorMap: Record<PositionWebhookPayload['event'], number> = {
    POSITION_OPENED: 0x22c55e,     // Green
    HWM_UPDATED: 0x3b82f6,         // Blue
    TRAILING_PEAK_ALERT: 0xf59e0b, // Amber
    POSITION_CLOSED: 0x64748b,     // Slate
  };

  const fields: Array<{ name: string; value: string; inline?: boolean }> = [
    { name: 'Position ID', value: `\`#${payload.positionId}\``, inline: true },
    { name: 'Status', value: `\`${payload.status}\``, inline: true },
    { name: 'Chain', value: `\`${payload.chain.toUpperCase()}\``, inline: true },
    {
      name: 'Entry Price',
      value: `**${payload.entryPriceEth.toFixed(4)} ${symbol}**`,
      inline: true,
    },
    {
      name: 'High-Water Mark (HWM)',
      value: `**${payload.highWaterMarkEth.toFixed(4)} ${symbol}**`,
      inline: true,
    },
    {
      name: 'Current / Exit Valuation',
      value: `**${currentPrice.toFixed(4)} ${symbol}** (${roiSign}${unrealizedRoiPct.toFixed(2)}%)`,
      inline: true,
    },
    {
      name: 'Contract',
      value: `\`${payload.contractAddress}\`${payload.tokenId ? ` (Token: \`${payload.tokenId}\`)` : ''}`,
      inline: false,
    },
  ];

  if (payload.note) {
    fields.push({ name: 'Note', value: payload.note, inline: false });
  }

  const embed: Record<string, unknown> = {
    title: `📊 [${payload.event}] ${payload.assetName}`,
    url: payload.txHash ? getExplorerTxUrl(payload.chain, payload.txHash) : undefined,
    color: colorMap[payload.event],
    fields,
    footer: { text: 'Pierre — Active Positions & HWM Tracker (#positions)' },
    timestamp: new Date().toISOString(),
  };

  return sendDiscordChannelEmbed('positions', embed, 'Pierre — Positions Tracker');
}

/**
 * Sends a dedicated Realized PnL & ROI card to #pnl (DISCORD_WEBHOOK_PNL).
 */
export async function broadcastPnlReport(payload: DiscordBroadcastPayload): Promise<boolean> {
  const symbol = getNativeCurrencySymbol(payload.chain);
  const explorerUrl = getExplorerTxUrl(payload.chain, payload.txHash);
  const entry = payload.entryPriceEth ?? 0;
  const realizedPnl = payload.realizedPnlEth ?? payload.priceEth - entry;
  const roiPct = entry > 0 ? (realizedPnl / entry) * 100 : 0;
  const isProfit = realizedPnl >= 0;
  const sign = isProfit ? '+' : '';

  const fields: Array<{ name: string; value: string; inline?: boolean }> = [
    {
      name: 'Result',
      value: isProfit ? '🟢 **PROFIT**' : '🔴 **LOSS**',
      inline: true,
    },
    {
      name: 'Realized PnL',
      value: `**${sign}${realizedPnl.toFixed(4)} ${symbol}**`,
      inline: true,
    },
    {
      name: 'Realized ROI',
      value: `**${sign}${roiPct.toFixed(2)}%**`,
      inline: true,
    },
    {
      name: 'Entry Price',
      value: `${entry.toFixed(4)} ${symbol}`,
      inline: true,
    },
    {
      name: 'Exit / Sold Price',
      value: `${payload.priceEth.toFixed(4)} ${symbol}`,
      inline: true,
    },
    {
      name: 'Peak HWM Reached',
      value: `${(payload.highWaterMarkEth ?? Math.max(entry, payload.priceEth)).toFixed(4)} ${symbol}`,
      inline: true,
    },
    {
      name: 'Chain & Trigger',
      value: `\`${payload.chain.toUpperCase()}\` • \`${payload.triggerSource}\``,
      inline: true,
    },
    {
      name: 'Explorer',
      value: `[View Settlement Tx](${explorerUrl})`,
      inline: true,
    },
  ];

  const embed: Record<string, unknown> = {
    title: `💰 [REALIZED PnL] ${payload.assetName}`,
    url: explorerUrl,
    color: isProfit ? 0x10b981 : 0xef4444,
    fields,
    footer: { text: 'Pierre — Realized PnL Ledger (#pnl)' },
    timestamp: new Date().toISOString(),
  };

  return sendDiscordChannelEmbed('pnl', embed, 'Pierre — PnL Ledger');
}

/**
 * Primary multi-channel broadcaster triggered on every trade execution:
 * 1. Always sends execution receipt to `#order-execution` (DISCORD_WEBHOOK_ORDER_EXECUTION).
 * 2. If BUY / MINT -> also sends POSITION_OPENED card to `#positions` (DISCORD_WEBHOOK_POSITIONS).
 * 3. If AUTO_SELL / EMERGENCY_SELL / SELL -> also sends POSITION_CLOSED card to `#positions`
 *    AND sends Realized PnL report card to `#pnl` (DISCORD_WEBHOOK_PNL).
 */
export async function broadcastToDiscord(payload: DiscordBroadcastPayload): Promise<boolean> {
  const explorerUrl = getExplorerTxUrl(payload.chain, payload.txHash);
  const symbol = getNativeCurrencySymbol(payload.chain);
  const actionUpper = payload.action.toUpperCase();
  const color = ACTION_COLORS[actionUpper] ?? 0x6366f1;

  // 1. Send Order Execution log to #order-execution
  const execFields: Array<{ name: string; value: string; inline?: boolean }> = [
    { name: 'Action', value: `\`${actionUpper}\``, inline: true },
    { name: 'Chain', value: `\`${payload.chain.toUpperCase()}\``, inline: true },
    { name: 'Execution Value', value: `**${payload.priceEth.toFixed(4)} ${symbol}**`, inline: true },
    {
      name: 'Contract',
      value: `\`${payload.contractAddress}\`${payload.tokenId ? ` (Token: \`${payload.tokenId}\`)` : ''}`,
      inline: false,
    },
    { name: 'Trigger Source', value: `\`${payload.triggerSource}\``, inline: true },
    { name: 'Explorer', value: `[View Transaction](${explorerUrl})`, inline: true },
  ];

  const execEmbed: Record<string, unknown> = {
    title: `⚡ [ORDER ${actionUpper}] ${payload.assetName}`,
    url: explorerUrl,
    color,
    fields: execFields,
    footer: { text: 'Pierre — Order Execution Feed (#order-execution)' },
    timestamp: new Date().toISOString(),
  };

  const results: boolean[] = [];
  results.push(await sendDiscordChannelEmbed('order-execution', execEmbed, 'Pierre — Order Execution'));

  // 2. Route to #positions on BUY / MINT
  if (actionUpper === 'BUY' || actionUpper === 'MINT') {
    results.push(
      await broadcastPositionUpdate({
        event: 'POSITION_OPENED',
        positionId: payload.positionId ?? 0,
        chain: payload.chain,
        assetName: payload.assetName,
        contractAddress: payload.contractAddress,
        tokenId: payload.tokenId,
        entryPriceEth: payload.entryPriceEth ?? payload.priceEth,
        currentBidEth: payload.priceEth,
        highWaterMarkEth: payload.highWaterMarkEth ?? payload.priceEth,
        status: 'OPEN',
        txHash: payload.txHash,
      })
    );
  }

  // 3. Route to #positions (CLOSED) and #pnl on SELL / AUTO_SELL / EMERGENCY_SELL
  if (actionUpper === 'AUTO_SELL' || actionUpper === 'EMERGENCY_SELL' || actionUpper === 'SELL') {
    results.push(
      await broadcastPositionUpdate({
        event: 'POSITION_CLOSED',
        positionId: payload.positionId ?? 0,
        chain: payload.chain,
        assetName: payload.assetName,
        contractAddress: payload.contractAddress,
        tokenId: payload.tokenId,
        entryPriceEth: payload.entryPriceEth ?? 0,
        currentBidEth: payload.priceEth,
        highWaterMarkEth: payload.highWaterMarkEth ?? payload.priceEth,
        status: 'CLOSED',
        txHash: payload.txHash,
      })
    );

    results.push(await broadcastPnlReport(payload));
  }

  return results.some(Boolean);
}
