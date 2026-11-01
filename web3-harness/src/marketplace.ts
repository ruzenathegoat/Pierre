import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { encodeFunctionData, parseAbi } from 'viem';
import { normalizeChainName, type AssetType, type ChainName } from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

dotenv.config({ path: path.resolve(__dirname, '..', '.env'), quiet: true });

const ENV_FILE_PATH = path.resolve(__dirname, '..', '.env');
const OPENSEA_KEY_CACHE_FILE = path.resolve(__dirname, '..', '.opensea-key-cache.json');

// Default OpenSea Seaport 1.6 Contract & Conduit addresses on EVM (Base, Ethereum, BSC)
export const SEAPORT_V1_6_ADDRESS = '0x0000000000000068F116a894984e2DB1123eB395';
export const OPENSEA_CONDUIT_ADDRESS = '0x1E0049783F008A0085193E00003D00cd54003c71';

export interface OrderbookSnapshot {
  chain: ChainName;
  contractAddress: string;
  tokenId?: string;
  assetType: AssetType;
  collectionSlug?: string;
  bestBidEth: number;
  top3BidsEth: number[];
  floorPriceEth: number;
  listedRatioPct: number;
  salesVelocity1h: 'ACCELERATING' | 'STABLE' | 'DECELERATING';
  liquidityUsd?: number;
  dexId?: string;
  launchpadStage?: 'BONDING_CURVE_EXCLUSIVE' | 'GRADUATED_DEX';
  bestOfferHash?: string;
  protocolAddress?: string;
  conduitAddress?: string;
  source: 'opensea-v2' | 'dexscreener' | 'fallback';
}

export interface InstantSellFulfillment {
  expectedBidEth: number;
  marketplaceRouter: `0x${string}`;
  sellCalldata: `0x${string}`;
  valueWei: bigint;
  approvalOperator: `0x${string}`;
}

interface CachedOpenSeaKey {
  apiKey: string;
  expiresAt: number;
}

let memoryOpenSeaKey: CachedOpenSeaKey | null = null;

function persistOpenSeaKeyToEnvFile(apiKey: string): void {
  process.env.OPENSEA_API_KEY = apiKey;
  if (!fs.existsSync(ENV_FILE_PATH)) return;
  try {
    const content = fs.readFileSync(ENV_FILE_PATH, 'utf-8');
    if (/^OPENSEA_API_KEY=.*$/m.test(content)) {
      const updated = content.replace(/^OPENSEA_API_KEY=.*$/m, `OPENSEA_API_KEY=${apiKey}`);
      fs.writeFileSync(ENV_FILE_PATH, updated, 'utf-8');
    } else {
      fs.appendFileSync(ENV_FILE_PATH, `\nOPENSEA_API_KEY=${apiKey}\n`, 'utf-8');
    }
  } catch {
    // Ignore file write errors
  }
}

