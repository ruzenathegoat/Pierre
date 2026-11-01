// End-to-end probe: does the live harness get real OpenSea data (opensea-v2)
// or fall back to zeros? Prints one word: opensea-v2 | fallback
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(here, '..', '.env'), quiet: true });

import { fetchBestBidEth } from '../src/marketplace';

(async () => {
  try {
    const r = await fetchBestBidEth(
      'ethereum',
      '0xBC4CA0EdA7647A8aB7C2061c2E118A18a936f13D',
      '768',
      'ERC721',
    );
    console.log(r.source === 'opensea-v2' ? 'opensea-v2' : 'fallback');
  } catch (e) {
    console.log(`error: ${(e as Error).message}`);
    process.exit(1);
  }
})();
