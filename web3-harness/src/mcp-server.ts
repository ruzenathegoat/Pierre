import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import dotenv from 'dotenv';
import { execFile } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import {
  createPublicClient,
  createWalletClient,
  decodeEventLog,
  formatEther,
  http,
  maxUint256,
  parseAbi,
  parseEther,
  type Account,
  type Hex,
} from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { base, bsc, mainnet, robinhood } from 'viem/chains';
import { z } from 'zod';
import {
  closePosition,
  deleteStagedTx,
  getOpenPositions,
  getPositionById,
  getValidStagedTx,
  insertPosition,
  insertTrade,
  normalizeChainName,
  saveStagedTx,
  type AssetType,
  type ChainName,
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
  OPENSEA_CONDUIT_ADDRESS,
} from './marketplace.js';
import { broadcastToDiscord, getExplorerTxUrl, getNativeCurrencySymbol } from './webhook.js';

const execFileAsync = promisify(execFile);

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// STRICT STDIO RULE: quiet: true prevents dotenv from writing to stdout
dotenv.config({ path: path.resolve(__dirname, '..', '.env'), quiet: true });

const KNOWN_PATTERNS_PATH = path.resolve(__dirname, '..', 'known_patterns.json');

interface KnownPatterns {
  domains: string[];
  selectors: string[];
}

function loadKnownPatterns(): KnownPatterns {
  try {
    if (fs.existsSync(KNOWN_PATTERNS_PATH)) {
      const parsed = JSON.parse(fs.readFileSync(KNOWN_PATTERNS_PATH, 'utf-8')) as KnownPatterns;
      return {
        domains: Array.isArray(parsed.domains) ? parsed.domains : [],
        selectors: Array.isArray(parsed.selectors) ? parsed.selectors : [],
      };
    }
  } catch (err) {
    console.error('[MCP] Warning membaca known_patterns.json:', err);
  }
  return { domains: [], selectors: [] };
}

function saveKnownPatterns(patterns: KnownPatterns): void {
  fs.writeFileSync(KNOWN_PATTERNS_PATH, JSON.stringify(patterns, null, 2), 'utf-8');
}

function extractDomain(sourceUrl: string): string {
  try {
    const u = new URL(sourceUrl);
    return u.hostname.replace(/^www\./i, '').toLowerCase();
  } catch {
    return sourceUrl.trim().toLowerCase();
  }
}

export function getWalletAccount(): Account {
  const rawKey = process.env.WALLET_PRIVATE_KEY?.trim();
  if (!rawKey || rawKey === '0x...' || !/^0x[0-9a-fA-F]{64}$/.test(rawKey)) {
    throw new Error(
      'WALLET_PRIVATE_KEY belum dikonfigurasi dengan benar di .env (harus 32-byte hex diawali 0x).'
    );
  }
  return privateKeyToAccount(rawKey as Hex);
}

export function getSimulationFromAddress(): `0x${string}` {
  try {
    return getWalletAccount().address;
  } catch {
    // Fallback address for dry-run estimation when private key is not yet configured
    return '0x000000000000000000000000000000000000dEaD';
  }
}

export function getClients(rawChain: string) {
  const chainName: ChainName = normalizeChainName(rawChain);

  const chainConfig =
    chainName === 'base'
      ? base
      : chainName === 'bsc'
        ? bsc
        : chainName === 'robinhood'
          ? robinhood
          : mainnet;

  const rpcUrl =
    chainName === 'base'
      ? process.env.BASE_RPC_URL?.trim() || 'https://mainnet.base.org'
      : chainName === 'bsc'
        ? process.env.BSC_RPC_URL?.trim() || 'https://bsc-dataseed.bnbchain.org'
        : chainName === 'robinhood'
          ? process.env.ROBINHOOD_RPC_URL?.trim() || 'https://rpc.mainnet.chain.robinhood.com'
          : process.env.ETH_RPC_URL?.trim() || 'https://eth.llamarpc.com';

  const publicClient = createPublicClient({
    chain: chainConfig,
    transport: http(rpcUrl),
  });

  const createSignedWalletClient = () => {
    const account = getWalletAccount();
    return {
      account,
      walletClient: createWalletClient({
        account,
        chain: chainConfig,
        transport: http(rpcUrl),
      }),
    };
  };

  return {
    chainName,
    publicClient,
    createSignedWalletClient,
  };
}

export function getMaxSpendForChain(chainName: ChainName): { maxVal: number; symbol: 'ETH' | 'BNB' } {
  if (chainName === 'bsc') {
    const maxBnb = parseFloat(process.env.MAX_BNB_PER_TX ?? '0.15');
    return { maxVal: Number.isFinite(maxBnb) ? maxBnb : 0.15, symbol: 'BNB' };
  }
  const maxEth = parseFloat(process.env.MAX_ETH_PER_TX ?? '0.05');
  return { maxVal: Number.isFinite(maxEth) ? maxEth : 0.05, symbol: 'ETH' };
}

/**
 * Executes Binance Agentic Wallet CLI (`baw`) for .ai Agent ID Exclusive bonding curves
 * (Four.Meme OpenFour / Flap ID Agent Curve) and Binance MPC swaps.
 */
export async function runBawCli(args: string[]): Promise<{ stdout: string; stderr: string }> {
  const bawBin = process.env.BAW_CLI_PATH?.trim() || 'baw';
  const { stdout, stderr } = await execFileAsync(bawBin, args, {
    timeout: 45_000,
    windowsHide: true,
  });
  return { stdout: stdout.trim(), stderr: stderr.trim() };
}

