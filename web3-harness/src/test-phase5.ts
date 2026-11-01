import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const EXPECTED_TOOLS = [
  'get_active_positions',
  'inspect_market_orderbook',
  'simulate_and_prepare_tx',
  'execute_signed_tx',
  'execute_autonomous_sell',
  'execute_baw_agentic_trade',
  'register_learned_pattern',
];

async function runPhase5Verification() {
  console.error('=== Phase 5 Hermes Config, VPS Bootstrap & MCP Tools Verification ===');

  const rootDir = path.resolve(__dirname, '..');
  const configYamlPath = path.join(rootDir, 'hermes-templates', 'config.yaml');
  const hermesEnvExamplePath = path.join(rootDir, 'hermes-templates', '.env.hermes.example');
  const setupScriptPath = path.join(rootDir, 'scripts', 'setup-vps.sh');

  if (!fs.existsSync(configYamlPath)) {
    throw new Error('hermes-templates/config.yaml tidak ditemukan');
  }
  if (!fs.existsSync(hermesEnvExamplePath)) {
    throw new Error('hermes-templates/.env.hermes.example tidak ditemukan');
  }
  if (!fs.existsSync(setupScriptPath)) {
    throw new Error('scripts/setup-vps.sh tidak ditemukan');
  }

  const configYaml = fs.readFileSync(configYamlPath, 'utf-8');
  if (
    !configYaml.includes('provider: openrouter') ||
    !configYaml.includes('default: deepseek/deepseek-v4-flash') ||
    !configYaml.includes('viem_web3_harness:')
  ) {
    throw new Error('config.yaml belum memiliki konfigurasi OpenRouter deepseek-v4-flash & viem_web3_harness');
  }
  console.error('[1] hermes-templates/config.yaml (OpenRouter + DeepSeek V4 Flash + MCP) verified.');

  const serverScript = path.resolve(__dirname, 'mcp-server.ts');
  const tsxCli = path.resolve(rootDir, 'node_modules', 'tsx', 'dist', 'cli.mjs');
  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [tsxCli, serverScript],
    cwd: rootDir,
    stderr: 'pipe',
  });

  const client = new Client({
    name: 'phase5-verifier',
    version: '1.0.0',
  });

  await client.connect(transport);
  const { tools } = await client.listTools();
  const registeredNames = tools.map((t) => t.name);

  for (const expected of EXPECTED_TOOLS) {
    if (!registeredNames.includes(expected)) {
      throw new Error(`Tool MCP wajib tidak ditemukan: ${expected}`);
    }
  }

  console.error(`[2] All ${EXPECTED_TOOLS.length} Phase 5 MCP Tools verified: ${registeredNames.join(', ')}`);
  await client.close();

  console.error('=== Phase 5 Local Verification Passed! ===');
}

runPhase5Verification().catch((err) => {
  console.error('Phase 5 Verification Failed:', err);
  process.exit(1);
});

