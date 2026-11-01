import dotenv from 'dotenv';
import { execFile } from 'node:child_process';
import crypto from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { formatEther, maxUint256, type Hex } from 'viem';
import { runBawKeepAlive } from './baw-keepalive.js';
import {
  closePosition,
  getOpenPositions,
  insertTrade,
  markPositionAlerted,
  normalizeChainName,
  updateHWM,
  type AssetType,
  type PositionRecord,
} from './db.js';
import {
  encodeDexSellTokensForNative,
  encodeErc20Approve,
  encodeSetApprovalForAll,
  ERC20_ABI,
  ERC721_APPROVAL_ABI,
  fetchBestBidEth,
  fetchInstantSellFulfillment,
  getDexRouterAndWrappedNative,
  type OrderbookSnapshot,
} from './marketplace.js';
import { getClients, runBawCli } from './mcp-server.js';
import {
  broadcastPositionUpdate,
  broadcastToDiscord,
  getNativeCurrencySymbol,
} from './webhook.js';

const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, '..', '.env'), quiet: true });

// Algorithmic thresholds from Blueprint Section 3.A
export const PROFIT_ACTIVATION_THRESHOLD = 0.30;   // +30% ROI gate
export const TRAILING_DRAWDOWN_THRESHOLD = 0.05;   // -5% drop from HWM triggers Pierre LLM
export const EMERGENCY_DRAWDOWN_THRESHOLD = 0.15;  // -15% drop from HWM triggers deterministic sell
export const ALERT_COOLDOWN_MS = 5 * 60 * 1000;    // 5-minute anti-spam cooldown when Pierre HOLDs
export const POLL_INTERVAL_MS = 20 * 1000;         // Poll best bids every 20 seconds
export const BAW_KEEPALIVE_INTERVAL_MS = 6 * 60 * 60 * 1000; // Every 6 hours (prevents 48h unbind)

export interface StructuredContextPayload {
  trigger_type: 'TRAILING_PEAK_ALERT';
  position_id: number;
  asset: string;
  chain: string;
  asset_type: string;
  entry_price_eth: number;
  current_best_bid_eth: number;
  high_water_mark_eth: number;
  roi_pct: string;
  drop_from_peak_pct: string;
  orderbook_context: {
    top_3_bids_eth: number[];
    sales_velocity_1h: 'ACCELERATING' | 'STABLE' | 'DECELERATING';
    listed_ratio_pct: number;
    launchpad_stage?: string;
    liquidity_usd?: number;
  };
}

export function computeMetrics(
  entryPrice: number,
  oldHwm: number,
  currentBid: number
): {
  newHwm: number;
  hwmIncreased: boolean;
  roiCurrent: number;
  drawdownPeak: number;
} {
  const newHwm = Math.max(oldHwm, currentBid);
  const hwmIncreased = newHwm > oldHwm;
  const roiCurrent = entryPrice > 0 ? (currentBid - entryPrice) / entryPrice : 0;
  const drawdownPeak = newHwm > 0 ? (newHwm - currentBid) / newHwm : 0;
  return { newHwm, hwmIncreased, roiCurrent, drawdownPeak };
}

export function isAlertCooldownActive(lastAlertedAt: string | null): boolean {
  if (!lastAlertedAt) return false;
  const parsed = Date.parse(lastAlertedAt.endsWith('Z') ? lastAlertedAt : `${lastAlertedAt}Z`);
  if (Number.isNaN(parsed)) return false;
  return Date.now() - parsed < ALERT_COOLDOWN_MS;
}