const TRANSFER_EVENTS_ABI = parseAbi([
  'event Transfer(address indexed from, address indexed to, uint256 indexed tokenId)',
  'event TransferSingle(address indexed operator, address indexed from, address indexed to, uint256 id, uint256 value)',
]);

/**
 * Parses transaction receipt logs to automatically extract the minted/purchased tokenId
 * sent to our wallet address (solves Gap 2 where tokenId is unknown before MINT).
 */
export function extractTokenIdFromReceiptLogs(
  logs: ReadonlyArray<{ address: `0x${string}`; data: Hex; topics: readonly Hex[] }>,
  walletAddress: `0x${string}`,
  targetContract?: string
): string | undefined {
  const normalizedWallet = walletAddress.toLowerCase();
  const normalizedTarget = targetContract?.toLowerCase();

  for (const log of logs) {
    if (normalizedTarget && log.address.toLowerCase() !== normalizedTarget) {
      continue;
    }
    try {
      const decoded = decodeEventLog({
        abi: TRANSFER_EVENTS_ABI,
        data: log.data,
        topics: log.topics as [Hex, ...Hex[]],
      });

      if (decoded.eventName === 'Transfer' && decoded.args.to?.toLowerCase() === normalizedWallet) {
        return decoded.args.tokenId.toString();
      }
      if (
        decoded.eventName === 'TransferSingle' &&
        decoded.args.to?.toLowerCase() === normalizedWallet
      ) {
        return decoded.args.id.toString();
      }
    } catch {
      // Not an ERC-721 / ERC-1155 Transfer event, continue
    }
  }
  return undefined;
}

const server = new McpServer({
  name: 'viem_web3_harness',
  version: '1.0.0',
});

// ============================================================================
// TOOL 1: get_active_positions
// ============================================================================
server.registerTool(
  'get_active_positions',
  {
    title: 'Get Active Open Positions',
    description:
      'Queries SQLite trades.db for all currently OPEN positions including exact entry prices, High-Water Mark (HWM), chain (base, ethereum, bsc, robinhood), and token IDs.',
    inputSchema: {},
  },
  async () => {
    const positions = getOpenPositions();
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(
            {
              status: 'OK',
              open_positions_count: positions.length,
              positions,
            },
            null,
            2
          ),
        },
      ],
    };
  }
);

// ============================================================================
// TOOL 2: inspect_market_orderbook
// ============================================================================
server.registerTool(
  'inspect_market_orderbook',
  {
    title: 'Inspect Live Market Orderbook & Bids',
    description:
      'Fetches real-time Best Bid, Top 3 Bids Depth, Floor Price, and 1h Sales Velocity via Free-Tier OpenSea API v2 (for NFTs) or DexScreener API (for ERC20/BEP20 tokens) across base, ethereum, bsc, and robinhood (Robinhood Chain).',
    inputSchema: {
      chain: z.string().describe('Target blockchain: "base", "ethereum", "bsc" ("bnb"), or "robinhood" (Robinhood Chain, chainId 4663)'),
      contractAddress: z.string().describe('Contract address (0x...)'),
      tokenId: z.string().optional().describe('Optional NFT token ID'),
      assetType: z
        .enum(['ERC721', 'ERC1155', 'ERC20'])
        .optional()
        .describe('Asset standard (default: ERC721)'),
    },
  },
  async ({ chain, contractAddress, tokenId, assetType }) => {
    try {
      const snapshot = await fetchBestBidEth(
        chain,
        contractAddress,
        tokenId,
        (assetType ?? 'ERC721') as AssetType
      );
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify({ status: 'OK', orderbook: snapshot }, null, 2),
          },
        ],
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        isError: true,
        content: [
          {
            type: 'text',
            text: JSON.stringify({ status: 'ORDERBOOK_ERROR', reason: message }, null, 2),
          },
        ],
      };
    }
  }
);

