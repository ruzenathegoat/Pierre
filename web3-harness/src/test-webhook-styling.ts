import dotenv from 'dotenv';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  broadcastPnlReport,
  broadcastPositionUpdate,
  broadcastToDiscord,
  sendDiscordChannelEmbed,
} from './webhook.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
dotenv.config({ path: path.resolve(__dirname, '..', '.env'), quiet: true });

async function runWebhookTest() {
  console.log('=== Testing Revised Discord Webhook Embeds ===');

  // 1. Test #positions embed (New Luxury Layout with 3-Column Top Grid + YAML On-Chain Telemetry)
  console.log('[1/4] Sending revised Position Opened card to #positions...');
  const posOk = await broadcastPositionUpdate({
    event: 'POSITION_OPENED',
    positionId: 101,
    chain: 'base',
    assetName: 'CyberPunks #101',
    contractAddress: '0x1234567890abcdef1234567890abcdef12345678',
    tokenId: '101',
    assetType: 'ERC721',
    entryPriceEth: 0.05,
    currentBidEth: 0.0585,
    highWaterMarkEth: 0.06,
    status: 'OPEN',
    txHash: '0x3a4b5c6d7e8f90123456789abcdef0123456789abcdef0123456789abcdef01',
    note: 'Optimal entry via OpenSea Seaport with strong bid wall support',
  });
  console.log(` -> Result: ${posOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}`);

  // 2. Test #order-execution embed (3-Column Settlement Grid + YAML Execution Ledger)
  console.log('[2/4] Sending revised Order Execution card to #order-execution...');
  const execOk = await broadcastToDiscord({
    action: 'BUY',
    chain: 'bsc',
    assetName: 'NiulaiAgent.ai',
    contractAddress: '0x15e47c22df42D94Fa2f0aD078Fec5Bea6453d5cF',
    tokenId: 'BAW_MPC',
    priceEth: 0.002,
    txHash: '0x4066a17821409d56b1b98718f648f2fa16129c81a50d4dfc54ba88d79b4e7692',
    triggerSource: 'BAW_EXCLUSIVE_BONDING_CURVE',
  });
  console.log(` -> Result: ${execOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}`);

  // 3. Test #pnl Trade Settlement embed (Profit / Loss Card)
  console.log('[3/4] Sending revised Realized PnL Settlement card to #pnl...');
  const pnlTradeOk = await broadcastPnlReport({
    action: 'AUTO_SELL',
    chain: 'base',
    assetName: 'CyberPunks #101',
    contractAddress: '0x1234567890abcdef1234567890abcdef12345678',
    tokenId: '101',
    positionId: 101,
    entryPriceEth: 0.05,
    priceEth: 0.075,
    realizedPnlEth: 0.025,
    highWaterMarkEth: 0.08,
    txHash: '0x7b8c9d0e1f2a34567890abcdef1234567890abcdef1234567890abcdef1234',
    triggerSource: 'WATCHER_HWM_TRAILING_PEAK',
  });
  console.log(` -> Result: ${pnlTradeOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}`);

  // 4. Test #pnl 30-Minute Dual-Wallet Performance Report (Direct comparison with user's screenshot)
  console.log('[4/4] Sending revised Dual-Wallet 30m Performance Report to #pnl...');
  const nowWib = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Jakarta',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date()).replace(',', '') + ' WIB';

  const dualWalletReport = {
    author: { name: 'RŮŽE HOUSE  ·  PORTFOLIO LEDGER' },
    title: 'Dual-Wallet Performance & Balance Report',
    description: '> Consolidated performance and spot liquidity across isolated Viem EOA and Binance Agentic `.ai` MPC wallets.',
    color: 0xd4af37, // Champagne Gold
    fields: [
      {
        name: 'NET PNL (USD)',
        value: '`$0.00`',
        inline: true,
      },
      {
        name: 'REALIZED TOTAL',
        value: '`0.0000 ETH  ·  0.0000 BNB`',
        inline: true,
      },
      {
        name: 'OPEN POSITIONS',
        value: '`2 Open  (0 EOA · 2 BAW)`',
        inline: true,
      },
      {
        name: 'WALLET I  ·  VIEM EOA  (0xBAD5…936c)',
        value: [
          '```yaml',
          'Realized PnL   :  0.0000 ETH  |  0.0000 BNB  (0 trades)',
          'Unrealized     :  0.0000 ETH  |  0.0000 BNB  (0 open)',
          'Spot Balance   :  0.0000 ETH (Base)  |  0.0000 ETH (ETH)  |  0.0000 BNB (BSC)',
          '```',
        ].join('\n'),
        inline: false,
      },
      {
        name: 'WALLET II  ·  BINANCE AGENTIC .AI  (0x7462…269F)',
        value: [
          '```yaml',
          'Realized PnL   :  0.0000 BNB  (2 trades)',
          'Unrealized     :  Pre-DEX Curve  (2 open, no market bid)',
          'Spot Balance   :  0.006561 BNB  (BSC)',
          '```',
        ].join('\n'),
        inline: false,
      },
    ],
    footer: { text: `Pierre Execution Desk  ·  30m Ledger  ·  ${nowWib}` },
    timestamp: new Date().toISOString(),
  };

  const dualWalletOk = await sendDiscordChannelEmbed(
    'pnl',
    dualWalletReport,
    'Pierre  |  PnL Ledger'
  );
  console.log(` -> Result: ${dualWalletOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}`);

  console.log('=== All Webhook Tests Finished ===');
}

runWebhookTest().catch((err) => {
  console.error('Test execution error:', err);
  process.exit(1);
});
