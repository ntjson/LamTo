"""Secure randomBytes32 must fail closed when crypto.getRandomValues is missing."""

import json
import re
import subprocess
from pathlib import Path

from django.test import SimpleTestCase

# Shipped static asset — tests load this file, never a reimplementation.
WALLET_SIGNING_JS = (
    Path(__file__).resolve().parents[1] / "static" / "web" / "wallet-signing.js"
)


class WalletSigningRandomTests(SimpleTestCase):
    def test_shipped_file_has_no_math_random_invocation(self):
        source = WALLET_SIGNING_JS.read_text(encoding="utf-8")
        # Comment-only mentions of Math.random are OK; callable form is not.
        self.assertIsNone(
            re.search(r"Math\.random\s*\(", source),
            "wallet-signing.js must not call Math.random",
        )

    def test_random_bytes32_throws_without_secure_crypto(self):
        self.assertTrue(WALLET_SIGNING_JS.is_file(), WALLET_SIGNING_JS)
        path_json = json.dumps(str(WALLET_SIGNING_JS))
        # Sandbox global has no crypto.getRandomValues; evaluate the shipped IIFE.
        node_script = f"""
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync({path_json}, 'utf8');
const document = {{
  readyState: 'complete',
  querySelectorAll: () => [],
  addEventListener: () => {{}},
}};
const window = {{ document }};
const sandbox = {{ window, document, globalThis: {{}} }};
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
const api = sandbox.window.LamToWalletSigning;
if (!api || typeof api.randomBytes32 !== 'function') {{
  console.error('LamToWalletSigning.randomBytes32 missing after loading shipped file');
  process.exit(2);
}}
try {{
  api.randomBytes32();
  console.error('NO_THROW');
  process.exit(3);
}} catch (err) {{
  const msg = String(err && err.message ? err.message : err);
  console.log(msg);
  if (!msg.includes('Secure random')) process.exit(4);
  process.exit(0);
}}
"""
        result = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"stdout={result.stdout!r} stderr={result.stderr!r}",
        )
        self.assertIn("Secure random", result.stdout)