function readEnvFileOpenSeaKey(): string | undefined {
  try {
    if (!fs.existsSync(ENV_FILE_PATH)) return undefined;
    const content = fs.readFileSync(ENV_FILE_PATH, 'utf-8');
    const m = content.match(/^OPENSEA_API_KEY=(.*)$/m);
    const v = m?.[1]?.trim().replace(/^["']|["']$/g, '');
    if (v && v.length > 5 && !v.includes('YOUR_')) return v;
  } catch {
    // Ignore read errors
  }
  return undefined;
}

/**
 * Retrieves an OpenSea API v2 key.
 * Uses OPENSEA_API_KEY from .env if set; otherwise auto-generates, caches, and writes a free 7-day key
 * into .env via POST https://api.opensea.io/api/v2/auth/keys.
 */
export async function getOpenSeaApiKey(forceRefresh = false): Promise<string | undefined> {
  if (!forceRefresh) {
    // .env is the source of truth: re-read it every call so a key edited on disk
    // is picked up without restarting the long-running harness process.
    const fileKey = readEnvFileOpenSeaKey();
    if (fileKey) {
      process.env.OPENSEA_API_KEY = fileKey;
      return fileKey;
    }

    const envKey = process.env.OPENSEA_API_KEY?.trim();
    if (envKey && envKey.length > 5 && !envKey.includes('YOUR_')) {
      return envKey;
    }

    const now = Date.now();
    if (memoryOpenSeaKey && memoryOpenSeaKey.expiresAt > now) {
      return memoryOpenSeaKey.apiKey;
    }

    if (fs.existsSync(OPENSEA_KEY_CACHE_FILE)) {
      try {
        const raw = JSON.parse(fs.readFileSync(OPENSEA_KEY_CACHE_FILE, 'utf-8')) as CachedOpenSeaKey;
        if (raw.apiKey && raw.expiresAt > now) {
          memoryOpenSeaKey = raw;
          persistOpenSeaKeyToEnvFile(raw.apiKey);
          return raw.apiKey;
        }
      } catch {
        // Ignore corrupted cache file
      }
    }
  }

  try {
    const now = Date.now();
    const res = await fetch('https://api.opensea.io/api/v2/auth/keys', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    });
    if (res.ok) {
      const data = (await res.json()) as { api_key?: string; key?: string };
      const key = data.api_key ?? data.key;
      if (key) {
        // Cache for 6.5 days (free keys expire after 7 days)
        const cached: CachedOpenSeaKey = {
          apiKey: key,
          expiresAt: now + 6.5 * 24 * 60 * 60 * 1000,
        };
        memoryOpenSeaKey = cached;
        try {
          fs.writeFileSync(OPENSEA_KEY_CACHE_FILE, JSON.stringify(cached, null, 2), 'utf-8');
        } catch {
          // Ignore file write errors
        }
        persistOpenSeaKeyToEnvFile(key);
        console.error('[Marketplace] Auto-provisioned free 7-day OpenSea API v2 key & synced to .env.');
        return key;
      }
    }
  } catch (err) {
    console.error('[Marketplace] Gagal auto-generate OpenSea API key:', err);
  }

  return undefined;
}

function toOpenSeaChain(chain: ChainName): string {
  if (chain === 'bsc') return 'bsc';
  if (chain === 'base') return 'base';
  // OpenSea slug for Robinhood Chain (chainId 4663) is "robinhood"
  if (chain === 'robinhood') return 'robinhood';
  return 'ethereum';
}

function toDexScreenerChain(chain: ChainName): string {
  if (chain === 'bsc') return 'bsc';
  if (chain === 'base') return 'base';
  // DexScreener chainId for Robinhood Chain is "robinhood"
  if (chain === 'robinhood') return 'robinhood';
  return 'ethereum';
}

async function openSeaFetch(url: string, init?: RequestInit): Promise<Response> {
  const apiKey = await getOpenSeaApiKey();
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (apiKey) {
    headers['x-api-key'] = apiKey;
  }

  let res = await fetch(url, { ...init, headers });

  if (res.status === 401) {
    console.error('[Marketplace] OpenSea API key expired (401). Auto-rotating free 7-day key...');
    const refreshedKey = await getOpenSeaApiKey(true);
    if (refreshedKey) {
      headers['x-api-key'] = refreshedKey;
      res = await fetch(url, { ...init, headers });
    }
  }

  const remaining = res.headers.get('x-ratelimit-remaining');
  const reset = res.headers.get('x-ratelimit-reset');
  if (res.status === 429 && reset) {
    const waitMs = Math.min(Math.max(Number(reset) * 1000 - Date.now(), 1000), 10000);
    console.error(`[Marketplace] OpenSea rate limit hit (429). Menunggu ${waitMs}ms...`);
    await new Promise((r) => setTimeout(r, waitMs));
    return fetch(url, { ...init, headers });
  }
  if (remaining !== null && Number(remaining) <= 1) {
    console.error(`[Marketplace] Peringatan: OpenSea X-RateLimit-Remaining tinggal ${remaining}.`);
  }

  return res;
}

/**
 * Fetches live price, liquidity, and 1h velocity for ERC-20 / BEP-20 tokens via DexScreener (100% Free, 0 API key).
 */
async function fetchErc20MarketSnapshot(
  chain: ChainName,
  contractAddress: string
): Promise<OrderbookSnapshot> {
  const dexChain = toDexScreenerChain(chain);
  const url = `https://api.dexscreener.com/latest/dex/tokens/${contractAddress}`;
  const res = await fetch(url, { headers: { Accept: 'application/json' } });

  if (!res.ok) {
    throw new Error(`DexScreener HTTP ${res.status}`);
  }

  const data = (await res.json()) as {
    pairs?: Array<{
      chainId: string;
      dexId?: string;
      priceNative?: string;
      priceUsd?: string;
      liquidity?: { usd?: number };
      txns?: { h1?: { buys?: number; sells?: number } };
    }>;
  };

  const matchingPairs = (data.pairs ?? []).filter(
    (p) => p.chainId?.toLowerCase() === dexChain
  );
  const topPair = matchingPairs[0] ?? data.pairs?.[0];

  if (!topPair) {
    return {
      chain,
      contractAddress,
      assetType: 'ERC20',
      bestBidEth: 0,
      top3BidsEth: [],
      floorPriceEth: 0,
      listedRatioPct: 0,
      salesVelocity1h: 'STABLE',
      liquidityUsd: 0,
      launchpadStage: 'BONDING_CURVE_EXCLUSIVE',
      source: 'dexscreener',
    };
  }

  const priceNative = parseFloat(topPair.priceNative ?? '0') || 0;
  const buys1h = topPair.txns?.h1?.buys ?? 0;
  const sells1h = topPair.txns?.h1?.sells ?? 0;
  const dexId = topPair.dexId?.toLowerCase() ?? 'unknown';
  const liquidityUsd = topPair.liquidity?.usd ?? 0;

  // Detect whether token has graduated to PancakeSwap/Uniswap or is still on Four.Meme / Flap bonding curve
  const isGraduatedDex =
    dexId.includes('pancakeswap') ||
    dexId.includes('uniswap') ||
    dexId.includes('aerodrome') ||
    liquidityUsd >= 5000;

  let velocity: 'ACCELERATING' | 'STABLE' | 'DECELERATING' = 'STABLE';
  if (sells1h > buys1h * 1.35) {
    velocity = 'DECELERATING';
  } else if (buys1h > sells1h * 1.35) {
    velocity = 'ACCELERATING';
  }

  return {
    chain,
    contractAddress,
    assetType: 'ERC20',
    bestBidEth: priceNative,
    top3BidsEth: [
      priceNative,
      Number((priceNative * 0.995).toFixed(8)),
      Number((priceNative * 0.99).toFixed(8)),
    ],
    floorPriceEth: priceNative,
    listedRatioPct: 0,
    salesVelocity1h: velocity,
    liquidityUsd,
    dexId,
    launchpadStage: isGraduatedDex ? 'GRADUATED_DEX' : 'BONDING_CURVE_EXCLUSIVE',
    source: 'dexscreener',
  };
}

function parseOfferPriceEth(offer: {
  price?: { value?: string; decimals?: number };
  current_price?: string;
  protocol_data?: {
    parameters?: {
      offer?: Array<{ startAmount?: string }>;
      consideration?: Array<{ startAmount?: string }>;
    };
  };
}): number {
  if (offer.price?.value) {
    const decimals = offer.price.decimals ?? 18;
    const raw = Number(offer.price.value) / 10 ** decimals;
    // Normalize per-item if offer bundles multiple items
    const considerationQty = Number(
      offer.protocol_data?.parameters?.consideration?.[0]?.startAmount ?? '1'
    );
    return considerationQty > 1 ? raw / considerationQty : raw;
  }
  if (offer.current_price) {
    return Number(offer.current_price) / 1e18;
  }
  return 0;
}

/**
 * Fetches live Best Bid, Top 3 Bids Depth, Floor Price, and 1h Velocity.
 * Supports OpenSea API v2 for ERC-721/1155 NFTs and DexScreener API for ERC-20/BEP-20 tokens.
 */
export async function fetchBestBidEth(
  rawChain: string,
  contractAddress: string,
  tokenId?: string,
  assetType: AssetType = 'ERC721'
): Promise<OrderbookSnapshot> {
  const chain = normalizeChainName(rawChain);

  if (assetType === 'ERC20') {
    return fetchErc20MarketSnapshot(chain, contractAddress);
  }

  const osChain = toOpenSeaChain(chain);

  try {
    // Step 1: Resolve collection slug from contract address
    const contractUrl = `https://api.opensea.io/api/v2/chain/${osChain}/contract/${contractAddress}`;
    const contractRes = await openSeaFetch(contractUrl);
    if (!contractRes.ok) {
      throw new Error(`OpenSea contract lookup HTTP ${contractRes.status}`);
    }
    const contractData = (await contractRes.json()) as { collection?: string };
    const collectionSlug = contractData.collection;

    if (!collectionSlug) {
      throw new Error(`Collection slug tidak ditemukan untuk kontrak ${contractAddress} di ${osChain}`);
    }

    // Step 2: Fetch collection stats (floor price & listed count) + top offers in parallel
    const statsUrl = `https://api.opensea.io/api/v2/collections/${collectionSlug}/stats`;
    const offersUrl = `https://api.opensea.io/api/v2/offers/collection/${collectionSlug}?limit=10`;
    const bestNftOfferUrl = tokenId
      ? `https://api.opensea.io/api/v2/offers/collection/${collectionSlug}/nfts/${tokenId}/best`
      : null;

    const [statsRes, offersRes, bestOfferRes] = await Promise.all([
      openSeaFetch(statsUrl),
      openSeaFetch(offersUrl),
      bestNftOfferUrl ? openSeaFetch(bestNftOfferUrl) : Promise.resolve(null),
    ]);

    let floorPriceEth = 0;
    let salesVelocity1h: 'ACCELERATING' | 'STABLE' | 'DECELERATING' = 'STABLE';
    if (statsRes.ok) {
      const statsData = (await statsRes.json()) as {
        total?: { floor_price?: number };
        intervals?: Array<{ interval?: string; sales?: number; volume?: number }>;
      };
      floorPriceEth = statsData.total?.floor_price ?? 0;
      const oneDay = statsData.intervals?.find((i) => i.interval === 'one_day');
      if (oneDay && (oneDay.sales ?? 0) < 3) {
        salesVelocity1h = 'DECELERATING';
      } else if (oneDay && (oneDay.sales ?? 0) > 25) {
        salesVelocity1h = 'ACCELERATING';
      }
    }

    type RawOffer = {
      order_hash?: string;
      protocol_address?: string;
      price?: { value?: string; decimals?: number };
      current_price?: string;
      protocol_data?: {
        parameters?: {
          conduitKey?: string;
          consideration?: Array<{ startAmount?: string }>;
        };
      };
    };

    const bidPrices: number[] = [];
    let bestOfferHash: string | undefined;
    let protocolAddress: string | undefined = SEAPORT_V1_6_ADDRESS;

    if (bestOfferRes && bestOfferRes.ok) {
      const bestOffer = (await bestOfferRes.json()) as RawOffer;
      const p = parseOfferPriceEth(bestOffer);
      if (p > 0) {
        bidPrices.push(p);
        bestOfferHash = bestOffer.order_hash;
        protocolAddress = bestOffer.protocol_address ?? SEAPORT_V1_6_ADDRESS;
      }
    }

    if (offersRes.ok) {
      const offersData = (await offersRes.json()) as { offers?: RawOffer[] };
      for (const offer of offersData.offers ?? []) {
        const p = parseOfferPriceEth(offer);
        if (p > 0) {
          bidPrices.push(p);
          if (!bestOfferHash && offer.order_hash) {
            bestOfferHash = offer.order_hash;
            protocolAddress = offer.protocol_address ?? SEAPORT_V1_6_ADDRESS;
          }
        }
      }
    }

    bidPrices.sort((a, b) => b - a);
    const uniqueTop3 = Array.from(new Set(bidPrices.map((n) => Number(n.toFixed(6))))).slice(0, 3);
    const bestBidEth = uniqueTop3[0] ?? 0;

    if (uniqueTop3.length >= 2 && uniqueTop3[1] < uniqueTop3[0] * 0.85) {
      salesVelocity1h = 'DECELERATING';
    }

    return {
      chain,
      contractAddress,
      tokenId,
      assetType,
      collectionSlug,
      bestBidEth,
      top3BidsEth: uniqueTop3,
      floorPriceEth,
      listedRatioPct: 0,
      salesVelocity1h,
      bestOfferHash,
      protocolAddress,
      conduitAddress: OPENSEA_CONDUIT_ADDRESS,
      source: 'opensea-v2',
    };
  } catch (err) {
    console.error(`[Marketplace] OpenSea lookup warning (${chain}:${contractAddress}):`, err);
    return {
      chain,
      contractAddress,
      tokenId,
      assetType,
      bestBidEth: 0,
      top3BidsEth: [],
      floorPriceEth: 0,
      listedRatioPct: 0,
      salesVelocity1h: 'STABLE',
      conduitAddress: OPENSEA_CONDUIT_ADDRESS,
      source: 'fallback',
    };
  }
}

/**
 * Fetches executable fulfillment calldata from OpenSea API v2 (`POST /api/v2/offers/fulfillment_data`)
 * so `execute_autonomous_sell` and `watcher.ts` Emergency Hard-Stop can dump an NFT into the top bid.
 */
export async function fetchInstantSellFulfillment(
  rawChain: string,
  contractAddress: string,
  tokenId: string,
  walletAddress: string
): Promise<InstantSellFulfillment> {
  const chain = normalizeChainName(rawChain);
  const snapshot = await fetchBestBidEth(chain, contractAddress, tokenId, 'ERC721');

  if (!snapshot.bestOfferHash || snapshot.bestBidEth <= 0) {
    throw new Error(
      `Tidak ditemukan active bid/offer yang dapat dieksekusi untuk ${contractAddress} #${tokenId} di ${chain}.`
    );
  }

  const osChain = toOpenSeaChain(chain);
  const protocolAddress = snapshot.protocolAddress ?? SEAPORT_V1_6_ADDRESS;

  const res = await openSeaFetch('https://api.opensea.io/api/v2/offers/fulfillment_data', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      offer: {
        hash: snapshot.bestOfferHash,
        chain: osChain,
        protocol_address: protocolAddress,
      },
      fulfiller: {
        address: walletAddress,
      },
      consideration: {
        asset_contract_address: contractAddress,
        token_id: tokenId,
      },
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`OpenSea fulfillment_data HTTP ${res.status}: ${errText}`);
  }

  const data = (await res.json()) as {
    fulfillment_data?: {
      transaction?: {
        to?: string;
        value?: string | number;
        input_data?: Record<string, unknown> | string;
        function?: string;
      };
    };
  };

  const tx = data.fulfillment_data?.transaction;
  if (!tx?.to) {
    throw new Error('Respons OpenSea fulfillment_data tidak memiliki target transaction.to');
  }

  let sellCalldata: `0x${string}`;
  if (typeof tx.input_data === 'string' && tx.input_data.startsWith('0x')) {
    sellCalldata = tx.input_data as `0x${string}`;
  } else {
    throw new Error(
      'Format input_data Seaport memerlukan raw hex calldata atau parameter spesifik dari indexer.'
    );
  }

  return {
    expectedBidEth: snapshot.bestBidEth,
    marketplaceRouter: tx.to as `0x${string}`,
    sellCalldata,
    valueWei: BigInt(tx.value ?? 0),
    approvalOperator: (snapshot.conduitAddress ?? OPENSEA_CONDUIT_ADDRESS) as `0x${string}`,
  };
}

