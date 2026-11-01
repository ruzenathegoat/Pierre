import {
  closePosition,
  getPositionById,
  insertPosition,
} from './db.js';
import type { OrderbookSnapshot } from './marketplace.js';
import { evaluatePositionSnapshot } from './watcher.js';

async function runPhase4Verification() {
  console.error('=== Phase 4 HWM Watcher & Trailing Peak Verification ===');

  // 1. Insert a mock OPEN position (e.g. AgentPierre.ai on BNB Chain at 0.05 BNB entry)
  const posId = insertPosition({
    chain: 'bsc',
    contract_address: '0x9999999999999999999999999999999999999999',
    token_id: 'BAW_MPC',
    asset_type: 'ERC20',
    asset_name: 'AgentPierre.ai',
    entry_price_eth: 0.05,
  });
  console.error(`[1] Mock position #${posId} created (Entry: 0.05 BNB, HWM: 0.05 BNB).`);

  // 2. Simulate price rising to 0.142 BNB (+184% ROI) -> HWM should update to 0.142
  let pos = getPositionById(posId)!;
  const risingSnapshot: OrderbookSnapshot = {
    chain: 'bsc',
    contractAddress: pos.contract_address,
    tokenId: pos.token_id,
    assetType: 'ERC20',
    bestBidEth: 0.142,
    top3BidsEth: [0.142, 0.140, 0.138],
    floorPriceEth: 0.142,
    listedRatioPct: 0,
    salesVelocity1h: 'ACCELERATING',
    launchpadStage: 'GRADUATED_DEX',
    source: 'dexscreener',
  };

  const step1 = await evaluatePositionSnapshot(pos, risingSnapshot, { dryRunTestMode: true });
  pos = getPositionById(posId)!;
  if (step1.actionTaken !== 'HWM_UPDATED' || pos.high_water_mark_eth !== 0.142) {
    throw new Error(`HWM gagal ter-update. Expected 0.142, got ${pos.high_water_mark_eth}`);
  }
  console.error(`[2] Rising price test passed: HWM updated to ${pos.high_water_mark_eth} BNB.`);

  // 3. Simulate price dropping from 0.142 BNB peak to 0.134 BNB (-5.63% drop from peak, ROI +168%)
  const droppingSnapshot: OrderbookSnapshot = {
    ...risingSnapshot,
    bestBidEth: 0.134,
    top3BidsEth: [0.134, 0.131, 0.115],
    salesVelocity1h: 'DECELERATING',
  };

  const step2 = await evaluatePositionSnapshot(pos, droppingSnapshot, { dryRunTestMode: true });
  if (step2.actionTaken !== 'LLM_ALERT_TRIGGERED' || !step2.payload) {
    throw new Error(`Expected LLM_ALERT_TRIGGERED, got ${step2.actionTaken}`);
  }
  console.error('[3] Trailing Peak Alert triggered! Structured Context Payload:');
  console.error(JSON.stringify(step2.payload, null, 2));

  // 4. Verify 5-minute Anti-Spam Cooldown immediately after alert
  pos = getPositionById(posId)!;
  const step3 = await evaluatePositionSnapshot(pos, droppingSnapshot, { dryRunTestMode: true });
  if (step3.actionTaken !== 'COOLDOWN_SKIPPED') {
    throw new Error(`Expected COOLDOWN_SKIPPED, got ${step3.actionTaken}`);
  }
  console.error('[4] 5-Minute Anti-Spam Cooldown verified (COOLDOWN_SKIPPED).');

  // 5. Simulate Emergency Crash (-18.3% drop from peak to 0.116 BNB) -> Bypass cooldown & trigger EMERGENCY_HARD_STOP
  const crashSnapshot: OrderbookSnapshot = {
    ...risingSnapshot,
    bestBidEth: 0.116,
    top3BidsEth: [0.116, 0.100, 0.080],
    salesVelocity1h: 'DECELERATING',
  };
  const step4 = await evaluatePositionSnapshot(pos, crashSnapshot, { dryRunTestMode: true });
  if (step4.actionTaken !== 'EMERGENCY_HARD_STOP') {
    throw new Error(`Expected EMERGENCY_HARD_STOP, got ${step4.actionTaken}`);
  }
  console.error('[5] Emergency Hard-Stop Fallback (-18.3% drop) verified!');

  // Clean up mock position
  closePosition(posId);
  console.error('=== Phase 4 Verification Passed! ===');
}

runPhase4Verification().catch((err) => {
  console.error('Phase 4 Verification Failed:', err);
  process.exit(1);
});