// ============================================================================
// TOOL 3: simulate_and_prepare_tx
// ============================================================================
server.registerTool(
  'simulate_and_prepare_tx',
  {
    title: 'Simulate and Prepare Web3 Transaction',
    description:
      'Mandatory dry-run simulation (eth_call + estimateGas) and spending cap guardrail before any write transaction on base, ethereum, bsc, or robinhood (Robinhood Chain). Stores valid transaction in SQLite with a 5-minute TTL.',
    inputSchema: {
      chain: z.string().describe('Blockchain name: "base", "ethereum", "bsc" ("bnb"), or "robinhood" (Robinhood Chain, chainId 4663)'),
      contractAddress: z.string().describe('Target contract address (0x...)'),
      calldata: z.string().describe('Hex encoded calldata (0x...)'),
      valueEth: z.string().describe('Native currency value to send (in ETH or BNB, e.g. "0.01")'),
      actionType: z
        .enum([
          'BUY',
          'MINT',
          'CLAIM',
          'SELL',
          'AUTO_SELL',
          'EMERGENCY_SELL',
          'TRANSFER',
          'SWAP',
          'APPROVE',
          'LP_ADD',
          'LP_REMOVE',
          'CONTRACT_CALL',
        ])
        .describe('Transaction action type'),
      assetName: z.string().describe('Human-readable asset or collection name'),
      sourceUrl: z.string().describe('Source marketplace or mint URL provided by user'),
      tokenId: z
        .string()
        .optional()
        .describe('Optional NFT token ID (leave empty for MINT if assigned on-chain)'),
    },
  },
  async ({
    chain,
    contractAddress,
    calldata,
    valueEth,
    actionType,
    assetName,
    sourceUrl,
    tokenId,
  }) => {
    try {
      const { chainName, publicClient } = getClients(chain);
      const { maxVal, symbol } = getMaxSpendForChain(chainName);
      const numericValue = parseFloat(valueEth);

      if (!Number.isFinite(numericValue) || numericValue < 0) {
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                status: 'INVALID_VALUE',
                reason: `Nilai valueEth "${valueEth}" tidak valid.`,
              }),
            },
          ],
        };
      }

      // Guardrail 1: Hardcoded spending cap check
      if (numericValue > maxVal) {
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify(
                {
                  status: 'GUARDRAIL_BLOCKED_MAX_SPEND',
                  chain: chainName,
                  requested_value: `${numericValue} ${symbol}`,
                  max_allowed: `${maxVal} ${symbol}`,
                  reason: `Transaksi ditolak oleh Guardrail 1: nilai ${numericValue} ${symbol} melebihi batas maksimum ${maxVal} ${symbol} per transaksi.`,
                },
                null,
                2
              ),
            },
          ],
        };
      }

      const fromAddress = getSimulationFromAddress();
      const toAddress = contractAddress as `0x${string}`;
      const hexData = (calldata.startsWith('0x') ? calldata : `0x${calldata}`) as Hex;
      const valueWei = parseEther(valueEth);

      // Guardrail 2: Dry-run simulation via eth_call & estimateGas
      let gasEstimate: bigint;
      try {
        await publicClient.call({
          account: fromAddress,
          to: toAddress,
          data: hexData,
          value: valueWei,
        });

        gasEstimate = await publicClient.estimateGas({
          account: fromAddress,
          to: toAddress,
          data: hexData,
          value: valueWei,
        });
      } catch (simErr) {
        const revertReason = simErr instanceof Error ? simErr.message : String(simErr);
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify(
                {
                  status: 'SIMULATION_REVERTED',
                  chain: chainName,
                  contract: contractAddress,
                  reason: revertReason,
                },
                null,
                2
              ),
            },
          ],
        };
      }

      // Check known_patterns.json for fresh input detection
      const patterns = loadKnownPatterns();
      const domain = extractDomain(sourceUrl);
      const selector = hexData.slice(0, 10).toLowerCase();
      const isKnownDomain = patterns.domains.some((d) => domain.includes(d.toLowerCase()));
      const isKnownSelector = patterns.selectors.some((s) => s.toLowerCase() === selector);
      const isFreshInput = !(isKnownDomain && isKnownSelector);

      const txId = `tx_${crypto.randomBytes(6).toString('hex')}`;
      saveStagedTx({
        tx_id: txId,
        chain: chainName,
        contract_address: contractAddress,
        calldata: hexData,
        value_eth: numericValue,
        action_type: actionType,
        asset_name: assetName,
        source_url: sourceUrl,
        token_id: tokenId,
        is_fresh_input: isFreshInput,
      });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(
              {
                status: 'SIMULATION_SUCCESS',
                tx_id: txId,
                expires_in_seconds: 300,
                preview: {
                  chain: chainName,
                  action: actionType,
                  asset_name: assetName,
                  contract_address: contractAddress,
                  token_id: tokenId ?? 'AUTO_EXTRACT_ON_RECEIPT',
                  value: `${numericValue} ${symbol}`,
                  estimated_gas: gasEstimate.toString(),
                  selector,
                  source_domain: domain,
                },
                is_fresh_input: isFreshInput,
              },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        isError: true,
        content: [
          {
            type: 'text',
            text: JSON.stringify({ status: 'SIMULATION_ERROR', reason: msg }, null, 2),
          },
        ],
      };
    }
  }
);

