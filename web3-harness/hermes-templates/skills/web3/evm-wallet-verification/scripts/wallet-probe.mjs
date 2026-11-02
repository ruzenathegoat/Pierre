// Derive an EVM address from a private key in an env file and read native balances.
// Usage: node wallet-probe.mjs /path/to/.env   (must run where `viem` resolves)
// Never prints the private key.
import fs from 'fs';
import { createPublicClient, http, formatEther } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';
import { base, mainnet, bsc } from 'viem/chains';

const envPath = process.argv[2] || '.env';
const env = {};
for (const line of fs.readFileSync(envPath, 'utf8').split('\n')) {
  const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
  if (m) env[m[1]] = m[2].replace(/^["']|["']$/g, '');
}

const KEY_VARS = ['WALLET_PRIVATE_KEY', 'PRIVATE_KEY', 'DEPLOYER_KEY'];
const keyVar = KEY_VARS.find((k) => env[k]);
if (!keyVar) { console.log(JSON.stringify({ ok: false, err: 'no private key variable found', checked: KEY_VARS })); process.exit(0); }

const raw = env[keyVar].trim();
const norm = raw.startsWith('0x') ? raw : '0x' + raw;
if (!/^0x[0-9a-fA-F]{64}$/.test(norm)) { console.log(JSON.stringify({ ok: false, hex_ok: false, key_var: keyVar, err: 'malformed private key' })); process.exit(0); }

let account;
try { account = privateKeyToAccount(norm); }
catch { console.log(JSON.stringify({ ok: false, hex_ok: true, key_var: keyVar, err: 'derivation failed' })); process.exit(0); }

const chains = [
  ['base', base, env.BASE_RPC_URL || 'https://mainnet.base.org', 'ETH'],
  ['ethereum', mainnet, env.ETH_RPC_URL || 'https://ethereum-rpc.publicnode.com', 'ETH'],
  ['bsc', bsc, env.BSC_RPC_URL || 'https://bsc-dataseed.bnbchain.org', 'BNB'],
];

const out = {
  ok: true,
  hex_ok: true,
  key_var: keyVar,
  address: account.address,
  balances: {},
  caps: { MAX_ETH_PER_TX: env.MAX_ETH_PER_TX, MAX_BNB_PER_TX: env.MAX_BNB_PER_TX },
};

for (const [name, chain, url, unit] of chains) {
  try {
    const client = createPublicClient({ chain, transport: http(url, { timeout: 15000 }) });
    const wei = await client.getBalance({ address: account.address });
    out.balances[name] = { rpc: url, value: formatEther(wei) + ' ' + unit };
  } catch (e) {
    out.balances[name] = { rpc: url, error: String(e.shortMessage || e.message).split('\n')[0] };
  }
}

console.log(JSON.stringify(out, null, 2));
