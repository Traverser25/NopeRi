"""
Generates the Naukri `vid` header token without a browser.

The token is produced by Naukri's BotGuard SDK:
  plaintext = f"v0|{timestamp_ms}|{app_id}_{action}"
  vid       = RSA_encrypt(PUBLIC_KEY, plaintext)   # base64 output

This module runs botguardSdk_v1.min.js inside Node.js using a small
driver script, then parses the output.  Node.js ≥14 required.
"""

import subprocess
import re
import os
import tempfile
import logging

logger = logging.getLogger(__name__)

_SDK_PATH = os.path.join(os.path.dirname(__file__), "botguardSdk_v1.min.js")

_APP_ID = "105"
_PUBLIC_KEY = (
    "MFwwDQYJKoZIhvcNAQEBBQADSwAwSAJBALbx2oNW1OsL+zv+GK4Ed70m4gr6sBjp"
    "zj1PCmLAYs3dQph0IS/DFWXMDN//CyC46DgSJZJZdaxT0xskFBIKNSMCAwEAAQ=="
)

_DRIVER_TEMPLATE = r"""
'use strict';
const fs = require('fs');

global.window = global;
global.self   = global;
global.document = {{ cookie: '' }};
try {{
    global.navigator = {{ userAgent: 'Mozilla/5.0' }};
}} catch(e) {{
    Object.defineProperty(global, 'navigator', {{
        value: {{ userAgent: 'Mozilla/5.0' }},
        writable: true, configurable: true
    }});
}}
try {{
    global.location = {{ href: 'https://www.naukri.com/nlogin/login' }};
}} catch(e) {{
    Object.defineProperty(global, 'location', {{
        value: {{ href: 'https://www.naukri.com/nlogin/login', pathname: '/nlogin/login' }},
        writable: true, configurable: true
    }});
}}
global.requirejs = function(d, cb, eb) {{ if (eb) eb(new Error('no requirejs')); }};
global.requirejs.config = function(){{}};

const sdkCode = fs.readFileSync({sdk_path!r}, 'utf8');
eval(sdkCode);

const shield = global.window.BotGuardSDK.createRequestShield({{
    appId:     {app_id!r},
    publicKey: {public_key!r},
    logger:    {{ log: function(){{}} }}
}});

shield.getDynamicToken({action!r}).then(function(vid) {{
    process.stdout.write(vid + '\n');
}}).catch(function(e) {{
    process.stderr.write('error: ' + e.message + '\n');
    process.exit(1);
}});
"""


def generate_vid(action: str = "nlogin-login") -> str:
    """
    Return a fresh `vid` token for the given Naukri page action.

    Args:
        action: The page identifier passed to getDynamicToken.
                Common values:
                  "nlogin-login"          – login page (default)
                  "nlogin-mod-login"      – mod-login page
                  "nlogin-logout"         – logout page
                  "nlogin-forgotpassword" – forgot-password page

    Returns:
        Base64-encoded vid string.

    Raises:
        RuntimeError: If Node.js is not found or token generation fails.
    """
    sdk_path = os.path.abspath(_SDK_PATH).replace("\\", "/")
    driver = _DRIVER_TEMPLATE.format(
        sdk_path=sdk_path,
        app_id=_APP_ID,
        public_key=_PUBLIC_KEY,
        action=action,
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".js", delete=False, encoding="utf-8"
    ) as f:
        f.write(driver)
        driver_path = f.name

    try:
        result = subprocess.run(
            ["node", driver_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
    finally:
        os.unlink(driver_path)

    if result.returncode != 0:
        raise RuntimeError(
            f"vid generation failed: {result.stderr.strip() or result.stdout.strip()}"
        )

    vid = result.stdout.strip()
    if not vid:
        raise RuntimeError("vid generation returned empty output")

    logger.debug("Generated vid (%d chars) for action=%r", len(vid), action)
    return vid
