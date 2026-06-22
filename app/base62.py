ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = 62

def encode(num: int) -> str:
    if num == 0:
        return ALPHABET[0]

    result = ""
    while num > 0:
        remainder = num % BASE
        result = ALPHABET[remainder] + result
        num = num // BASE
    return result

def decode(short_code: str) -> int:
    num = 0
    for char in short_code:
        num = num * BASE + ALPHABET.index(char)
    return num