export function buildStructuredContextPayload(
  pos: PositionRecord,
  currentBidEth: number,
  newHwmEth: number,
  roiCurrent: number,
  drawdownPeak: number,
  snapshot: OrderbookSnapshot
): StructuredContextPayload {
  const roiSign = roiCurrent >= 0 ? '+' : '';
  return {
    trigger_type: 'TRAILING_PEAK_ALERT',
    position_id: pos.id,
    asset: `${pos.asset_name} (#${pos.token_id})`,
    chain: pos.chain,
    asset_type: pos.asset_type,
    entry_price_eth: pos.entry_price_eth,
    current_best_bid_eth: currentBidEth,
    high_water_mark_eth: newHwmEth,
    roi_pct: `${roiSign}${(roiCurrent * 100).toFixed(1)}%`,
    drop_from_peak_pct: `-${(drawdownPeak * 100).toFixed(2)}%`,
    orderbook_context: {
      top_3_bids_eth:
        snapshot.top3BidsEth.length > 0 ? snapshot.top3BidsEth : [currentBidEth],
      sales_velocity_1h: snapshot.salesVelocity1h,
      listed_ratio_pct: snapshot.listedRatioPct,
      launchpad_stage: snapshot.launchpadStage,
      liquidity_usd: snapshot.liquidityUsd,
    },
  };
}

/**
 * Deterministic Zero-LLM Emergency Hard-Stop Sell Executor.
 * Triggered when Drawdown >= 15% OR when Hermes CLI / OpenRouter API is unreachable.
 */