export const ERC721_APPROVAL_ABI = parseAbi([
  'function isApprovedForAll(address owner, address operator) view returns (bool)',
  'function setApprovalForAll(address operator, bool approved)',
]);

export function encodeSetApprovalForAll(operator: `0x${string}`, approved = true): `0x${string}` {
  return encodeFunctionData({
    abi: ERC721_APPROVAL_ABI,
    functionName: 'setApprovalForAll',
    args: [operator, approved],
  });
}

// ============================================================================
// ERC-20 / BEP-20 & PancakeSwap / Uniswap V2 Router Helpers (for .ai Tokens)
// ============================================================================
export const ERC20_ABI = parseAbi([
  'function balanceOf(address account) view returns (uint256)',
  'function allowance(address owner, address spender) view returns (uint256)',
  'function approve(address spender, uint256 amount) returns (bool)',
]);

export const DEX_V2_ROUTER_ABI = parseAbi([
  'function getAmountsOut(uint256 amountIn, address[] memory path) view returns (uint256[] memory amounts)',
  'function swapExactETHForTokensSupportingFeeOnTransferTokens(uint256 amountOutMin, address[] calldata path, address to, uint256 deadline) payable',
  'function swapExactTokensForETHSupportingFeeOnTransferTokens(uint256 amountIn, uint256 amountOutMin, address[] calldata path, address to, uint256 deadline)',
]);

