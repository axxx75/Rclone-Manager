
import hashlib

def hash_file(filepath: str, method: str = "md5") -> str:
    h = hashlib.new(method)
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()
