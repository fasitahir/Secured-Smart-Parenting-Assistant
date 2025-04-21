import base64, os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from dotenv import load_dotenv

load_dotenv()
key = base64.b64decode(os.getenv("AES_KEY"))

def encrypt_field(plain_text: str) -> str:
    iv = os.urandom(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ct = cipher.encrypt(pad(plain_text.encode(), AES.block_size))
    return base64.b64encode(iv + ct).decode()

def decrypt_field(enc_text: str) -> str:
    try:
        missing_padding = len(enc_text) % 4
        if missing_padding:
            enc_text += '=' * (4 - missing_padding)

        raw = base64.b64decode(enc_text)
        if len(raw) < 16:
            raise ValueError("Encoded text too short to contain valid IV and ciphertext")

        iv = raw[:16]
        ct = raw[16:]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(ct), AES.block_size).decode()

    except Exception as e:
        print(f"[decrypt_field] Warning: treating as plaintext. Error: {e}")
        return enc_text  # fallback
