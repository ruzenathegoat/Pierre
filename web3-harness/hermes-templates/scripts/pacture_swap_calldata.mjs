// Build approve + swap calldata for selling PACTURE out of the agentic wallet (BAW).
//
//   node ~/.hermes/scripts/pacture_swap_calldata.mjs --wallet 0x7462...269F \
//        [--amount 40000000] [--slippage-bps 400] [--deadline-seconds 600]
//
// Auto-detects which PancakeSwap V2 pair exists (PACTURE/WBNB or PACTURE/USDT) and
// picks the right router entry point: WBNB pair -> swapExactTokensForETH... (payout in
// BNB), USDT pair -> swapExactTokensForTokens (payout in USDT).
// Prints one JSON object; no signing happens here.
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const HARNESS = path.join(process.env.HOME, '.hermes', 'web3-harness')
const require = createRequire(path.join(HARNESS, 'package.json'))
const { createPublicClient, http, parseAbi, encodeFunctionData, parseUnits, formatUnits } = require('viem')
const { bsc } = require('viem/chains')

const TOKEN = '0x10b80088fDAf9363d83671BE66b64f231f9e92f6'   // PACTURE
const WBNB = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'
const USDT = '0x55d398326f99059fF775485246999027B3197955'
const FACTORY = '0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73'
const ROUTER = '0x10ED43C718714eb63d5aA57B78B54704E256024E'

const argv = process.argv.slice(2)
const arg = (name, dflt) => {
  const i = argv.indexOf(name)
  return i >= 0 ? argv[i + 1] : dflt
}
const wallet = arg('--wallet')
const amountHuman = arg('--amount', '40000000')
const slippageBps = BigInt(arg('--slippage-bps', '400'))     // 400 = 4% tolerance
const deadlineSeconds = BigInt(arg('--deadline-seconds', '600'))
if (!wallet) {
  console.error('usage: pacture_swap_calldata.mjs --wallet <address> [--amount 40000000] [--slippage-bps 400]')
  process.exit(2)
}

const env = {}
for (const line of readFileSync(path.join(HARNESS, '.env'), 'utf8').split('\n')) {
  const i = line.indexOf('=')
  if (i > 0 && !line.trimStart().startsWith('#')) env[line.slice(0, i).trim()] = line.slice(i + 1).trim()
}
const pub = createPublicClient({ chain: bsc, transport: http(env.BSC_RPC_URL || 'https://rpc-bsc.48.club') })

const factoryAbi = parseAbi(['function getPair(address,address) view returns (address)'])
const pairAbi = parseAbi([
  'function getReserves() view returns (uint112,uint112,uint32)',
  'function token0() view returns (address)',
])
const erc20 = parseAbi(['function approve(address,uint256) returns (bool)'])
const routerAbi = parseAbi([
  'function getAmountsOut(uint256,address[]) view returns (uint256[])',
  'function swapExactTokensForETHSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)',
  'function swapExactTokensForTokens(uint256,uint256,address[],address,uint256)',
])

const pairWbnb = await pub.readContract({ address: FACTORY, abi: factoryAbi, functionName: 'getPair', args: [TOKEN, WBNB] })
const pairUsdt = await pub.readContract({ address: FACTORY, abi: factoryAbi, functionName: 'getPair', args: [TOKEN, USDT] })
const zero = '0x0000000000000000000000000000000000000000'
const pair = pairWbnb !== zero ? pairWbnb : (pairUsdt !== zero ? pairUsdt : null)
if (!pair) {
  console.error(JSON.stringify({ error: 'no PACTURE pair on PancakeSwap V2 factory yet', pairWbnb, pairUsdt }))
  process.exit(3)
}
const quote = pair === pairWbnb ? WBNB : USDT
const path_ = [TOKEN, quote]

const amountIn = parseUnits(amountHuman, 18)
const quoted = await pub.readContract({ address: ROUTER, abi: routerAbi, functionName: 'getAmountsOut', args: [amountIn, path_] })
const minOut = (quoted[1] * (10000n - slippageBps)) / 10000n
const deadline = BigInt(Math.floor(Date.now() / 1000)) + deadlineSeconds

const approveData = encodeFunctionData({ abi: erc20, functionName: 'approve', args: [ROUTER, amountIn] })
const fn = quote === WBNB ? 'swapExactTokensForETHSupportingFeeOnTransferTokens' : 'swapExactTokensForTokens'
const swapData = encodeFunctionData({ abi: routerAbi, functionName: fn, args: [amountIn, minOut, path_, wallet, deadline] })

const reserves = await pub.readContract({ address: pair, abi: pairAbi, functionName: 'getReserves' })
const t0 = (await pub.readContract({ address: pair, abi: pairAbi, functionName: 'token0' })).toLowerCase()
const tokIs0 = t0 === TOKEN.toLowerCase()
const rTok = tokIs0 ? reserves[0] : reserves[1]
const rQuote = tokIs0 ? reserves[1] : reserves[0]

console.log(JSON.stringify({
  pair, quoteToken: quote, functionName: fn, path: path_,
  amountIn: formatUnits(amountIn, 18),
  quotedOut: formatUnits(quoted[1], 18),
  minOut: formatUnits(minOut, 18),
  slippageBps: slippageBps.toString(),
  poolTokenReserve: formatUnits(rTok, 18),
  poolQuoteReserve: formatUnits(rQuote, 18),
  spotQuotePerToken: formatUnits((rQuote * 10n ** 18n) / rTok, 18),
  deadline: deadline.toString(),
  approveTo: ROUTER,
  approveData,
  swapTo: ROUTER,
  swapData,
}, null, 2))
