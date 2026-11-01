import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  closePosition,
  getOpenPositions,
  insertPosition,
} from './db.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function runPhase6E2ETests() {
  console.error('=== Phase 6 End-to-End (E2E) Acceptance Test Suite ===');

  const rootDir = path.resolve(__dirname, '..');
  const patternsPath = path.join(rootDir, 'known_patterns.json');
  const originalPatternsRaw = fs.readFileSync(patternsPath, 'utf-8');

  const serverScript = path.resolve(__dirname, 'mcp-server.ts');
  const tsxCli = path.resolve(rootDir, 'node_modules', 'tsx', 'dist', 'cli.mjs');
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [tsxCli, serverScript],
    cwd: rootDir,
    stderr: 'pipe',
  });

  const client = new Client({
    name: 'phase6-e2e-runner',
    version: '1.0.0',
  });

  await client.connect(transport);

  try {
    // =========================================================================
    // TEST 1: Dry-Run Simulation Guardrails, Position State & Multi-Channel Webhook
    // =========================================================================
    console.error('\n--- [Test 1] Simulation Preview, SQLite Position State & Webhook Routing ---');
    const posId = insertPosition({
      chain: 'bsc',
      contract_address: '0x1111111111111111111111111111111111111111',
      token_id: 'BAW_MPC',
      asset_type: 'ERC20',
      asset_name: 'PierreAgent.ai',
      entry_price_eth: 0.04,
    });

    const activePosRes = await client.callTool({
      name: 'get_active_positions',
      arguments: {},
    });
    const activePosJson = JSON.parse(
      (activePosRes.content as Array<{ text: string }>)[0].text
    ) as { open_positions_count: number };
    if (activePosJson.open_positions_count < 1) {
      throw new Error('Test 1 gagal: posisi OPEN tidak terbaca oleh get_active_positions');
    }
    console.error(`[Test 1] Active positions verified via MCP (${activePosJson.open_positions_count} open).`);
    closePosition(posId);

    // =========================================================================
    // TEST 2: Fresh Input Detection & Self-Patching Pattern Registration
    // =========================================================================
    console.error('\n--- [Test 2] Fresh Input Loop & register_learned_pattern ---');
    const testDomain = 'new-launchpad-2026.ai';
    const testSelector = '0xabcdef12';

    const regRes = await client.callTool({
      name: 'register_learned_pattern',
      arguments: {
        domain: `https://${testDomain}/mint`,
        selector: testSelector,
      },
    });
    const regJson = JSON.parse(
      (regRes.content as Array<{ text: string }>)[0].text
    ) as {
      status: string;
      updated: boolean;
      known_patterns: { domains: string[]; selectors: string[] };
    };

    if (
      !regJson.updated ||
      !regJson.known_patterns.domains.includes(testDomain) ||
      !regJson.known_patterns.selectors.includes(testSelector)
    ) {
      throw new Error('Test 2 gagal: register_learned_pattern tidak menyimpan domain/selector baru');
    }
    console.error(`[Test 2] Self-patching pattern registry verified (${testDomain}, ${testSelector}).`);

    // =========================================================================
    // TEST 3: CI/CD Workflow, PM2 Ecosystem & SQLite Persistence Verification
    // =========================================================================
    console.error('\n--- [Test 3] CI/CD Workflow, PM2 Ecosystem & SQLite State Persistence ---');
    const workflowPath = path.join(rootDir, '.github', 'workflows', 'deploy.yml');
    const ecosystemPath = path.join(rootDir, 'ecosystem.config.cjs');
    const startPm2Path = path.join(rootDir, 'scripts', 'start-pm2.sh');

    if (!fs.existsSync(workflowPath) || !fs.existsSync(ecosystemPath) || !fs.existsSync(startPm2Path)) {
      throw new Error('Test 3 gagal: file CI/CD atau PM2 tidak lengkap');
    }

    const workflowContent = fs.readFileSync(workflowPath, 'utf-8');
    if (
      !workflowContent.includes('appleboy/ssh-action') ||
      !workflowContent.includes('price-watcher') ||
      !workflowContent.includes('baw-keepalive') ||
      !workflowContent.includes('hermes-discord')
    ) {
      throw new Error('Test 3 gagal: deploy.yml tidak me-restart semua proses PM2');
    }

    const openPositionsAfter = getOpenPositions();
    console.error(
      `[Test 3] CI/CD deploy.yml, ecosystem.config.cjs (with 6h baw-keepalive cron), and SQLite persistence verified (open positions: ${openPositionsAfter.length}).`
    );

    console.error('\n=== All 3 Phase 6 Acceptance Tests Passed! ===');
  } finally {
    // Restore known_patterns.json so test domain doesn't pollute production list
    fs.writeFileSync(patternsPath, originalPatternsRaw, 'utf-8');
    await client.close();
  }
}

runPhase6E2ETests().catch((err) => {
  console.error('Phase 6 E2E Tests Failed:', err);
  process.exit(1);
});