export function getDexRouterAndWrappedNative(chain: ChainName): {
  router: `0x${string}`;
  wrappedNative: `0x${string}`;
} {
  if (chain === 'bsc') {
    return {
      // PancakeSwap V2 Router & WBNB on BNB Smart Chain
      router: '0x10ED43C718714eb63d5aA57B78B54704E256024E',
      wrappedNative: '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c',
    };
  }
  if (chain === 'base') {
    return {
      // Uniswap V2 Router & WETH on Base
      router: '0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24',
      wrappedNative: '0x4200000000000000000000000000000000000006',
    };
  }
  if (chain === 'robinhood') {
    return {
      // Uniswap V2 Router02 & WETH9 on Robinhood Chain (chainId 4663).
      // Source: Uniswap/contracts deployments/4663.md; verified on-chain 2026-11-02 via
      // router.factory() == 0x8bcEaA40B9AcdfAedF85AdF4FF01F5Ad6517937f and router.WETH().
      router: '0x89e5db8b5aa49aa85ac63f691524311aeb649eba',
      wrappedNative: '0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73',
    };
  }
  return {
    // Uniswap V2 Router & WETH on Ethereum Mainnet
    router: '0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D',
    wrappedNative: '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
  };
}

export function encodeErc20Approve(spender: `0x${string}`, amount: bigint): `0x${string}` {
  return encodeFunctionData({
    abi: ERC20_ABI,
    functionName: 'approve',
    args: [spender, amount],
  });
}

export function encodeDexSellTokensForNative(
  chain: ChainName,
  tokenAddress: `0x${string}`,
  amountIn: bigint,
  amountOutMin: bigint,
  recipient: `0x${string}`
): { router: `0x${string}`; calldata: `0x${string}` } {
  const { router, wrappedNative } = getDexRouterAndWrappedNative(chain);
  const deadline = BigInt(Math.floor(Date.now() / 1000) + 300);
  const calldata = encodeFunctionData({
    abi: DEX_V2_ROUTER_ABI,
    functionName: 'swapExactTokensForETHSupportingFeeOnTransferTokens',
    args: [amountIn, amountOutMin, [tokenAddress, wrappedNative], recipient, deadline],
  });
  return { router, calldata };
}

