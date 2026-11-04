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
  console.log('====================================================');
  console.log('   PIERRE LUXURY EMBED STYLING VERIFICATION SUITE   ');
  console.log('   Testing all 5 target Discord channels...         ');
  console.log('====================================================\n');

  const nowWib =
    new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Jakarta',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
      .format(new Date())
      .replace(',', '') + ' WIB';

  // ------------------------------------------------------------------
  // 1. Channel: #positions
  // ------------------------------------------------------------------
  console.log('[1/5] Testing #positions: Active Open Position Lifecycle...');
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
  console.log(`      -> #positions result: ${posOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}\n`);

  // ------------------------------------------------------------------
  // 2. Channel: #order-execution
  // ------------------------------------------------------------------
  console.log('[2/5] Testing #order-execution: Trade Execution Card...');
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
  console.log(`      -> #order-execution result: ${execOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}\n`);

  // ------------------------------------------------------------------
  // 3. Channel: #pnl
  //    (Includes both Trade Settlement card and Dual-Wallet 30m Report)
  // ------------------------------------------------------------------
  console.log('[3/5] Testing #pnl: Realized Settlement + Dual-Wallet Report...');
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
  console.log(`      -> #pnl (Trade Settlement): ${pnlTradeOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}`);

  const binanceLogo = 'https://raw.githubusercontent.com/trustwallet/assets/master/blockchains/binance/info/logo.png';

  const dualWalletReport = {
    author: {
      name: 'RŮŽE HOUSE  ·  PORTFOLIO LEDGER',
      icon_url: binanceLogo,
    },
    title: '💼 Dual-Wallet Performance & Balance Report',
    thumbnail: {
      url: binanceLogo,
    },
    description: '> 🏛️ Consolidated performance, cash reserves, and open curve positions across dual execution wallets.',
    color: 0xd4af37, // Champagne Gold
    fields: [
      {
        name: '💰 NET PNL (EST.)',
        value: '`$0.00`',
        inline: true,
      },
      {
        name: '📊 REALIZED TOTAL',
        value: '`0.0000 ETH  ·  0.0000 BNB`',
        inline: true,
      },
      {
        name: '💼 OPEN POSITIONS',
        value: '`2 Active (0 EOA · 2 BAW)`',
        inline: true,
      },
      {
        name: '💳 WALLET I  ·  VIEM EOA (0xBAD5…936c)',
        value: [
          '```yaml',
          'Realized PnL   :  0.0000 ETH  |  0.0000 BNB  (0 trades)',
          'Unrealized     :  0.0000 ETH  |  0.0000 BNB  (0 open)',
          'Spot Balance   :  0.0000 ETH (Base)  |  0.0000 ETH (ETH)  |  0.0000 BNB (BSC)',
          '```',
          '> 🔗 [Basescan ↗](https://basescan.org/address/0xBAD577476432726C45267e2B57602dd4594a936c)  •  [Etherscan ↗](https://etherscan.io/address/0xBAD577476432726C45267e2B57602dd4594a936c)',
        ].join('\n'),
        inline: false,
      },
      {
        name: '🤖 WALLET II  ·  BINANCE AGENTIC .AI (0x7462…269F)',
        value: [
          '```yaml',
          'Realized PnL   :  0.0000 BNB  (2 trades)',
          'Unrealized     :  Pre-DEX Curve  (2 open, no market bid)',
          'Spot Balance   :  0.006561 BNB  (BSC)',
          '```',
          '> 🔗 [BscScan ↗](https://bscscan.com/address/0x74624463e902C11aB37C0034EB216A2B4466269F)',
        ].join('\n'),
        inline: false,
      },
    ],
    footer: {
      text: `Pierre Execution Desk  ·  30m Ledger  ·  ${nowWib}`,
      icon_url: binanceLogo,
    },
    timestamp: new Date().toISOString(),
  };

  const dualWalletOk = await sendDiscordChannelEmbed(
    'pnl',
    dualWalletReport,
    'Pierre  |  PnL Ledger'
  );
  console.log(`      -> #pnl (Dual-Wallet Report): ${dualWalletOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}\n`);

  // ------------------------------------------------------------------
  // 4. Channel: #preview-token
  // ------------------------------------------------------------------
  console.log('[4/5] Testing #preview-token: Portfolio Advisory Digest...');
  const previewReport = {
    author: {
      name: 'RŮŽE HOUSE  ·  PORTFOLIO ADVISORY',
      icon_url: binanceLogo,
    },
    title: '🔭 Position Risk & Orderbook Digest',
    thumbnail: {
      url: binanceLogo,
    },
    description: '> 🔭 Live orderbook depth, liquidity flow, and launchpad stage telemetry for **2** open position(s).',
    color: 0xd4af37,
    fields: [
      {
        name: '💼 ACTIVE POSITIONS',
        value: '`2 Open`',
        inline: true,
      },
      {
        name: '💳 WALLET SPLIT',
        value: '`0 EOA  ·  2 BAW`',
        inline: true,
      },
      {
        name: '⏱️ ENGINE CADENCE',
        value: '`20s HWM  ·  15m Digest`',
        inline: true,
      },
      {
        name: '🟢 #1  ·  NiulaiAgent.ai  [BSC]  —  HOLD (PRE-LAUNCH MINTING)',
        value: [
          '```yaml',
          'Wallet         :  Wallet II (Agentic .ai)',
          'Cost Basis     :  0.002 BNB  |  Stage: Pre-Launch Minting',
          'Pool Progress  :  Paid 1,024/10,000  |  Free 500/500',
          'Contract       :  0x15e47c22df42D94Fa2f0aD078Fec5Bea6453d5cF',
          '```',
          '> 🔗 [BscScan ↗](https://bscscan.com/address/0x15e47c22df42D94Fa2f0aD078Fec5Bea6453d5cF)  •  [DexScreener ↗](https://dexscreener.com/bsc/0x15e47c22df42D94Fa2f0aD078Fec5Bea6453d5cF)',
        ].join('\n'),
        inline: false,
      },
      {
        name: '🟡 #2  ·  BNBbaby  [BSC]  —  WATCH (POOL LAUNCH PENDING)',
        value: [
          '```yaml',
          'Wallet         :  Wallet II (Agentic .ai)',
          'Cost Basis     :  0.000 BNB  |  Holding: 10,000,000 BNBbaby',
          'Pair Status    :  Pair Created (USDT/BNBbaby)  |  poolOpen: false',
          'Contract       :  0xD0079025a9Bb66a7a1de991De2E4326FABA35729',
          '```',
          '> 🔗 [BscScan ↗](https://bscscan.com/address/0xD0079025a9Bb66a7a1de991De2E4326FABA35729)',
        ].join('\n'),
        inline: false,
      },
    ],
    footer: {
      text: `Pierre Execution Desk  ·  15m Advisory Digest  ·  ${nowWib}`,
      icon_url: binanceLogo,
    },
    timestamp: new Date().toISOString(),
  };

  const previewOk = await sendDiscordChannelEmbed(
    'preview-token',
    previewReport,
    'Pierre  |  Advisory'
  );
  console.log(`      -> #preview-token result: ${previewOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}\n`);

  // ------------------------------------------------------------------
  // 5. Channel: #pierre
  // ------------------------------------------------------------------
  console.log('[5/5] Testing #pierre: Daily Execution Recap...');
  const pierreReport = {
    author: {
      name: 'RŮŽE HOUSE  ·  DAILY SETTLEMENT',
      icon_url: binanceLogo,
    },
    title: '📜 24-Hour Execution Recap',
    thumbnail: {
      url: binanceLogo,
    },
    description: '> Daily execution and realized settlement summary across hybrid execution wallets.',
    color: 0xd4af37,
    fields: [
      {
        name: '⚡ 24H EXECUTIONS',
        value: '`2 Trades`',
        inline: true,
      },
      {
        name: '🔄 FLOW RATIO',
        value: '`2 Buy  ·  0 Sell`',
        inline: true,
      },
      {
        name: '💼 OPEN POSITIONS',
        value: '`2 Active`',
        inline: true,
      },
      {
        name: '💳 DUAL-WALLET 24H PERFORMANCE',
        value: [
          '```yaml',
          'Wallet I  (Viem EOA)     :  PnL 0.0000 ETH  |  W/L 0/0',
          'Wallet II (Agentic .ai)  :  PnL 0.0000 BNB  |  W/L 0/0',
          '```',
        ].join('\n'),
        inline: false,
      },
      {
        name: '📋 RECENT EXECUTIONS',
        value: [
          '```yaml',
          '13:06  MINT  NiulaiAgent.ai  0.002 BNB  [BSC]',
          '08:42  CLAIM BNBbaby (Free)   0.000 BNB  [BSC]',
          '```',
        ].join('\n'),
        inline: false,
      },
    ],
    footer: {
      text: `Pierre Execution Desk  ·  Daily Report  ·  ${nowWib}`,
      icon_url: binanceLogo,
    },
    timestamp: new Date().toISOString(),
  };

  const pierreOk = await sendDiscordChannelEmbed(
    'pierre',
    pierreReport,
    'Pierre  |  Settlement'
  );
  console.log(`      -> #pierre result: ${pierreOk ? 'SUCCESS (HTTP 204/200)' : 'FAILED'}\n`);

  console.log('====================================================');
  console.log('            ALL 5 CHANNEL TESTS COMPLETED           ');
  console.log('====================================================');
}

runWebhookTest().catch((err) => {
  console.error('Test execution error:', err);
  process.exit(1);
});
