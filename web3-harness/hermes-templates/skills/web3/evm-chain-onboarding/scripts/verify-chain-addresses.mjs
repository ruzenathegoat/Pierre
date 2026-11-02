// Prove a chain + DEX address set before wiring it into a harness.
// Run from a directory where `viem` resolves (the harness dir), e.g.:
//   node verify-chain-addresses.mjs robinhood 0x89e5db8b5aa49aa85ac63f691524311aeb649eba [more addresses...]
// Prints chainId, live block, router.factory(), router.WETH(), and code size per address.
import { createPublicClient, http, parseAbi } from 'viem';
import * as chains from 'viem/chains';

const [chainName, ...addresses] = process.argv.slice(2);
if (!chainName) {
  console.error('usage: node verify-chain-addresses.mjs <viem-chain-name> [address ...]');
  process.exit(2);
}

const chain = chains[chainName];
if (!chain) {
  console.error(`viem has no chain "${chainName}". Candidates:`);
  console.error(Object.keys(chains).filter((k) => k.toLowerCase().includes(chainName.toLowerCase())));
  process.exit(2);
}

const client = createPublicClient({ chain, transport: http(process.env.RPC_URL || undefined) });
const routerAbi = parseAbi([
  'function factory() view returns (address)',
  'function WETH() view returns (address)',
]);

const out = { chain: chain.name, id: await client.getChainId(), block: (await client.getBlockNumber()).toString() };

for (const address of addresses) {
  const code = await client.getCode({ address });
  const entry = { address, codeBytes: code ? (code.length - 2) / 2 : 0 };
  if (entry.codeBytes > 0) {
    // Only Router02-style contracts expose both getters; ignore reverts.
    for (const functionName of ['factory', 'WETH']) {
      try {
        entry[functionName] = await client.readContract({ address, abi: routerAbi, functionName });
      } catch {
        entry[functionName] = null;
      }
    }
  }
  out[address] = entry;
}

console.log(JSON.stringify(out, null, 2));
console.log('\nCheck: factory() must equal the documented factory, WETH() must equal the wrapped native you hardcode.');