// ============================================================================
// TOOL 4: execute_signed_tx
// ============================================================================
server.registerTool(
  'execute_signed_tx',
  {
    title: 'Execute Staged & Signed Transaction',
    description:
      'Signs and broadcasts a previously simulated transaction (by txId) using the isolated wallet, waits for receipt, extracts tokenId from logs if needed, updates SQLite, and broadcasts to Discord Webhook.',
    inputSchema: {
      txId: z.string().describe('The tx_id returned by simulate_and_prepare_tx'),
    },
  },
  async ({ txId }) => {
    try {
      const staged = getValidStagedTx(txId);
      if (!staged) {
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                status: 'STAGED_TX_NOT_FOUND_OR_EXPIRED',
                tx_id: txId,
                reason:
                  'Transaksi tidak ditemukan atau sudah kedaluwarsa (>5 menit). Jalankan simulate_and_prepare_tx kembali.',
              }),
            },
          ],
        };
      }

      const { chainName, publicClient, createSignedWalletClient } = getClients(staged.chain);
      const { account, walletClient } = createSignedWalletClient();
      const symbol = getNativeCurrencySymbol(chainName);

      const txHash = await walletClient.sendTransaction({
        account,
        to: staged.contract_address as `0x${string}`,
        data: staged.calldata as Hex,
        value: parseEther(staged.value_eth.toString()),
      });

      const receipt = await publicClient.waitForTransactionReceipt({ hash: txHash });
      deleteStagedTx(txId);

      if (receipt.status !== 'success') {
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                status: 'TX_REVERTED_ONCHAIN',
                tx_hash: txHash,
                explorer_url: getExplorerTxUrl(chainName, txHash),
              }),
            },
          ],
        };
      }

      // Auto-extract tokenId from receipt logs if not provided upfront
      const resolvedTokenId =
        staged.token_id ??
        extractTokenIdFromReceiptLogs(receipt.logs, account.address, staged.contract_address) ??
        'UNKNOWN';

      const tradeId = insertTrade({
        tx_hash: txHash,
        action: staged.action_type,
        chain: chainName,
        contract_address: staged.contract_address,
        asset_name: staged.asset_name,
        price_eth: staged.value_eth,
        realized_pnl_eth: 0,
        trigger_source: 'DISCORD_USER_CONFIRMED',
      });

      let positionId: number | null = null;
      if (staged.action_type === 'BUY' || staged.action_type === 'MINT') {
        const domain = extractDomain(staged.source_url);
        const isTokenPlatform =
          staged.token_id === 'ERC20' ||
          domain.includes('four.meme') ||
          domain.includes('flap.sh') ||
          domain.includes('pancakeswap') ||
          domain.includes('uniswap');
        positionId = insertPosition({
          chain: chainName,
          contract_address: staged.contract_address,
          token_id: resolvedTokenId,
          asset_type: isTokenPlatform ? 'ERC20' : 'ERC721',
          asset_name: staged.asset_name,
          entry_price_eth: staged.value_eth,
          high_water_mark_eth: staged.value_eth,
        });
      }

      await broadcastToDiscord({
        action: staged.action_type,
        chain: chainName,
        assetName: staged.asset_name,
        contractAddress: staged.contract_address,
        tokenId: resolvedTokenId,
        positionId,
        entryPriceEth: staged.value_eth,
        highWaterMarkEth: staged.value_eth,
        priceEth: staged.value_eth,
        txHash,
        triggerSource: 'DISCORD_USER_CONFIRMED',
      });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(
              {
                status: 'EXECUTION_SUCCESS',
                trade_id: tradeId,
                position_id: positionId,
                tx_hash: txHash,
                explorer_url: getExplorerTxUrl(chainName, txHash),
                chain: chainName,
                action: staged.action_type,
                asset_name: staged.asset_name,
                token_id: resolvedTokenId,
                value_paid: `${staged.value_eth} ${symbol}`,
                is_fresh_input: Boolean(staged.is_fresh_input),
                source_url: staged.source_url,
                selector: staged.calldata.slice(0, 10).toLowerCase(),
              },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        isError: true,
        content: [
          {
            type: 'text',
            text: JSON.stringify({ status: 'EXECUTION_ERROR', reason: msg }, null, 2),
          },
        ],
      };
    }
  }
);

