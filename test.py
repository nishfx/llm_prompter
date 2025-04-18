#!/usr/bin/env python3
"""
Creative Text Encryption Using a Seed Phrase

This script allows a user to input any text (word or sentence) and a seed phrase
to produce an encrypted string. The encryption algorithm is designed to be:
1. Not trivially predictable.
2. Dependent on the seed phrase to ensure uniqueness.
3. Production-ready.

Usage:
    1. Run the script.
    2. Enter the text you want to encrypt.
    3. Enter the seed phrase.

Example:
    python3 seed_encryption.py
"""

import hashlib
import random


def _derive_int_from_seed(seed_phrase: str) -> int:
    """
    Derive an integer from the seed phrase by hashing and interpreting it.
    This integer will be used for seeding the random generator.
    """
    # Create a SHA256 hash from the seed_phrase
    hash_object = hashlib.sha256(seed_phrase.encode('utf-8')).hexdigest()
    # Convert the first 16 characters of the hex digest to an integer
    # (Slicing is arbitrary, ensures we don't exceed integer bounds and get variation)
    return int(hash_object[:16], 16)


def _random_shifts(text_length: int) -> list:
    """
    Return a list of pseudo-random shift amounts (one shift for each character).
    Each shift is between 1 and 25 (inclusive).
    """
    return [random.randint(1, 25) for _ in range(text_length)]


def _shift_characters(text: str, shifts: list) -> str:
    """
    Shift each character of `text` by the corresponding amount in `shifts`.

    1. For letters (uppercase or lowercase), shift within A-Z / a-z.
    2. For digits, rotate within '0'-'9'.
    3. Other characters remain as is.
    """
    shifted_chars = []

    for ch, shift in zip(text, shifts):
        # Uppercase letter
        if 'A' <= ch <= 'Z':
            alpha_index = ord(ch) - ord('A')
            new_index = (alpha_index + shift) % 26
            new_ch = chr(ord('A') + new_index)
            shifted_chars.append(new_ch)

        # Lowercase letter
        elif 'a' <= ch <= 'z':
            alpha_index = ord(ch) - ord('a')
            new_index = (alpha_index + shift) % 26
            new_ch = chr(ord('a') + new_index)
            shifted_chars.append(new_ch)

        # Digit
        elif '0' <= ch <= '9':
            digit_index = ord(ch) - ord('0')
            new_index = (digit_index + shift) % 10
            new_ch = chr(ord('0') + new_index)
            shifted_chars.append(new_ch)

        # Non-alphanumeric, leave as-is
        else:
            shifted_chars.append(ch)

    return ''.join(shifted_chars)


def _random_transposition(text: str) -> str:
    """
    Perform a pseudo-random transposition on the entire string.

    1. Create a list of all indices [0, 1, 2, ...].
    2. Shuffle the list of indices.
    3. Rearrange text based on this new index order.
    """
    indices = list(range(len(text)))
    random.shuffle(indices)
    return ''.join(text[i] for i in indices)


def encrypt_text(text: str, seed_phrase: str) -> str:
    """
    Encrypt the given text using the specified seed phrase.
    This is a two-part encryption process:
      1. Per-character shift (using a unique shift for each character).
      2. A transposition shuffle across the entire string.
    """
    # 1) Derive integer from seed phrase to seed RNG
    seed_int = _derive_int_from_seed(seed_phrase)
    random.seed(seed_int)

    # 2) Generate random shifts for each character and apply them
    shifts = _random_shifts(len(text))
    shifted = _shift_characters(text, shifts)

    # 3) Perform final transposition and return
    transposed = _random_transposition(shifted)
    return transposed


def main():
    """
    Main driver function:
    1. Prompts user for text and seed.
    2. Encrypts the text using the seed.
    3. Prints out the encrypted result.
    """
    print("===== Creative Seed-Based Text Encryption =====")
    user_text = input("Enter text (word or sentence) to encrypt: ")
    seed_phrase = input("Enter your secret seed phrase: ")

    encrypted = encrypt_text(user_text, seed_phrase)
    print(f"\nEncrypted Output:\n{encrypted}\n")


if __name__ == "__main__":
    main()
