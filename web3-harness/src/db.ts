import Database from 'better-sqlite3';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export const DB_PATH = path.resolve(__dirname, '..', 'trades.db');

const db = new Database(DB_PATH);

// Enable WAL mode and busy timeout to prevent SQLITE_BUSY between mcp-server.ts and watcher.ts
db.pragma('journal_mode = WAL');
db.pragma('busy_timeout = 5000');

db.exec(`
  CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_hash TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    action TEXT,
    chain TEXT,
    contract_address TEXT,
    asset_name TEXT,
    price_eth REAL,
    realized_pnl_eth REAL DEFAULT 0,
    trigger_source TEXT
  );

  CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain TEXT,
    contract_address TEXT,
    token_id TEXT,
    asset_type TEXT DEFAULT 'ERC721',
    asset_name TEXT,
    entry_price_eth REAL,
    high_water_mark_eth REAL,
    status TEXT DEFAULT 'OPEN',
    last_alerted_at DATETIME,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
  );

  CREATE TABLE IF NOT EXISTS staged_transactions (
    tx_id TEXT PRIMARY KEY,
    chain TEXT,
    contract_address TEXT,
    calldata TEXT,
    value_eth REAL,
    action_type TEXT,
    asset_name TEXT,
    source_url TEXT,
    token_id TEXT,
    is_fresh_input INTEGER DEFAULT 0,
    expires_at INTEGER
  );
`);

export type ChainName = 'base' | 'ethereum' | 'bsc' | 'robinhood';
export type AssetType = 'ERC721' | 'ERC1155' | 'ERC20';
export type TradeActionType =
  | 'BUY'
  | 'MINT'
  | 'CLAIM'
  | 'AUTO_SELL'
  | 'EMERGENCY_SELL'
  | 'SELL'
  | 'TRANSFER'
  | 'SWAP'
  | 'APPROVE'
  | 'LP_ADD'
  | 'LP_REMOVE'
  | 'CONTRACT_CALL';

export function normalizeChainName(chain: string): ChainName {
  const c = chain.trim().toLowerCase();
  if (c === 'bsc' || c === 'bnb' || c === 'binance') return 'bsc';
  if (c === 'eth' || c === 'ethereum' || c === 'mainnet') return 'ethereum';
  if (c === 'base') return 'base';
  // Robinhood Chain: Arbitrum Orbit L2, chainId 4663, gas in ETH
  if (c === 'robinhood' || c === 'rh' || c === 'robinhood-chain' || c === 'hood') return 'robinhood';
  throw new Error(
    `Unsupported chain "${chain}". Supported chains: base, ethereum, bsc (bnb), robinhood.`
  );
}

export interface NewTradeInput {
  tx_hash: string;
  action: TradeActionType | string;
  chain: ChainName | string;
  contract_address: string;
  asset_name: string;
  price_eth: number;
  realized_pnl_eth?: number;
  trigger_source: string;
}

export interface TradeRecord extends NewTradeInput {
  id: number;
  timestamp: string;
  realized_pnl_eth: number;
}

export interface NewPositionInput {
  chain: ChainName | string;
  contract_address: string;
  token_id: string;
  asset_type?: AssetType | string;
  asset_name: string;
  entry_price_eth: number;
  high_water_mark_eth?: number;
}

export interface PositionRecord {
  id: number;
  chain: string;
  contract_address: string;
  token_id: string;
  asset_type: string;
  asset_name: string;
  entry_price_eth: number;
  high_water_mark_eth: number;
  status: 'OPEN' | 'CLOSED';
  last_alerted_at: string | null;
  updated_at: string;
}

export interface NewStagedTxInput {
  tx_id: string;
  chain: ChainName | string;
  contract_address: string;
  calldata: string;
  value_eth: number;
  action_type: TradeActionType | string;
  asset_name: string;
  source_url: string;
  token_id?: string;
  is_fresh_input: boolean;
}

export interface StagedTxRecord {
  tx_id: string;
  chain: string;
  contract_address: string;
  calldata: string;
  value_eth: number;
  action_type: string;
  asset_name: string;
  source_url: string;
  token_id: string | null;
  is_fresh_input: number;
  expires_at: number;
}

const insertTradeStmt = db.prepare(`
  INSERT INTO trades (tx_hash, action, chain, contract_address, asset_name, price_eth, realized_pnl_eth, trigger_source)
  VALUES (@tx_hash, @action, @chain, @contract_address, @asset_name, @price_eth, @realized_pnl_eth, @trigger_source)
`);