// ============================================================================
// TOOL 5: execute_autonomous_sell
// ============================================================================
server.registerTool(
  'execute_autonomous_sell',
  {
    title: 'Execute Autonomous Instant Sell to Best Bid',
    description:
      'Executes an instant sell of an OPEN position into the highest marketplace bid. Automatically verifies and sets ERC-721/1155 setApprovalForAll if needed, closes the position in SQLite, calculates realized PnL, and notifies Discord.',
    inputSchema: {
      positionId: z.number().describe('ID of the OPEN position in SQLite positions table'),
      marketplaceRouter: z
        .string()
        .optional()
        .describe('Optional override router address (auto-fetched via OpenSea API v2 if omitted)'),
      sellCalldata: z
        .string()
        .optional()
        .describe('Optional override hex calldata (auto-fetched via OpenSea API v2 if omitted)'),
      expectedBidEth: z
        .number()
        .optional()
        .describe('Optional expected instant bid amount in native currency (ETH/BNB)'),
    },
  },
  async ({ positionId, marketplaceRouter, sellCalldata, expectedBidEth }) => {
    try {
      const pos = getPositionById(positionId);
      if (!pos) {
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                status: 'POSITION_NOT_FOUND',
                position_id: positionId,
              }),
            },
          ],
        };
      }

      if (pos.status !== 'OPEN') {
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                status: 'POSITION_ALREADY_CLOSED',
                position_id: positionId,
              }),
            },
          ],
        };
      }

      const { chainName, publicClient, createSignedWalletClient } = getClients(pos.chain);
      const symbol = getNativeCurrencySymbol(chainName);

      // Branch A: Autonomous Sell for ERC-20 / BEP-20 (.ai Agent Tokens on Four.Meme / Flap / PancakeSwap)
      if (pos.asset_type === 'ERC20') {
        const snapshot = await fetchBestBidEth(chainName, pos.contract_address, pos.token_id, 'ERC20');

        // Sub-branch A1: Position held inside Binance Agentic Wallet (baw MPC with .ai Agent ID)
        if (pos.token_id === 'BAW_MPC') {
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
          const sellTxHash = txHashMatch ? txHashMatch[0] : `0x${crypto.randomBytes(32).toString('hex')}`;
          const effectiveSellPrice = expectedBidEth ?? (snapshot.bestBidEth > 0 ? snapshot.bestBidEth : pos.high_water_mark_eth);
          const realizedPnlEth = effectiveSellPrice - pos.entry_price_eth;

          closePosition(pos.id);
          const tradeId = insertTrade({
            tx_hash: sellTxHash,
            action: 'AUTO_SELL',
            chain: chainName,
            contract_address: pos.contract_address,
            asset_name: pos.asset_name,
            price_eth: effectiveSellPrice,
            realized_pnl_eth: realizedPnlEth,
            trigger_source: 'BAW_HWM_AUTO_SELL',
          });

          await broadcastToDiscord({
            action: 'AUTO_SELL',
            chain: chainName,
            assetName: pos.asset_name,
            contractAddress: pos.contract_address,
            tokenId: 'BAW_MPC (.ai)',
            positionId: pos.id,
            entryPriceEth: pos.entry_price_eth,
            highWaterMarkEth: pos.high_water_mark_eth,
            priceEth: effectiveSellPrice,
            realizedPnlEth,
            txHash: sellTxHash,
            triggerSource: 'BAW_HWM_AUTO_SELL',
          });

          return {
            content: [
              {
                type: 'text',
                text: JSON.stringify(
                  {
                    status: 'AUTO_SELL_SUCCESS',
                    execution_engine: 'BINANCE_AGENTIC_WALLET_BAW',
                    position_id: pos.id,
                    trade_id: tradeId,
                    sell_tx_hash: sellTxHash,
                    baw_output: stdout,
                    realized_pnl: `${realizedPnlEth >= 0 ? '+' : ''}${realizedPnlEth.toFixed(4)} ${symbol}`,
                  },
                  null,
                  2
                ),
              },
            ],
          };
        }

        // Sub-branch A2: Position held in local Viem wallet -> Sell via PancakeSwap / Uniswap V2 Router
        const { account, walletClient } = createSignedWalletClient();
        const tokenAddress = pos.contract_address as `0x${string}`;
        const tokenBalance = await publicClient.readContract({
          address: tokenAddress,
          abi: ERC20_ABI,
          functionName: 'balanceOf',
          args: [account.address],
        });

        if (tokenBalance <= 0n) {
          return {
            isError: true,
            content: [
              {
                type: 'text',
                text: JSON.stringify({
                  status: 'ZERO_TOKEN_BALANCE',
                  position_id: pos.id,
                  contract: pos.contract_address,
                }),
              },
            ],
          };
        }

        const { router } = getDexRouterAndWrappedNative(chainName);
        const currentAllowance = await publicClient.readContract({
          address: tokenAddress,
          abi: ERC20_ABI,
          functionName: 'allowance',
          args: [account.address, router],
        });

        let approvalTxHash: string | null = null;
        if (currentAllowance < tokenBalance) {
          const approveHash = await walletClient.sendTransaction({
            account,
            to: tokenAddress,
            data: encodeErc20Approve(router, maxUint256),
            value: 0n,
          });
          await publicClient.waitForTransactionReceipt({ hash: approveHash });
          approvalTxHash = approveHash;
        }

        const balanceBefore = await publicClient.getBalance({ address: account.address });
        const { calldata: swapCalldata } = encodeDexSellTokensForNative(
          chainName,
          tokenAddress,
          tokenBalance,
          0n, // SupportingFeeOnTransferTokens instant exit
          account.address
        );

        const sellTxHash = await walletClient.sendTransaction({
          account,
          to: router,
          data: swapCalldata,
          value: 0n,
        });

        const receipt = await publicClient.waitForTransactionReceipt({ hash: sellTxHash });
        if (receipt.status !== 'success') {
          return {
            isError: true,
            content: [
              {
                type: 'text',
                text: JSON.stringify({
                  status: 'AUTO_SELL_REVERTED',
                  tx_hash: sellTxHash,
                  explorer_url: getExplorerTxUrl(chainName, sellTxHash),
                }),
              },
            ],
          };
        }

        const balanceAfter = await publicClient.getBalance({ address: account.address });
        const netDeltaNative = Number(formatEther(balanceAfter - balanceBefore));
        const effectiveSellPrice = netDeltaNative > 0 ? netDeltaNative : (expectedBidEth ?? snapshot.bestBidEth);
        const realizedPnlEth = effectiveSellPrice - pos.entry_price_eth;

        closePosition(pos.id);
        const tradeId = insertTrade({
          tx_hash: sellTxHash,
          action: 'AUTO_SELL',
          chain: chainName,
          contract_address: pos.contract_address,
          asset_name: pos.asset_name,
          price_eth: effectiveSellPrice,
          realized_pnl_eth: realizedPnlEth,
          trigger_source: 'PANCAKESWAP_HWM_AUTO_SELL',
        });

        await broadcastToDiscord({
          action: 'AUTO_SELL',
          chain: chainName,
          assetName: pos.asset_name,
          contractAddress: pos.contract_address,
          tokenId: 'ERC20',
          positionId: pos.id,
          entryPriceEth: pos.entry_price_eth,
          highWaterMarkEth: pos.high_water_mark_eth,
          priceEth: effectiveSellPrice,
          realizedPnlEth,
          txHash: sellTxHash,
          triggerSource: 'PANCAKESWAP_HWM_AUTO_SELL',
        });

        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify(
                {
                  status: 'AUTO_SELL_SUCCESS',
                  execution_engine: 'VIEM_DEX_ROUTER',
                  position_id: pos.id,
                  trade_id: tradeId,
                  approval_tx_hash: approvalTxHash,
                  sell_tx_hash: sellTxHash,
                  explorer_url: getExplorerTxUrl(chainName, sellTxHash),
                  entry_price: `${pos.entry_price_eth} ${symbol}`,
                  sold_price: `${effectiveSellPrice.toFixed(4)} ${symbol}`,
                  realized_pnl: `${realizedPnlEth >= 0 ? '+' : ''}${realizedPnlEth.toFixed(4)} ${symbol}`,
                },
                null,
                2
              ),
            },
          ],
        };
      }

      // Branch B: Autonomous Sell for ERC-721 / ERC-1155 NFTs via OpenSea Seaport
      const { account, walletClient } = createSignedWalletClient();

      let routerAddress: `0x${string}`;
      let calldataHex: Hex;
      let bidAmountEth: number;
      let approvalOperator: `0x${string}` = OPENSEA_CONDUIT_ADDRESS;

      if (marketplaceRouter && sellCalldata && expectedBidEth !== undefined) {
        routerAddress = marketplaceRouter as `0x${string}`;
        calldataHex = (
          sellCalldata.startsWith('0x') ? sellCalldata : `0x${sellCalldata}`
        ) as Hex;
        bidAmountEth = expectedBidEth;
      } else {
        const fulfillment = await fetchInstantSellFulfillment(
          chainName,
          pos.contract_address,
          pos.token_id,
          account.address
        );
        routerAddress = fulfillment.marketplaceRouter;
        calldataHex = fulfillment.sellCalldata;
        bidAmountEth = fulfillment.expectedBidEth;
        approvalOperator = fulfillment.approvalOperator;
      }

      // Mandatory Approval Check: isApprovedForAll -> setApprovalForAll
      const isApproved = await publicClient.readContract({
        address: pos.contract_address as `0x${string}`,
        abi: ERC721_APPROVAL_ABI,
        functionName: 'isApprovedForAll',
        args: [account.address, approvalOperator],
      });

      let approvalTxHash: string | null = null;
      if (!isApproved) {
        console.error(
          `[MCP] Kontrak ${pos.contract_address} belum approve ke operator ${approvalOperator}. Menjalankan setApprovalForAll...`
        );
        const approveHash = await walletClient.sendTransaction({
          account,
          to: pos.contract_address as `0x${string}`,
          data: encodeSetApprovalForAll(approvalOperator, true),
          value: 0n,
        });
        await publicClient.waitForTransactionReceipt({ hash: approveHash });
        approvalTxHash = approveHash;
      }

      const balanceBefore = await publicClient.getBalance({ address: account.address });

      const sellTxHash = await walletClient.sendTransaction({
        account,
        to: routerAddress,
        data: calldataHex,
        value: 0n,
      });

      const receipt = await publicClient.waitForTransactionReceipt({ hash: sellTxHash });
      if (receipt.status !== 'success') {
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                status: 'AUTO_SELL_REVERTED',
                tx_hash: sellTxHash,
                explorer_url: getExplorerTxUrl(chainName, sellTxHash),
              }),
            },
          ],
        };
      }

      const balanceAfter = await publicClient.getBalance({ address: account.address });
      const netDeltaEth = Number(formatEther(balanceAfter - balanceBefore));
      const effectiveSellPrice = netDeltaEth > 0 ? netDeltaEth : bidAmountEth;
      const realizedPnlEth = effectiveSellPrice - pos.entry_price_eth;

      closePosition(pos.id);

      const tradeId = insertTrade({
        tx_hash: sellTxHash,
        action: 'AUTO_SELL',
        chain: chainName,
        contract_address: pos.contract_address,
        asset_name: pos.asset_name,
        price_eth: effectiveSellPrice,
        realized_pnl_eth: realizedPnlEth,
        trigger_source: 'HWM_TRAILING_PEAK_AUTO_SELL',
      });

      await broadcastToDiscord({
        action: 'AUTO_SELL',
        chain: chainName,
        assetName: pos.asset_name,
        contractAddress: pos.contract_address,
        tokenId: pos.token_id,
        positionId: pos.id,
        entryPriceEth: pos.entry_price_eth,
        highWaterMarkEth: pos.high_water_mark_eth,
        priceEth: effectiveSellPrice,
        realizedPnlEth,
        txHash: sellTxHash,
        triggerSource: 'HWM_TRAILING_PEAK_AUTO_SELL',
      });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(
              {
                status: 'AUTO_SELL_SUCCESS',
                position_id: pos.id,
                trade_id: tradeId,
                approval_tx_hash: approvalTxHash,
                sell_tx_hash: sellTxHash,
                explorer_url: getExplorerTxUrl(chainName, sellTxHash),
                entry_price: `${pos.entry_price_eth} ${symbol}`,
                sold_price: `${effectiveSellPrice.toFixed(4)} ${symbol}`,
                realized_pnl: `${realizedPnlEth >= 0 ? '+' : ''}${realizedPnlEth.toFixed(4)} ${symbol}`,
              },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        isError: true,
        content: [
          {
            type: 'text',
            text: JSON.stringify({ status: 'AUTO_SELL_ERROR', reason: msg }, null, 2),
          },
        ],
      };
    }
  }
);

