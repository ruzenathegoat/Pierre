// Build the approve + swap calldata for selling AGC straight from the agentic wallet (BAW).
//
//   node ~/.hermes/scripts/agc_swap_calldata.mjs --amount 1400000 --wallet 0x7462...269F [--slippage-bps 600]
//
// Prints one JSON object so a cron job can feed `data` straight into
// `baw contract-call preview/execute`. No signing happens here.
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const HARNESS = path.join(process.env.HOME, '.hermes', 'web3-harness')
const require = createRequire(path.join(HARNESS, 'package.json'))
const { createPublicClient, http, parseAbi, encodeFunctionData, parseUnits, formatUnits } = require('viem')
const { bsc } = require('viem/chains')

const AGC = '0x63dea5aCdbE1F27c968907D08610A5f0A0284bA6'
const ROUTER = '0x10ED43C718714eb63d5aA57B78B54704E256024E'
const WBNB = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'

const argv = process.argv.slice(2)
const arg = (name, dflt) => {
  const i = argv.indexOf(name)
  return i >= 0 ? argv[i + 1] : dflt
}
const amountHuman = arg('--amount')
const wallet = arg('--wallet')
const slippageBps = BigInt(arg('--slippage-bps', '600'))   // 600 = 6% tolerance
const deadlineSeconds = BigInt(arg('--deadline-seconds', '600'))
if (!amountHuman || !wallet) {
  console.error('usage: agc_swap_calldata.mjs --amount <AGC> --wallet <address> [--slippage-bps 600]')
  process.exit(2)
}

const env = {}
for (const line of readFileSync(path.join(HARNESS, '.env'), 'utf8').split('\n')) {
  const i = line.indexOf('=')
  if (i > 0 && !line.trimStart().startsWith('#')) env[line.slice(0, i).trim()] = line.slice(i + 1).trim()
}
const pub = createPublicClient({ chain: bsc, transport: http(env.BSC_RPC_URL || 'https://rpc-bsc.48.club') })

const erc20 = parseAbi(['function approve(address,uint256) returns (bool)'])
const routerAbi = parseAbi([
  'function getAmountsOut(uint256,address[]) view returns (uint256[])',
  'function swapExactTokensForETHSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)',
])

const amountIn = parseUnits(amountHuman, 18)
const quoted = await pub.readContract({ address: ROUTER, abi: routerAbi, functionName: 'getAmountsOut', args: [amountIn, [AGC, WBNB]] })
const minOut = (quoted[1] * (10000n - slippageBps)) / 10000n
const deadline = BigInt(Math.floor(Date.now() / 1000)) + deadlineSeconds

const approveData = encodeFunctionData({ abi: erc20, functionName: 'approve', args: [ROUTER, amountIn] })
const swapData = encodeFunctionData({
  abi: routerAbi,
  functionName: 'swapExactTokensForETHSupportingFeeOnTransferTokens',
  args: [amountIn, minOut, [AGC, WBNB], wallet, deadline],
})

console.log(JSON.stringify({
  amountIn: formatUnits(amountIn, 18),
  amountInWei: amountIn.toString(),
  quoteWbnb: formatUnits(quoted[1], 18),
  minOutWei: minOut.toString(),
  minOutWbnb: formatUnits(minOut, 18),
  deadline: Number(deadline),
  slippageBps: Number(slippageBps),
  approve: { to: AGC, value: '0', data: approveData },
  swap: { to: ROUTER, value: '0', data: swapData },
  note: 'approve first, then swap; both from the agentic wallet, value 0',
}, null, 1))
