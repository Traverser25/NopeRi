from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import base64
import time
from src.config.constants import *


key = RSA.import_key(PUBLIC_KEY)
cipher = PKCS1_v1_5.new(key)

def generate_nkparam(page_type: str = "srp") -> str:
    timestamp = int(time.time() * 1000)
    plaintext = f"v0|{timestamp}|121_{page_type}"
    encrypted = cipher.encrypt(plaintext.encode('utf-8'))
    return base64.b64encode(encrypted).decode('utf-8')
