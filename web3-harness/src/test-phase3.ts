import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function runPhase3Verification() {
  console.error('=== Phase 3 Self-Patching Skill & MEMORY.md Verification ===');

  const skillTemplatePath = path.resolve(
    __dirname,
    '..',
    'hermes-templates',
    'skills',
    'pierre-web3',
    'SKILL.md'
  );
  const memoryTemplatePath = path.resolve(__dirname, '..', 'hermes-templates', 'MEMORY.md');

  if (!fs.existsSync(skillTemplatePath)) {
    throw new Error(`SKILL.md template tidak ditemukan di ${skillTemplatePath}`);
  }
  if (!fs.existsSync(memoryTemplatePath)) {
    throw new Error(`MEMORY.md template tidak ditemukan di ${memoryTemplatePath}`);
  }

  const skillContent = fs.readFileSync(skillTemplatePath, 'utf-8');
  const memoryContent = fs.readFileSync(memoryTemplatePath, 'utf-8');

  // 1. Validate YAML Frontmatter in SKILL.md
  const frontmatterMatch = skillContent.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!frontmatterMatch) {
    throw new Error('SKILL.md tidak memiliki YAML frontmatter yang valid');
  }
  const frontmatter = frontmatterMatch[1];
  if (!frontmatter.includes('name: pierre-web3') || !frontmatter.includes('description:')) {
    throw new Error('YAML frontmatter SKILL.md harus memiliki name: pierre-web3 dan description');
  }
  console.error('[1] SKILL.md YAML Frontmatter validated (name: pierre-web3).');

  // 2. Validate required directives in MEMORY.md
  const requiredDirectives = [
    'simulate_and_prepare_tx',
    'get_active_positions',
    'inspect_market_orderbook',
    'execute_autonomous_sell',
    'skill_manage',
    'register_learned_pattern',
  ];
  for (const directive of requiredDirectives) {
    if (!memoryContent.includes(directive)) {
      throw new Error(`MEMORY.md kehilangan referensi penting: ${directive}`);
    }
  }
  console.error('[2] MEMORY.md operational & self-patching directives validated.');

  // 3. Sync templates to ~/.hermes/ (if writable) so local & VPS environments are ready
  const hermesHome = process.env.HERMES_HOME || path.join(os.homedir(), '.hermes');
  const targetSkillDir = path.join(hermesHome, 'skills', 'pierre-web3');
  const targetSkillFile = path.join(targetSkillDir, 'SKILL.md');
  const targetMemoryFile = path.join(hermesHome, 'MEMORY.md');

  try {
    fs.mkdirSync(targetSkillDir, { recursive: true });
    if (!fs.existsSync(targetSkillFile)) {
      fs.copyFileSync(skillTemplatePath, targetSkillFile);
      console.error(`[3] Copied SKILL.md to ${targetSkillFile}`);
    } else {
      console.error(`[3] SKILL.md already exists at ${targetSkillFile} (preserved).`);
    }

    if (!fs.existsSync(targetMemoryFile)) {
      fs.copyFileSync(memoryTemplatePath, targetMemoryFile);
      console.error(`[4] Copied MEMORY.md to ${targetMemoryFile}`);
    } else {
      console.error(`[4] MEMORY.md already exists at ${targetMemoryFile} (preserved).`);
    }
  } catch {
    console.error(
      `[3] Templates validated in repository (hermes-templates/); will sync to ~/.hermes on VPS deploy.`
    );
  }

  console.error('=== Phase 3 Verification Passed! ===');
}

runPhase3Verification().catch((err) => {
  console.error('Phase 3 Verification Failed:', err);
  process.exit(1);
});
