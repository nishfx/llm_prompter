# promptbuilder/core/context_assembler.py
import re
import html # For escaping
from pathlib import Path
from typing import List, Set, Tuple, Callable, Optional
import mmap
import threading
from loguru import logger

from .models import ContextResult, ContextFile
from .token_counter import count_tokens_sync, _get_cached_encoder, DEFAULT_ENCODING # Use sync counter, import helper

# --- Core Logic (Pure Python) ---

class _ContextAssemblerCore:
    """Pure Python implementation of context assembly."""
    MAX_FILE_SIZE_MMAP = 10 * 1024 * 1024; MAX_FILE_SIZE_WARN = 50 * 1024 * 1024

    def __init__(self, secret_patterns: List[str],
                 progress_callback: Optional[Callable[[str], None]] = None, error_callback: Optional[Callable[[str], None]] = None):
        self.secret_patterns_compiled = [re.compile(pattern, re.IGNORECASE) for pattern in secret_patterns]
        self.progress_callback = progress_callback; self.error_callback = error_callback
        self._is_cancelled = threading.Event(); logger.debug("Context assembler core initialized.")

    def _emit_progress(self, message: str):
        if self.progress_callback:
            try:
                self.progress_callback(message)
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")
    def _emit_error(self, message: str):
        if self.error_callback:
            try:
                self.error_callback(message)
            except Exception as e:
                logger.error(f"Error in error callback: {e}")

    def _read_file_content(self, file_path: Path) -> Tuple[str, str, int]:
        """Reads file content, handles encoding, size, secrets. Returns (content, status, initial_token_count)."""
        status = "read_ok"; content = ""; initial_tokens = 0
        try:
            fsize = file_path.stat().st_size
            if fsize > self.MAX_FILE_SIZE_WARN: logger.warning(f"Reading large file ({fsize / 1024**2:.1f} MB): {file_path.name}"); self._emit_progress(f"Reading large file: {file_path.name}...")
            use_mmap = fsize > self.MAX_FILE_SIZE_MMAP and fsize > 0; encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
            if use_mmap:
                with open(file_path, "rb") as f:
                    if fsize == 0: content = ""
                    else:
                        try:
                            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                                decoded = False
                                for enc in encodings_to_try:
                                    if self._is_cancelled.is_set(): return "<cancelled>", "read_cancelled", 0
                                    try: content = mm[:].decode(enc); decoded = True; break
                                    except UnicodeDecodeError: continue
                                if not decoded: content = mm[:].decode('utf-8', errors='replace'); status = "read_decode_error"
                        except ValueError as mmap_err:
                             if "mmap length is greater than file size" in str(mmap_err): content = ""
                             else: raise
            else:
                 decoded = False
                 for enc in encodings_to_try:
                     if self._is_cancelled.is_set(): return "<cancelled>", "read_cancelled", 0
                     try: content = file_path.read_text(encoding=enc); decoded = True; break
                     except UnicodeDecodeError: continue
                     except OSError as read_err: logger.error(f"Error reading file {file_path}: {read_err}"); return f"<Error reading file: {read_err}>", "read_error", 0
                 if not decoded:
                     try: binary_content = file_path.read_bytes(); content = binary_content.decode('utf-8', errors='replace'); status = "read_decode_error"
                     except OSError as read_err: logger.error(f"Error reading file as binary {file_path}: {read_err}"); return f"<Error reading file: {read_err}>", "read_error", 0
            # Secrets Scrubbing
            lines = content.splitlines(); scrubbed_lines = []; was_scrubbed = False
            for line_num, line in enumerate(lines):
                if self._is_cancelled.is_set(): return "<cancelled>", "read_cancelled", 0
                scrubbed_line = line
                for pattern in self.secret_patterns_compiled:
                    def repl(match): nonlocal was_scrubbed; was_scrubbed = True; return '<redacted reason="secret">'
                    scrubbed_line = pattern.sub(repl, scrubbed_line)
                scrubbed_lines.append(scrubbed_line)
            if was_scrubbed: content = "\n".join(scrubbed_lines); logger.info(f"Scrubbed potential secrets in: {file_path.name}");
            if status == "read_ok": status = "read_scrubbed"
            # Token Counting & Progress
            self._emit_progress(f"Counting tokens for: {file_path.name}...")
            initial_tokens = count_tokens_sync(content)
            self._emit_progress(f"Processed: {file_path.name} ({initial_tokens} tokens)")
            return content, status, initial_tokens
        except FileNotFoundError: logger.error(f"File not found during context assembly: {file_path}"); return "<Error: File not found>", "read_error_not_found", 0
        except OSError as e: logger.error(f"OS error reading file {file_path}: {e}"); return f"<Error reading file: {e}>", "read_error", 0
        except Exception as e: logger.exception(f"Unexpected error reading file {file_path}: {e}"); return f"<Unexpected error reading file: {e}>", "read_error_unexpected", 0

    def _apply_budget(self, files_data: List[ContextFile], max_tokens: int) -> Tuple[List[ContextFile], List[ContextFile], int, str]:
        """Applies token budget. Modifies ContextFile objects in place."""
        included_files: List[ContextFile] = []; skipped_files: List[ContextFile] = []
        current_tokens = 0; budget_details = ""
        files_data.sort(key=lambda f: f.path); encoder = _get_cached_encoder(DEFAULT_ENCODING)

        for file_info in files_data:
            if self._is_cancelled.is_set():
                 # Fixes Polish P-2: Remove "(cancelled)" string as CLI doesn't cancel
                 budget_details += f"Skipped remaining files. "
                 idx = files_data.index(file_info); skipped_files.extend(files_data[idx:]); break

            needed_tokens = file_info.tokens
            if current_tokens + needed_tokens <= max_tokens:
                included_files.append(file_info); current_tokens += needed_tokens
            else:
                remaining_tokens = max_tokens - current_tokens
                if remaining_tokens > 50 and encoder:
                    logger.warning(f"Truncating file {file_info.path.name} to fit budget ({remaining_tokens} tokens remaining).")
                    try:
                        if self._is_cancelled.is_set(): break
                        encoded_tokens = encoder.encode(file_info.content)
                        truncated_tokens_list = encoded_tokens[:remaining_tokens]
                        if self._is_cancelled.is_set(): break
                        try: truncated_content = encoder.decode(truncated_tokens_list)
                        except Exception as decode_err:
                             logger.warning(f"Error decoding truncated tokens for {file_info.path.name}, falling back to char estimate: {decode_err}")
                             chars_approx = remaining_tokens * 3; truncated_content = file_info.content[:chars_approx]
                        file_info.content = truncated_content + "\n... [truncated]"
                        if self._is_cancelled.is_set(): break
                        file_info.tokens = count_tokens_sync(file_info.content); file_info.status = "truncated"
                        included_files.append(file_info); current_tokens += file_info.tokens
                        budget_details += f"Truncated {file_info.path.name}. "
                    except Exception as trunc_err:
                         logger.error(f"Error during token truncation for {file_info.path.name}: {trunc_err}. Skipping file.")
                         file_info.status = "skipped_trunc_error"; skipped_files.append(file_info)
                         budget_details += f"Skipped {file_info.path.name} (trunc error). "
                else:
                    reason = "budget" if encoder else "budget (no encoder)"
                    logger.warning(f"Skipping {file_info.path.name} ({reason} exceeded).")
                    file_info.status = f"skipped_{reason.split()[0]}"; skipped_files.append(file_info)
                    budget_details += f"Skipped {file_info.path.name} ({reason}). "
                # Stop processing once budget is hit
                idx = files_data.index(file_info); skipped_files.extend(files_data[idx+1:])
                budget_details += f"Skipped {len(files_data) - (idx+1)} more files (budget)."
                break

        if self._is_cancelled.is_set():
             for f in skipped_files:
                 if f.status == "read_ok": f.status = "skipped_cancelled" # Mark correctly if cancelled

        return included_files, skipped_files, current_tokens, budget_details.strip()

    def assemble_context_sync(self, selected_paths: Set[Path], max_tokens: int) -> ContextResult:
        """Synchronously assembles the context block."""
        logger.info(f"[Sync Assemble] Starting for {len(selected_paths)} paths, max_tokens={max_tokens}")
        self._is_cancelled.clear(); all_files_data: List[ContextFile] = []; processed_count = 0
        sorted_paths = sorted(list(selected_paths)); total_paths = len(sorted_paths)
        for file_path in sorted_paths:
            if self._is_cancelled.is_set(): break
            if not file_path.is_file(): logger.warning(f"Skipping non-file path: {file_path}"); continue
            processed_count += 1
            content, status, initial_tokens = self._read_file_content(file_path)
            if status == "read_cancelled": break
            all_files_data.append(ContextFile(path=file_path, content=content, tokens=initial_tokens, status=status))

        if self._is_cancelled.is_set():
            logger.info("[Sync Assemble] Cancelled during file reading.")
            # Fixes Polish P-2: Remove "(cancelled)" string
            return ContextResult(context_xml="<context><cancelled/></context>", included_files=[], skipped_files=all_files_data, total_tokens=0, budget_details="Assembly cancelled")

        self._emit_progress("Applying token budget...")
        included_files, skipped_files, total_tokens, budget_details = self._apply_budget(all_files_data, max_tokens)

        if self._is_cancelled.is_set():
             logger.info("[Sync Assemble] Cancelled during budgeting.")
             # Fixes Polish P-2: Remove "(cancelled)" string
             return ContextResult(context_xml="<context><cancelled/></context>", included_files=included_files, skipped_files=skipped_files, total_tokens=total_tokens, budget_details="Assembly cancelled during budget")

        self._emit_progress("Building final XML...")
        context_lines = ["<context>"]
        for file_info in included_files:
             safe_name = html.escape(file_info.path.name, quote=True); safe_path = html.escape(str(file_info.path), quote=True)
             safe_status = html.escape(file_info.status, quote=True); escaped_content = html.escape(file_info.content)
             context_lines.append(f"    <file name='{safe_name}' path='{safe_path}' status='{safe_status}' tokens='{file_info.tokens}'>")
             context_lines.append(escaped_content); context_lines.append(f"    </file>")
        context_lines.append("</context>"); context_xml = "\n".join(context_lines)
        result = ContextResult(context_xml=context_xml, included_files=included_files, skipped_files=skipped_files, total_tokens=total_tokens, budget_details=budget_details)
        logger.info(f"[Sync Assemble] Finished. Tokens: {total_tokens}/{max_tokens}. Included: {len(included_files)}, Skipped: {len(skipped_files)}.")
        return result

    def cancel(self):
        logger.info("Cancellation requested for context assembler core."); self._is_cancelled.set()

