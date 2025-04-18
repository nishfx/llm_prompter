# promptbuilder/core/token_counter.py
from functools import lru_cache
from typing import Optional, Any # Added Any for encoder type hint flexibility
from loguru import logger

# --- Tiktoken Initialization ---
try:
    import tiktoken
    # Test common encodings on import to fail early if needed
    _ = tiktoken.get_encoding("cl100k_base")
    _ = tiktoken.get_encoding("gpt2") # Fallback
    TIKTOKEN_AVAILABLE = True
    logger.info("tiktoken library loaded successfully.")
except ImportError:
    logger.warning("tiktoken library not found. Token counting will be estimated.")
    tiktoken = None # type: ignore
    TIKTOKEN_AVAILABLE = False
except Exception as e:
    logger.error(f"Failed to initialize tiktoken, token counting will be estimated: {e}")
    tiktoken = None # type: ignore
    TIKTOKEN_AVAILABLE = False

DEFAULT_ENCODING = "cl100k_base" # Common for GPT-3.5/4
FALLBACK_ENCODING = "gpt2"

# --- Core Logic (Pure Python) ---

@lru_cache(maxsize=4) # Cache a few loaded encoder objects
def _get_cached_encoder(encoding_name: str) -> Optional[Any]:
    """Internal helper to load and cache encoder objects."""
    if not TIKTOKEN_AVAILABLE:
        logger.trace(f"Tiktoken unavailable, cannot get encoder '{encoding_name}'.")
        return None
    try:
        logger.debug(f"Attempting to load tiktoken encoder: {encoding_name}")
        encoder = tiktoken.get_encoding(encoding_name) # type: ignore
        logger.debug(f"Successfully loaded encoder '{encoding_name}'.")
        return encoder
    except Exception as e:
        logger.warning(f"Failed to get tiktoken encoder '{encoding_name}': {e}. Trying fallback '{FALLBACK_ENCODING}'.")
        if encoding_name == FALLBACK_ENCODING: # Avoid infinite recursion if fallback fails
             logger.error(f"Fallback encoder '{FALLBACK_ENCODING}' also failed. No encoder available.")
             return None
        # Try fallback (recursive call, but cache prevents repeated load attempts for the *same* name)
        # The result of the fallback call will also be cached under the fallback name.
        return _get_cached_encoder(FALLBACK_ENCODING)

def count_tokens_sync(text: str, encoding_name: str = DEFAULT_ENCODING) -> int:
    """
    Counts tokens in a string using the specified tiktoken encoding (synchronous).
    Falls back to character estimation if tiktoken fails or is unavailable.
    """
    if not text:
        return 0

    encoder = _get_cached_encoder(encoding_name)

    if encoder:
        try:
            tokens = encoder.encode(text)
            return len(tokens)
        except Exception as e:
            # Log error but still fallback to estimation
            logger.error(f"Error encoding text for token count with '{encoding_name}': {e}")
            # Fallback: estimate based on characters (very rough)
            estimated_tokens = len(text) // 4
            logger.warning(f"Falling back to character-based estimation: {estimated_tokens} tokens.")
            return estimated_tokens
    else:
        # Fallback if tiktoken is unavailable or failed during load
        estimated_tokens = len(text) // 4
        # logger.debug(f"tiktoken unavailable, using character-based estimation: {estimated_tokens} tokens.")
        return estimated_tokens

# --- Alias for backward compatibility / simpler usage ---
# Fixes critical issue #1: Call sites expecting count_tokens
def count_tokens(text: str, encoding_name: str = DEFAULT_ENCODING) -> int:
    """Public alias for count_tokens_sync."""
    return count_tokens_sync(text, encoding_name)

# --- Optional: Qt Adapter Task (if async counting needed for UI responsiveness) ---
# (Remains commented out unless explicitly needed)
# from PySide6.QtCore import QObject, QRunnable, Signal, Slot
# ... (TokenCounterTask definition) ...