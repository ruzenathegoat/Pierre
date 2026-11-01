import 'dotenv/config';
import { createPublicClient, http, formatEther } from 'viem';
import { base, mainnet, bsc } from 'viem/chains';

const addr = '0xBAD577476432726C45267e2B57602dd4594a936c';
const cfg = [
  ['base', base, process.env.BASE_RPC_URL],
  ['ethereum', mainnet, process.env.ETH_RPC_URL],
  ['bsc', bsc, process.env.BSC_RPC_URL],
];
for (const [name, chain, rpc] of cfg) {
  try {
    if (!rpc) { console.log(name + ': n/a (no RPC)'); continue; }
    const c = createPublicClient({ chain, transport: http(rpc) });
    const b = await c.getBalance({ address: addr });
    console.log(name + ': ' + formatEther(b));
  } catch (e) {
    console.log(name + ': ERROR ' + (e.shortMessage || e.message));
  }
}
