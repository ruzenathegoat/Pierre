import {
  DB_PATH,
  insertTrade,
  insertPosition,
  getOpenPositions,
  updateHWM,
  markPositionAlerted,
  closePosition,
  saveStagedTx,
  getValidStagedTx,
  deleteStagedTx,
} from './db.js';
import { broadcastToDiscord } from './webhook.js';

async function runPhase1Test() {
  console.error('=== Phase 1 Verification Test ===');
  console.error(`[1] SQLite Database Path: ${DB_PATH}`);

  // 1. Test staged_transactions lifecycle
  const testTxId = 'test-staged-001';
  saveStagedTx({
    tx_id: testTxId,
    chain: 'base',
    contract_address: '0x1234567890abcdef1234567890abcdef12345678',
    calldata: '0x1249c58b',
    value_eth: 0.015,
    action_type: 'MINT',
    asset_name: 'Pierre Genesis #1',
    source_url: 'https://opensea.io/collection/pierre-genesis',
    token_id: '1',
    is_fresh_input: false,
  });

  const staged = getValidStagedTx(testTxId);
  if (!staged || staged.tx_id !== testTxId) {
    throw new Error('Gagal menyimpan/membaca staged_transactions');
  }
  console.error(`[2] Staged TX verified: ${staged.tx_id} (${staged.asset_name})`);
  deleteStagedTx(testTxId);

  // 2. Test positions & trades lifecycle
  const posId = insertPosition({
    chain: 'base',
    contract_address: '0x1234567890abcdef1234567890abcdef12345678',
    token_id: '42',
    asset_type: 'ERC721',
    asset_name: 'Base Punks #42',
    entry_price_eth: 0.02,
  });

  updateHWM(posId, 0.035);
  markPositionAlerted(posId);

  const openPositions = getOpenPositions();
  console.error(`[3] Open Positions count: ${openPositions.length}`);

  const tradeId = insertTrade({
    tx_hash: '0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
    action: 'MINT',
    chain: 'base',
    contract_address: '0x1234567890abcdef1234567890abcdef12345678',
    asset_name: 'Base Punks #42',
    price_eth: 0.02,
    realized_pnl_eth: 0,
    trigger_source: 'PHASE1_TEST',
  });
  console.error(`[4] Inserted Trade ID: ${tradeId}`);

  // Clean up test position so DB stays clean for live usage
  closePosition(posId);

  // 3. Test Discord Webhook broadcaster
  const sent = await broadcastToDiscord({
    action: 'MINT',
    chain: 'base',
    assetName: 'Base Punks #42 (Phase 1 Test)',
    contractAddress: '0x1234567890abcdef1234567890abcdef12345678',
    tokenId: '42',
    priceEth: 0.02,
    txHash: '0xabcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890',
    triggerSource: 'PHASE1_VERIFICATION',
  });

  console.error(`[5] Discord Webhook Broadcast Result: ${sent ? 'SENT' : 'SKIPPED (No Webhook URL in .env yet)'}`);
  console.error('=== Phase 1 Verification Passed! ===');
}

runPhase1Test().catch((err) => {
  console.error('Phase 1 Test Failed:', err);
  process.exit(1);
});