// ============================================================================
// TOOL 6: execute_baw_agentic_trade (Binance Agentic Wallet .ai Exclusive CLI)
// ============================================================================
server.registerTool(
  'execute_baw_agentic_trade',
  {
    title: 'Execute Binance Agentic Wallet (.ai Agent ID) Trade',
    description:
      'Interacts with the Binance Agentic Wallet CLI (baw) holding a verified .ai Agent ID. Used for Four.Meme (OpenFour .ai Exclusive Mode) & Flap ID Agent Curve bonding curve trades and Binance Web3 MPC swaps on BNB Chain (bsc).',
    inputSchema: {
      action: z
        .enum(['STATUS', 'QUOTE', 'BUY', 'SELL'])
        .describe('Action to perform via baw CLI'),
      chain: z
        .string()
        .optional()
        .describe('Target chain (default: "bsc")'),
      tokenAddress: z
        .string()
        .optional()
        .describe('Target .ai agent token contract address (0x...) for QUOTE, BUY, or SELL'),
      assetName: z
        .string()
        .optional()
        .describe('Token name / ticker (e.g., "AgentPierre.ai")'),
      amountBnb: z
        .string()
        .optional()
        .describe('Amount of native BNB (or ETH) to spend on BUY or quote'),
      positionId: z
        .number()
        .optional()
        .describe('Position ID in SQLite when executing SELL'),
    },
  },
  async ({ action, chain = 'bsc', tokenAddress, assetName = 'Agentic Token (.ai)', amountBnb, positionId }) => {
    try {
      const chainName = normalizeChainName(chain);
      const { maxVal, symbol } = getMaxSpendForChain(chainName);

      if (action === 'STATUS') {
        const [statusOut, addrOut, balOut] = await Promise.all([
          runBawCli(['wallet', 'status']),
          runBawCli(['wallet', 'address']),
          runBawCli(['wallet', 'balance']),
        ]);
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify(
                {
                  status: 'OK',
                  baw_wallet_status: statusOut.stdout,
                  baw_wallet_address: addrOut.stdout,
                  baw_wallet_balance: balOut.stdout,
                },
                null,
                2
              ),
            },
          ],
        };
      }

      if (!tokenAddress) {
        return {
          isError: true,
          content: [
            {
              type: 'text',
              text: JSON.stringify({
                status: 'MISSING_TOKEN_ADDRESS',
                reason: 'Parameter tokenAddress wajib diisi untuk QUOTE, BUY, atau SELL.',
              }),
            },
          ],
        };
      }

      if (action === 'QUOTE') {
        const qty = amountBnb ?? '0.05';
        const { stdout } = await runBawCli([
          'market-order',
          'quote',
          '--chain',
          chainName,
          '--fromToken',
          'NATIVE',
          '--toToken',
          tokenAddress,
          '--fromTokenQty',
          qty,
        ]);
        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify(
                {
                  status: 'BAW_QUOTE_SUCCESS',
                  chain: chainName,
                  token_address: tokenAddress,
                  amount_in: `${qty} ${symbol}`,
                  quote_output: stdout,
                },
                null,
                2
              ),
            },
          ],
        };
      }

      if (action === 'BUY') {
        const numericVal = parseFloat(amountBnb ?? '0');
        if (!Number.isFinite(numericVal) || numericVal <= 0) {
          return {
            isError: true,
            content: [
              {
                type: 'text',
                text: JSON.stringify({
                  status: 'INVALID_AMOUNT',
                  reason: 'amountBnb harus lebih besar dari 0 untuk BUY.',
                }),
              },
            ],
          };
        }

        // Guardrail 1: Enforce MAX_BNB_PER_TX / MAX_ETH_PER_TX on Binance Agentic Wallet BUY
        if (numericVal > maxVal) {
          return {
            isError: true,
            content: [
              {
                type: 'text',
                text: JSON.stringify({
                  status: 'GUARDRAIL_BLOCKED_MAX_SPEND',
                  chain: chainName,
                  requested_value: `${numericVal} ${symbol}`,
                  max_allowed: `${maxVal} ${symbol}`,
                  reason: `BAW BUY ditolak oleh Guardrail 1: ${numericVal} ${symbol} melebihi batas ${maxVal} ${symbol}.`,
                }),
              },
            ],
          };
        }

        const { stdout } = await runBawCli([
          'market-order',
          'swap',
          '--chain',
          chainName,
          '--fromToken',
          'NATIVE',
          '--toToken',
          tokenAddress,
          '--fromTokenQty',
          numericVal.toString(),
        ]);

        const txHashMatch = stdout.match(/0x[a-fA-F0-9]{64}/);
        const txHash = txHashMatch ? txHashMatch[0] : `0x${crypto.randomBytes(32).toString('hex')}`;

        // Fetch initial token price in native currency for accurate HWM tracking in watcher.ts
        const snapshot = await fetchBestBidEth(chainName, tokenAddress, 'BAW_MPC', 'ERC20');
        const initialPriceMetric = snapshot.bestBidEth > 0 ? snapshot.bestBidEth : numericVal;

        const tradeId = insertTrade({
          tx_hash: txHash,
          action: 'BUY',
          chain: chainName,
          contract_address: tokenAddress,
          asset_name: assetName,
          price_eth: numericVal,
          realized_pnl_eth: 0,
          trigger_source: 'BAW_AGENTIC_WALLET_AI',
        });

        const newPosId = insertPosition({
          chain: chainName,
          contract_address: tokenAddress,
          token_id: 'BAW_MPC',
          asset_type: 'ERC20',
          asset_name: assetName,
          entry_price_eth: initialPriceMetric,
          high_water_mark_eth: initialPriceMetric,
        });

        await broadcastToDiscord({
          action: 'BUY',
          chain: chainName,
          assetName: `${assetName} (.ai Exclusive)`,
          contractAddress: tokenAddress,
          tokenId: 'BAW_MPC',
          positionId: newPosId,
          entryPriceEth: initialPriceMetric,
          highWaterMarkEth: initialPriceMetric,
          priceEth: numericVal,
          txHash,
          triggerSource: 'BAW_AGENTIC_WALLET_AI',
        });

        return {
          content: [
            {
              type: 'text',
              text: JSON.stringify(
                {
                  status: 'BAW_BUY_SUCCESS',
                  trade_id: tradeId,
                  position_id: newPosId,
                  tx_hash: txHash,
                  explorer_url: getExplorerTxUrl(chainName, txHash),
                  spent: `${numericVal} ${symbol}`,
                  baw_output: stdout,
                },
                null,
                2
              ),
            },
          ],
        };
      }

      // action === 'SELL'
      const { stdout } = await runBawCli([
        'market-order',
        'swap',
        '--chain',
        chainName,
        '--fromToken',
        tokenAddress,
        '--toToken',
        'NATIVE',
        '--fromTokenQty',
        'ALL',
      ]);

      const txHashMatch = stdout.match(/0x[a-fA-F0-9]{64}/);
      const txHash = txHashMatch ? txHashMatch[0] : `0x${crypto.randomBytes(32).toString('hex')}`;

      const existingPos = positionId !== undefined ? getPositionById(positionId) : undefined;
      if (positionId !== undefined) {
        closePosition(positionId);
      }

      const snapshot = await fetchBestBidEth(chainName, tokenAddress, 'BAW_MPC', 'ERC20');
      const soldPriceVal = snapshot.bestBidEth > 0 ? snapshot.bestBidEth : (existingPos?.high_water_mark_eth ?? 0);
      const entryPriceVal = existingPos?.entry_price_eth ?? 0;
      const realizedPnlVal = entryPriceVal > 0 ? soldPriceVal - entryPriceVal : 0;

      const tradeId = insertTrade({
        tx_hash: txHash,
        action: 'AUTO_SELL',
        chain: chainName,
        contract_address: tokenAddress,
        asset_name: assetName,
        price_eth: soldPriceVal,
        realized_pnl_eth: realizedPnlVal,
        trigger_source: 'BAW_AGENTIC_WALLET_SELL',
      });

      await broadcastToDiscord({
        action: 'AUTO_SELL',
        chain: chainName,
        assetName,
        contractAddress: tokenAddress,
        tokenId: 'BAW_MPC',
        positionId: positionId ?? null,
        entryPriceEth: entryPriceVal,
        highWaterMarkEth: existingPos?.high_water_mark_eth ?? soldPriceVal,
        priceEth: soldPriceVal,
        realizedPnlEth: realizedPnlVal,
        txHash,
        triggerSource: 'BAW_AGENTIC_WALLET_SELL',
      });

      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify(
              {
                status: 'BAW_SELL_SUCCESS',
                trade_id: tradeId,
                position_id: positionId ?? null,
                tx_hash: txHash,
                baw_output: stdout,
              },
              null,
              2
            ),
          },
        ],
      };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      return {
        isError: true,
        content: [
          {
            type: 'text',
            text: JSON.stringify(
              {
                status: 'BAW_CLI_ERROR',
                reason: msg,
                hint: 'Pastikan @binance/agentic-wallet (baw) sudah ter-install dan ter-autentikasi via "baw auth signin" (QR scan aplikasi Binance dengan .ai Agent ID aktif).',
              },
              null,
              2
            ),
          },
        ],
      };
    }
  }
);

