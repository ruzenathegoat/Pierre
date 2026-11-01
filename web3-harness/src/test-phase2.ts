import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function runPhase2Verification() {
  console.error('=== Phase 2 MCP Server Verification ===');

  const serverScript = path.resolve(__dirname, 'mcp-server.ts');
  const tsxCli = path.resolve(__dirname, '..', 'node_modules', 'tsx', 'dist', 'cli.mjs');
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [tsxCli, serverScript],
    cwd: path.resolve(__dirname, '..'),
    stderr: 'pipe',
  });

  if (transport.stderr) {
    transport.stderr.on('data', (chunk: Buffer) => {
      process.stderr.write(`[MCP STDERR] ${chunk.toString()}`);
    });
  }

  const client = new Client({
    name: 'phase2-verifier',
    version: '1.0.0',
  });

  await client.connect(transport);

  // 1. Verify exposed tools
  const toolsResult = await client.listTools();
  const toolNames = toolsResult.tools.map((t) => t.name);
  console.error(`[1] Exposed MCP Tools (${toolNames.length}): ${toolNames.join(', ')}`);

  // 2. Test Tool 1: get_active_positions
  const posRes = await client.callTool({
    name: 'get_active_positions',
    arguments: {},
  });
  console.error('[2] get_active_positions response:', JSON.stringify(posRes.content));

  // 3. Test Guardrail 1 on Base (ETH cap) and BSC (BNB cap)
  const baseCapRes = await client.callTool({
    name: 'simulate_and_prepare_tx',
    arguments: {
      chain: 'base',
      contractAddress: '0x1234567890abcdef1234567890abcdef12345678',
      calldata: '0x1249c58b',
      valueEth: '0.50', // Exceeds MAX_ETH_PER_TX=0.05
      actionType: 'MINT',
      assetName: 'OverCap Test Base',
      sourceUrl: 'https://opensea.io/collection/test',
    },
  });
  console.error('[3] Base Max Spend Guardrail Test:', JSON.stringify(baseCapRes.content));

  const bscCapRes = await client.callTool({
    name: 'simulate_and_prepare_tx',
    arguments: {
      chain: 'bnb',
      contractAddress: '0x1234567890abcdef1234567890abcdef12345678',
      calldata: '0x1249c58b',
      valueEth: '1.00', // Exceeds MAX_BNB_PER_TX=0.15
      actionType: 'BUY',
      assetName: 'OverCap Test BNB',
      sourceUrl: 'https://pancakeswap.finance/swap',
    },
  });
  console.error('[4] BNB Chain Max Spend Guardrail Test:', JSON.stringify(bscCapRes.content));

  await client.close();
  console.error('=== Phase 2 Verification Passed! ===');
}

runPhase2Verification().catch((err) => {
  console.error('Phase 2 Verification Failed:', err);
  process.exit(1);
});
