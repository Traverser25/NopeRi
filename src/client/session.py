# Default backend is httpcloak. On some Windows setups it fails with a
# permission error during session init. If you hit that, switch to
# curl_cffi by changing the line below.

USE_CURL_CFFI = False # set True if httpcloak throws a permission error


def build_session():
    if USE_CURL_CFFI:
        from curl_cffi import requests
        return requests.Session(impersonate="chrome124", timeout=30)

    import httpcloak
    return httpcloak.Session(preset="chrome-latest", timeout=30)