# --- Qt Adapter Task --- (No changes needed in adapter itself)
from PySide6.QtCore import QObject, QRunnable, Signal, Slot
class ContextAssemblerSignals(QObject): finished = Signal(object); error = Signal(str); progress = Signal(str)
class ContextAssemblerTask(QRunnable):
    def __init__(self, selected_paths: Set[Path], max_tokens: int, secret_patterns: List[str]):
        super().__init__(); self.selected_paths = selected_paths; self.max_tokens = max_tokens; self.secret_patterns = secret_patterns
        self.signals = ContextAssemblerSignals(); self.assembler_core: Optional[_ContextAssemblerCore] = None; self.setAutoDelete(True)
    @Slot()
    def run(self) -> None:
        try:
            self.assembler_core = _ContextAssemblerCore(secret_patterns=self.secret_patterns, progress_callback=self.signals.progress.emit, error_callback=self.signals.error.emit)
            result = self.assembler_core.assemble_context_sync(self.selected_paths, self.max_tokens)
            if self.assembler_core._is_cancelled.is_set(): self.signals.error.emit("Context assembly cancelled")
            else: self.signals.finished.emit(result)
        except Exception as e: logger.exception(f"Unexpected error during context assembly task: {e}"); self.signals.error.emit(f"Unexpected Assembly Error: {e}")
        finally: self.assembler_core = None
    def cancel(self):
        logger.info("Cancellation signal received for context assembly task.");
        if self.assembler_core: self.assembler_core.cancel()