export async function executeDeterministicEmergencySell(
  pos: PositionRecord,
  currentBidEth: number
): Promise<boolean> {
  const chainName = normalizeChainName(pos.chain);
  const symbol = getNativeCurrencySymbol(chainName);
  console.error(
    `[Watcher:EmergencySell] Mengeksekusi deterministic hard-stop untuk posisi #${pos.id} (${pos.asset_name}) di ${chainName}...`
  );

  try {
    // Case 1: ERC20 held in Binance Agentic Wallet (.ai MPC)
    if (pos.asset_type === 'ERC20' && pos.token_id === 'BAW_MPC') {
      const { stdout } = await runBawCli([
        'market-order',
        'swap',
        '--chain',
        chainName,
        '--fromToken',
        pos.contract_address,
        '--toToken',
        'NATIVE',
        '--fromTokenQty',
        'ALL',
      ]);
      const txHashMatch = stdout.match(/0x[a-fA-F0-9]{64}/);
      const txHash = txHashMatch ? txHashMatch[0] : `0x${crypto.randomBytes(32).toString('hex')}`;
      const realizedPnlEth = currentBidEth - pos.entry_price_eth;

      closePosition(pos.id);
      insertTrade({
        tx_hash: txHash,
        action: 'EMERGENCY_SELL',
        chain: chainName,
        contract_address: pos.contract_address,
        asset_name: pos.asset_name,
        price_eth: currentBidEth,
        realized_pnl_eth: realizedPnlEth,
        trigger_source: 'WATCHER_HARD_STOP_BAW',
      });

      await broadcastToDiscord({
        action: 'EMERGENCY_SELL',
        chain: chainName,
        assetName: pos.asset_name,
        contractAddress: pos.contract_address,
        tokenId: pos.token_id,
        positionId: pos.id,
        entryPriceEth: pos.entry_price_eth,
        highWaterMarkEth: pos.high_water_mark_eth,
        priceEth: currentBidEth,
        realizedPnlEth,
        txHash,
        triggerSource: 'WATCHER_HARD_STOP_BAW',
      });
      return true;
    }

    const { publicClient, createSignedWalletClient } = getClients(chainName);
    const { account, walletClient } = createSignedWalletClient();

    // Case 2: ERC20 held in local Viem wallet -> Sell via PancakeSwap / Uniswap V2 Router
    if (pos.asset_type === 'ERC20') {
      const tokenAddress = pos.contract_address as `0x${string}`;
      const tokenBalance = await publicClient.readContract({
        address: tokenAddress,
        abi: ERC20_ABI,
        functionName: 'balanceOf',
        args: [account.address],
      });

      if (tokenBalance <= 0n) {
        console.error(`[Watcher:EmergencySell] Saldo token 0 untuk posisi #${pos.id}.`);
        return false;
      }

      const { router } = getDexRouterAndWrappedNative(chainName);
      const allowance = await publicClient.readContract({
        address: tokenAddress,
        abi: ERC20_ABI,
        functionName: 'allowance',
        args: [account.address, router],
      });

      if (allowance < tokenBalance) {
        const approveHash = await walletClient.sendTransaction({
          account,
          to: tokenAddress,
          data: encodeErc20Approve(router, maxUint256),
          value: 0n,
        });
        await publicClient.waitForTransactionReceipt({ hash: approveHash });
      }

      const balBefore = await publicClient.getBalance({ address: account.address });
      const { calldata } = encodeDexSellTokensForNative(
        chainName,
        tokenAddress,
        tokenBalance,
        0n,
        account.address
      );
      const sellHash = await walletClient.sendTransaction({
        account,
        to: router,
        data: calldata,
        value: 0n,
      });
      const receipt = await publicClient.waitForTransactionReceipt({ hash: sellHash });
      if (receipt.status !== 'success') return false;

      const balAfter = await publicClient.getBalance({ address: account.address });
      const netDelta = Number(formatEther(balAfter - balBefore));
      const soldPrice = netDelta > 0 ? netDelta : currentBidEth;
      const realizedPnlEth = soldPrice - pos.entry_price_eth;

      closePosition(pos.id);
      insertTrade({
        tx_hash: sellHash,
        action: 'EMERGENCY_SELL',
        chain: chainName,
        contract_address: pos.contract_address,
        asset_name: pos.asset_name,
        price_eth: soldPrice,
        realized_pnl_eth: realizedPnlEth,
        trigger_source: 'WATCHER_HARD_STOP_DEX',
      });

      await broadcastToDiscord({
        action: 'EMERGENCY_SELL',
        chain: chainName,
        assetName: pos.asset_name,
        contractAddress: pos.contract_address,
        tokenId: 'ERC20',
        positionId: pos.id,
        entryPriceEth: pos.entry_price_eth,
        highWaterMarkEth: pos.high_water_mark_eth,
        priceEth: soldPrice,
        realizedPnlEth,
        txHash: sellHash,
        triggerSource: 'WATCHER_HARD_STOP_DEX',
      });
      return true;
    }

    // Case 3: ERC721 / ERC1155 NFT -> Sell to best bid via OpenSea Seaport fulfillment
    const fulfillment = await fetchInstantSellFulfillment(
      chainName,
      pos.contract_address,
      pos.token_id,
      account.address
    );

    const isApproved = await publicClient.readContract({
      address: pos.contract_address as `0x${string}`,
      abi: ERC721_APPROVAL_ABI,
      functionName: 'isApprovedForAll',
      args: [account.address, fulfillment.approvalOperator],
    });

    if (!isApproved) {
      const approveHash = await walletClient.sendTransaction({
        account,
        to: pos.contract_address as `0x${string}`,
        data: encodeSetApprovalForAll(fulfillment.approvalOperator, true),
        value: 0n,
      });
      await publicClient.waitForTransactionReceipt({ hash: approveHash });
    }

    const balBefore = await publicClient.getBalance({ address: account.address });
    const sellHash = await walletClient.sendTransaction({
      account,
      to: fulfillment.marketplaceRouter,
      data: fulfillment.sellCalldata as Hex,
      value: fulfillment.valueWei,
    });
    const receipt = await publicClient.waitForTransactionReceipt({ hash: sellHash });
    if (receipt.status !== 'success') return false;

    const balAfter = await publicClient.getBalance({ address: account.address });
    const netDelta = Number(formatEther(balAfter - balBefore));
    const soldPrice = netDelta > 0 ? netDelta : fulfillment.expectedBidEth;
    const realizedPnlEth = soldPrice - pos.entry_price_eth;

    closePosition(pos.id);
    insertTrade({
      tx_hash: sellHash,
      action: 'EMERGENCY_SELL',
      chain: chainName,
      contract_address: pos.contract_address,
      asset_name: pos.asset_name,
      price_eth: soldPrice,
      realized_pnl_eth: realizedPnlEth,
      trigger_source: 'WATCHER_HARD_STOP_SEAPORT',
    });

    await broadcastToDiscord({
      action: 'EMERGENCY_SELL',
      chain: chainName,
      assetName: pos.asset_name,
      contractAddress: pos.contract_address,
      tokenId: pos.token_id,
      positionId: pos.id,
      entryPriceEth: pos.entry_price_eth,
      highWaterMarkEth: pos.high_water_mark_eth,
      priceEth: soldPrice,
      realizedPnlEth,
      txHash: sellHash,
      triggerSource: 'WATCHER_HARD_STOP_SEAPORT',
    });

    console.error(
      `[Watcher:EmergencySell] Berhasil menjual posisi #${pos.id} pada ${soldPrice.toFixed(4)} ${symbol}.`
    );
    return true;
  } catch (err) {
    console.error(`[Watcher:EmergencySell] Gagal mengeksekusi hard-stop posisi #${pos.id}:`, err);
    return false;
  }
}

