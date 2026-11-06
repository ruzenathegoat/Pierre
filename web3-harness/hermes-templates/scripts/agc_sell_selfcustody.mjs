// Sell AGC from the self-custody wallet (0xbad5…) through PancakeSwap V2.
//
// Run AFTER the claim has landed and the AGC has been transferred into this
// wallet. Prints one machine-readable line per stage so a cron job can report it.
//
//   node ~/.hermes/scripts/agc_sell_selfcustody.mjs [--min-bnb 0.005]
//
// Exit codes: 0 sold | 3 no AGC balance (nothing to do) | 4 swap reverted | 5 setup error
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import path from 'node:path'

const HARNESS = path.join(process.env.HOME, '.hermes', 'web3-harness')
const require = createRequire(path.join(HARNESS, 'package.json'))
const { createWalletClient, createPublicClient, http, parseAbi, formatUnits, parseUnits } = require('viem')
const { privateKeyToAccount } = require('viem/accounts')
const { bsc } = require('viem/chains')

const AGC = '0x63dea5acdbe1f27c968907d08610a5f0a0284ba6'
const ROUTER = '0x10ED43C718714eb63d5aA57B78B54704E256024E'
const WBNB = '0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c'

// 2% transfer tax + 0.25% pool fee are not in the router quote, so clamp hard.
const MINOUT_BPS = 9400n
const DEADLINE_S = 300n

const env = {}
for (const line of readFileSync(path.join(HARNESS, '.env'), 'utf8').split('\n')) {
  const i = line.indexOf('=')
  if (i > 0 && !line.trimStart().startsWith('#')) env[line.slice(0, i).trim()] = line.slice(i + 1).trim()
}

const args = process.argv.slice(2)
const minBnbArg = args.indexOf('--min-bnb')
const MIN_BNB = minBnbArg >= 0 ? Number(args[minBnbArg + 1]) : 0

const account = privateKeyToAccount(env.WALLET_PRIVATE_KEY.startsWith('0x') ? env.WALLET_PRIVATE_KEY : '0x' + env.WALLET_PRIVATE_KEY)
const transport = http(env.BSC_RPC_URL || 'https://bsc-dataseed.bnbchain.org')
const pub = createPublicClient({ chain: bsc, transport })
const wallet = createWalletClient({ account, chain: bsc, transport })

const erc20 = parseAbi([
  'function balanceOf(address) view returns (uint256)',
  'function allowance(address,address) view returns (uint256)',
  'function approve(address,uint256) returns (bool)',
])
const routerAbi = parseAbi([
  'function getAmountsOut(uint256,address[]) view returns (uint256[])',
  'function swapExactTokensForETHSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)',
])

const amountIn = await pub.readContract({ address: AGC, abi: erc20, functionName: 'balanceOf', args: [account.address] })
console.log(`wallet=${account.address} agc_balance=${formatUnits(amountIn, 18)}`)
if (amountIn === 0n) {
  console.log('NO_AGC_BALANCE')
  process.exit(3)
}

const quoted = await pub.readContract({
  address: ROUTER, abi: routerAbi, functionName: 'getAmountsOut', args: [amountIn, [AGC, WBNB]],
})
const minOut = (quoted[1] * MINOUT_BPS) / 10000n
console.log(`quote_wbnb=${formatUnits(quoted[1], 18)} min_out=${formatUnits(minOut, 18)}`)

const allowance = await pub.readContract({ address: AGC, abi: erc20, functionName: 'allowance', args: [account.address, ROUTER] })
if (allowance < amountIn) {
  const gas = await pub.estimateGas({ account, to: AGC, abi: erc20, functionName: 'approve', args: [ROUTER, amountIn] })
  const hash = await wallet.writeContract({ address: AGC, abi: erc20, functionName: 'approve', args: [ROUTER, amountIn], gas })
  const rc = await pub.waitForTransactionReceipt({ hash })
  console.log(`approve tx=${hash} status=${rc.status} block=${rc.blockNumber}`)
  if (rc.status !== 'success') process.exit(5)
}

const bnbBefore = await pub.getBalance({ address: account.address })
const deadline = BigInt(Math.floor(Date.now() / 1000)) + DEADLINE_S
let hash
try {
  const gas = await pub.estimateGas({
    account, to: ROUTER, abi: routerAbi,
    functionName: 'swapExactTokensForETHSupportingFeeOnTransferTokens',
    args: [amountIn, minOut, [AGC, WBNB], account.address, deadline],
  })
  hash = await wallet.writeContract({
    address: ROUTER, abi: routerAbi,
    functionName: 'swapExactTokensForETHSupportingFeeOnTransferTokens',
    args: [amountIn, minOut, [AGC, WBNB], account.address, deadline], gas,
  })
} catch (err) {
  console.log(`SWAP_REVERTED ${String(err.shortMessage || err.message).slice(0, 200)}`)
  process.exit(4)
}

const rc = await pub.waitForTransactionReceipt({ hash })
const bnbAfter = await pub.getBalance({ address: account.address })
const proceeds = Number(formatUnits(bnbAfter - bnbBefore, 18))
console.log(`swap tx=${hash} status=${rc.status} block=${rc.blockNumber} gasUsed=${rc.gasUsed}`)
console.log(`proceeds_bnb=${proceeds.toFixed(6)}`)
if (rc.status !== 'success') process.exit(4)
if (MIN_BNB > 0 && proceeds < MIN_BNB) {
  console.log(`WARNING proceeds below --min-bnb ${MIN_BNB}`)
}
console.log('SOLD_OK')