export function insertTrade(trade: NewTradeInput): number {
  const result = insertTradeStmt.run({
    ...trade,
    realized_pnl_eth: trade.realized_pnl_eth ?? 0,
  });
  return Number(result.lastInsertRowid);
}

const insertPositionStmt = db.prepare(`
  INSERT INTO positions (chain, contract_address, token_id, asset_type, asset_name, entry_price_eth, high_water_mark_eth, status)
  VALUES (@chain, @contract_address, @token_id, @asset_type, @asset_name, @entry_price_eth, @high_water_mark_eth, 'OPEN')
`);

export function insertPosition(pos: NewPositionInput): number {
  const result = insertPositionStmt.run({
    chain: pos.chain,
    contract_address: pos.contract_address.toLowerCase(),
    token_id: pos.token_id,
    asset_type: pos.asset_type ?? 'ERC721',
    asset_name: pos.asset_name,
    entry_price_eth: pos.entry_price_eth,
    high_water_mark_eth: pos.high_water_mark_eth ?? pos.entry_price_eth,
  });
  return Number(result.lastInsertRowid);
}

const getOpenPositionsStmt = db.prepare(`
  SELECT * FROM positions WHERE status = 'OPEN' ORDER BY id ASC
`);

export function getOpenPositions(): PositionRecord[] {
  return getOpenPositionsStmt.all() as PositionRecord[];
}

const getPositionByIdStmt = db.prepare(`
  SELECT * FROM positions WHERE id = ?
`);

export function getPositionById(id: number): PositionRecord | undefined {
  return getPositionByIdStmt.get(id) as PositionRecord | undefined;
}

const updateHWMStmt = db.prepare(`
  UPDATE positions
  SET high_water_mark_eth = ?, updated_at = CURRENT_TIMESTAMP
  WHERE id = ?
`);

export function updateHWM(id: number, newHwmEth: number): void {
  updateHWMStmt.run(newHwmEth, id);
}

const markAlertedStmt = db.prepare(`
  UPDATE positions
  SET last_alerted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
  WHERE id = ?
`);

export function markPositionAlerted(id: number): void {
  markAlertedStmt.run(id);
}

const closePositionStmt = db.prepare(`
  UPDATE positions
  SET status = 'CLOSED', updated_at = CURRENT_TIMESTAMP
  WHERE id = ?
`);

export function closePosition(id: number): void {
  closePositionStmt.run(id);
}

const saveStagedTxStmt = db.prepare(`
  INSERT OR REPLACE INTO staged_transactions
  (tx_id, chain, contract_address, calldata, value_eth, action_type, asset_name, source_url, token_id, is_fresh_input, expires_at)
  VALUES (@tx_id, @chain, @contract_address, @calldata, @value_eth, @action_type, @asset_name, @source_url, @token_id, @is_fresh_input, @expires_at)
`);

export function saveStagedTx(tx: NewStagedTxInput, ttlMs = 5 * 60 * 1000): void {
  const expiresAt = Date.now() + ttlMs;
  saveStagedTxStmt.run({
    tx_id: tx.tx_id,
    chain: tx.chain,
    contract_address: tx.contract_address,
    calldata: tx.calldata,
    value_eth: tx.value_eth,
    action_type: tx.action_type,
    asset_name: tx.asset_name,
    source_url: tx.source_url,
    token_id: tx.token_id ?? null,
    is_fresh_input: tx.is_fresh_input ? 1 : 0,
    expires_at: expiresAt,
  });
}

const getStagedTxStmt = db.prepare(`
  SELECT * FROM staged_transactions WHERE tx_id = ?
`);

const deleteStagedTxStmt = db.prepare(`
  DELETE FROM staged_transactions WHERE tx_id = ?
`);

const cleanupExpiredStagedTxStmt = db.prepare(`
  DELETE FROM staged_transactions WHERE expires_at < ?
`);

export function getValidStagedTx(txId: string): StagedTxRecord | undefined {
  cleanupExpiredStagedTxStmt.run(Date.now());
  const row = getStagedTxStmt.get(txId) as StagedTxRecord | undefined;
  if (!row) return undefined;
  if (Date.now() > row.expires_at) {
    deleteStagedTxStmt.run(txId);
    return undefined;
  }
  return row;
}

export function deleteStagedTx(txId: string): void {
  deleteStagedTxStmt.run(txId);
}

export default db;