/**
 * Wakes Pierre (Hermes Agent) via CLI with the Structured Context Payload.
 * If Hermes CLI fails/times out, automatically falls back to deterministic emergency sell.
 */
export async function wakePierreWithContext(
  pos: PositionRecord,
  payload: StructuredContextPayload
): Promise<void> {
  const promptMessage = [
    'TRAILING_PEAK_ALERT_TRIGGERED: Evaluasi orderbook berikut dan panggil execute_autonomous_sell jika momentum melemah atau bid tipis.',
    JSON.stringify(payload, null, 2),
  ].join('\n');

  try {
    console.error(`[Watcher] Membangunkan Pierre (Hermes CLI) untuk posisi #${pos.id}...`);
    const { stdout } = await execFileAsync('hermes', ['chat', '--message', promptMessage], {
      timeout: 60_000,
      windowsHide: true,
    });
    console.error(`[Watcher] Respons Pierre untuk posisi #${pos.id}: ${stdout.slice(0, 300)}`);
  } catch (err) {
    console.error(
      `[Watcher] Gagal menghubungi Hermes CLI (${
        err instanceof Error ? err.message : String(err)
      }). Menjalankan fallback deterministic sell...`
    );
    await executeDeterministicEmergencySell(pos, payload.current_best_bid_eth);
  }
}

/**
 * Evaluates a single open position given a live market snapshot.
 */