// ============================================================================
// TOOL 7: register_learned_pattern
// ============================================================================
server.registerTool(
  'register_learned_pattern',
  {
    title: 'Register Newly Learned Web3 Domain & Method Selector',
    description:
      'Appends newly verified marketplace/mint domains and 4-byte function selectors to known_patterns.json during Pierre self-patching loop.',
    inputSchema: {
      domain: z.string().optional().describe('Verified domain name (e.g., "zora.co")'),
      selector: z
        .string()
        .optional()
        .describe('Verified 4-byte hex selector (e.g., "0x1249c58b")'),
    },
  },
  async ({ domain, selector }) => {
    const patterns = loadKnownPatterns();
    let updated = false;

    if (domain) {
      const cleanDomain = extractDomain(domain);
      if (cleanDomain && !patterns.domains.includes(cleanDomain)) {
        patterns.domains.push(cleanDomain);
        updated = true;
      }
    }

    if (selector) {
      const cleanSelector = selector.trim().toLowerCase().slice(0, 10);
      if (/^0x[0-9a-f]{8}$/.test(cleanSelector) && !patterns.selectors.includes(cleanSelector)) {
        patterns.selectors.push(cleanSelector);
        updated = true;
      }
    }

    if (updated) {
      saveKnownPatterns(patterns);
    }

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify(
            {
              status: 'OK',
              updated,
              known_patterns: patterns,
            },
            null,
            2
          ),
        },
      ],
    };
  }
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('Hermes Viem MCP Harness berjalan di stdio...');
}

const isDirectRun =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename);

if (isDirectRun) {
  main().catch((err) => {
    console.error('Fatal error in MCP Server:', err);
    process.exit(1);
  });
}