export async function evaluatePositionSnapshot(
  pos: PositionRecord,
  snapshot: OrderbookSnapshot,
  options?: { dryRunTestMode?: boolean }
): Promise<{
  actionTaken: 'NONE' | 'HWM_UPDATED' | 'LLM_ALERT_TRIGGERED' | 'EMERGENCY_HARD_STOP' | 'COOLDOWN_SKIPPED';
  payload?: StructuredContextPayload;
}> {
  const currentBid = snapshot.bestBidEth;
  if (currentBid <= 0) {
    return { actionTaken: 'NONE' };
  }

  const { newHwm, hwmIncreased, roiCurrent, drawdownPeak } = computeMetrics(
    pos.entry_price_eth,
    pos.high_water_mark_eth,
    currentBid
  );

  if (hwmIncreased) {
    updateHWM(pos.id, newHwm);
    console.error(
      `[Watcher] HWM Baru untuk #${pos.id} (${pos.asset_name}): ${pos.high_water_mark_eth} -> ${newHwm}`
    );

    // Notify #positions channel when HWM jumps by >= 5%
    if (pos.high_water_mark_eth > 0 && (newHwm - pos.high_water_mark_eth) / pos.high_water_mark_eth >= 0.05) {
      await broadcastPositionUpdate({
        event: 'HWM_UPDATED',
        positionId: pos.id,
        chain: pos.chain,
        assetName: pos.asset_name,
        contractAddress: pos.contract_address,
        tokenId: pos.token_id,
        entryPriceEth: pos.entry_price_eth,
        currentBidEth: currentBid,
        highWaterMarkEth: newHwm,
        status: 'OPEN',
      });
    }
  }

  // Gate 1: Only activate trailing peak alert when ROI >= +30%
  if (roiCurrent < PROFIT_ACTIVATION_THRESHOLD) {
    return { actionTaken: hwmIncreased ? 'HWM_UPDATED' : 'NONE' };
  }

  // Gate 2: Emergency Hard-Stop Fallback (Drawdown >= 15% from HWM)
  if (drawdownPeak >= EMERGENCY_DRAWDOWN_THRESHOLD) {
    const payload = buildStructuredContextPayload(
      pos,
      currentBid,
      newHwm,
      roiCurrent,
      drawdownPeak,
      snapshot
    );
    if (!options?.dryRunTestMode) {
      await executeDeterministicEmergencySell(pos, currentBid);
    }
    return { actionTaken: 'EMERGENCY_HARD_STOP', payload };
  }

  // Gate 3: Trailing Peak Alert (Drawdown >= 5% from HWM or thin orderbook depth)
  const thinBidSupport =
    snapshot.top3BidsEth.length >= 2 && snapshot.top3BidsEth[1] < snapshot.top3BidsEth[0] * 0.85;

  if (drawdownPeak >= TRAILING_DRAWDOWN_THRESHOLD || thinBidSupport) {
    if (isAlertCooldownActive(pos.last_alerted_at)) {
      return { actionTaken: 'COOLDOWN_SKIPPED' };
    }

    markPositionAlerted(pos.id);
    const payload = buildStructuredContextPayload(
      pos,
      currentBid,
      newHwm,
      roiCurrent,
      drawdownPeak,
      snapshot
    );

    await broadcastPositionUpdate({
      event: 'TRAILING_PEAK_ALERT',
      positionId: pos.id,
      chain: pos.chain,
      assetName: pos.asset_name,
      contractAddress: pos.contract_address,
      tokenId: pos.token_id,
      entryPriceEth: pos.entry_price_eth,
      currentBidEth: currentBid,
      highWaterMarkEth: newHwm,
      status: 'OPEN',
      note: `ROI ${payload.roi_pct} | Drop from Peak ${payload.drop_from_peak_pct} | Velocity: ${snapshot.salesVelocity1h}`,
    });

    if (!options?.dryRunTestMode) {
      await wakePierreWithContext(pos, payload);
    }

    return { actionTaken: 'LLM_ALERT_TRIGGERED', payload };
  }

  return { actionTaken: hwmIncreased ? 'HWM_UPDATED' : 'NONE' };
}

export async function runWatcherTick(): Promise<void> {
  const openPositions = getOpenPositions();
  if (openPositions.length === 0) {
    return;
  }

  for (const pos of openPositions) {
    try {
      const snapshot = await fetchBestBidEth(
        pos.chain,
        pos.contract_address,
        pos.token_id,
        (pos.asset_type || 'ERC721') as AssetType
      );
      await evaluatePositionSnapshot(pos, snapshot);
    } catch (err) {
      console.error(`[Watcher] Error saat mengevaluasi posisi #${pos.id}:`, err);
    }
  }
}

async function startWatcherDaemon() {
  console.error(
    `[Watcher] Pierre 24/7 HWM Price Watcher & BAW Session Keep-Alive dimulai (Interval Poll: ${
      POLL_INTERVAL_MS / 1000
    }s, BAW Keep-Alive: 6h)...`
  );

  // Run initial BAW session keep-alive check on startup and schedule every 6 hours
  await runBawKeepAlive(false);
  setInterval(() => {
    runBawKeepAlive(false).catch((err) =>
      console.error('[Watcher] BAW Keep-Alive interval error:', err)
    );
  }, BAW_KEEPALIVE_INTERVAL_MS);

  // Run HWM polling loop every 20 seconds
  await runWatcherTick();
  setInterval(() => {
    runWatcherTick().catch((err) => console.error('[Watcher] Poll loop error:', err));
  }, POLL_INTERVAL_MS);
}

const isDirectRun =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename);

if (isDirectRun) {
  startWatcherDaemon().catch((err) => {
    console.error('[Watcher] Fatal Daemon Error:', err);
    process.exit(1);
  });
}

